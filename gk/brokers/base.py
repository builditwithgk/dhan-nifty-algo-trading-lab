"""The Broker interface. Paper and live implement the SAME contract, so the
engine, risk manager and order manager never know or care which is underneath.

Contract guarantees every implementation must honour:
  * place_bracket() attaches a broker-side stop (and target) to the entry.
    There is NO way to open a position without a resting stop at the broker.
  * A returned Position always reflects the ACTUAL entry fill price.
  * flatten() / flatten_all() close at market and return the realised Fill(s).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from ..models import Funds, OrderRequest, OrderResult, Position


class Broker(ABC):
    name: str = "base"

    @abstractmethod
    def get_funds(self) -> Funds:
        """Available balance / margin, read from the broker."""

    @abstractmethod
    def get_ltp(self, security_id: str, segment: str) -> float:
        """Last traded price for a security."""

    @abstractmethod
    def place_bracket(self, req: OrderRequest) -> OrderResult:
        """Place entry + broker-side stop (+ optional target/trail).

        Must reject if req has no stop. On success returns OrderResult with the
        live Position (entry filled) attached.
        """

    @abstractmethod
    def modify_stop(self, order_id: str, new_stop: float) -> bool:
        """Move the resting stop (used for trailing). True on success."""

    @abstractmethod
    def flatten(self, order_id: str) -> Optional[Position]:
        """Market-close the position for order_id. Returns the closed Position."""

    @abstractmethod
    def get_positions(self) -> List[Position]:
        """Current open positions, from the broker's truth."""

    def flatten_all(self) -> List[Position]:
        closed = []
        for pos in list(self.get_positions()):
            done = self.flatten(pos.order_id)
            if done:
                closed.append(done)
        return closed
