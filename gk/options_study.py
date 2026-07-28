"""Options edge measurement — the Variance Risk Premium (VRP).

The only durable reason to SELL index options/spreads is that implied volatility
(what buyers pay) tends to sit ABOVE the volatility that actually shows up
(realized). That gap is the VRP. The prior work concluded "no edge" only because
it used realized vol AS the implied vol (which sets the VRP to zero by
construction). With Dhan's Data API we now read the REAL implied vol per strike,
so we can measure the gap directly.

This module is a measurement, not a strategy. Logged daily it tells us whether a
credit-selling edge even exists right now, before we build/trust a spread system.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import numpy as np
import pandas as pd

from . import constants as C
from .models import AssetKind, Instrument


def realized_vol(closes: pd.Series, window: int = 20) -> float:
    """Annualized realized volatility (%) from daily closes."""
    rets = np.log(closes / closes.shift(1)).dropna()
    if len(rets) < window:
        window = len(rets)
    if window < 2:
        return float("nan")
    return float(rets.tail(window).std() * np.sqrt(252) * 100)


@dataclass
class VRPSnapshot:
    spot: float
    expiry: str
    dte: int
    atm_strike: float
    call_iv: float
    put_iv: float
    atm_iv: float
    rv20: float
    vrp: float          # atm_iv - rv20 (vol points)
    skew: float         # put_iv - call_iv (vol points)

    def verdict(self) -> str:
        if np.isnan(self.vrp):
            return "insufficient data"
        if self.vrp > 3:
            return "IV richly above realized -> selling has a real tailwind"
        if self.vrp > 1:
            return "IV modestly above realized -> thin selling edge"
        if self.vrp > -1:
            return "IV ~= realized -> little/no selling edge (costs likely win)"
        return "IV BELOW realized -> selling is a losing proposition; favor buying"


def nifty_index_instrument() -> Instrument:
    return Instrument(symbol="NIFTY", security_id="13", segment=C.IDX_I,
                      kind=AssetKind.EQUITY)  # kind used only for cost class; feed maps IDX->INDEX


def vrp_snapshot(feed, underlying: str = "NIFTY", rv_days: int = 40) -> VRPSnapshot:
    # Real implied vol from the live chain
    expiries = feed.expiries(underlying)
    chain = feed.option_chain(underlying, expiries[0])
    atm = chain.atm_strike()
    ce = chain.quote(atm, "CE")
    pe = chain.quote(atm, "PE")
    call_iv = ce.iv if ce else float("nan")
    put_iv = pe.iv if pe else float("nan")
    atm_iv = np.nanmean([call_iv, put_iv])

    # Realized vol from NIFTY daily closes
    daily = feed.daily(nifty_index_instrument(), days=max(60, rv_days + 10))
    rv20 = realized_vol(daily["close"], window=20) if len(daily) else float("nan")

    # Days to expiry
    try:
        exp_d = datetime.strptime(chain.expiry, "%Y-%m-%d").date()
        dte = (exp_d - date.today()).days
    except Exception:
        dte = -1

    return VRPSnapshot(
        spot=chain.spot, expiry=chain.expiry, dte=dte, atm_strike=atm,
        call_iv=call_iv, put_iv=put_iv, atm_iv=float(atm_iv),
        rv20=rv20, vrp=float(atm_iv - rv20), skew=float(put_iv - call_iv),
    )
