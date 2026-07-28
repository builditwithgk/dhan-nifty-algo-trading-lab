"""Real historical NIFTY credit-spread backtest — on ACTUAL option prices.

Uses Dhan's expired-options "rolling" series (real premium + IV + spot per 5-min
bar, strike relative to spot: ATM, ATM-3, ...). This is the test the prior work
couldn't run: it priced spreads with a Black-Scholes guess; we use what the
options ACTUALLY traded at.

Strategy tested: weekly BULL-PUT SPREAD (harvests the put skew we measured).
  * Sell the ATM-`short_otm` put, buy the ATM-`long_otm` put as the hedge.
  * Enter near the start of each weekly cycle (max theta to collect).
  * Hold to expiry; settle at the real spot on expiry day.
  * Full option charges on all four legs (entry + exit), conservative.

Method notes / honesty:
  * Weekly expiry = Tuesday (NIFTY, 2026). Expiries are taken from Tuesdays
    present in the data; a holiday-shifted week is simply skipped.
  * The rolling series' strike moves with spot; we read the ACTUAL entry strikes
    from the data and settle on the ACTUAL expiry-day spot, so entry premium and
    payoff are both real. No Black-Scholes anywhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional

import numpy as np
import pandas as pd

from . import constants as C
from . import costs

LOT_NIFTY = 65


def _chunks(frm: str, to: str, max_days: int = 30):
    d0 = datetime.strptime(frm, "%Y-%m-%d")
    d1 = datetime.strptime(to, "%Y-%m-%d")
    cur = d0
    while cur < d1:
        end = min(cur + timedelta(days=max_days), d1)
        yield cur.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
        cur = end


def fetch_rolling_put(api, strike_label: str, frm: str, to: str,
                      interval: int = 5) -> pd.DataFrame:
    """Rolling nearest-weekly PUT series -> DataFrame[close, iv, strike, spot]."""
    frames = []
    for a, b in _chunks(frm, to):
        r = api.expired_options_data(
            security_id="13", exchange_segment=C.NSE_FNO, instrument_type="OPTIDX",
            expiry_flag="WEEK", expiry_code=1, strike=strike_label,
            drv_option_type="PUT",
            required_data=["close", "iv", "strike", "spot"],
            from_date=a, to_date=b, interval=interval)
        d = (r.get("data") or {}).get("data") or {}
        pe = d.get("pe") or {}
        ts = pe.get("timestamp") or []
        if not ts:
            continue
        frames.append(pd.DataFrame({
            "close": pe["close"], "iv": pe["iv"],
            "strike": pe["strike"], "spot": pe["spot"],
        }, index=pd.to_datetime(ts, unit="s")))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames).sort_index()
    return df[~df.index.duplicated(keep="first")]


def fetch_put_grid(api, frm: str, to: str, rel_low: int = 10, rel_high: int = 5,
                   interval: int = 60):
    """Pull a GRID of rolling puts (ATM+rel_high .. ATM-rel_low) so we can mark a
    FIXED spread's exact strikes intra-week (needed for a stop-loss). Returns
    (grid, spot) where grid is a DataFrame [timestamp x strike] = put close."""
    labels = ([f"ATM+{i}" for i in range(rel_high, 0, -1)] + ["ATM"]
              + [f"ATM-{i}" for i in range(1, rel_low + 1)])
    parts, spot_parts = [], []
    for lab in labels:
        d = fetch_rolling_put(api, lab, frm, to, interval)
        if d.empty:
            continue
        t = d.reset_index(names="ts")
        parts.append(t[["ts", "strike", "close"]])
        spot_parts.append(t[["ts", "spot"]])
    if not parts:
        return pd.DataFrame(), pd.Series(dtype=float)
    grid = (pd.concat(parts).pivot_table(index="ts", columns="strike",
                                         values="close", aggfunc="last").sort_index())
    spot = pd.concat(spot_parts).drop_duplicates("ts").set_index("ts")["spot"].sort_index()
    return grid, spot


@dataclass
class SpreadTrade:
    entry_time: pd.Timestamp
    expiry: pd.Timestamp
    short_strike: float
    long_strike: float
    credit: float          # per unit
    width: float           # points
    expiry_spot: float
    gross: float           # per unit P&L before costs
    charges: float
    net: float             # total rupees (x qty)


@dataclass
class SpreadResult:
    trades: List[SpreadTrade] = field(default_factory=list)

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


def _tuesday_expiries(index: pd.DatetimeIndex) -> List[pd.Timestamp]:
    dates = sorted({ts.normalize() for ts in index})
    return [d for d in dates if d.weekday() == 1]   # Tue=1


def _daily_sma_from_spot(series: pd.DataFrame, window: int = 20) -> pd.Series:
    """NIFTY daily close (last spot per day) and its SMA — for a regime filter.
    Uses only the option data's own spot column, so no extra API calls."""
    daily = series["spot"].groupby(series.index.normalize()).last()
    return daily.rolling(window, min_periods=window).mean()


def _regime_ok(sma: pd.Series, entry_date, entry_spot: float) -> bool:
    """Bullish regime = spot above its SMA, judged on the PRIOR day (no lookahead)."""
    prior = sma[sma.index < entry_date]
    if prior.empty or pd.isna(prior.iloc[-1]):
        return False          # not enough history -> skip (conservative)
    return entry_spot > prior.iloc[-1]


def backtest_bull_put(api, frm: str, to: str, short_otm: int = 3, long_otm: int = 6,
                      lots: int = 1, interval: int = 60,
                      regime_filter: bool = False, sma_window: int = 20) -> SpreadResult:
    short = fetch_rolling_put(api, f"ATM-{short_otm}", frm, to, interval)
    long_ = fetch_rolling_put(api, f"ATM-{long_otm}", frm, to, interval)
    res = SpreadResult()
    if short.empty or long_.empty:
        return res

    sma = _daily_sma_from_spot(short, sma_window) if regime_filter else None
    qty = LOT_NIFTY * lots
    expiries = _tuesday_expiries(short.index)
    prev_e = None
    for e in expiries:
        # entry = first bar strictly after the previous expiry, within this cycle
        lo = prev_e if prev_e is not None else short.index[0].normalize() - timedelta(days=1)
        prev_e = e
        cycle = short[(short.index.normalize() > lo) & (short.index.normalize() < e)]
        if cycle.empty:
            continue
        entry_ts = cycle.index[0]
        if entry_ts not in long_.index:
            near = long_.index[long_.index.get_indexer([entry_ts], method="nearest")[0]]
            if abs((near - entry_ts).total_seconds()) > 3600:
                continue
            entry_ts_long = near
        else:
            entry_ts_long = entry_ts

        s_row = short.loc[entry_ts]; l_row = long_.loc[entry_ts_long]
        if regime_filter and not _regime_ok(sma, entry_ts.normalize(), float(s_row["spot"])):
            continue          # skip the week: NIFTY not in an uptrend
        short_k, long_k = float(s_row["strike"]), float(l_row["strike"])
        short_prem, long_prem = float(s_row["close"]), float(l_row["close"])
        width = short_k - long_k
        if width <= 0 or short_prem <= 0:
            continue
        credit = short_prem - long_prem
        if credit <= 0:
            continue

        # settlement spot = last bar on expiry day
        e_bars = short[short.index.normalize() == e]
        if e_bars.empty:
            continue
        exp_spot = float(e_bars.iloc[-1]["spot"])

        short_pay = max(0.0, short_k - exp_spot)
        long_pay = max(0.0, long_k - exp_spot)
        spread_loss = min(width, short_pay - long_pay)      # capped at width
        gross_per_unit = credit - spread_loss

        # costs: 4 option legs (sell+buy entry, buy+sell exit), conservative
        ch = (costs.option_charges(short_prem, qty, is_buy=False).total
              + costs.option_charges(long_prem, qty, is_buy=True).total
              + costs.option_charges(max(short_pay, 0.05), qty, is_buy=True).total
              + costs.option_charges(max(long_pay, 0.05), qty, is_buy=False).total)
        net = gross_per_unit * qty - ch
        res.trades.append(SpreadTrade(
            entry_time=entry_ts, expiry=e, short_strike=short_k, long_strike=long_k,
            credit=round(credit, 2), width=width, expiry_spot=exp_spot,
            gross=round(gross_per_unit, 2), charges=round(ch, 2), net=round(net, 2)))
    return res


def backtest_bull_put_managed(api, frm: str, to: str, short_otm: int = 3,
                              long_otm: int = 6, stop_mult: float = 2.0,
                              lots: int = 1, interval: int = 60) -> SpreadResult:
    """Bull-put spread with a HARD intra-week STOP: close if the spread's buyback
    cost reaches stop_mult x the credit (e.g. 2x credit => lose ~1x credit),
    instead of riding every loser to expiry. Uses the real strike grid to mark
    the exact held strikes bar by bar."""
    grid, spot = fetch_put_grid(api, frm, to, interval=interval)
    res = SpreadResult()
    if grid.empty:
        return res
    qty = LOT_NIFTY * lots
    strikes = np.array(sorted(grid.columns))
    expiries = _tuesday_expiries(grid.index)
    prev_e = None

    def price(ts, strike):
        if strike in grid.columns and ts in grid.index:
            v = grid.at[ts, strike]
            return float(v) if pd.notna(v) else None
        return None

    for e in expiries:
        lo = prev_e if prev_e is not None else grid.index[0].normalize() - timedelta(days=1)
        prev_e = e
        cycle = spot[(spot.index.normalize() > lo) & (spot.index.normalize() < e)]
        if cycle.empty:
            continue
        entry_ts = cycle.index[0]
        entry_spot = float(spot.loc[entry_ts])
        atm = round(entry_spot / 50) * 50
        short_k = atm - short_otm * 50
        long_k = atm - long_otm * 50
        sp, lp = price(entry_ts, short_k), price(entry_ts, long_k)
        if sp is None or lp is None:
            continue
        credit = sp - lp
        width = short_k - long_k
        if credit <= 0 or width <= 0:
            continue

        # walk the cycle to expiry, checking the stop each bar
        path = grid.index[(grid.index > entry_ts) & (grid.index.normalize() <= e)]
        exit_val = None
        for ts in path:
            s2, l2 = price(ts, short_k), price(ts, long_k)
            if s2 is None or l2 is None:
                continue
            spread_val = s2 - l2                     # cost to buy back
            if spread_val >= stop_mult * credit:
                exit_val = spread_val
                break
        if exit_val is None:                          # not stopped -> settle at expiry
            exp_spot = float(spot[spot.index.normalize() == e].iloc[-1])
            short_pay = max(0.0, short_k - exp_spot)
            long_pay = max(0.0, long_k - exp_spot)
            exit_val = min(width, short_pay - long_pay)
            exp_ref = exp_spot
        else:
            exp_ref = float('nan')

        gross_per_unit = credit - exit_val
        ch = (costs.option_charges(sp, qty, is_buy=False).total
              + costs.option_charges(lp, qty, is_buy=True).total
              + costs.option_charges(max(exit_val + lp, 0.05), qty, is_buy=True).total
              + costs.option_charges(max(lp, 0.05), qty, is_buy=False).total)
        net = gross_per_unit * qty - ch
        res.trades.append(SpreadTrade(
            entry_time=entry_ts, expiry=e, short_strike=short_k, long_strike=long_k,
            credit=round(credit, 2), width=width, expiry_spot=exp_ref,
            gross=round(gross_per_unit, 2), charges=round(ch, 2), net=round(net, 2)))
    return res
