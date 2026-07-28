"""Dhan NIFTY Algo Trading Lab — safety-first research platform (PAPER ONLY).

Package layout:
    constants.py    real DhanHQ v2.2.0 enums (captured from the installed SDK)
    models.py       typed data objects (Signal, OrderRequest, Fill, Position, ...)
    config.py       loads config.yaml + .env
    instruments.py  symbol -> security_id / lot size / tick size registry
    costs.py        Indian cost model (brokerage, STT, GST, slippage, ...)
    clock.py        IST market-hours helper
    journal.py      SQLite journal + persisted state (kill switch, day P&L)
    risk.py         position sizing + risk veto pipeline + kill switch
    execution.py    OrderManager — the single choke-point for placing orders
    brokers/        base.Broker, paper.PaperBroker  (no live broker in v1)
"""

__version__ = "1.0.0"
