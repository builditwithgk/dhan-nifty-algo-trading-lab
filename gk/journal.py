"""SQLite journal + persisted state.

Why SQLite (and not flat CSV/JSON like the reviewed repos): several processes
touch this — the engine writes trades, the dashboard reads P&L and flips the
kill switch. CSV with concurrent writers corrupts; SQLite in WAL mode gives us
atomic writes and safe cross-process reads with zero server to run. It earns
its place; nothing heavier is needed.

Persisted here (survives a crash/restart):
  * every order and its ACTUAL fills (never the intended price)
  * an append-only event/audit log
  * key/value state: kill-switch flag, the day's realized P&L, the day's date
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Optional

from .clock import now_ist
from .models import Fill, Position

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    order_id     TEXT PRIMARY KEY,
    symbol       TEXT, security_id TEXT, side TEXT, quantity INTEGER,
    entry_price  REAL, stop REAL, target REAL, product TEXT,
    strategy     TEXT, status TEXT,
    opened_at    TEXT, closed_at TEXT
);
CREATE TABLE IF NOT EXISTS fills (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id  TEXT, symbol TEXT, side TEXT, quantity INTEGER,
    price     REAL, charges REAL, kind TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    ts   TEXT, kind TEXT, message TEXT
);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY, value TEXT
);
-- PERMANENT history (survives --reset) for week/month look-back --
CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, date TEXT, symbol TEXT, kind TEXT, strategy TEXT, side TEXT,
    entry_ref REAL, stop REAL, target REAL, if_target REAL, if_stop REAL,
    taken INTEGER, note TEXT
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT, entry_ts TEXT, exit_ts TEXT, symbol TEXT, kind TEXT,
    strategy TEXT, side TEXT, qty INTEGER, entry REAL, exit REAL,
    charges REAL, net REAL, source TEXT, reason TEXT
);
"""


class Journal:
    def __init__(self, db_path: str | Path):
        self.path = str(db_path)
        self._lock = threading.Lock()
        self._con = sqlite3.connect(self.path, check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA journal_mode=WAL;")
        self._con.executescript(_SCHEMA)
        self._con.commit()
        # Stamp today's date on first use so a same-day restart is NOT mistaken
        # for a new day (which would wrongly clear a persisted kill switch).
        self._roll_day()

    # ---------- audit ----------
    def event(self, kind: str, message: str) -> None:
        with self._lock:
            self._con.execute(
                "INSERT INTO events(ts, kind, message) VALUES(?,?,?)",
                (now_ist().isoformat(), kind, message),
            )
            self._con.commit()

    # ---------- orders & fills ----------
    def record_open(self, pos: Position) -> None:
        with self._lock:
            self._con.execute(
                """INSERT OR REPLACE INTO orders(order_id, symbol, security_id, side,
                   quantity, entry_price, stop, target, product, strategy, status,
                   opened_at, closed_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (pos.order_id, pos.instrument.symbol, pos.instrument.security_id,
                 pos.side.value, pos.quantity, pos.entry_price, pos.stop, pos.target,
                 "INTRADAY", pos.strategy, "OPEN", now_ist().isoformat(), None),
            )
            self._con.commit()

    def abandon_open_orders(self) -> int:
        """Mark leftover OPEN orders as CLOSED on restart. The in-memory paper
        broker starts empty, so any OPEN order in the journal is an orphan from a
        previous run — clearing it keeps the dashboard honest."""
        with self._lock:
            n = self._con.execute("SELECT COUNT(*) FROM orders WHERE status='OPEN'").fetchone()[0]
            if n:
                self._con.execute(
                    "UPDATE orders SET status='ABANDONED', closed_at=? WHERE status='OPEN'",
                    (now_ist().isoformat(),))
                self._con.commit()
        if n:
            self.event("RECONCILE", f"abandoned {n} stale open order(s) from a previous run")
        return n

    def reset_all(self) -> None:
        """Wipe the working journal for a fresh start — but KEEP the permanent
        suggestions + history tables so week/month look-back survives."""
        with self._lock:
            for t in ("orders", "fills", "events", "kv"):   # NOT suggestions/history
                self._con.execute(f"DELETE FROM {t}")
            self._con.commit()
        self._roll_day()
        self.event("RESET", "working journal cleared (history preserved)")

    # ---------------- permanent history (survives reset) ----------------
    def log_suggestion(self, symbol, kind, strategy, side, entry_ref, stop, target,
                       if_target, if_stop, taken, note="") -> None:
        with self._lock:
            self._con.execute(
                """INSERT INTO suggestions(ts, date, symbol, kind, strategy, side,
                   entry_ref, stop, target, if_target, if_stop, taken, note)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (now_ist().isoformat(), now_ist().date().isoformat(), symbol, kind,
                 strategy, side, entry_ref, stop, target, if_target, if_stop,
                 1 if taken else 0, note))
            self._con.commit()

    def log_history(self, entry_ts, exit_ts, symbol, kind, strategy, side, qty,
                    entry, exit_, charges, net, source, reason) -> None:
        with self._lock:
            self._con.execute(
                """INSERT INTO history(date, entry_ts, exit_ts, symbol, kind, strategy,
                   side, qty, entry, exit, charges, net, source, reason)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (str(exit_ts)[:10], str(entry_ts), str(exit_ts), symbol, kind, strategy,
                 side, int(qty), entry, exit_, charges, net, source, reason))
            self._con.commit()

    def record_close(self, order_id: str) -> None:
        with self._lock:
            self._con.execute(
                "UPDATE orders SET status='CLOSED', closed_at=? WHERE order_id=?",
                (now_ist().isoformat(), order_id),
            )
            self._con.commit()

    def entries_today(self, kind: str) -> int:
        """Count today's NEW entries by asset class (options inferred from the
        ' CE'/' PE' in the symbol). Survives restart, so per-day caps hold."""
        today = now_ist().date().isoformat()
        with self._lock:
            if kind == "OPTION":
                row = self._con.execute(
                    "SELECT COUNT(*) FROM fills WHERE kind='ENTRY' AND ts LIKE ? "
                    "AND (symbol LIKE '% CE%' OR symbol LIKE '% PE%' OR symbol LIKE '%SPREAD%')",
                    (today + "%",)).fetchone()
            else:
                row = self._con.execute(
                    "SELECT COUNT(*) FROM fills WHERE kind='ENTRY' AND ts LIKE ? "
                    "AND symbol NOT LIKE '% CE%' AND symbol NOT LIKE '% PE%' "
                    "AND symbol NOT LIKE '%SPREAD%'",
                    (today + "%",)).fetchone()
        return row[0] if row else 0

    def record_fill(self, order_id: str, fill: Fill) -> None:
        with self._lock:
            self._con.execute(
                """INSERT INTO fills(order_id, symbol, side, quantity, price,
                   charges, kind, ts) VALUES(?,?,?,?,?,?,?,?)""",
                (order_id, fill.instrument.symbol, fill.side.value, fill.quantity,
                 fill.price, fill.charges, fill.kind, fill.ts),
            )
            self._con.commit()

    # ---------- key/value state ----------
    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._lock:
            row = self._con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set(self, key: str, value: str) -> None:
        with self._lock:
            self._con.execute(
                "INSERT OR REPLACE INTO kv(key, value) VALUES(?,?)", (key, str(value))
            )
            self._con.commit()

    # ---------- day P&L (auto-rolls at date change) ----------
    def _roll_day(self) -> None:
        today = now_ist().date().isoformat()
        if self.get("day_date") != today:
            self.set("day_date", today)
            self.set("day_realized_pnl", "0.0")
            self.set("killed", "0")

    def add_realized_pnl(self, amount: float) -> float:
        with self._lock_free_roll():
            cur = float(self.get("day_realized_pnl", "0.0"))
            cur += amount
            self.set("day_realized_pnl", f"{cur:.2f}")
            return cur

    def day_realized_pnl(self) -> float:
        self._roll_day()
        return float(self.get("day_realized_pnl", "0.0"))

    # kill switch (persisted; survives restart frozen — never wakes up live)
    def is_killed(self) -> bool:
        self._roll_day()
        return self.get("killed", "0") == "1"

    def kill(self, reason: str = "") -> None:
        self.set("killed", "1")
        self.event("KILL", reason or "kill switch engaged")

    def reset_kill(self) -> None:
        self.set("killed", "0")
        self.event("KILL_RESET", "kill switch reset")

    # helper: roll the day without deadlocking the outer lock
    class _NoLock:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def _lock_free_roll(self):
        self._roll_day()
        return self._NoLock()

    def close(self) -> None:
        with self._lock:
            self._con.close()
