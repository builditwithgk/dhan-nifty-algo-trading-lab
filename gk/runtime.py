"""Broker factory — v1 is PAPER ONLY.

This release ships no live-order broker at all. `build_broker` can only ever
return the PaperBroker (fake money), so placing a real order is not merely
disabled by a config flag — the code path does not exist in this version.

If `config.yaml` asks for `mode: live`, we refuse loudly rather than silently
falling back, so nobody can believe they are trading live when they are not.
Live trading (Dhan Super Orders, broker-side stops) is planned for v2 — see
ROADMAP.md.
"""
from __future__ import annotations

from .brokers.base import Broker
from .brokers.paper import PaperBroker
from .config import Settings
from .journal import Journal


def build_broker(settings: Settings, journal: Journal,
                 confirm_live: bool = False) -> Broker:
    """Always returns the PaperBroker. `confirm_live` is accepted only so the
    call sites stay stable for v2; setting it changes nothing in v1."""
    if settings.mode == "live":
        raise RuntimeError(
            "config.yaml has mode: live, but this is the PAPER-ONLY release "
            "(v1) — it contains no live broker. Set mode: paper to continue.")
    journal.event("MODE", "paper broker (fake money)")
    return PaperBroker(journal, starting_capital=settings.capital,
                       equity_slippage_pct=settings.equity_slippage_pct,
                       option_slippage_pct=settings.option_slippage_pct)
