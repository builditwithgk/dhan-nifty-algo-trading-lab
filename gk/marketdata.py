"""Step 2 — the market-data feed.

A swappable data source so the SAME strategy/backtest code runs on cached data
now and live Dhan data later. Live source wraps the verified dhanhq facade.

Provides:
  * intraday(instrument, interval, days) -> OHLCV DataFrame (IST datetime index)
  * daily(instrument, days)             -> OHLCV DataFrame
  * ltp(instrument) / ltp_batch(...)    -> real-time last price
  * expiries(underlying) / option_chain(underlying, expiry)
      -> normalized chain WITH real IV + delta + per-strike security_id
  * strike selection helpers (ATM, by-delta) used by the options strategies

Response shapes were captured from the live API (2026-07-22):
  intraday: {open,high,low,close,volume,timestamp[]}  (timestamp = epoch secs)
  chain:    {last_price: spot, oc: {strike: {ce:{...}, pe:{...}}}}
            each ce/pe: last_price, implied_volatility, greeks{delta,...}, oi,
            security_id, top_bid_price, top_ask_price, ...
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from . import constants as C
from . import instruments as I
from .models import AssetKind, Instrument

IST = "Asia/Kolkata"


def _candles_to_df(payload: dict) -> pd.DataFrame:
    """Dhan OHLCV dict -> DataFrame indexed by IST datetime."""
    if not payload or "close" not in payload:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame({
        "open": payload["open"], "high": payload["high"], "low": payload["low"],
        "close": payload["close"], "volume": payload["volume"],
    })
    ts = pd.to_datetime(payload["timestamp"], unit="s", utc=True).tz_convert(IST)
    df.index = ts
    df.index.name = "datetime"
    return df


@dataclass
class OptionQuote:
    strike: float
    opt_type: str          # "CE" | "PE"
    ltp: float
    iv: float              # implied volatility (%) from the exchange
    delta: float
    oi: int
    security_id: str
    bid: float
    ask: float


@dataclass
class OptionChain:
    underlying: str
    expiry: str
    spot: float
    calls: Dict[float, OptionQuote]
    puts: Dict[float, OptionQuote]

    @property
    def strikes(self) -> List[float]:
        return sorted(self.calls.keys())

    def atm_strike(self) -> float:
        return min(self.strikes, key=lambda k: abs(k - self.spot))

    def by_delta(self, target_delta: float, opt_type: str) -> Optional[OptionQuote]:
        """Nearest strike whose |delta| is closest to target (e.g. 0.30 short leg)."""
        book = self.calls if opt_type.upper() == "CE" else self.puts
        cands = [q for q in book.values() if q.delta]
        if not cands:
            return None
        return min(cands, key=lambda q: abs(abs(q.delta) - abs(target_delta)))

    def quote(self, strike: float, opt_type: str) -> Optional[OptionQuote]:
        book = self.calls if opt_type.upper() == "CE" else self.puts
        return book.get(strike)

    def to_instrument(self, q: OptionQuote, expiry: Optional[str] = None) -> Instrument:
        return I.option(self.underlying, int(q.strike), q.opt_type,
                        security_id=str(q.security_id), expiry=expiry or self.expiry)


class DataSource(ABC):
    @abstractmethod
    def intraday(self, instrument: Instrument, interval: int = 5, days: int = 5) -> pd.DataFrame: ...
    @abstractmethod
    def daily(self, instrument: Instrument, days: int = 200) -> pd.DataFrame: ...
    @abstractmethod
    def ltp(self, instrument: Instrument) -> float: ...


class DhanLive(DataSource):
    """Live data from Dhan (Data API). Wraps the dhanhq facade."""

    def __init__(self, api):
        self.api = api

    @staticmethod
    def _unwrap(resp):
        if isinstance(resp, dict):
            d = resp.get("data", resp)
            if isinstance(d, dict) and "data" in d:
                d = d["data"]
            return d
        return resp

    def _instrument_type(self, instrument: Instrument) -> str:
        if instrument.kind is AssetKind.OPTION:
            return "OPTIDX" if instrument.symbol.startswith(("NIFTY", "BANKNIFTY")) else "OPTSTK"
        if instrument.segment == C.IDX_I:
            return "INDEX"
        return "EQUITY"

    def intraday(self, instrument: Instrument, interval: int = 5, days: int = 5) -> pd.DataFrame:
        to_d = datetime.now().strftime("%Y-%m-%d")
        frm = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        r = self.api.intraday_minute_data(
            security_id=str(instrument.security_id),
            exchange_segment=instrument.segment,
            instrument_type=self._instrument_type(instrument),
            from_date=frm, to_date=to_d, interval=interval)
        return _candles_to_df(self._unwrap(r))

    def daily(self, instrument: Instrument, days: int = 200) -> pd.DataFrame:
        to_d = datetime.now().strftime("%Y-%m-%d")
        frm = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        r = self.api.historical_daily_data(
            security_id=str(instrument.security_id),
            exchange_segment=instrument.segment,
            instrument_type=self._instrument_type(instrument),
            from_date=frm, to_date=to_d)
        return _candles_to_df(self._unwrap(r))

    def ltp(self, instrument: Instrument) -> float:
        d = self.ltp_batch([instrument])
        return d.get(str(instrument.security_id), 0.0)

    def ltp_batch(self, insts: List[Instrument]) -> Dict[str, float]:
        by_seg: Dict[str, List[int]] = {}
        for ins in insts:
            by_seg.setdefault(ins.segment, []).append(int(ins.security_id))
        r = self.api.ticker_data(by_seg)
        data = self._unwrap(r)
        out: Dict[str, float] = {}
        if isinstance(data, dict):
            for seg, secmap in data.items():
                if isinstance(secmap, dict):
                    for sid, info in secmap.items():
                        out[str(sid)] = float(info.get("last_price", 0.0))
        return out

    # ---------- options ----------
    def expiries(self, underlying: str = "NIFTY") -> List[str]:
        meta = I.underlying_meta(underlying)
        r = self.api.expiry_list(under_security_id=int(meta["security_id"]),
                                 under_exchange_segment=C.IDX_I)
        d = self._unwrap(r)
        return list(d) if isinstance(d, list) else list(d.get("data", []))

    def option_chain(self, underlying: str = "NIFTY", expiry: Optional[str] = None) -> OptionChain:
        meta = I.underlying_meta(underlying)
        if expiry is None:
            expiry = self.expiries(underlying)[0]
        r = self.api.option_chain(under_security_id=int(meta["security_id"]),
                                  under_exchange_segment=C.IDX_I, expiry=expiry)
        d = self._unwrap(r)
        spot = float(d.get("last_price", 0.0))
        calls, puts = {}, {}
        for strike_str, legs in d.get("oc", {}).items():
            strike = float(strike_str)
            for side, book in (("ce", calls), ("pe", puts)):
                leg = legs.get(side) or {}
                if not leg:
                    continue
                book[strike] = OptionQuote(
                    strike=strike, opt_type=side.upper(),
                    ltp=float(leg.get("last_price", 0.0)),
                    iv=float(leg.get("implied_volatility", 0.0)),
                    delta=float((leg.get("greeks") or {}).get("delta", 0.0)),
                    oi=int(leg.get("oi", 0)),
                    security_id=str(leg.get("security_id", "")),
                    bid=float(leg.get("top_bid_price", 0.0)),
                    ask=float(leg.get("top_ask_price", 0.0)),
                )
        return OptionChain(underlying, expiry, spot, calls, puts)


class CsvCache(DataSource):
    """Offline candle cache (for backtests / repeatable paper runs).

    On a miss it can delegate to a live source and persist the result, so a
    backtest pulls each series from Dhan once, then reads from disk.
    """
    def __init__(self, folder: str | Path, live: Optional[DhanLive] = None):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.live = live

    def _path(self, instrument: Instrument, tag: str) -> Path:
        safe = instrument.symbol.replace(" ", "_")
        return self.folder / f"{safe}_{tag}.csv"

    def _load_or_fetch(self, instrument, tag, fetch) -> pd.DataFrame:
        p = self._path(instrument, tag)
        if p.exists():
            return pd.read_csv(p, index_col=0, parse_dates=True)
        if self.live is None:
            return pd.DataFrame()
        df = fetch()
        if not df.empty:
            df.to_csv(p)
        return df

    def intraday(self, instrument, interval=5, days=5) -> pd.DataFrame:
        return self._load_or_fetch(instrument, f"{interval}m",
                                   lambda: self.live.intraday(instrument, interval, days))

    def daily(self, instrument, days=200) -> pd.DataFrame:
        return self._load_or_fetch(instrument, "1d",
                                   lambda: self.live.daily(instrument, days))

    def ltp(self, instrument) -> float:
        return self.live.ltp(instrument) if self.live else 0.0
