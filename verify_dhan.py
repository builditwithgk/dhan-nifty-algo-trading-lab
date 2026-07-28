"""Read-only connection check for your Dhan account.

Run:  python verify_dhan.py

Confirms your .env credentials work and that BOTH APIs are live:
  * Trading API (free)  -> reads your fund balance, positions
  * Data API (paid)     -> real-time price, intraday candles, NIFTY option chain

It places NO orders and changes nothing. Your access token is never printed.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gk import constants as C
from gk.config import load

PASS, FAIL = "PASS", "FAIL"
results = []


def show(name, ok, detail=""):
    tag = PASS if ok else FAIL
    print(f"  [{tag}] {name}" + (f" -> {detail}" if detail else ""))
    results.append(ok)


def main():
    s = load()
    print("\n" + "=" * 60)
    print("Dhan connection check (read-only, no orders)")
    print("=" * 60)

    # 0) creds present (never print the token itself)
    have = bool(s.dhan_client_id) and bool(s.dhan_access_token)
    show("credentials found in .env", have,
         f"client_id ...{s.dhan_client_id[-4:]}" if s.dhan_client_id else "MISSING")
    if not have:
        print("\n  Fill DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env, then re-run.")
        sys.exit(1)

    # connect
    try:
        from dhanhq import DhanContext, dhanhq
        ctx = DhanContext(s.dhan_client_id, s.dhan_access_token)
        api = dhanhq(ctx)
        show("SDK connected (DhanContext)", True)
    except Exception as e:                       # noqa: BLE001
        show("SDK connected (DhanContext)", False, str(e))
        sys.exit(1)

    # 1) Trading API (free): fund balance
    try:
        r = api.get_fund_limits()
        data = r.get("data", r) if isinstance(r, dict) else r
        bal = data.get("availabelBalance", data.get("availableBalance"))
        show("Trading API: fund limits", bal is not None, f"available Rs.{bal}")
    except Exception as e:                        # noqa: BLE001
        show("Trading API: fund limits", False, str(e))

    # 2) Data API: real-time price (NIFTY index + RELIANCE)
    try:
        securities = {C.IDX_I: [13], C.NSE_EQ: [2885]}   # NIFTY 50, RELIANCE
        r = api.ticker_data(securities)
        data = r.get("data", r) if isinstance(r, dict) else r
        show("Data API: real-time LTP (ticker_data)", bool(data), str(data)[:160])
    except Exception as e:                        # noqa: BLE001
        show("Data API: real-time LTP (ticker_data)", False, str(e))

    # 3) Data API: intraday minute candles (RELIANCE, today)
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        frm = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        r = api.intraday_minute_data(
            security_id="2885", exchange_segment=C.NSE_EQ,
            instrument_type="EQUITY", from_date=frm, to_date=today, interval=5)
        data = r.get("data", r) if isinstance(r, dict) else r
        n = len(data.get("close", [])) if isinstance(data, dict) else 0
        show("Data API: intraday 5-min candles", n > 0, f"{n} candles for RELIANCE")
    except Exception as e:                        # noqa: BLE001
        show("Data API: intraday 5-min candles", False, str(e))

    # 4) Data API: NIFTY option chain
    try:
        el = api.expiry_list(under_security_id=13, under_exchange_segment=C.IDX_I)
        ed = el.get("data", el) if isinstance(el, dict) else el
        expiries = ed.get("data", ed) if isinstance(ed, dict) else ed
        first = expiries[0] if expiries else None
        show("Data API: NIFTY expiry list", bool(first), f"nearest expiry {first}")
        if first:
            oc = api.option_chain(under_security_id=13,
                                  under_exchange_segment=C.IDX_I, expiry=first)
            od = oc.get("data", oc) if isinstance(oc, dict) else oc
            show("Data API: NIFTY option chain", bool(od),
                 f"chain payload received ({len(str(od))} bytes)")
    except Exception as e:                        # noqa: BLE001
        show("Data API: NIFTY option chain", False, str(e))

    print("=" * 60)
    if all(results):
        print("ALL LIVE. Trading API + Data API are working. Ready for Step 2.")
    else:
        print("Some checks failed — see above. (Data API may take a few minutes")
        print("to activate after purchase; if so, wait and re-run.)")
    print("=" * 60)


if __name__ == "__main__":
    main()
