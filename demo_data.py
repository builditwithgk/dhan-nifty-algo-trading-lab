"""Step 2 demo — pull REAL Dhan data through the feed.

Run:  python demo_data.py

Read-only. Shows live candles, the NIFTY option chain with real IV/delta, and
delta-based strike selection (the building block for options strategies).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gk import instruments as I
from gk.config import load
from gk.marketdata import DhanLive
from dhanhq import DhanContext, dhanhq


def main():
    s = load()
    if not (s.dhan_client_id and s.dhan_access_token):
        print("No creds in .env — fill them and re-run."); return
    feed = DhanLive(dhanhq(DhanContext(s.dhan_client_id, s.dhan_access_token)))

    print("\n" + "=" * 64)
    print("STEP 2 - live market-data feed")
    print("=" * 64)

    # 1) Real intraday candles for a stock
    rel = I.equity("RELIANCE")
    df = feed.intraday(rel, interval=5, days=3)
    print(f"\nRELIANCE 5-min candles: {len(df)} bars")
    if len(df):
        print(f"  first bar: {df.index[0]}   (should be ~09:15 IST)")
        print(f"  last  bar: {df.index[-1]}   close={df['close'].iloc[-1]}")
        print(f"  today's range so far: {df['low'].tail(75).min()} - {df['high'].tail(75).max()}")

    # 2) Live LTP batch across the equity universe
    insts = [I.equity(sym) for sym in s.equity_universe]
    ltps = feed.ltp_batch(insts)
    print(f"\nLive LTP for {len(ltps)} universe stocks (sample):")
    for ins in insts[:5]:
        print(f"  {ins.symbol:10s} Rs.{ltps.get(ins.security_id, 0)}")

    # 3) NIFTY option chain with REAL IV + delta
    expiries = feed.expiries("NIFTY")
    chain = feed.option_chain("NIFTY", expiries[0])
    atm = chain.atm_strike()
    print(f"\nNIFTY spot {chain.spot} | expiry {chain.expiry} | {len(chain.strikes)} strikes")
    print(f"  ATM strike: {atm}")
    ce = chain.quote(atm, "CE"); pe = chain.quote(atm, "PE")
    print(f"  ATM CE: ltp={ce.ltp} iv={ce.iv:.1f}% delta={ce.delta:.2f} oi={ce.oi}")
    print(f"  ATM PE: ltp={pe.ltp} iv={pe.iv:.1f}% delta={pe.delta:.2f} oi={pe.oi}")

    # 4) Delta-based strike selection (the spread building block)
    short_put = chain.by_delta(0.30, "PE")   # ~30-delta short leg
    print(f"\n~0.30-delta PUT (spread short leg candidate):")
    print(f"  strike={short_put.strike} ltp={short_put.ltp} "
          f"delta={short_put.delta:.2f} iv={short_put.iv:.1f}% "
          f"security_id={short_put.security_id}")

    print("\n" + "=" * 64)
    print("Real data flowing: candles, live LTP, and an option chain with the")
    print("IV/delta we need to (a) pick strikes and (b) test the options edge.")
    print("=" * 64)


if __name__ == "__main__":
    main()
