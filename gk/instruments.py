"""Symbol -> Instrument registry (security_id, lot size, tick size).

At go-live this loads Dhan's real scrip master CSV so EVERY symbol resolves
(the reviewed repos hardcoded 4 ids and crashed on the rest). Until the Dhan
API/CSV is wired, a small offline fallback lets the paper spine run and be
tested without network. Equity ids in the fallback are placeholders and are
NOT used for live orders — live always resolves from the real CSV.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from . import constants as C
from .models import AssetKind, Instrument

# ---- Index / options metadata (verify before trading; NSE changes these) ----
# NIFTY: weekly expiry moved to Tuesday in mid-2026; lot revised 75 -> 65.
UNDERLYINGS = {
    "NIFTY": {
        "security_id": "13",        # NIFTY 50 index (IDX_I)
        "expiry_weekday": 1,         # Tue=1  (Mon=0..Fri=4)
        "lot_size": 65,
        "strike_step": 50,
        "fno_segment": C.NSE_FNO,
    },
    "BANKNIFTY": {
        "security_id": "25",
        "expiry_weekday": 3,         # Thu (verify)
        "lot_size": 15,
        "strike_step": 100,
        "fno_segment": C.NSE_FNO,
    },
}

# Offline fallback for the 12-name equity universe (placeholder security_ids).
# tick size 0.05 for cash equities. Real ids/lots come from the CSV at go-live.
_EQUITY_FALLBACK = {
    "RELIANCE": "2885", "HDFCBANK": "1333", "ICICIBANK": "4963", "SBIN": "3045",
    "AXISBANK": "5900", "INFY": "1594", "TCS": "11536", "BHARTIARTL": "10604",
    "LT": "11483", "BAJFINANCE": "317", "TATASTEEL": "3499", "MARUTI": "10999",
}


@lru_cache(maxsize=None)
def equity(symbol: str) -> Instrument:
    """Return an equity Instrument. Uses the offline fallback id for paper."""
    sym = symbol.upper().strip()
    sec = _EQUITY_FALLBACK.get(sym, f"UNKNOWN_{sym}")
    return Instrument(
        symbol=sym,
        security_id=sec,
        segment=C.NSE_EQ,
        kind=AssetKind.EQUITY,
        lot_size=1,
        tick_size=0.05,
    )


def option(underlying: str, strike: int, opt_type: str, security_id: str,
           expiry: Optional[str] = None) -> Instrument:
    """Build a NIFTY (or other) option Instrument.

    opt_type: "CE" or "PE". security_id must come from the option chain / CSV.
    """
    u = UNDERLYINGS[underlying.upper()]
    label = f"{underlying.upper()} {strike} {opt_type.upper()}"
    if expiry:
        label += f" {expiry}"
    return Instrument(
        symbol=label,
        security_id=security_id,
        segment=u["fno_segment"],
        kind=AssetKind.OPTION,
        lot_size=u["lot_size"],
        tick_size=0.05,
    )


def underlying_meta(name: str) -> dict:
    return UNDERLYINGS[name.upper()]
