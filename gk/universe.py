"""F&O stock universe, derived from Dhan's scrip master.

The ~210 NSE stocks that have options (so: deep liquidity + optionable). We scan
these to find where a strategy actually has an edge, rather than guessing 12.
Cached to data/fo_universe.csv so we download the 40MB master only once.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

import pandas as pd

from . import constants as C
from .models import AssetKind, Instrument

_CACHE = Path(__file__).parent.parent / "data" / "fo_universe.csv"
_OPT_RE = re.compile(r'^(.*)-[A-Za-z]{3}\d{4}-\d+(?:\.\d+)?-(?:CE|PE)$')


def _build_from_master() -> pd.DataFrame:
    df = pd.read_csv(C.COMPACT_CSV_URL, low_memory=False)
    opt = df[(df.SEM_EXM_EXCH_ID == "NSE") & (df.SEM_INSTRUMENT_NAME == "OPTSTK")].copy()
    opt["und"] = opt.SEM_TRADING_SYMBOL.apply(
        lambda s: (_OPT_RE.match(s).group(1) if _OPT_RE.match(s) else None))
    unds = sorted(opt.und.dropna().unique())
    eq = df[(df.SEM_EXM_EXCH_ID == "NSE") & (df.SEM_SERIES == "EQ")
            & (df.SEM_INSTRUMENT_NAME == "EQUITY")]
    eqmap = dict(zip(eq.SEM_TRADING_SYMBOL, eq.SEM_SMST_SECURITY_ID.astype(int)))
    lotmap = dict(zip(eq.SEM_TRADING_SYMBOL, eq.SEM_LOT_UNITS))
    rows = [{"symbol": u, "security_id": eqmap[u]} for u in unds if u in eqmap]
    out = pd.DataFrame(rows)
    _CACHE.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(_CACHE, index=False)
    return out


def fo_stocks(refresh: bool = False) -> List[Instrument]:
    if _CACHE.exists() and not refresh:
        df = pd.read_csv(_CACHE)
    else:
        df = _build_from_master()
    return [Instrument(symbol=r.symbol, security_id=str(int(r.security_id)),
                       segment=C.NSE_EQ, kind=AssetKind.EQUITY,
                       lot_size=1, tick_size=0.05)
            for r in df.itertuples()]
