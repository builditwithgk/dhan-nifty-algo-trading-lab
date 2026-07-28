"""Generalized out-of-sample test for ANY intraday strategy, on cached data.

Run:  python run_strategy_oos.py [orb|momentum|vwap_rev]

Uses the already-cached 180-day data for ~210 F&O stocks (from the ORB
validation). Splits each stock train/test, and reports the two things that
separate a real edge from noise:
  * whole-field profit factor in BOTH halves  (a real edge is profitable across
    the universe, not just cherry-picked names)
  * train->test persistence (Spearman)        (good-in-train predicts good-in-test)
Plus the top-20-by-train basket's TEST result. No new API calls.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gk import backtest
from gk.config import load
from gk.strategies import MomentumMover, OpeningRangeBreakout, VWAPReversion

CACHE = Path(__file__).parent / "data" / "fo_oos"
STRATS = {"orb": OpeningRangeBreakout, "momentum": MomentumMover, "vwap_rev": VWAPReversion}
MIN_TRADES_HALF = 10
TOP_K = 20


def field_pf(rows_net):
    gp = sum(x for x in rows_net if x > 0)
    gl = -sum(x for x in rows_net if x < 0)
    return gp / gl if gl > 0 else float("inf") if gp > 0 else 0.0


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "vwap_rev"
    if name not in STRATS:
        print(f"unknown strategy '{name}'. choose: {list(STRATS)}"); return
    s = load()
    make = STRATS[name]
    files = sorted(CACHE.glob("*.csv"))
    if not files:
        print("No cached data — run run_oos_validation.py first."); return

    rows = []
    for p in files:
        df = pd.read_csv(p, index_col=0, parse_dates=True)
        if len(df) < 400:
            continue
        mid = df.index[len(df) // 2].normalize()
        tr, te = df[df.index.normalize() < mid], df[df.index.normalize() >= mid]
        from gk import instruments
        inst = instruments.equity(p.stem)
        rtr = backtest.run(tr, make(), inst, s.risk_per_trade, s.max_notional_per_trade,
                           s.equity_slippage_pct, s.square_off)
        rte = backtest.run(te, make(), inst, s.risk_per_trade, s.max_notional_per_trade,
                           s.equity_slippage_pct, s.square_off)
        if rtr.n >= MIN_TRADES_HALF and rte.n >= MIN_TRADES_HALF:
            rows.append(dict(sym=p.stem, tr_pf=rtr.profit_factor, tr_net=rtr.net_pnl,
                             te_pf=rte.profit_factor, te_net=rte.net_pnl))

    df = pd.DataFrame(rows).replace([np.inf, -np.inf], np.nan).dropna()
    if df.empty:
        print("Not enough trades."); return

    field_tr = field_pf(df.tr_net.tolist())
    field_te = field_pf(df.te_net.tolist())
    sel = df.sort_values("tr_pf", ascending=False).head(TOP_K)
    sel_te = field_pf(sel.te_net.tolist())
    spear = df["tr_pf"].corr(df["te_pf"], method="spearman")

    print("\n" + "=" * 66)
    print(f"OUT-OF-SAMPLE TEST — strategy '{name}'  ({len(df)} stocks)")
    print("=" * 66)
    print(f"  whole-field PF   TRAIN {field_tr:.2f}   TEST {field_te:.2f}")
    print(f"  top-{TOP_K} basket (picked on train) TEST PF: {sel_te:.2f}")
    print(f"  train->test rank persistence (Spearman): {spear:+.2f}")
    print(f"  field TRAIN net Rs.{df.tr_net.sum():,.0f} | TEST net Rs.{df.te_net.sum():,.0f}")
    print("-" * 66)
    if field_te > 1.1 and sel_te > 1.15 and spear > 0.1:
        print("READ: real, persistent edge — advance to a small paper forward-test.")
    elif field_te > 1.0 and spear > 0.1:
        print("READ: marginal but present. Worth a tighter filter, then paper.")
    else:
        print("READ: no edge that survives out-of-sample. Move on.")
    print("=" * 66)


if __name__ == "__main__":
    main()
