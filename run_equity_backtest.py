"""Step 3A — equity intraday backtest on REAL Dhan data.

Run:  python run_equity_backtest.py [days]

Pulls intraday candles for the 12-stock universe (cached to data/ after the
first fetch), runs each strategy through the no-lookahead engine with full costs,
and reports whether it clears the gate: PROFIT FACTOR > 1.2 after costs.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gk import backtest, instruments
from gk.config import load
from gk.marketdata import CsvCache, DhanLive
from gk.strategies import MomentumMover, OpeningRangeBreakout
from dhanhq import DhanContext, dhanhq

GATE_PF = 1.2
MIN_TRADES = 20          # below this, results aren't statistically meaningful


def summarize(name, results):
    trades = [t for r in results for t in r.trades]
    n = len(trades)
    if n == 0:
        print(f"\n{name.upper():14s} no trades"); return None
    gp = sum(t.net for t in trades if t.net > 0)
    gl = -sum(t.net for t in trades if t.net < 0)
    pf = (gp / gl) if gl > 0 else float("inf")
    wins = sum(1 for t in trades if t.net > 0)
    net = sum(t.net for t in trades)
    charges = sum(t.charges for t in trades)
    exp = net / n
    passed = pf > GATE_PF and n >= MIN_TRADES
    verdict = "PASS" if passed else ("FAIL" if n >= MIN_TRADES else "THIN")
    print(f"\n{name.upper():14s} [{verdict}]")
    print(f"  trades {n:4d} | win% {100*wins/n:5.1f} | PF {pf:5.2f} "
          f"(gate >{GATE_PF}) | net Rs.{net:>10,.0f} | exp Rs.{exp:7.1f}/trade "
          f"| costs Rs.{charges:,.0f}")
    return dict(name=name, n=n, pf=pf, net=net, passed=passed)


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    s = load()
    if not (s.dhan_client_id and s.dhan_access_token):
        print("No creds in .env."); return
    feed = DhanLive(dhanhq(DhanContext(s.dhan_client_id, s.dhan_access_token)))
    cache = CsvCache(Path(__file__).parent / "data", live=feed)

    strategies = [OpeningRangeBreakout(), MomentumMover()]
    per_strategy = {st.name: [] for st in strategies}

    print(f"\nPulling ~{days} days of 5-min data for {len(s.equity_universe)} stocks "
          f"(first run fetches from Dhan, then caches)...")
    bar_report = []
    for sym in s.equity_universe:
        inst = instruments.equity(sym)
        df = cache.intraday(inst, interval=5, days=days)
        bar_report.append((sym, len(df)))
        for st in strategies:
            res = backtest.run(df, st, inst,
                               risk_rupees=s.risk_per_trade,
                               max_notional=s.max_notional_per_trade,
                               slippage_pct=s.equity_slippage_pct,
                               square_off=s.square_off)
            per_strategy[st.name].append(res)

    print("\nData pulled (bars per stock):")
    print("  " + "  ".join(f"{sym}:{n}" for sym, n in bar_report))

    print("\n" + "=" * 68)
    print("BACKTEST RESULTS (net of all Indian intraday charges + slippage)")
    print("=" * 68)
    outcomes = []
    for name, results in per_strategy.items():
        o = summarize(name, results)
        if o:
            outcomes.append(o)
        # per-symbol PF for the curious
        rows = [(r.symbol, r.n, r.profit_factor, r.net_pnl) for r in results if r.n]
        for sym, n, pf, net in sorted(rows, key=lambda x: -x[2]):
            print(f"      {sym:10s} trades {n:3d}  PF {pf:5.2f}  net Rs.{net:>9,.0f}")

    print("\n" + "=" * 68)
    passed = [o["name"] for o in outcomes if o["passed"]]
    if passed:
        print(f"CLEARED THE GATE (PF>{GATE_PF}, >={MIN_TRADES} trades): {passed}")
        print("-> these advance to 2 weeks of paper trading before any real money.")
    else:
        print(f"NOTHING cleared PF>{GATE_PF} yet. That's the system working as")
        print("intended - it kills weak edges cheap. Next: tune params in coarse")
        print("steps, widen the data window, or try other entries. No real money.")
    print("=" * 68)


if __name__ == "__main__":
    main()
