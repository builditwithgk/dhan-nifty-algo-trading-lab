"""Scan ORB across the whole F&O stock universe (~210 names) to find where it
actually has an edge — data picks the winners, not us.

Run:  python run_fo_scan.py [limit]

Pulls ~60 days of 5-min data per stock (cached to data/fo/), runs the ORB
backtest with full costs, and ranks by profit factor. Writes a results CSV.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gk import backtest
from gk.config import load
from gk.marketdata import CsvCache, DhanLive
from gk.strategies import OpeningRangeBreakout
from gk.universe import fo_stocks
from dhanhq import DhanContext, dhanhq

GATE_PF = 1.2
MIN_TRADES = 20


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 9999
    s = load()
    if not (s.dhan_client_id and s.dhan_access_token):
        print("No creds in .env."); return
    feed = DhanLive(dhanhq(DhanContext(s.dhan_client_id, s.dhan_access_token)))
    cache = CsvCache(Path(__file__).parent / "data" / "fo", live=feed)
    strat = OpeningRangeBreakout()

    stocks = fo_stocks()[:limit]
    print(f"Scanning ORB across {len(stocks)} F&O stocks "
          f"(first run fetches + caches; be patient)...")
    results = []
    for i, inst in enumerate(stocks, 1):
        try:
            df = cache.intraday(inst, interval=5, days=60)
            if len(df) < 200:
                continue
            r = backtest.run(df, strat, inst, risk_rupees=s.risk_per_trade,
                             max_notional=s.max_notional_per_trade,
                             slippage_pct=s.equity_slippage_pct, square_off=s.square_off)
            if r.n:
                results.append((inst.symbol, r.n, r.win_rate, r.profit_factor, r.net_pnl))
        except Exception as e:                     # noqa: BLE001
            pass
        if i % 25 == 0:
            print(f"  ...{i}/{len(stocks)} scanned")
        time.sleep(0.2)   # be gentle on the Data API

    results.sort(key=lambda x: -x[3])
    out = Path(__file__).parent / "data" / "fo_scan_results.csv"
    with open(out, "w") as fh:
        fh.write("symbol,trades,win_rate,profit_factor,net_pnl\n")
        for sym, n, wr, pf, net in results:
            fh.write(f"{sym},{n},{wr:.3f},{pf:.3f},{net:.0f}\n")

    passers = [r for r in results if r[3] > GATE_PF and r[1] >= MIN_TRADES]
    print("\n" + "=" * 66)
    print(f"ORB scan complete: {len(results)} stocks tested, "
          f"{len(passers)} cleared PF>{GATE_PF} with >={MIN_TRADES} trades")
    print("=" * 66)
    print(f"{'symbol':12s} {'trades':>6s} {'win%':>6s} {'PF':>6s} {'net Rs.':>10s}")
    for sym, n, wr, pf, net in results[:30]:
        flag = " *" if (pf > GATE_PF and n >= MIN_TRADES) else ""
        print(f"{sym:12s} {n:>6d} {100*wr:>5.1f} {pf:>6.2f} {net:>10,.0f}{flag}")
    print("-" * 66)
    print(f"(* = clears the gate)  full ranking saved to {out.name}")
    if passers:
        names = [p[0] for p in passers]
        print(f"\nCandidate ORB universe ({len(names)}): {names}")


if __name__ == "__main__":
    main()
