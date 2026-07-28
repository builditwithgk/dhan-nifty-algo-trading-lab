"""Indian transaction-cost model (statutory charges + brokerage).

Costs are a first-class concern here — retail intraday/option edges die on them,
so every backtest and paper P&L runs net of these. Slippage is modelled
separately at fill time (see brokers), because it is a market-impact assumption,
not a statutory charge.

Rates below are for NSE, current as of 2026 (verify against Dhan's live charge
sheet before go-live; they change). Key correction vs the prior codebase:
options STT is 0.1% on the SELL side of premium (raised from 0.0625% on
2024-10-01), not 0.000625.

References for the structure:
  * Brokerage (Dhan): equity delivery = 0; intraday = min(20, 0.03% * turnover)
    per order; F&O = flat 20 per order.
  * STT: equity intraday 0.025% on SELL turnover; equity delivery 0.1% both
    sides; options 0.1% on SELL premium.
  * Exchange txn: NSE equity 0.00297%; NSE options 0.03503% (on premium).
  * SEBI: 0.0001% (10 per crore). Stamp: equity/opt buy-side 0.003% (delivery
    0.015%). GST: 18% on (brokerage + exchange txn + SEBI).
"""
from __future__ import annotations

from dataclasses import dataclass

GST_RATE = 0.18


@dataclass
class ChargeBreakdown:
    brokerage: float = 0.0
    stt: float = 0.0
    exchange_txn: float = 0.0
    sebi: float = 0.0
    stamp: float = 0.0
    gst: float = 0.0

    @property
    def total(self) -> float:
        return round(
            self.brokerage + self.stt + self.exchange_txn
            + self.sebi + self.stamp + self.gst,
            2,
        )


def _gst(brokerage: float, exchange_txn: float, sebi: float) -> float:
    return GST_RATE * (brokerage + exchange_txn + sebi)


def equity_charges(price: float, qty: int, is_buy: bool, intraday: bool = True) -> ChargeBreakdown:
    """Statutory + brokerage for ONE equity order side."""
    turnover = price * qty
    b = ChargeBreakdown()

    if intraday:
        b.brokerage = min(20.0, 0.0003 * turnover)
        b.stt = 0.00025 * turnover if not is_buy else 0.0       # sell side only
        b.stamp = 0.00003 * turnover if is_buy else 0.0          # buy side only
    else:  # delivery
        b.brokerage = 0.0                                        # Dhan: zero
        b.stt = 0.001 * turnover                                 # both sides
        b.stamp = 0.00015 * turnover if is_buy else 0.0

    b.exchange_txn = 0.0000297 * turnover
    b.sebi = 0.000001 * turnover
    b.gst = _gst(b.brokerage, b.exchange_txn, b.sebi)
    return b


def option_charges(premium: float, qty: int, is_buy: bool) -> ChargeBreakdown:
    """Statutory + brokerage for ONE option order side.

    qty is total units (lots * lot_size). premium is per-unit price.
    """
    turnover = premium * qty
    b = ChargeBreakdown()
    b.brokerage = 20.0                                          # flat per order
    b.stt = 0.001 * turnover if not is_buy else 0.0            # 0.1% SELL premium
    b.exchange_txn = 0.0003503 * turnover
    b.sebi = 0.000001 * turnover
    b.stamp = 0.00003 * turnover if is_buy else 0.0
    b.gst = _gst(b.brokerage, b.exchange_txn, b.sebi)
    return b


def round_trip_equity(entry: float, exit_: float, qty: int, intraday: bool = True) -> float:
    """Total charges for a full equity trade (buy + sell). Convenience."""
    return (
        equity_charges(entry, qty, is_buy=True, intraday=intraday).total
        + equity_charges(exit_, qty, is_buy=False, intraday=intraday).total
    )


def round_trip_option(entry: float, exit_: float, qty: int, is_long: bool) -> float:
    """Total charges for a full option trade. is_long => buy then sell."""
    if is_long:
        return (
            option_charges(entry, qty, is_buy=True).total
            + option_charges(exit_, qty, is_buy=False).total
        )
    # short: sell to open, buy to close
    return (
        option_charges(entry, qty, is_buy=False).total
        + option_charges(exit_, qty, is_buy=True).total
    )
