"""Strategy contract. The SAME object is used by the backtester and the live
engine — so what we validate is exactly what trades.

A strategy turns a candle frame into three added columns, computed causally:
  signal  : +1 (go long), -1 (go short), 0 (nothing) — decided at bar close
  stop    : protective stop price for a signal bar (else NaN)
  target  : profit target price for a signal bar (else NaN)

The engine enters on the NEXT bar's open, so a signal at bar i never uses i+1.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class Strategy(ABC):
    name: str = "base"

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return df with 'signal', 'stop', 'target' columns added."""

    def _blank(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["signal"] = 0
        out["stop"] = float("nan")
        out["target"] = float("nan")
        return out
