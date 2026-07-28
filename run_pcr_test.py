"""Test whether PCR predicts NIFTY's next-day move. Real OI data.

Run:  python run_pcr_test.py [months]
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gk.config import load
from gk.pcr_study import analyze, build_daily_pcr
from dhanhq import DhanContext, dhanhq


def main():
    months = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    s = load()
    api = dhanhq(DhanContext(s.dhan_client_id, s.dhan_access_token))
    to = datetime.now().strftime("%Y-%m-%d")
    frm = (datetime.now() - timedelta(days=months * 30)).strftime("%Y-%m-%d")
    print(f"Building daily PCR from real OI | {frm}..{to} (this pulls a lot of data)...")
    df = build_daily_pcr(api, frm, to, rel=4, interval=60)
    if df.empty or len(df) < 30:
        print("Not enough data."); return
    df.to_csv(Path(__file__).parent / "data" / "pcr_daily.csv")
    r = analyze(df)

    print("\n" + "=" * 66)
    print(f"PCR -> next-day NIFTY return   ({r.n} trading days)")
    print("=" * 66)
    print(f"  PCR range: {df.pcr.min():.2f} .. {df.pcr.max():.2f}  (median {df.pcr.median():.2f})")
    print(f"  Spearman corr(PCR, next-day return): {r.corr:+.3f}")
    print(f"  baseline next-day return (all days): {r.baseline_ret:+.3f}%")
    print("-" * 66)
    print(f"  your rule -> PCR < 1 (bullish?):")
    print(f"     mean next-day return: {r.mean_ret_low:+.3f}%   up-day rate: {r.up_rate_low:.0f}%")
    print(f"  PCR >= 1:")
    print(f"     mean next-day return: {r.mean_ret_high:+.3f}%   up-day rate: {r.up_rate_high:.0f}%")
    print("-" * 66)
    print("  mean next-day return by PCR quintile (Q1=lowest PCR):")
    for k, v in r.quintile.items():
        print(f"     {k}: {v:+.3f}%")
    print("-" * 66)
    print(f"  VERDICT: {r.verdict()}")
    print("=" * 66)


if __name__ == "__main__":
    main()
