"""Typed data objects that flow through the system.

Design rules baked in here (each fixes a bug seen in the reviewed repos):
  * A Fill carries the ACTUAL executed price + charges — never the requested
    price. We never treat an intended price as a fill.
  * An OrderRequest MUST carry a stop. Entries without a broker-side stop are
    rejected upstream — no software-only stops.
  * Quantity is in absolute units; lot rounding happens in risk.sizing before
    an OrderRequest is ever built.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def opposite(self) -> "Side":
        return Side.SELL if self is Side.BUY else Side.BUY

    @property
    def sign(self) -> int:
        """+1 for a long position, -1 for a short."""
        return 1 if self is Side.BUY else -1


class AssetKind(str, Enum):
    EQUITY = "EQUITY"
    OPTION = "OPTION"


class OrderStatus(str, Enum):
    PENDING = "PENDING"      # submitted, not yet confirmed filled
    OPEN = "OPEN"            # entry filled, position live with broker-side SL/target
    CLOSED = "CLOSED"        # exited (SL/target/square-off/manual)
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class Instrument:
    """A tradable contract. security_id + segment are what Dhan needs."""
    symbol: str                 # human symbol, e.g. "RELIANCE" or "NIFTY 24000 CE"
    security_id: str            # Dhan security id
    segment: str                # constants.NSE_EQ / NSE_FNO / ...
    kind: AssetKind
    lot_size: int = 1           # 1 for equity; real lot for F&O
    tick_size: float = 0.05

    def round_to_tick(self, price: float) -> float:
        if self.tick_size <= 0:
            return round(price, 2)
        return round(round(price / self.tick_size) * self.tick_size, 2)


@dataclass
class Signal:
    """A strategy's request to open a trade. Produced by pure strategy code.

    stop is REQUIRED. target/trail are optional. entry_price is the reference
    price the signal was computed at (used only for logging/sizing sanity).
    """
    instrument: Instrument
    side: Side
    stop: float
    entry_ref_price: float
    target: Optional[float] = None
    trail_jump: float = 0.0      # >0 => broker trails the stop by this many rupees
    strategy: str = "unknown"
    reason: str = ""

    def __post_init__(self):
        if self.stop is None:
            raise ValueError("Signal.stop is required — no software-only stops")
        # Sanity: a long's stop is below entry; a short's stop is above.
        if self.side is Side.BUY and self.stop >= self.entry_ref_price:
            raise ValueError(f"BUY stop {self.stop} must be below entry {self.entry_ref_price}")
        if self.side is Side.SELL and self.stop <= self.entry_ref_price:
            raise ValueError(f"SELL stop {self.stop} must be above entry {self.entry_ref_price}")


@dataclass
class OrderRequest:
    """What we actually ask the broker to place: a bracket (entry + SL + target).

    Quantity is final (already lot-rounded and risk-checked). This is only ever
    built inside execution.OrderManager, after the risk pipeline passes.
    """
    instrument: Instrument
    side: Side
    quantity: int
    stop: float
    target: Optional[float] = None
    trail_jump: float = 0.0
    product: str = "INTRADAY"
    strategy: str = "unknown"
    tag: str = ""
    charges: Optional[float] = None   # override (e.g. a spread's full round-trip cost)
    is_spread: bool = False           # a defined-risk credit spread (short position)


@dataclass
class Fill:
    """An ACTUAL execution. price is the real fill, charges are computed on it."""
    instrument: Instrument
    side: Side
    quantity: int
    price: float
    charges: float
    ts: str                      # ISO timestamp
    kind: str = "ENTRY"          # ENTRY | EXIT


@dataclass
class Position:
    """A live position with its broker-side protective levels."""
    instrument: Instrument
    side: Side                   # side of the OPEN (BUY = long)
    quantity: int
    entry_price: float           # actual avg entry fill
    stop: float
    target: Optional[float]
    order_id: str                # broker order id (or paper id)
    strategy: str = "unknown"
    entry_charges: float = 0.0
    ltp: float = 0.0             # last known mark
    trail_jump: float = 0.0
    is_spread: bool = False      # credit spread: costs front-loaded, no exit charge
    entry_ts: str = ""           # ISO entry timestamp (for the permanent history)
    product: str = "INTRADAY"    # actual broker product (INTRADAY / MARGIN / CNC)

    @property
    def unrealized(self) -> float:
        """Mark-to-market P&L in rupees (before exit charges)."""
        return (self.ltp - self.entry_price) * self.quantity * self.side.sign


@dataclass
class OrderResult:
    """The broker's response to a placement attempt."""
    ok: bool
    order_id: str = ""
    status: OrderStatus = OrderStatus.PENDING
    message: str = ""
    position: Optional[Position] = None   # set when the entry filled immediately (paper)


@dataclass
class Funds:
    """Account money snapshot, read from the broker."""
    available_balance: float
    utilized: float = 0.0
    collateral: float = 0.0
