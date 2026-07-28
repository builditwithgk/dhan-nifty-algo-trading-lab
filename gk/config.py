"""Load config.yaml + .env into a simple, typed settings object."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv optional at import time
    load_dotenv = None

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    raw: dict
    # money / risk
    mode: str
    live_trading_enabled: bool
    capital: float
    risk_per_trade_pct: float
    max_daily_loss_pct: float
    daily_profit_target: float
    daily_loss_override: float
    max_open_positions: int
    max_equity_positions: int
    max_option_positions: int
    max_equity_trades_per_day: int
    max_option_trades_per_day: int
    catch_up: bool
    catchup_min_rr: float
    max_notional_per_trade_pct: float
    # options
    options_enabled: bool
    option_lots: int
    option_sl_pct: float
    option_tp_pct: float
    option_cooldown_min: int
    option_buy_enabled: bool
    option_sell_enabled: bool
    sell_min_iv: float
    spread_short_otm: int
    spread_width: int
    spread_sl_mult: float
    spread_tp_frac: float
    # session
    market_open: str
    market_close: str
    entry_cutoff: str
    square_off: str
    # costs
    equity_slippage_pct: float
    option_slippage_pct: float
    # universe
    equity_universe: list
    options_underlying: str
    # state
    state_dir: Path
    # creds (may be empty until go-live)
    dhan_client_id: str
    dhan_access_token: str

    @property
    def max_daily_loss(self) -> float:
        return self.capital * self.max_daily_loss_pct / 100.0

    @property
    def effective_max_daily_loss(self) -> float:
        """Absolute rupee override if set, else the %-of-capital value."""
        return self.daily_loss_override if self.daily_loss_override else self.max_daily_loss

    @property
    def risk_per_trade(self) -> float:
        return self.capital * self.risk_per_trade_pct / 100.0

    @property
    def max_notional_per_trade(self) -> float:
        return self.capital * self.max_notional_per_trade_pct / 100.0


def load(config_path: str | os.PathLike | None = None) -> Settings:
    path = Path(config_path) if config_path else ROOT / "config.yaml"
    with open(path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)

    # Load .env if present (never fails if absent).
    if load_dotenv is not None:
        load_dotenv(ROOT / ".env")

    costs = cfg.get("costs", {})
    options = cfg.get("options", {})
    state_dir = ROOT / cfg.get("state_dir", "state")
    state_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        raw=cfg,
        mode=cfg.get("mode", "paper"),
        live_trading_enabled=bool(cfg.get("live_trading_enabled", False)),
        capital=float(cfg["capital"]),
        risk_per_trade_pct=float(cfg["risk_per_trade_pct"]),
        max_daily_loss_pct=float(cfg["max_daily_loss_pct"]),
        daily_profit_target=float(cfg.get("daily_profit_target", 0)),
        daily_loss_override=0.0,
        max_open_positions=int(cfg.get("max_open_positions", 10)),
        max_equity_positions=int(cfg.get("max_equity_positions", 5)),
        max_option_positions=int(cfg.get("max_option_positions", 5)),
        max_equity_trades_per_day=int(cfg.get("max_equity_trades_per_day", 5)),
        max_option_trades_per_day=int(cfg.get("max_option_trades_per_day", 5)),
        catch_up=bool(cfg.get("catch_up", True)),
        catchup_min_rr=float(cfg.get("catchup_min_rr", 0.5)),
        max_notional_per_trade_pct=float(cfg.get("max_notional_per_trade_pct", 25.0)),
        options_enabled=bool(options.get("enabled", False)),
        option_lots=int(options.get("lots", 1)),
        option_sl_pct=float(options.get("sl_pct", 35)),
        option_tp_pct=float(options.get("tp_pct", 60)),
        option_cooldown_min=int(options.get("cooldown_min", 15)),
        option_buy_enabled=bool(options.get("buy_enabled", True)),
        option_sell_enabled=bool(options.get("sell_enabled", True)),
        sell_min_iv=float(options.get("sell_min_iv", 11)),
        spread_short_otm=int(options.get("spread_short_otm", 2)),
        spread_width=int(options.get("spread_width", 3)),
        spread_sl_mult=float(options.get("spread_sl_mult", 2.0)),
        spread_tp_frac=float(options.get("spread_tp_frac", 0.5)),
        market_open=cfg.get("market_open", "09:15"),
        market_close=cfg.get("market_close", "15:30"),
        entry_cutoff=cfg.get("entry_cutoff", "15:00"),
        square_off=cfg.get("square_off", "15:15"),
        equity_slippage_pct=float(costs.get("equity_slippage_pct", 0.03)),
        option_slippage_pct=float(costs.get("option_slippage_pct", 0.5)),
        equity_universe=list(cfg.get("equity_universe", [])),
        options_underlying=options.get("underlying", "NIFTY"),
        state_dir=state_dir,
        dhan_client_id=os.getenv("DHAN_CLIENT_ID", ""),
        dhan_access_token=os.getenv("DHAN_ACCESS_TOKEN", ""),
    )
