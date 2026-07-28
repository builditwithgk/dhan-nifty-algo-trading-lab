"""Step 3B flagship — REAL historical NIFTY bull-put-spread backtest.

Run:  python run_spread_backtest.py [months_back]

Tests the skew-harvesting spread on ACTUAL Dhan option prices (no Black-Scholes).
This is the direct answer to "do NIFTY credit spreads make money after costs?".
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gk.config import load
from gk.spread_backtest import backtest_bull_put
from dhanhq import DhanContext, dhanhq

GATE_PF = 1.2


def main():
    months = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    s = load()
    if not (s.dhan_client_id and s.dhan_access_token):
        print("No creds in .env."); return
    api = dhanhq(DhanContext(s.dhan_client_id, s.dhan_access_token))

    to = datetime.now().strftime("%Y-%m-%d")
    frm = (datetime.now() - timedelta(days=months * 30)).strftime("%Y-%m-%d")
    print(f"\nBacktesting weekly NIFTY bull-put spreads on REAL option data")
    print(f"window {frm} .. {to}  |  sell ATM-3 put / buy ATM-6 put / hold to expiry")
    print("(pulling real expired-option premiums, this takes a moment)...")

    res = backtest_bull_put(api, frm, to, short_otm=3, long_otm=6, lots=1)
    if res.n == 0:
        print("No trades reconstructed — check window/expiry detection."); return

    print("\n" + "=" * 72)
    print("PER-WEEK RESULTS (1 lot = 65 qty, net of all option charges)")
    print("=" * 72)
    print(f"  {'entry':16s} {'exp':10s} {'strikes':13s} {'credit':>7s} "
          f"{'exp_spot':>9s} {'net Rs.':>9s}")
    for t in res.trades:
        print(f"  {str(t.entry_time)[:16]:16s} {str(t.expiry.date()):10s} "
              f"{int(t.short_strike)}/{int(t.long_strike):<7d} {t.credit:>7.1f} "
              f"{t.expiry_spot:>9.0f} {t.net:>9,.0f}")

    pf = res.profit_factor
    passed = pf > GATE_PF and res.n >= 10
    print("\n" + "=" * 72)
    print(f"SUMMARY: {res.n} weekly spreads | win% {100*res.win_rate:.0f} | "
          f"PF {pf:.2f} (gate >{GATE_PF}) | net Rs.{res.net_pnl:,.0f} | "
          f"worst week Rs.{res.max_loss:,.0f}")
    print(f"VERDICT: {'PASS - advance to paper' if passed else 'FAIL - no real edge after costs (yet)'}")
    print("=" * 72)
    print("Reminder: held-to-expiry, no intra-week stop. Adding a stop/roll rule")
    print("and testing other OTM widths/entry timing is the next refinement.")


if __name__ == "__main__":
    main()
