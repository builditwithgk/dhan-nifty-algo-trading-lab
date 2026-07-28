"""Opening Range Breakout — session-anchored (fixes the peer-repo bug where the
'opening range' was the first bars of a multi-day frame).

Per trading day:
  * The opening range (OR) = high/low of the first `or_minutes`.
  * The FIRST bar that closes beyond the OR triggers a trade (long above, short
    below). One trade per day.
  * Stop = the opposite end of the OR. Target = entry +/- target_r * OR-width.
  * No entries after `entry_cutoff` or in the last part of the day.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import Strategy


class OpeningRangeBreakout(Strategy):
    name = "orb"

    def __init__(self, or_minutes: int = 15, bar_minutes: int = 5,
                 target_r: float = 1.5, entry_cutoff: str = "14:30"):
        self.or_bars = max(1, or_minutes // bar_minutes)
        self.target_r = target_r
        self.cutoff = entry_cutoff

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = self._blank(df)
        cutoff_h, cutoff_m = map(int, self.cutoff.split(":"))
        for _, day in out.groupby(out.index.normalize()):
            if len(day) <= self.or_bars:
                continue
            or_block = day.iloc[:self.or_bars]
            or_high, or_low = or_block["high"].max(), or_block["low"].min()
            width = or_high - or_low
            if width <= 0:
                continue
            traded = False
            for ts, row in day.iloc[self.or_bars:].iterrows():
                if traded or (ts.hour, ts.minute) >= (cutoff_h, cutoff_m):
                    break
                if row["close"] > or_high:
                    out.at[ts, "signal"] = 1
                    out.at[ts, "stop"] = or_low
                    out.at[ts, "target"] = row["close"] + self.target_r * width
                    traded = True
                elif row["close"] < or_low:
                    out.at[ts, "signal"] = -1
                    out.at[ts, "stop"] = or_high
                    out.at[ts, "target"] = row["close"] - self.target_r * width
                    traded = True
        return out
