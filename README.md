# Dhan NIFTY Algo Trading Lab

**An algorithmic trading research platform for Indian markets (Dhan / NSE)**

![Python](https://img.shields.io/badge/python-3.13-blue) ![License](https://img.shields.io/badge/license-MIT-green) ![Version](https://img.shields.io/badge/version-1.0.0-blue) ![Mode](https://img.shields.io/badge/mode-paper%20trading-brightgreen)

Back-test, validate, and **paper-trade** equity-intraday and NIFTY-options strategies —
with a full Indian cost model, out-of-sample validation, and a live control dashboard.

> **Find out whether a strategy actually works — before you risk a rupee.**
> A backtest that ignores brokerage, STT and slippage will tell you almost anything you
> want to hear. This platform is built to give you the real answer: every trade is
> booked at a realistic fill price net of the full Indian charge stack, and every
> promising result is re-tested on data it has never seen.
>
> It is deliberately strategy-agnostic. Bring your own idea, run it through the same
> pipeline, and get a verdict you can trust — the included strategies come with their
> complete, unedited test results as a worked example of the method.

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

## The engineering that makes the results trustworthy

*Results are only as good as the machine that produced them. This is what backs them:*

- **Real fills, real costs.** A fill is the *actual* executed price with slippage, never the intended price, and every trade is booked net of the full Indian charge stack — brokerage, STT, exchange, SEBI, stamp duty, GST.
- **Risk sizing from the stop.** `qty = fixed-rupee risk ÷ stop distance`, rounded down to whole lots and capped by a max-notional rule. If one lot is too big, the trade is *skipped* — never forced to a single unit.
- **An un-bypassable veto pipeline.** Every order funnels through one choke-point whose checks run in order: kill switch → daily-loss halt → position caps (re-read live, enforced per-position).
- **Stops are mandatory.** A signal without a stop raises at construction; there is no way to open an unprotected position.
- **A kill switch that flattens and survives a restart.** It comes back *frozen* — it never wakes up trading by accident.
- **No-lookahead backtester + out-of-sample validator.** Strategy selection is validated on unseen data; in-sample winners are treated as luck until they persist.

## The method, demonstrated

Rather than ship a polished backtest, this repo publishes its **complete test results**
so you can judge the pipeline for yourself. Each classic intraday strategy was run on
real market data, net of costs, and validated out-of-sample:

| Strategy | Test | Result vs the gate |
|---|---|---|
| Equity — ORB breakout | 210 F&O stocks, out-of-sample split | did not clear (Spearman +0.05; field PF 0.07) |
| Equity — momentum | full universe | did not clear (PF 0.65) |
| Equity — VWAP mean-reversion | 210 stocks, OOS | did not clear (field PF ~0.00) |
| NIFTY — bull-put spread (sell) | 6 months real option data | did not clear (PF 0.60) |
| NIFTY — directional option buying | 85 days real option data | did not clear (best PF 0.51) |

The gate is deliberately strict: profit factor **> 1.2 after costs**, a meaningful
number of trades, and persistence on unseen data. None of these textbook intraday
setups cleared it — a result worth knowing *before* funding them, and consistent with
the structural cost hurdle in Indian intraday trading.

**The most useful lesson is in the near-miss.** A full-sample scan surfaced 21
"winning" ORB names, the best at PF 2.75. Out-of-sample, they collapsed to luck. Any
pipeline without that second step would have shipped them as a strategy — which is
exactly the failure mode this project is built to catch.

Where results did look more promising: **lower-frequency** approaches (monthly
cross-sectional momentum, index SIP), where costs stop dominating once holding periods
stretch to days or months. That is the direction the [roadmap](ROADMAP.md) points.

Full write-up with methodology: **[FINDINGS.md](FINDINGS.md)**.

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

## Before you use this — please read

This project is shared for **education and research**. It is a testing platform, not a
money-making product, and nothing in it is financial advice.

**What you can rely on**
- The engine, cost model, backtester and validator are the deliverable, and they are
  built to be correct. Run `python tests/test_spine.py` to check the safety machine yourself.
- v1 is **paper trading only** — it ships no live-order broker, so it cannot place a
  real order. Nothing you do here can move real money.
- Every number in the results above is reproducible with the included research scripts.

**What you should not assume**
- The bundled strategies are **examples of the method, not recommendations**. They were
  tested and did not clear the profitability gate after costs. Please do not fund them
  because they appear in a repository.
- A passing backtest is evidence, not a guarantee. Markets change, and past results
  never promise future returns.
- Cost, lot-size and expiry rules are current as of 2026 and change over time — verify
  them against your broker before drawing conclusions.
- If you extend this toward live trading, that is your own risk to own. Test on paper
  first, start at the smallest possible size, and never trade money you cannot afford
  to lose.

**Not investment advice.** The authors are not licensed financial advisers and accept
no liability for any loss arising from use of this software. Trading equities and
options carries substantial risk, including loss of your entire capital.

## License

MIT — see [LICENSE](LICENSE).
