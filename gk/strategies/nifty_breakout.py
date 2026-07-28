"""NIFTY intraday breakout — an ACTIVE directional signal for options.

Unlike ORB (one signal/day at the open), this fires every time NIFTY makes a
FRESH break of its recent range, so it produces several signals through the day
— enough to actually see option trades happen. Price-only (the index has no
tradable volume), direction-only (the option leg sets its own premium stop/target).
"""
from __future__ import annotations

import pandas as pd

from .. import indicators as ind
from .base import Strategy


class NiftyIntradayBreakout(Strategy):
    name = "nifty_breakout"

    def __init__(self, lookback: int = 20, entry_cutoff: str = "14:00"):
        self.lookback = lookback
        self.cutoff = entry_cutoff

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = self._blank(df)
        ph = ind.rolling_high(df["high"], self.lookback)
        pl = ind.rolling_low(df["low"], self.lookback)
        # fresh break = crosses the prior extreme this bar (not already beyond it)
        up = (df["close"] > ph) & (df["close"].shift(1) <= ph.shift(1))
        dn = (df["close"] < pl) & (df["close"].shift(1) >= pl.shift(1))
        ch, cm = map(int, self.cutoff.split(":"))
        before = pd.Series([(t.hour, t.minute) < (ch, cm) for t in df.index], index=df.index)
        out.loc[up & before, "signal"] = 1     # break up  -> buy CE
        out.loc[dn & before, "signal"] = -1    # break down -> buy PE
        return out
