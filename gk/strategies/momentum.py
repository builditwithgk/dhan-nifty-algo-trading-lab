"""Momentum "mover" strategy — the movement + volume + level-break logic we
discussed. A stock qualifies as a genuine mover only when all three align:

  * TREND     : EMA(fast) above EMA(slow)  (and price on the right side of VWAP)
  * VOLUME    : current volume > vol_mult x its recent average (real interest)
  * LEVEL     : price breaks the prior `breakout_n`-bar high (or low for shorts)

Stop = recent swing low/high; target = target_r x risk. All causal; entries are
taken by the engine on the next bar's open. Session-anchored VWAP.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import indicators as ind
from .base import Strategy


class MomentumMover(Strategy):
    name = "momentum"

    def __init__(self, ema_fast: int = 9, ema_slow: int = 21, vol_mult: float = 1.5,
                 breakout_n: int = 12, stop_lookback: int = 10, target_r: float = 2.0,
                 entry_cutoff: str = "14:30"):
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.vol_mult = vol_mult
        self.breakout_n = breakout_n
        self.stop_lookback = stop_lookback
        self.target_r = target_r
        self.cutoff = entry_cutoff

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = self._blank(df)
        ef = ind.ema(df["close"], self.ema_fast)
        es = ind.ema(df["close"], self.ema_slow)
        vwap = ind.session_vwap(df)
        vol_avg = ind.avg_volume(df, 20)
        prior_high = ind.rolling_high(df["high"], self.breakout_n)
        prior_low = ind.rolling_low(df["low"], self.breakout_n)
        swing_low = ind.rolling_low(df["low"], self.stop_lookback)
        swing_high = ind.rolling_high(df["high"], self.stop_lookback)

        vol_spike = df["volume"] > self.vol_mult * vol_avg
        cutoff_h, cutoff_m = map(int, self.cutoff.split(":"))
        before_cutoff = pd.Series(
            [(t.hour, t.minute) < (cutoff_h, cutoff_m) for t in df.index],
            index=df.index)

        long_ok = (ef > es) & (df["close"] > vwap) & vol_spike & \
                  (df["close"] > prior_high) & before_cutoff
        short_ok = (ef < es) & (df["close"] < vwap) & vol_spike & \
                   (df["close"] < prior_low) & before_cutoff

        # Long entries
        out.loc[long_ok, "signal"] = 1
        out.loc[long_ok, "stop"] = swing_low[long_ok]
        risk = (df["close"] - swing_low)
        out.loc[long_ok, "target"] = df["close"][long_ok] + self.target_r * risk[long_ok]

        # Short entries (don't overwrite longs; they're mutually exclusive here)
        out.loc[short_ok, "signal"] = -1
        out.loc[short_ok, "stop"] = swing_high[short_ok]
        risk_s = (swing_high - df["close"])
        out.loc[short_ok, "target"] = df["close"][short_ok] - self.target_r * risk_s[short_ok]

        # Drop signals with an invalid/degenerate stop (NaN or wrong side).
        bad = out["signal"].ne(0) & (
            out["stop"].isna() | out["target"].isna() |
            ((out["signal"] == 1) & (out["stop"] >= df["close"])) |
            ((out["signal"] == -1) & (out["stop"] <= df["close"]))
        )
        out.loc[bad, ["signal", "stop", "target"]] = [0, np.nan, np.nan]
        return out
