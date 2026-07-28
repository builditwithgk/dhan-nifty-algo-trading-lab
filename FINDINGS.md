# Research findings — what was tested, and what the data said

*Version 1.0.0 · tests run July 2026*

Every test below uses **real market data** from the Dhan API, is booked net of the full
Indian cost stack plus slippage, and uses out-of-sample (train/test) validation wherever
strategy selection was involved.

**Pass gate:** profit factor **> 1.2 after costs**, a meaningful number of trades, and
persistence on unseen data.

## Bottom line

None of the **intraday / short-term** strategies tested cleared that gate. This is
consistent with the structural cost hurdle in Indian intraday trading: a round-trip runs
roughly 0.09%+, so a strategy needs to net about 0.25% per trade merely to break even.
Longer holding periods, where that fixed hurdle is amortised over a larger move, remain
the more promising direction.

These are results for *these* strategies under *this* gate — not a claim that intraday
trading cannot work. They are published so the method can be inspected and reproduced.

## What was tested

| Strategy | Test | Result |
|---|---|---|
| Equity intraday — ORB breakout | 210 F&O stocks, out-of-sample split | did not clear — winners did not persist (Spearman +0.05); field test PF 0.07 |
| Equity intraday — momentum | full sample, 12+ universe | did not clear — PF 0.65 |
| Equity intraday — VWAP mean-reversion | 210 stocks, out-of-sample | did not clear — field PF ~0.00 in both halves (overtrading + costs) |
| NIFTY options — bull-put spread (sell) | 6 months real option data, held to expiry | did not clear — PF 0.60 |
| …+ uptrend filter / wider strikes / stop-loss | same | did not clear — 0.29–0.73 across variants |
| NIFTY options — directional buying (ORB → ATM CE/PE) | 85 days real option data | did not clear — best PF 0.51 |

## The most important lesson

A full-sample scan of 210 stocks produced **21 "winning" ORB names**, the best at
PF 2.75. Under a proper out-of-sample test they **collapsed to luck** — no persistence.

Any pipeline lacking that second step would have shipped those names as a validated
strategy. Never trust in-sample selection; always confirm on unseen data.

## Where results looked more promising

**Lower-frequency** approaches: cross-sectional *monthly* momentum (an earlier study
showed PF ~2.26, but it was survivorship-biased and needs a clean re-test) and index
SIP. Costs stop dominating once holding periods stretch to days, weeks or months. This
is the direction the [roadmap](ROADMAP.md) points.

## The platform is strategy-agnostic

The value here is the machine, not the sample strategies. The cost model, no-lookahead
backtester, out-of-sample validator and real option-data pipeline will test any new idea
with the same rigor. Reproduce the results above with:

- `demo_spine.py` — risk + execution spine walk-through (paper money, fully offline)
- `verify_dhan.py` — market-data connection check (read-only)
- `run_equity_backtest.py` / `run_fo_scan.py` — equity backtests + universe scan
- `run_oos_validation.py` / `run_strategy_oos.py` — out-of-sample validation
- `run_spread_backtest.py` / `run_spread_retest.py` / `run_spread_stoploss.py` — option spreads
- `run_option_buy.py` — directional option buying
- `run_options_study.py` — daily IV / skew (variance risk premium) logger

These scripts need historical market data, which is not redistributed here — fetch your
own via the Dhan API.
