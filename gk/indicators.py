"""Causal technical indicators (pure pandas/numpy — no external TA lib).

Every function uses only past+current data, so a value at bar i never peeks at
i+1. VWAP is SESSION-ANCHORED (reset each trading day) — the reviewed repos got
this wrong by running VWAP/ORB across multi-day frames.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def rsi(s: pd.Series, period: int = 14) -> pd.Series:
    delta = s.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def session_vwap(df: pd.DataFrame) -> pd.Series:
    """VWAP reset each calendar day (IST index required)."""
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    tpv = tp * df["volume"]
    day = df.index.normalize()
    cum_tpv = tpv.groupby(day).cumsum()
    cum_vol = df["volume"].groupby(day).cumsum().replace(0, np.nan)
    return (cum_tpv / cum_vol).ffill()


def rolling_high(s: pd.Series, n: int) -> pd.Series:
    """Highest of the PRIOR n bars (excludes current)."""
    return s.rolling(n).max().shift(1)


def rolling_low(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).min().shift(1)


def avg_volume(df: pd.DataFrame, n: int = 20) -> pd.Series:
    return df["volume"].rolling(n).mean().shift(1)


def day_key(df: pd.DataFrame) -> pd.Series:
    return pd.Series(df.index.normalize(), index=df.index)
