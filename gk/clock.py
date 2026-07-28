"""IST market-hours helper. All trading-time decisions go through here."""
from __future__ import annotations

from datetime import datetime, time
from typing import Optional

import pytz

IST = pytz.timezone("Asia/Kolkata")


def _to_time(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))


def now_ist() -> datetime:
    return datetime.now(IST)


def is_weekday(dt: Optional[datetime] = None) -> bool:
    dt = dt or now_ist()
    return dt.weekday() < 5   # Mon-Fri (holiday calendar added at go-live)


def is_market_open(open_="09:15", close="15:30", dt: Optional[datetime] = None) -> bool:
    dt = dt or now_ist()
    if not is_weekday(dt):
        return False
    return _to_time(open_) <= dt.time() <= _to_time(close)


def past(hhmm: str, dt: Optional[datetime] = None) -> bool:
    """True if the current IST time is at/after hhmm."""
    dt = dt or now_ist()
    return dt.time() >= _to_time(hhmm)


def before(hhmm: str, dt: Optional[datetime] = None) -> bool:
    dt = dt or now_ist()
    return dt.time() < _to_time(hhmm)
