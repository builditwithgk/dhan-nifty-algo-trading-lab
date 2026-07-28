"""VWAP mean-reversion — a DIFFERENT edge type than breakout.

Idea: intraday, price that stretches too far from the session VWAP and is
overbought/oversold tends to snap back toward VWAP. We fade the extreme.
  * Long  when price is >= band% BELOW VWAP and RSI oversold  -> target = VWAP.
  * Short when price is >= band% ABOVE VWAP and RSI overbought -> target = VWAP.
Stop is an ATR beyond the entry. All causal; entry on next bar's open.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import indicators as ind
from .base import Strategy


class VWAPReversion(Strategy):
    name = "vwap_rev"

    def __init__(self, band_pct: float = 0.5, rsi_os: float = 30, rsi_ob: float = 70,
                 stop_atr: float = 1.0, entry_cutoff: str = "14:30"):
        self.band = band_pct / 100.0
        self.rsi_os = rsi_os
        self.rsi_ob = rsi_ob
        self.stop_atr = stop_atr
        self.cutoff = entry_cutoff

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = self._blank(df)
        vwap = ind.session_vwap(df)
        rsi = ind.rsi(df["close"], 14)
        atr = ind.atr(df, 14)
        dev = (df["close"] - vwap) / vwap

        cutoff_h, cutoff_m = map(int, self.cutoff.split(":"))
        before = pd.Series([(t.hour, t.minute) < (cutoff_h, cutoff_m) for t in df.index],
                           index=df.index)

        long_ok = (dev <= -self.band) & (rsi <= self.rsi_os) & before & (atr > 0)
        short_ok = (dev >= self.band) & (rsi >= self.rsi_ob) & before & (atr > 0)

        out.loc[long_ok, "signal"] = 1
        out.loc[long_ok, "stop"] = (df["close"] - self.stop_atr * atr)[long_ok]
        out.loc[long_ok, "target"] = vwap[long_ok]

        out.loc[short_ok, "signal"] = -1
        out.loc[short_ok, "stop"] = (df["close"] + self.stop_atr * atr)[short_ok]
        out.loc[short_ok, "target"] = vwap[short_ok]

        # drop degenerate (target on wrong side, or NaN)
        bad = out["signal"].ne(0) & (
            out["stop"].isna() | out["target"].isna() |
            ((out["signal"] == 1) & (out["target"] <= df["close"])) |
            ((out["signal"] == -1) & (out["target"] >= df["close"]))
        )
        out.loc[bad, ["signal", "stop", "target"]] = [0, np.nan, np.nan]
        return out
