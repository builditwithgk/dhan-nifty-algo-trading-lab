"""Directional option-BUYING backtest on real NIFTF option data.

Opposite payoff to spread-selling: loss is capped at the premium, but a strong
directional move pays off convexly (gamma). So a sub-50% hit rate can still win
IF the underlying makes real moves. We test that honestly on actual prices.

Signal:  NIFTY opening-range breakout (first 30 min). Break up -> buy ATM CE;
         break down -> buy ATM PE. One trade/day.
Manage:  stop at -sl% of premium, target at +tp% of premium, else exit at EOD.
         The specific strike is marked bar-by-bar from a real option grid.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from . import constants as C
from . import costs

LOT = 65
IST = "Asia/Kolkata"


def _rolling_option(api, opt_type: str, label: str, frm: str, to: str, interval: int):
    key = "ce" if opt_type == "CALL" else "pe"
    frames = []
    for a, b in _chunks(frm, to):
        r = api.expired_options_data(
            security_id="13", exchange_segment=C.NSE_FNO, instrument_type="OPTIDX",
            expiry_flag="WEEK", expiry_code=1, strike=label, drv_option_type=opt_type,
            required_data=["close", "strike", "spot"], from_date=a, to_date=b, interval=interval)
        d = (r.get("data") or {}).get("data") or {}
        leg = d.get(key) or {}
        ts = leg.get("timestamp") or []
        if ts:
            frames.append(pd.DataFrame(
                {"strike": leg["strike"], "close": leg["close"], "spot": leg["spot"]},
                index=pd.to_datetime(ts, unit="s", utc=True).tz_convert(IST)))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames).sort_index()
    return df[~df.index.duplicated(keep="first")]


def _chunks(frm, to, max_days=30):
    d0 = datetime.strptime(frm, "%Y-%m-%d"); d1 = datetime.strptime(to, "%Y-%m-%d")
    cur = d0
    while cur < d1:
        end = min(cur + timedelta(days=max_days), d1)
        yield cur.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
        cur = end


def option_grid(api, opt_type: str, frm: str, to: str, interval: int = 5,
                rel: int = 3):
    labels = [f"ATM+{i}" for i in range(rel, 0, -1)] + ["ATM"] + [f"ATM-{i}" for i in range(1, rel + 1)]
    parts, spot_parts = [], []
    for lab in labels:
        d = _rolling_option(api, opt_type, lab, frm, to, interval)
        if d.empty:
            continue
        t = d.reset_index(names="ts")
        parts.append(t[["ts", "strike", "close"]]); spot_parts.append(t[["ts", "spot"]])
    if not parts:
        return pd.DataFrame(), pd.Series(dtype=float)
    grid = pd.concat(parts).pivot_table(index="ts", columns="strike", values="close",
                                        aggfunc="last").sort_index()
    spot = pd.concat(spot_parts).drop_duplicates("ts").set_index("ts")["spot"].sort_index()
    return grid, spot


@dataclass
class OBTrade:
    entry_time: pd.Timestamp
    opt_type: str
    strike: float
    entry_prem: float
    exit_prem: float
    net: float
    reason: str


@dataclass
class OBResult:
    trades: List[OBTrade] = field(default_factory=list)
    @property
    def n(self): return len(self.trades)
    @property
    def net_pnl(self): return sum(t.net for t in self.trades)
    @property
    def wins(self): return sum(1 for t in self.trades if t.net > 0)
    @property
    def win_rate(self): return self.wins / self.n if self.n else 0.0
    @property
    def profit_factor(self):
        gp = sum(t.net for t in self.trades if t.net > 0)
        gl = -sum(t.net for t in self.trades if t.net < 0)
        return gp / gl if gl > 0 else float("inf") if gp > 0 else 0.0
    @property
    def max_loss(self): return min((t.net for t in self.trades), default=0.0)


def backtest_option_buy(api, frm: str, to: str, or_min: int = 30, bar_min: int = 5,
                        sl_pct: float = 35, tp_pct: float = 60, lots: int = 1,
                        entry_cutoff: str = "13:30") -> OBResult:
    ce_grid, spot = option_grid(api, "CALL", frm, to, interval=bar_min)
    pe_grid, _ = option_grid(api, "PUT", frm, to, interval=bar_min)
    res = OBResult()
    if ce_grid.empty or pe_grid.empty or spot.empty:
        return res

    qty = LOT * lots
    or_bars = or_min // bar_min
    cutoff = tuple(map(int, entry_cutoff.split(":")))
    sl, tp = sl_pct / 100.0, tp_pct / 100.0

    def price(grid, ts, strike):
        if ts in grid.index and strike in grid.columns:
            v = grid.at[ts, strike]
            return float(v) if pd.notna(v) else None
        return None

    for day, sser in spot.groupby(spot.index.normalize()):
        if len(sser) <= or_bars + 2:
            continue
        or_block = sser.iloc[:or_bars]
        or_hi, or_lo = or_block.max(), or_block.min()
        after = sser.iloc[or_bars:]
        entered = False
        for ts, sp in after.items():
            if entered or (ts.hour, ts.minute) >= cutoff:
                break
            direction = None
            if sp > or_hi:
                direction = ("CALL", ce_grid)
            elif sp < or_lo:
                direction = ("PUT", pe_grid)
            if direction is None:
                continue
            opt_type, grid = direction
            atm = round(sp / 50) * 50
            entry_prem = price(grid, ts, atm)
            if entry_prem is None or entry_prem <= 0:
                continue
            # manage to EOD
            path = sser[sser.index > ts]
            exit_prem, reason = None, None
            for ts2 in path.index:
                p = price(grid, ts2, atm)
                if p is None:
                    continue
                if p <= entry_prem * (1 - sl):
                    exit_prem, reason = entry_prem * (1 - sl), "STOP"; break
                if p >= entry_prem * (1 + tp):
                    exit_prem, reason = entry_prem * (1 + tp), "TARGET"; break
            if exit_prem is None:
                last_p = None
                for ts2 in reversed(path.index):
                    last_p = price(grid, ts2, atm)
                    if last_p is not None:
                        break
                exit_prem, reason = (last_p if last_p is not None else entry_prem), "EOD"
            ch = (costs.option_charges(entry_prem, qty, is_buy=True).total
                  + costs.option_charges(max(exit_prem, 0.05), qty, is_buy=False).total)
            net = (exit_prem - entry_prem) * qty - ch
            res.trades.append(OBTrade(ts, opt_type, atm, round(entry_prem, 2),
                                      round(exit_prem, 2), round(net, 2), reason))
            entered = True
    return res
