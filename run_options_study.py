"""Step 3B (start) — measure the options selling edge (VRP) on live data.

Run:  python run_options_study.py

Reads the real NIFTY option-chain IV and compares it to realized volatility.
Logged daily this builds the evidence base for whether spreads are worth trading
at all — the question the old system couldn't answer (it used realized vol as IV).
"""
import csv
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gk.config import load
from gk.options_study import vrp_snapshot
from gk.marketdata import DhanLive
from dhanhq import DhanContext, dhanhq

LOG = Path(__file__).parent / "data" / "vrp_log.csv"


def append_log(snap):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    new = not LOG.exists()
    with open(LOG, "a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["date", "spot", "expiry", "dte", "atm_iv", "call_iv",
                        "put_iv", "rv20", "vrp", "skew"])
        w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M"), snap.spot, snap.expiry,
                    snap.dte, round(snap.atm_iv, 2), round(snap.call_iv, 2),
                    round(snap.put_iv, 2), round(snap.rv20, 2), round(snap.vrp, 2),
                    round(snap.skew, 2)])


def main():
    s = load()
    if not (s.dhan_client_id and s.dhan_access_token):
        print("No creds in .env."); return
    feed = DhanLive(dhanhq(DhanContext(s.dhan_client_id, s.dhan_access_token)))
    snap = vrp_snapshot(feed, "NIFTY")
    append_log(snap)

    print("\n" + "=" * 60)
    print("NIFTY options edge check (live)")
    print("=" * 60)
    print(f"  spot {snap.spot} | expiry {snap.expiry} ({snap.dte} days) | ATM {snap.atm_strike}")
    print(f"  implied vol:  call {snap.call_iv:.1f}%  put {snap.put_iv:.1f}%  "
          f"ATM avg {snap.atm_iv:.1f}%")
    print(f"  realized vol (20d): {snap.rv20:.1f}%")
    print(f"  VRP (implied - realized): {snap.vrp:+.1f} vol points")
    print(f"  put skew (put - call IV):  {snap.skew:+.1f} vol points")
    print("-" * 60)
    print(f"  read: {snap.verdict()}")
    print("=" * 60)
    print(f"  (logged to {LOG.name})")
    print("Note: one snapshot is not a verdict. Logged daily for weeks it shows")
    print("WHEN the selling edge is present. No orders here.")


if __name__ == "__main__":
    main()
