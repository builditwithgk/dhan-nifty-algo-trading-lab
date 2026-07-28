"""Position sizing + the risk veto pipeline + kill switch.

Sizing rules (each fixes a specific bug from the reviewed repos):
  * Quantity comes from the STOP DISTANCE and a fixed rupee risk — not a guess.
  * Rounded DOWN to a whole lot. If even one lot exceeds risk/notional, we
    return 0 and the trade is skipped. NEVER `max(1, qty)` (that silently
    forces a trade the risk model rejected).
  * A hard notional cap (% of capital) so a tight stop can't create a huge
    position.

Veto pipeline (checked fresh for EVERY prospective entry):
  kill switch -> daily loss (realised + unrealised) -> max open positions.
  It reads live positions from the broker each call, so the max-positions cap
  is enforced per-position, not once-per-cycle (the leak that let a repo open
  7 against a cap of 3).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple

from .brokers.base import Broker
from .config import Settings
from .journal import Journal
from .models import Instrument, Side


@dataclass
class SizeResult:
    quantity: int
    ok: bool
    reason: str


def size_position(instrument: Instrument, entry_price: float, stop: float,
                  risk_rupees: float, max_notional: float) -> SizeResult:
    risk_per_unit = abs(entry_price - stop)
    if risk_per_unit <= 0:
        return SizeResult(0, False, "stop equals entry")

    raw_units = risk_rupees / risk_per_unit
    lot = max(1, instrument.lot_size)
    lots = math.floor(raw_units / lot)
    qty = lots * lot

    if qty <= 0:
        return SizeResult(0, False,
                          f"one lot ({lot}) risks more than the per-trade budget")

    # Notional cap — shrink whole lots until within cap.
    while qty > 0 and qty * entry_price > max_notional:
        lots -= 1
        qty = lots * lot
    if qty <= 0:
        return SizeResult(0, False, "one lot exceeds the notional cap")

    return SizeResult(qty, True, f"{lots} lot(s) x {lot}")


class Decision:
    def __init__(self, ok: bool, reason: str):
        self.ok = ok
        self.reason = reason

    def __bool__(self):
        return self.ok


class RiskManager:
    def __init__(self, settings: Settings, journal: Journal):
        self.s = settings
        self.j = journal

    def day_pnl(self, broker: Broker) -> float:
        """Realised (net) + unrealised mark-to-market, in rupees."""
        realized = self.j.day_realized_pnl()
        unrealized = sum(p.unrealized for p in broker.get_positions())
        return realized + unrealized

    def approve_entry(self, broker: Broker, kind=None) -> Decision:
        from .models import AssetKind
        if self.j.is_killed():
            return Decision(False, "kill switch engaged")

        pnl = self.day_pnl(broker)
        loss_cap = self.s.effective_max_daily_loss
        if pnl <= -loss_cap:
            self.j.kill(f"daily loss limit hit: {pnl:.0f} <= -{loss_cap:.0f}")
            return Decision(False, "daily loss limit hit — trading halted for the day")

        if self.s.daily_profit_target and pnl >= self.s.daily_profit_target:
            return Decision(False, f"daily profit target reached (+{pnl:.0f}) — done for the day")

        positions = broker.get_positions()
        if len(positions) >= self.s.max_open_positions:
            return Decision(False, f"max total positions ({self.s.max_open_positions}) reached")

        # Per-asset-class caps so equity and options are limited independently.
        if kind is AssetKind.OPTION:
            n = sum(1 for p in positions if p.instrument.kind is AssetKind.OPTION)
            if n >= self.s.max_option_positions:
                return Decision(False, f"max option positions ({self.s.max_option_positions}) reached")
        elif kind is AssetKind.EQUITY:
            n = sum(1 for p in positions if p.instrument.kind is AssetKind.EQUITY)
            if n >= self.s.max_equity_positions:
                return Decision(False, f"max equity positions ({self.s.max_equity_positions}) reached")

        return Decision(True, "ok")

    def check_daily_loss(self, broker: Broker) -> bool:
        """Call after any exit; engages kill switch if the day's loss breached.
        Returns True if the kill switch is now engaged."""
        if self.j.is_killed():
            return True
        if self.day_pnl(broker) <= -self.s.effective_max_daily_loss:
            self.j.kill("daily loss limit breached")
            return True
        return False
