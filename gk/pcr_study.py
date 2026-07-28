"""Does PCR predict NIFTY's next move? A clean, honest test.

PCR (Put-Call Ratio) = total put OI / total call OI. We compute it daily from
REAL historical open interest (near-the-money band, ATM +/- `rel` strikes), then
ask a simple question: does today's PCR predict tomorrow's NIFTY return?

We test the SIGNAL on the underlying directly (spot returns), before any option
trading costs — if there's no predictive power here, no PCR strategy can work.
Both readings are checked:
  * momentum  : low PCR -> up next day  (negative corr of PCR vs next return)
  * contrarian: low PCR -> down next day (positive corr)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from . import constants as C

IST = "Asia/Kolkata"


def _chunks(frm, to, max_days=30):
    d0 = datetime.strptime(frm, "%Y-%m-%d"); d1 = datetime.strptime(to, "%Y-%m-%d")
    cur = d0
    while cur < d1:
        end = min(cur + timedelta(days=max_days), d1)
        yield cur.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
        cur = end


def _daily_oi_and_spot(api, opt_type: str, label: str, frm: str, to: str, interval: int):
    """EOD open interest (and spot) per day for one relative strike."""
    key = "ce" if opt_type == "CALL" else "pe"
    frames = []
    for a, b in _chunks(frm, to):
        r = api.expired_options_data(
            security_id="13", exchange_segment=C.NSE_FNO, instrument_type="OPTIDX",
            expiry_flag="WEEK", expiry_code=1, strike=label, drv_option_type=opt_type,
            required_data=["oi", "spot"], from_date=a, to_date=b, interval=interval)
        d = (r.get("data") or {}).get("data") or {}
        leg = d.get(key) or {}
        ts = leg.get("timestamp") or []
        if ts:
            idx = pd.to_datetime(ts, unit="s", utc=True).tz_convert(IST)
            frames.append(pd.DataFrame({"oi": leg["oi"], "spot": leg["spot"]}, index=idx))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames).sort_index()
    df = df[~df.index.duplicated(keep="first")]
    # EOD value per day
    return df.groupby(df.index.normalize()).last()


def build_daily_pcr(api, frm: str, to: str, rel: int = 4, interval: int = 60) -> pd.DataFrame:
    labels = [f"ATM+{i}" for i in range(rel, 0, -1)] + ["ATM"] + [f"ATM-{i}" for i in range(1, rel + 1)]
    ce_oi, pe_oi, spot = None, None, None
    for lab in labels:
        ce = _daily_oi_and_spot(api, "CALL", lab, frm, to, interval)
        pe = _daily_oi_and_spot(api, "PUT", lab, frm, to, interval)
        if not ce.empty:
            ce_oi = ce["oi"] if ce_oi is None else ce_oi.add(ce["oi"], fill_value=0)
            spot = ce["spot"] if spot is None else spot.combine_first(ce["spot"])
        if not pe.empty:
            pe_oi = pe["oi"] if pe_oi is None else pe_oi.add(pe["oi"], fill_value=0)
    if ce_oi is None or pe_oi is None:
        return pd.DataFrame()
    df = pd.DataFrame({"ce_oi": ce_oi, "pe_oi": pe_oi, "spot": spot}).dropna()
    df["pcr"] = df["pe_oi"] / df["ce_oi"]
    df["ret_next"] = df["spot"].pct_change().shift(-1) * 100   # next-day % return
    return df.dropna()


@dataclass
class PCRResult:
    n: int
    corr: float                 # Spearman(pcr, next return)
    mean_ret_low: float         # PCR < 1
    mean_ret_high: float        # PCR >= 1
    up_rate_low: float          # % up-days after PCR<1
    up_rate_high: float
    baseline_ret: float         # unconditional mean next-day return
    quintile: pd.Series         # mean next return by PCR quintile

    def verdict(self) -> str:
        if abs(self.corr) < 0.1:
            return "NO predictive power — PCR does not forecast next-day direction."
        if self.corr < 0:
            return "momentum sign: LOWER PCR -> higher next return (your rule's direction)."
        return "contrarian sign: HIGHER PCR -> higher next return (opposite of the rule)."


def analyze(df: pd.DataFrame) -> PCRResult:
    corr = df["pcr"].corr(df["ret_next"], method="spearman")
    low, high = df[df.pcr < 1.0], df[df.pcr >= 1.0]
    q = pd.qcut(df["pcr"], 5, labels=[f"Q{i}" for i in range(1, 6)], duplicates="drop")
    quint = df.groupby(q, observed=True)["ret_next"].mean()
    return PCRResult(
        n=len(df), corr=float(corr),
        mean_ret_low=float(low["ret_next"].mean()) if len(low) else float("nan"),
        mean_ret_high=float(high["ret_next"].mean()) if len(high) else float("nan"),
        up_rate_low=float((low["ret_next"] > 0).mean() * 100) if len(low) else float("nan"),
        up_rate_high=float((high["ret_next"] > 0).mean() * 100) if len(high) else float("nan"),
        baseline_ret=float(df["ret_next"].mean()),
        quintile=quint,
    )
