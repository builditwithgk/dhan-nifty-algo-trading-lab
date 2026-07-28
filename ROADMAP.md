# Roadmap

## v1.0 — Paper trading (current release)

Everything needed to research, back-test, and paper-trade a strategy end to end:

- [x] Risk + execution spine (sizing from the stop, un-bypassable veto pipeline, kill switch)
- [x] Full Indian cost model (brokerage, STT, exchange, SEBI, stamp, GST) + slippage
- [x] No-lookahead backtester and out-of-sample validator
- [x] Paper engine — equity intraday + NIFTY options (directional and credit spreads)
- [x] Streamlit dashboard — pause / kill / flatten, per-class P&L, net-of-cost projections
- [x] SQLite journal with permanent trade history and week/month/all-time reporting
- [x] Offline demo mode (no API keys, no market data required)

**v1 ships no live-order broker.** Real orders are impossible in this release, not
merely switched off — see `gk/runtime.py`.

## v2 — Live trading (planned)

- [ ] Live broker with **Dhan Super Orders** so the stop and target rest at the broker
      in a single order id — a crashed process still leaves the position protected
- [ ] Multi-lock go-live gate (config flags + typed confirmation + per-order approval)
- [ ] Read-only pre-flight validation (funds, margin calculator) before any order
- [ ] Reconcile the broker's real trade book against what the engine suggested
- [ ] Automated token refresh for unattended sessions

## Research backlog

The honest finding in [FINDINGS.md](FINDINGS.md) is that no intraday strategy tested
here clears costs. Directions that remain genuinely worth testing:

- [ ] **Lower-frequency strategies** — cross-sectional monthly momentum and index SIP.
      This is the one place an edge appeared; costs stop dominating once holds are
      days to months. Needs a clean, survivorship-bias-free re-test.
- [ ] **Conditional opening-range breakout** — naive ORB fails, but gating it on a
      volume surge, index/sector agreement, a retest entry, or a volatility regime
      filter has not been ruled out.
- [ ] **A defensive news layer** — use an events/results calendar and a volatility
      index to *avoid* trouble (skip entries around high-impact events), rather than
      to predict direction. News as a shield, not a sword.

## Engine / UX backlog

- [ ] Soft-stop vs hard-stop toggle for the daily loss limit and profit target
      (today both block new entries; open positions keep running)
- [ ] Restore open positions on restart instead of abandoning them
- [ ] Suggest-only mode — surface trade ideas without auto-entering (human in the loop)
- [ ] Strategy picker and intraday equity curve in the dashboard
- [ ] Containerised deployment. If exposed, the dashboard must be bound to localhost
      and reached over an SSH tunnel — it controls the engine and Streamlit has no
      built-in auth.
