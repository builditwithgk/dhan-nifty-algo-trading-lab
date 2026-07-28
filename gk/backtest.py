"""No-lookahead intraday backtest engine.

Rules that keep it honest (each mirrors the live PaperBroker so backtest == live):
  * A signal at bar i is entered at bar i+1's OPEN. Never peeks at the future.
  * Intrabar exits: within a bar, the STOP is checked before the target (if both
    are touched, we assume the stop — conservative).
  * Entry fills slip against us; stop exits slip; target fills at the limit.
  * Full Indian intraday charges on entry and exit (costs.py).
  * Everything is squared off at `square_off`; no position crosses a day.
  * Size is the SAME risk-based sizing the live path uses (so net-of-cost P&L is
    realistic, including the fixed brokerage drag on small trades).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import numpy as np
import pandas as pd

from . import costs
from .models import Instrument
from .risk import size_position
from .strategies.base import Strategy


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    side: int
    entry: float
    exit: float
    qty: int
    gross: float
    charges: float
    net: float
    reason: str


@dataclass
class BacktestResult:
    strategy: str
    symbol: str
    trades: List[Trade] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.trades)

    @property
    def net_pnl(self) -> float:
        return sum(t.net for t in self.trades)

    @property
    def total_charges(self) -> float:
        return sum(t.charges for t in self.trades)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t.net > 0)

    @property
    def win_rate(self) -> float:
        return self.wins / self.n if self.n else 0.0

    @property
    def profit_factor(self) -> float:
        gp = sum(t.net for t in self.trades if t.net > 0)
        gl = -sum(t.net for t in self.trades if t.net < 0)
        return (gp / gl) if gl > 0 else float("inf") if gp > 0 else 0.0

    @property
    def expectancy(self) -> float:
        return self.net_pnl / self.n if self.n else 0.0

    @property
    def max_drawdown(self) -> float:
        if not self.trades:
            return 0.0
        eq = np.cumsum([t.net for t in self.trades])
        peak = np.maximum.accumulate(eq)
        return float(np.max(peak - eq)) if len(eq) else 0.0


def run(df: pd.DataFrame, strategy: Strategy, instrument: Instrument,
        risk_rupees: float, max_notional: float,
        slippage_pct: float = 0.03, square_off: str = "15:15") -> BacktestResult:
    res = BacktestResult(strategy=strategy.name, symbol=instrument.symbol)
    if df is None or len(df) < 30:
        return res

    sig = strategy.generate_signals(df)
    o = df["open"].values; h = df["high"].values
    l = df["low"].values; c = df["close"].values
    s_sig = sig["signal"].values; s_stop = sig["stop"].values; s_tgt = sig["target"].values
    idx = df.index
    day = idx.normalize()
    so_h, so_m = map(int, square_off.split(":"))
    slip = slippage_pct / 100.0
    n = len(df)
    pos = None

    def _charges(price, qty, is_buy):
        return costs.equity_charges(price, qty, is_buy=is_buy, intraday=True).total

    for i in range(n):
        t = idx[i]
        is_so = (t.hour, t.minute) >= (so_h, so_m)
        last_of_day = (i == n - 1) or (day[i + 1] != day[i])

        # 1) OPEN at this bar's open if the PRIOR bar (same day) signalled.
        if pos is None and i > 0 and day[i - 1] == day[i] and not is_so and not last_of_day:
            ps = s_sig[i - 1]
            if ps != 0:
                stop = s_stop[i - 1]; tgt = s_tgt[i - 1]; side = int(ps)
                entry = o[i] * (1 + slip) if side == 1 else o[i] * (1 - slip)
                entry = instrument.round_to_tick(entry)
                # stop must still be on the correct side after the open
                valid = (stop < entry) if side == 1 else (stop > entry)
                if valid and not np.isnan(stop) and not np.isnan(tgt):
                    sized = size_position(instrument, entry, stop, risk_rupees, max_notional)
                    if sized.ok:
                        pos = dict(side=side, entry=entry, stop=stop, target=tgt,
                                   qty=sized.quantity, entry_time=t,
                                   entry_charges=_charges(entry, sized.quantity, side == 1))

        # 2) MANAGE the (possibly just-opened) position on THIS bar.
        if pos is not None:
            exit_price = None; reason = None
            if pos["side"] == 1:
                if l[i] <= pos["stop"]:
                    exit_price = pos["stop"] * (1 - slip); reason = "STOP"
                elif h[i] >= pos["target"]:
                    exit_price = pos["target"]; reason = "TARGET"
            else:
                if h[i] >= pos["stop"]:
                    exit_price = pos["stop"] * (1 + slip); reason = "STOP"
                elif l[i] <= pos["target"]:
                    exit_price = pos["target"]; reason = "TARGET"
            if exit_price is None and (is_so or last_of_day):
                exit_price = c[i] * (1 - slip) if pos["side"] == 1 else c[i] * (1 + slip)
                reason = "SQUAREOFF" if is_so else "EOD"

            if exit_price is not None:
                exit_price = instrument.round_to_tick(exit_price)
                is_buy_exit = pos["side"] == -1
                exit_ch = _charges(exit_price, pos["qty"], is_buy_exit)
                gross = (exit_price - pos["entry"]) * pos["qty"] * pos["side"]
                charges = pos["entry_charges"] + exit_ch
                res.trades.append(Trade(
                    entry_time=pos["entry_time"], exit_time=t, side=pos["side"],
                    entry=pos["entry"], exit=exit_price, qty=pos["qty"],
                    gross=round(gross, 2), charges=round(charges, 2),
                    net=round(gross - charges, 2), reason=reason))
                pos = None

    return res
