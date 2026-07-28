# Dhan NIFTY Algo Trading Lab

**An algorithmic trading research platform for Indian markets (Dhan / NSE)**

![Python](https://img.shields.io/badge/python-3.13-blue) ![License](https://img.shields.io/badge/license-MIT-green) ![Version](https://img.shields.io/badge/version-1.0.0-blue) ![Mode](https://img.shields.io/badge/mode-paper%20trading-brightgreen)

Back-test, validate, and **paper-trade** equity-intraday and NIFTY-options strategies —
with a full Indian cost model, out-of-sample validation, and a live control dashboard.

> **This project's headline result is a negative one.** After realistic costs, none of
> the intraday strategies tested here showed a durable edge — and the platform says so
> out loud, with the data. Most retail "algo trading" repos ship a curve-fit backtest
> and overclaim. This one is engineered like a real trading system and used that rigor
> to *falsify its own strategies* instead of flattering them. The reusable machine is
> the deliverable; the honest findings are the proof it works.

**🟢 v1 is paper trading only.** It ships no live-order broker, so real orders are
impossible in this release — not merely switched off. Live trading is planned for v2
(see [ROADMAP.md](ROADMAP.md)).

---

## Try it in 60 seconds — fully offline

No broker account, no API keys, no market-data files.

```bash
pip install -r requirements.txt
python run_paper.py --demo
```

Then in a second terminal, open the dashboard:

```bash
streamlit run dashboard.py
```

→ **http://localhost:8501** — watch simulated trades open and close, and use the live
pause / kill / flatten controls.

## What it does

- **Equity intraday** — opening-range breakout, momentum, and VWAP mean-reversion across a liquid F&O universe.
- **NIFTY options** — directional ATM buying and defined-risk credit spreads (bull-put / bear-call).
- **Research → paper in one code path** — back-test, then out-of-sample validation, then paper-trade the same strategy object.
- **Streamlit dashboard** — pause / kill / flatten controls, per-class P&L, net-of-cost projections, permanent history.
- **SQLite journal** — every fill, every charge, each day's P&L; trade history survives a daily reset.

## The engineering that makes it trustworthy

*(the part most repos get wrong)*

- **Real fills, real costs.** A fill is the *actual* executed price with slippage, never the intended price, and every trade is booked net of the full Indian charge stack — brokerage, STT, exchange, SEBI, stamp duty, GST.
- **Risk sizing from the stop.** `qty = fixed-rupee risk ÷ stop distance`, rounded down to whole lots and capped by a max-notional rule. If one lot is too big, the trade is *skipped* — never forced to a single unit.
- **An un-bypassable veto pipeline.** Every order funnels through one choke-point whose checks run in order: kill switch → daily-loss halt → position caps (re-read live, enforced per-position).
- **Stops are mandatory.** A signal without a stop raises at construction; there is no way to open an unprotected position.
- **A kill switch that flattens and survives a restart.** It comes back *frozen* — it never wakes up trading by accident.
- **No-lookahead backtester + out-of-sample validator.** Strategy selection is validated on unseen data; in-sample winners are treated as luck until they persist.

## Honest research findings

Every intraday / short-term strategy tested on **real market data**, net of costs, with out-of-sample validation:

| Strategy | Test | Result |
|---|---|---|
| Equity — ORB breakout | 210 F&O stocks, out-of-sample split | ❌ no persistence (Spearman +0.05; field PF 0.07) |
| Equity — momentum | full universe | ❌ PF 0.65 |
| Equity — VWAP mean-reversion | 210 stocks, OOS | ❌ field PF ~0.00 |
| NIFTY — bull-put spread (sell) | 6 months real option data | ❌ PF 0.60 |
| NIFTY — directional option buying | 85 days real option data | ❌ best PF 0.51 |

Pass gate = profit factor **> 1.2 after costs**, enough trades, and out-of-sample
persistence. A full-sample scan produced 21 "winning" ORB names (top PF 2.75) that
**collapsed to luck** out-of-sample — the single most important lesson here.

The one place an edge ever appeared was **lower-frequency** strategies (monthly
cross-sectional momentum, index SIP): costs stop dominating once holds are days to
months. Full write-up: **[FINDINGS.md](FINDINGS.md)**.

## Verify the safety machine

```bash
python demo_spine.py         # plain-English walk-through of the risk/execution spine
python tests/test_spine.py   # automated safety checks (sizing, vetoes, kill switch)
```

## Optional: paper-trade on real live prices

The demo above is fully synthetic. To run the paper engine against **real live market
data**, add Dhan Data API credentials (see `.env.example`) and run:

```bash
python run_paper.py --strategy orb --reset
```

Trades are still fake — v1 has no live-order broker. Credentials are read-only market
data here, are gitignored, and are never logged.

## Architecture

```
config.yaml            all knobs: capital, risk, session, universe, options
run_paper.py           paper engine (equity + options; --demo runs fully offline)
dashboard.py           Streamlit control panel
run_report.py          week / month / all-time P&L report (+ Excel export)
demo_spine.py          offline walk-through of the safety machine
verify_dhan.py         read-only market-data connection check

gk/
  models.py            typed objects (Signal, OrderRequest, Fill, Position, ...)
  config.py            loads config.yaml + .env into a typed Settings
  constants.py         DhanHQ v2.2.0 enums (captured from the SDK)
  instruments.py       symbol -> security_id / lot / tick
  costs.py             full Indian cost model
  clock.py             IST market-hours helpers
  journal.py           SQLite: fills, audit log, kill switch, day P&L, history
  risk.py              position sizing + un-bypassable veto pipeline
  execution.py         OrderManager — the single order choke-point
  runtime.py           broker factory (paper only in v1)
  control.py           dashboard <-> engine control bridge + heartbeat
  reports.py           P&L projections + performance reporting
  marketdata.py        live LTP / candles / option chain (Dhan Data API)
  backtest.py          no-lookahead backtester
  strategies/          orb.py, momentum.py, vwap.py, nifty_breakout.py
  brokers/
    base.py            Broker interface
    paper.py           PaperBroker — fake money, realistic mechanics
tests/test_spine.py    automated safety-spine checks
```

### Research scripts

`run_equity_backtest.py` · `run_fo_scan.py` · `run_oos_validation.py` ·
`run_strategy_oos.py` · `run_spread_backtest.py` · `run_option_buy.py` ·
`run_options_study.py` · `run_pcr_test.py`

These reproduce the findings above. They need historical data, which is not
redistributed here — fetch your own via the Dhan API.

## Tech stack

Python 3.13 · dhanhq 2.2.0 · pandas / numpy · Streamlit · SQLite (WAL) · PyYAML · python-dotenv

## What is deliberately *not* in this repo

- `.env` / API tokens — bring your own (`.env.example` shows the shape)
- `state/` databases — trade history stays local
- `data/` historical CSVs — licensed market data; fetch it yourself

## Disclaimer

Educational and research use only. **Not financial advice.** Trading equities and
options involves substantial risk of loss and there is **no guarantee of profit**. The
strategies included here were tested and found *unprofitable* after costs — they are
published as honest research, not as recommendations. Use at your own risk, and never
trade money you cannot afford to lose.

## License

MIT — see [LICENSE](LICENSE).
