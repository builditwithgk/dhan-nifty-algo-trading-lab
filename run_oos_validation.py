"""Out-of-sample validation of the ORB stock-selection.

The scan picked the best 21 of 210 stocks ON THE SAME DATA — that can be luck.
This does the honest test:
  1. Split each stock's ~180 days into TRAIN (older half) and TEST (newer half).
  2. Rank all stocks by ORB profit factor on TRAIN only.
  3. Take the top-K by TRAIN, then measure how that basket does on TEST — data it
     had NO role in selecting.
  4. Compare the selected basket vs the whole field on TEST, and measure whether
     train-rank persists into test (Spearman correlation).

If the train-selected basket beats the field out-of-sample and the ranks persist,
the edge is real. If it collapses to the field average, it was overfitting.

Run:  python run_oos_validation.py
(First run fetches ~180 days x 210 stocks — several minutes. Cached after.)
"""
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gk import backtest, constants as C
from gk.config import load
from gk.strategies import OpeningRangeBreakout
from gk.universe import fo_stocks
from dhanhq import DhanContext, dhanhq

CACHE = Path(__file__).parent / "data" / "fo_oos"
TOTAL_DAYS = 180
CHUNK = 85
TOP_K = 20
MIN_TRADES_HALF = 10


def fetch_history(api, security_id: str) -> pd.DataFrame:
    frames, end, remaining = [], datetime.now(), TOTAL_DAYS
    while remaining > 0:
        d = min(CHUNK, remaining)
        frm = (end - timedelta(days=d)).strftime("%Y-%m-%d")
        to = end.strftime("%Y-%m-%d")
        try:
            r = api.intraday_minute_data(security_id, C.NSE_EQ, "EQUITY", frm, to, interval=5)
            data = r.get("data", r) if isinstance(r, dict) else None
            if isinstance(data, dict) and data.get("close"):
                idx = pd.to_datetime(data["timestamp"], unit="s", utc=True).tz_convert("Asia/Kolkata")
                frames.append(pd.DataFrame({
                    "open": data["open"], "high": data["high"], "low": data["low"],
                    "close": data["close"], "volume": data["volume"]}, index=idx))
        except Exception:
            pass
        end = end - timedelta(days=d)
        remaining -= d
        time.sleep(0.15)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames).sort_index()
    return df[~df.index.duplicated(keep="first")]


def get_data(api, inst) -> pd.DataFrame:
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"{inst.symbol}.csv"
    if p.exists():
        return pd.read_csv(p, index_col=0, parse_dates=True)
    df = fetch_history(api, inst.security_id)
    if not df.empty:
        df.to_csv(p)
    return df


def pf_net(df, inst, s):
    r = backtest.run(df, OpeningRangeBreakout(), inst, risk_rupees=s.risk_per_trade,
                     max_notional=s.max_notional_per_trade,
                     slippage_pct=s.equity_slippage_pct, square_off=s.square_off)
    return r


def main():
    s = load()
    api = dhanhq(DhanContext(s.dhan_client_id, s.dhan_access_token))
    stocks = fo_stocks()
    print(f"Out-of-sample validation over {len(stocks)} stocks (fetching if needed)...")

    rows = []
    for i, inst in enumerate(stocks, 1):
        df = get_data(api, inst)
        if len(df) < 400:
            continue
        mid = df.index[len(df) // 2].normalize()
        train, test = df[df.index.normalize() < mid], df[df.index.normalize() >= mid]
        rtr, rte = pf_net(train, inst, s), pf_net(test, inst, s)
        if rtr.n >= MIN_TRADES_HALF and rte.n >= MIN_TRADES_HALF:
            rows.append(dict(sym=inst.symbol, tr_pf=rtr.profit_factor, tr_n=rtr.n,
                             te_pf=rte.profit_factor, te_n=rte.n, te_net=rte.net_pnl))
        if i % 30 == 0:
            print(f"  ...{i}/{len(stocks)}")

    df = pd.DataFrame(rows)
    if df.empty:
        print("Not enough data."); return
    df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=["tr_pf", "te_pf"])

    # selection: top-K by TRAIN pf
    selected = df.sort_values("tr_pf", ascending=False).head(TOP_K)
    sel_test_pf = selected.te_net[selected.te_net > 0].sum() / max(
        1e-9, -selected.te_net[selected.te_net < 0].sum())
    field_test_pf = df.te_net[df.te_net > 0].sum() / max(
        1e-9, -df.te_net[df.te_net < 0].sum())
    spear = df["tr_pf"].corr(df["te_pf"], method="spearman")
    stayed = (selected.te_pf > 1.0).sum()

    print("\n" + "=" * 74)
    print(f"OUT-OF-SAMPLE VALIDATION  ({len(df)} stocks with enough trades both halves)")
    print("=" * 74)
    print(f"  Top-{TOP_K} by TRAIN profit factor, then measured on unseen TEST half:")
    print(f"    selected basket TEST profit factor : {sel_test_pf:.2f}")
    print(f"    whole-field    TEST profit factor  : {field_test_pf:.2f}  (baseline)")
    print(f"    of {TOP_K} selected, stayed profitable on test: {stayed}/{TOP_K}")
    print(f"    train->test rank persistence (Spearman): {spear:+.2f}")
    print("-" * 74)
    print(f"  {'symbol':12s} {'train PF':>9s} {'test PF':>8s} {'test net':>10s}")
    for r in selected.itertuples():
        print(f"  {r.sym:12s} {r.tr_pf:>9.2f} {r.te_pf:>8.2f} {r.te_net:>10,.0f}")
    print("-" * 74)
    if sel_test_pf > 1.15 and sel_test_pf > field_test_pf and spear > 0.1:
        print("READ: selection HOLDS out-of-sample -> real, persistent edge. Advance")
        print("the survivors (test PF>1) to a small paper forward-test.")
    elif spear > 0.1:
        print("READ: weak persistence. Some signal, but selection is noisy — need")
        print("more data / a stricter filter before trusting.")
    else:
        print("READ: selection does NOT hold out-of-sample — the scan winners were")
        print("largely luck. Do NOT trade them; ORB needs a different edge/filter.")
    print("=" * 74)
    df.sort_values("tr_pf", ascending=False).to_csv(
        Path(__file__).parent / "data" / "oos_results.csv", index=False)


if __name__ == "__main__":
    main()
