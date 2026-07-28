# Research findings — what we tested and what the data said

All tests use **real Dhan data**, net of full Indian costs + slippage, with
out-of-sample (train/test) validation where selection was involved. Dates: built
and tested July 2026.

## Bottom line
None of the **intraday / short-term** strategies tested cleared the profitability gate
after costs. That is consistent with the structural cost hurdle in Indian intraday
trading: a round-trip runs ~0.09%+, so a strategy must net roughly 0.25% per trade
before it breaks even. Longer holding periods, where that hurdle is amortised over a
bigger move, remain the more promising direction.

## What was tested

| Strategy | Test | Result |
|---|---|---|
| Equity intraday — ORB breakout | 210 F&O stocks, out-of-sample split | ❌ winners didn't persist (Spearman +0.05); field test PF 0.07 |
| Equity intraday — momentum | full sample, 12 + universe | ❌ PF 0.65 |
| Equity intraday — VWAP mean-reversion | 210 stocks, out-of-sample | ❌ field PF 0.00 both halves (overtrading + costs) |
| NIFTY options — bull-put spread (sell) | 6mo real option data, held-to-expiry | ❌ PF 0.60 |
| …+ uptrend filter / wider strikes / stop-loss | same | ❌ none cleared the gate (0.29–0.73) |
| NIFTY options — directional buying (ORB→ATM CE/PE) | 85d real option data | ❌ best PF 0.51 |

Gate to pass = profit factor > 1.2 after costs, with enough trades and
out-of-sample persistence.

## Key lesson (do not forget)
A full-sample scan of 210 stocks produced **21 "winning" ORB names** (top PF 2.75).
Under a proper out-of-sample test they **collapsed to luck** — no persistence.
Never trust in-sample selection; always validate on unseen data.

## The one place an edge ever appeared
**Lower-frequency** strategies: the owner's prior cross-sectional *monthly*
momentum (PF ~2.26, but survivorship-biased — needs a clean re-test) and index
SIP. Costs stop dominating once holding periods are days/weeks/months.

## The system is strategy-agnostic
The platform (safe execution + broker-side stops + live data + backtester +
out-of-sample validator + real option-data pipeline) works and will faithfully
test any future idea. Scripts:
- `demo_spine.py` — safety spine on paper money
- `verify_dhan.py` — live connection check (read-only)
- `run_equity_backtest.py` / `run_fo_scan.py` — equity backtests + universe scan
- `run_oos_validation.py` / `run_strategy_oos.py` — out-of-sample validation
- `run_spread_backtest.py` / `run_spread_retest.py` / `run_spread_stoploss.py` — option spreads
- `run_option_buy.py` — directional option buying
- `run_options_study.py` — daily IV/skew (VRP) logger
