"""PaperBroker — fake money, realistic mechanics.

It exists to prove the whole spine works before a rupee is at risk, and to
forward-test strategies. It deliberately models the things the reviewed repos
got wrong:
  * Entries fill at LTP +/- slippage — the ACTUAL fill, not the requested price.
  * Every entry carries a broker-side stop & target; price ticks trigger them.
  * Stop exits slip (SL-M); target exits fill at the limit. Honest, slightly
    conservative.
  * Full statutory charges are deducted on entry and exit (costs.py).
  * Realised P&L (net of charges) is pushed to the journal so the daily-loss
    kill switch sees the truth.

Drive it in tests/paper by calling `set_price()` / `feed()` to move the market.
"""
from __future__ import annotations

import itertools
from typing import Dict, List, Optional

from .. import costs
from ..clock import now_ist
from ..journal import Journal
from ..models import (AssetKind, Fill, Funds, OrderRequest, OrderResult,
                      OrderStatus, Position, Side)
from .base import Broker

_ids = itertools.count(1)


class PaperBroker(Broker):
    name = "paper"

    def __init__(self, journal: Journal, starting_capital: float,
                 equity_slippage_pct: float = 0.03,
                 option_slippage_pct: float = 0.5,
                 equity_leverage: float = 5.0):
        self.j = journal
        self.starting_capital = float(starting_capital)
        self.realized_pnl = 0.0
        self.equity_slip = equity_slippage_pct / 100.0
        self.option_slip = option_slippage_pct / 100.0
        self.equity_leverage = equity_leverage
        self._positions: Dict[str, Position] = {}
        self._prices: Dict[str, float] = {}   # security_id -> ltp

    # ---------------- market plumbing (paper only) ----------------
    def set_price(self, security_id: str, price: float) -> None:
        self._prices[security_id] = float(price)

    def feed(self, security_id: str, price: float) -> List[Position]:
        """Set a price AND run stop/target checks. Returns positions closed."""
        self.set_price(security_id, price)
        return self._check_triggers(security_id, price)

    def _slip(self, pos_or_instr) -> float:
        kind = pos_or_instr.kind if hasattr(pos_or_instr, "kind") else pos_or_instr.instrument.kind
        return self.option_slip if kind is AssetKind.OPTION else self.equity_slip

    def _charges(self, instrument, price: float, qty: int, is_buy: bool) -> float:
        if instrument.kind is AssetKind.OPTION:
            return costs.option_charges(price, qty, is_buy=is_buy).total
        return costs.equity_charges(price, qty, is_buy=is_buy, intraday=True).total

    @staticmethod
    def _kind(instrument) -> str:
        s = instrument.symbol
        if "SPREAD" in s:
            return "SPREAD"
        return "OPTION" if instrument.kind is AssetKind.OPTION else "EQUITY"

    def _project(self, req, fill_price, entry_charges):
        from .. import reports
        return reports.project_pnl(fill_price, req.stop, req.target, req.quantity,
                                   req.side.value, req.instrument.symbol, entry_charges)

    def _margin(self, pos: Position) -> float:
        notional = pos.entry_price * pos.quantity
        if pos.instrument.kind is AssetKind.OPTION:
            return notional if pos.side is Side.BUY else notional  # simplistic; refined for shorts later
        return notional / self.equity_leverage

    # ---------------- Broker interface ----------------
    def get_funds(self) -> Funds:
        blocked = sum(self._margin(p) for p in self._positions.values())
        cash = self.starting_capital + self.realized_pnl
        return Funds(available_balance=round(cash - blocked, 2),
                     utilized=round(blocked, 2))

    def get_ltp(self, security_id: str, segment: str) -> float:
        return self._prices.get(security_id, 0.0)

    def place_bracket(self, req: OrderRequest) -> OrderResult:
        if req.stop is None:
            return OrderResult(ok=False, status=OrderStatus.REJECTED,
                               message="no stop — refused")
        ltp = self._prices.get(req.instrument.security_id)
        if not ltp:
            return OrderResult(ok=False, status=OrderStatus.REJECTED,
                               message=f"no price for {req.instrument.symbol}")

        slip = self._slip(req.instrument)
        # entry fills against us (spreads are marked at mid — no synthetic slippage)
        if req.is_spread:
            fill_price = req.instrument.round_to_tick(ltp)
        else:
            fill_price = ltp * (1 + slip) if req.side is Side.BUY else ltp * (1 - slip)
            fill_price = req.instrument.round_to_tick(fill_price)
        # spreads carry a pre-computed full round-trip cost; else compute one side
        entry_charges = (req.charges if req.charges is not None
                         else self._charges(req.instrument, fill_price, req.quantity,
                                            is_buy=(req.side is Side.BUY)))

        order_id = f"PAPER-{next(_ids)}"
        entry_ts = now_ist().isoformat()
        pos = Position(
            instrument=req.instrument, side=req.side, quantity=req.quantity,
            entry_price=fill_price, stop=req.stop, target=req.target,
            order_id=order_id, strategy=req.strategy, entry_charges=entry_charges,
            ltp=ltp, trail_jump=req.trail_jump, is_spread=req.is_spread, entry_ts=entry_ts,
        )
        self._positions[order_id] = pos

        fill = Fill(req.instrument, req.side, req.quantity, fill_price,
                    entry_charges, entry_ts, kind="ENTRY")
        self.j.record_open(pos)
        self.j.record_fill(order_id, fill)
        # permanent suggestions ledger (a taken suggestion) with if-target/if-stop
        self.j.log_suggestion(req.instrument.symbol, self._kind(req.instrument),
                              req.strategy, req.side.value, fill_price, req.stop,
                              req.target, *self._project(req, fill_price, entry_charges),
                              taken=True)
        self.j.event("ENTRY",
                     f"{req.strategy} {req.side.value} {req.quantity} "
                     f"{req.instrument.symbol} @ {fill_price} "
                     f"stop={req.stop} target={req.target}")
        return OrderResult(ok=True, order_id=order_id, status=OrderStatus.OPEN,
                           position=pos)

    def modify_stop(self, order_id: str, new_stop: float) -> bool:
        pos = self._positions.get(order_id)
        if not pos:
            return False
        pos.stop = new_stop
        self.j.event("TRAIL", f"{pos.instrument.symbol} stop -> {new_stop}")
        return True

    def flatten(self, order_id: str) -> Optional[Position]:
        pos = self._positions.get(order_id)
        if not pos:
            return None
        ltp = self._prices.get(pos.instrument.security_id, pos.ltp)
        return self._exit(pos, ltp, reason="FLATTEN", limit=False)

    def get_positions(self) -> List[Position]:
        return list(self._positions.values())

    # ---------------- internal exit logic ----------------
    def _check_triggers(self, security_id: str, price: float) -> List[Position]:
        closed = []
        for pos in list(self._positions.values()):
            if pos.instrument.security_id != security_id:
                continue
            pos.ltp = price
            hit_stop = (price <= pos.stop) if pos.side is Side.BUY else (price >= pos.stop)
            hit_tgt = (pos.target is not None and
                       ((price >= pos.target) if pos.side is Side.BUY
                        else (price <= pos.target)))
            if hit_stop:
                closed.append(self._exit(pos, pos.stop, reason="STOP", limit=False))
            elif hit_tgt:
                closed.append(self._exit(pos, pos.target, reason="TARGET", limit=True))
        return [c for c in closed if c]

    def _exit(self, pos: Position, level: float, reason: str, limit: bool) -> Position:
        exit_side = pos.side.opposite
        if pos.is_spread:
            exit_price = pos.instrument.round_to_tick(level)   # marked at mid
            exit_charges = 0.0                                  # round-trip front-loaded at entry
        else:
            slip = 0.0 if limit else self._slip(pos)
            exit_price = level * (1 - slip) if exit_side is Side.SELL else level * (1 + slip)
            exit_price = pos.instrument.round_to_tick(exit_price)
            exit_charges = self._charges(pos.instrument, exit_price, pos.quantity,
                                         is_buy=(exit_side is Side.BUY))

        gross = (exit_price - pos.entry_price) * pos.quantity * pos.side.sign
        net = gross - pos.entry_charges - exit_charges
        self.realized_pnl += net
        self.j.add_realized_pnl(net)

        exit_ts = now_ist().isoformat()
        fill = Fill(pos.instrument, exit_side, pos.quantity, exit_price,
                    exit_charges, exit_ts, kind="EXIT")
        self.j.record_fill(pos.order_id, fill)
        self.j.record_close(pos.order_id)
        self.j.event(reason,
                     f"{pos.instrument.symbol} exit @ {exit_price} "
                     f"net={net:.2f} (gross={gross:.2f})")
        # permanent history (survives --reset) for week/month look-back
        self.j.log_history(pos.entry_ts or exit_ts, exit_ts, pos.instrument.symbol,
                           self._kind(pos.instrument), pos.strategy, pos.side.value,
                           pos.quantity, pos.entry_price, exit_price,
                           round(pos.entry_charges + exit_charges, 2), round(net, 2),
                           source="paper", reason=reason)
        del self._positions[pos.order_id]
        return pos
