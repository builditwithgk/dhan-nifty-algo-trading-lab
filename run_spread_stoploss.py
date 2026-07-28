"""Final options lever — does a hard intra-week STOP-LOSS rescue the spread?

Run:  python run_spread_stoploss.py [months_back]

Compares held-to-expiry (loses) against closing the spread when its buyback cost
hits 1.5x / 2x / 2.5x the credit received. Real option data, full costs.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gk.config import load
from gk.spread_backtest import backtest_bull_put, backtest_bull_put_managed
from dhanhq import DhanContext, dhanhq

GATE_PF = 1.2


def line(res, label):
    if res.n == 0:
        print(f"  {label:28s} no trades"); return None
    print(f"  {label:28s} n {res.n:3d} | win% {100*res.win_rate:3.0f} | "
          f"PF {res.profit_factor:4.2f} | net Rs.{res.net_pnl:>8,.0f} | "
          f"worst Rs.{res.max_loss:>7,.0f}")


def main():
    months = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    s = load()
    api = dhanhq(DhanContext(s.dhan_client_id, s.dhan_access_token))
    to = datetime.now().strftime("%Y-%m-%d")
    frm = (datetime.now() - timedelta(days=months * 30)).strftime("%Y-%m-%d")
    print(f"\nStop-loss spread test | window {frm}..{to} | real option data")
    print("=" * 74)
    line(backtest_bull_put(api, frm, to, short_otm=3, long_otm=6), "held to expiry (no stop)")
    for sm in (2.5, 2.0, 1.5):
        line(backtest_bull_put_managed(api, frm, to, short_otm=3, long_otm=6, stop_mult=sm),
             f"stop at {sm}x credit")
    print("=" * 74)
    print(f"gate = PF > {GATE_PF}. If a stop level clears it, spreads become a real")
    print("candidate; otherwise we shelve naive spread-selling for good.")


if __name__ == "__main__":
    main()
