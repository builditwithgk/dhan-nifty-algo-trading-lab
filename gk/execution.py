"""OrderManager — the ONE place orders are created. Safety by architecture.

Every entry funnels through open_from_signal(), whose first statement is the
kill-switch check (structurally unbypassable, the pattern from the best repo we
reviewed). Order: kill switch -> risk pipeline -> sizing -> broker bracket.
The broker itself refuses any bracket without a stop, so there is no code path
that opens an unprotected position.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .brokers.base import Broker
from .config import Settings
from .journal import Journal
from .models import OrderRequest, OrderResult, OrderStatus, Position, Signal
from .risk import RiskManager, size_position


@dataclass
class Outcome:
    ok: bool
    reason: str
    result: OrderResult | None = None


class OrderManager:
    def __init__(self, settings: Settings, broker: Broker,
                 risk: RiskManager, journal: Journal):
        self.s = settings
        self.broker = broker
        self.risk = risk
        self.j = journal

    def open_from_signal(self, sig: Signal, fixed_qty: int | None = None,
                         charges_override: float | None = None,
                         is_spread: bool = False) -> Outcome:
        # 1) KILL SWITCH — first statement, always.
        if self.j.is_killed():
            self.j.event("BLOCKED", f"kill switch: {sig.instrument.symbol}")
            return Outcome(False, "kill switch engaged")

        # 2) Risk veto pipeline (daily loss, per-class position caps — read live).
        decision = self.risk.approve_entry(self.broker, kind=sig.instrument.kind)
        if not decision:
            self.j.event("BLOCKED", f"{sig.instrument.symbol}: {decision.reason}")
            return Outcome(False, decision.reason)

        # 3) Size. Options use fixed lots (a NIFTY lot exceeds the per-trade risk
        #    budget at small capital); equity uses stop-distance sizing.
        if fixed_qty is not None:
            from .risk import SizeResult
            sized = SizeResult(fixed_qty, fixed_qty > 0, f"{fixed_qty} units (fixed)")
        else:
            sized = size_position(
                instrument=sig.instrument,
                entry_price=sig.entry_ref_price,
                stop=sig.stop,
                risk_rupees=self.s.risk_per_trade,
                max_notional=self.s.max_notional_per_trade,
            )
        if not sized.ok:
            self.j.event("SKIP", f"{sig.instrument.symbol}: {sized.reason}")
            return Outcome(False, f"not sized: {sized.reason}")

        # 3b) TOTAL DEPLOYMENT CAP — never let all open positions together exceed
        #     the allocated capital, no matter how much the account actually holds.
        open_value = sum(p.entry_price * p.quantity for p in self.broker.get_positions())
        new_value = sized.quantity * sig.entry_ref_price
        if open_value + new_value > self.s.capital:
            self.j.event("SKIP", f"{sig.instrument.symbol}: deployment cap "
                                 f"(open {open_value:.0f} + new {new_value:.0f} > "
                                 f"capital {self.s.capital:.0f})")
            return Outcome(False, f"would exceed allocated capital "
                                  f"Rs.{self.s.capital:,.0f}")

        # 4) Build the final request and place a broker-side bracket.
        req = OrderRequest(
            instrument=sig.instrument, side=sig.side, quantity=sized.quantity,
            stop=sig.stop, target=sig.target, trail_jump=sig.trail_jump,
            product="INTRADAY", strategy=sig.strategy, tag=sig.strategy,
            charges=charges_override, is_spread=is_spread,
        )
        result = self.broker.place_bracket(req)
        if not result.ok:
            self.j.event("REJECTED", f"{sig.instrument.symbol}: {result.message}")
            return Outcome(False, result.message, result)

        return Outcome(True, f"opened {sized.quantity} @ ~{sig.entry_ref_price} "
                             f"({sized.reason})", result)

    def flatten_all(self, reason: str = "flatten") -> List[Position]:
        self.j.event("FLATTEN_ALL", reason)
        return self.broker.flatten_all()

    def square_off(self) -> List[Position]:
        return self.flatten_all("15:15 square-off")

    def engage_kill(self, reason: str, flatten: bool = True) -> None:
        """Kill switch that ACTUALLY flattens (the dashboard button that lied
        in the prior work only set a flag)."""
        self.j.kill(reason)
        if flatten:
            self.flatten_all(f"kill switch: {reason}")
