"""Track 4 — directional NIFTY option-buying backtest on real option data.

Run:  python run_option_buy.py [days]

NIFTY opening-range breakout -> buy ATM CE/PE -> manage on premium. Tests a few
stop/target settings. Real prices, full costs.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gk.config import load
from gk.option_buy_backtest import backtest_option_buy
from dhanhq import DhanContext, dhanhq

GATE_PF = 1.2


def line(res, label):
    if res.n == 0:
        print(f"  {label:26s} no trades"); return
    print(f"  {label:26s} n {res.n:3d} | win% {100*res.win_rate:3.0f} | "
          f"PF {res.profit_factor:4.2f} | net Rs.{res.net_pnl:>8,.0f} | "
          f"worst Rs.{res.max_loss:>7,.0f}")


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 85
    s = load()
    api = dhanhq(DhanContext(s.dhan_client_id, s.dhan_access_token))
    to = datetime.now().strftime("%Y-%m-%d")
    frm = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    print(f"\nNIFTY directional option-buying | window {frm}..{to} | real option data")
    print("ORB(30min) -> buy ATM CE/PE -> manage on premium")
    print("=" * 74)
    for sl, tp in [(35, 60), (40, 80), (50, 100), (30, 50)]:
        res = backtest_option_buy(api, frm, to, sl_pct=sl, tp_pct=tp)
        line(res, f"stop -{sl}% / target +{tp}%")
    print("=" * 74)
    print(f"gate = PF > {GATE_PF}. Note: ~{days}d is a small sample — a promising")
    print("result would need OOS confirmation before trusting.")


if __name__ == "__main__":
    main()
