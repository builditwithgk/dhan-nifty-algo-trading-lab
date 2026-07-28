"""Dashboard <-> engine control bridge.

The dashboard WRITES state/control.json; the running engine READS it at the top
of every cycle and obeys. This is how you start/stop and re-tune the engine from
the web UI without restarting it. Writes are atomic (temp + replace) so the
engine never reads a half-written file.

Also: the engine writes state/heartbeat.json each cycle so the dashboard can
show whether it is actually alive.
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULTS = {
    "paused": False,                 # stop opening NEW trades (still manages + squares off)
    "kill": False,                   # engage kill switch + flatten everything
    "reset_kill": False,             # one-shot: clear a kill switch, then auto-resets
    "flatten_now": False,            # one-shot: flatten all, then auto-resets
    "equity_enabled": True,
    "options_enabled": True,
    "capital": None,                 # None -> use config.yaml (change per day here)
    "risk_per_trade_pct": None,
    "daily_loss_limit": None,        # rupees; None -> use % of capital
    "daily_profit_target": None,     # rupees; halt the day once up this much
    "max_equity_positions": None,    # None -> use config.yaml
    "max_option_positions": None,
    "max_equity_trades_day": None,
    "max_option_trades_day": None,
}


def _path(state_dir) -> Path:
    return Path(state_dir) / "control.json"


def read_control(state_dir) -> dict:
    p = _path(state_dir)
    d = dict(DEFAULTS)
    if p.exists():
        try:
            data = json.loads(p.read_text())
            d.update({k: v for k, v in data.items() if k in DEFAULTS})
        except Exception:
            pass
    return d


def write_control(state_dir, updates: dict) -> dict:
    cur = read_control(state_dir)
    cur.update({k: v for k, v in updates.items() if k in DEFAULTS})
    p = _path(state_dir)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur, indent=2))
    tmp.replace(p)
    return cur


def write_heartbeat(state_dir, payload: dict) -> None:
    p = Path(state_dir) / "heartbeat.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload))
    tmp.replace(p)


def read_heartbeat(state_dir) -> dict:
    p = Path(state_dir) / "heartbeat.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}
