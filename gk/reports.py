"""Performance reporting — turns the trade journal into day-by-day P&L, an
equity curve, breakdowns, and summary stats. Used by the dashboard's Performance
panel and the standalone Excel report (run_report.py).

The raw data is every ENTRY/EXIT fill already stored in the journal, so history
is fully reconstructable for any period — nothing needs to be pre-aggregated.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd


def _is_option(sym: str) -> bool:
    s = str(sym)
    return " CE" in s or " PE" in s or "SPREAD" in s


def project_pnl(entry, stop, target, qty, side, symbol, entry_charge=0.0):
    """Projected rupee P&L if the TARGET hits vs if the STOP hits, net of costs.

    Works for equity, single options, and credit spreads:
      * side +1 for BUY (long), -1 for SELL (short/credit spread)
      * for spreads, entry/stop/target are the net value and the full round-trip
        cost is already the entry_charge (front-loaded), so we use it directly.
    Returns (profit_if_target, loss_if_stop), both in rupees (loss is negative).
    """
    from gk import costs
    entry, stop, target, qty = float(entry), float(stop), float(target), int(qty)
    sign = 1 if str(side).upper() == "BUY" else -1
    s = str(symbol)
    is_spread = "SPREAD" in s
    is_opt = is_spread or " CE" in s or " PE" in s
    gt = (target - entry) * qty * sign          # gross at target
    gs = (stop - entry) * qty * sign            # gross at stop
    if is_spread:
        ct = cs = float(entry_charge)           # full round trip front-loaded
    elif is_opt:
        ct = costs.round_trip_option(entry, target, qty, is_long=(sign == 1))
        cs = costs.round_trip_option(entry, stop, qty, is_long=(sign == 1))
    else:
        ct = costs.round_trip_equity(entry, target, qty)
        cs = costs.round_trip_equity(entry, stop, qty)
    return round(gt - ct, 0), round(gs - cs, 0)


def load_trades(db_path) -> pd.DataFrame:
    """Completed trades (paired ENTRY+EXIT fills) with net P&L, net of costs."""
    p = Path(db_path)
    if not p.exists():
        return pd.DataFrame()
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        fills = pd.read_sql_query("SELECT * FROM fills ORDER BY id", con)
        orders = pd.read_sql_query("SELECT order_id, strategy FROM orders", con)
    except Exception:
        return pd.DataFrame()
    finally:
        con.close()
    if fills.empty:
        return pd.DataFrame()
    strat = dict(zip(orders.order_id, orders.strategy)) if not orders.empty else {}
    rows = []
    for oid, g in fills.groupby("order_id"):
        e, x = g[g.kind == "ENTRY"], g[g.kind == "EXIT"]
        if e.empty or x.empty:
            continue
        e, x = e.iloc[0], x.iloc[0]
        sign = 1 if e.side == "BUY" else -1
        gross = (x.price - e.price) * e.quantity * sign
        charges = e.charges + x.charges
        rows.append(dict(
            symbol=e.symbol, strategy=strat.get(oid, "?"),
            kind="OPTION" if _is_option(e.symbol) else "EQUITY", side=e.side,
            qty=int(e.quantity), entry=round(e.price, 2), exit=round(x.price, 2),
            gross=round(gross, 2), charges=round(charges, 2),
            net=round(gross - charges, 2), entry_ts=e.ts, exit_ts=x.ts,
            date=str(x.ts)[:10]))
    return pd.DataFrame(rows)


def load_history(db_path) -> pd.DataFrame:
    """PERMANENT trade history (survives --reset) — the multi-day / week / month
    record. Each row is a completed trade with net P&L."""
    p = Path(db_path)
    if not p.exists():
        return pd.DataFrame()
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        df = pd.read_sql_query("SELECT * FROM history ORDER BY id", con)
    except Exception:
        return pd.DataFrame()
    finally:
        con.close()
    if df.empty:
        return df
    df["gross"] = (df["net"] + df["charges"]).round(2)      # for daily_pnl compatibility
    return df


def last_n_days(df: pd.DataFrame, days: int) -> pd.DataFrame:
    """Filter a history/trades frame to the last `days` calendar days (0 = all)."""
    if df.empty or not days:
        return df
    from datetime import date, timedelta
    cutoff = (date.today() - timedelta(days=days - 1)).isoformat()
    return df[df["date"] >= cutoff]


def daily_pnl(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    d = trades.groupby("date").agg(
        trades=("net", "size"),
        wins=("net", lambda s: int((s > 0).sum())),
        gross=("gross", "sum"),
        costs=("charges", "sum"),
        net=("net", "sum"),
    ).reset_index()
    d["win_rate"] = (d["wins"] / d["trades"] * 100).round(0)
    d["cum_net"] = d["net"].cumsum().round(0)
    for c in ("gross", "costs", "net"):
        d[c] = d[c].round(0)
    return d


def summary(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {}
    net = trades["net"]
    wins, losses = net[net > 0], net[net < 0]
    daily = daily_pnl(trades)
    eq = daily["cum_net"].values if not daily.empty else np.array([0.0])
    peak = np.maximum.accumulate(eq)
    dd = float(np.max(peak - eq)) if len(eq) else 0.0
    gl = abs(losses.sum())
    return dict(
        total_net=round(net.sum(), 0), n_trades=int(len(trades)),
        days=int(len(daily)),
        win_rate=round((net > 0).mean() * 100, 0),
        profit_factor=round(wins.sum() / gl, 2) if gl else float("inf"),
        avg_win=round(wins.mean(), 0) if len(wins) else 0.0,
        avg_loss=round(losses.mean(), 0) if len(losses) else 0.0,
        best_day=round(daily["net"].max(), 0) if not daily.empty else 0.0,
        worst_day=round(daily["net"].min(), 0) if not daily.empty else 0.0,
        total_costs=round(trades["charges"].sum(), 0),
        max_drawdown=round(dd, 0),
    )


def by_class(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    return (trades.groupby("kind")["net"].agg(trades="size", net="sum")
            .reset_index())


def by_strategy(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    return (trades.groupby("strategy")["net"].agg(trades="size", net="sum")
            .reset_index())


def monthly(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    t = trades.copy()
    t["month"] = t["date"].str[:7]
    return (t.groupby("month")["net"].agg(trades="size", net="sum")
            .reset_index())
