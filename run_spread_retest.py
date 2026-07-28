"""Managed-spread retest — does a regime filter fix the bull-put spread?

Run:  python run_spread_retest.py [months_back]

Compares the naive spread (fails) against variants that (a) only sell when NIFTY
is in an uptrend, and (b) sell further OTM. Real option data, full costs.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gk.config import load
from gk.spread_backtest import backtest_bull_put
from dhanhq import DhanContext, dhanhq

GATE_PF = 1.2


def line(res, label):
    if res.n == 0:
        print(f"  {label:34s} no trades"); return
    print(f"  {label:34s} n {res.n:3d} | win% {100*res.win_rate:3.0f} | "
          f"PF {res.profit_factor:4.2f} | net Rs.{res.net_pnl:>8,.0f} | "
          f"worst Rs.{res.max_loss:>7,.0f}")


def main():
    months = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    s = load()
    api = dhanhq(DhanContext(s.dhan_client_id, s.dhan_access_token))
    to = datetime.now().strftime("%Y-%m-%d")
    frm = (datetime.now() - timedelta(days=months * 30)).strftime("%Y-%m-%d")

    print(f"\nManaged bull-put spread retest | window {frm}..{to} | real option data")
    print("=" * 78)
    configs = [
        ("baseline ATM-3/ATM-6",            dict(short_otm=3, long_otm=6, regime_filter=False)),
        ("+ uptrend filter",                dict(short_otm=3, long_otm=6, regime_filter=True)),
        ("further OTM ATM-5/ATM-8",         dict(short_otm=5, long_otm=8, regime_filter=False)),
        ("further OTM + uptrend filter",    dict(short_otm=5, long_otm=8, regime_filter=True)),
    ]
    for label, kw in configs:
        res = backtest_bull_put(api, frm, to, lots=1, **kw)
        line(res, label)
    print("=" * 78)
    print(f"gate = PF > {GATE_PF}. If the uptrend filter clears it, that's a real")
    print("edge candidate -> next step is a small paper forward-test.")


if __name__ == "__main__":
    main()
