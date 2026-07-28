"""DhanHQ v2.2.0 constants — captured directly from the installed SDK.

These are the EXACT string values the dhanhq==2.2.0 API expects. The #1 failure
mode in the repos we reviewed was code written against a hallucinated/older SDK
(e.g. `dhanhq(client_id, token)` monolithic init, `get_market_quote`, `NSE`).
The v2.2.0 SDK is modular (DhanContext + Funds/Order/SuperOrder/... classes) and
uses the segment strings below. Verified via `inspect` on 2026-07-22.
"""

# ---- Exchange segments ----
NSE_EQ = "NSE_EQ"
NSE_FNO = "NSE_FNO"
BSE_EQ = "BSE_EQ"
BSE_FNO = "BSE_FNO"
IDX_I = "IDX_I"          # index (spot), e.g. NIFTY index value
MCX_COMM = "MCX_COMM"

# ---- Transaction types ----
BUY = "BUY"
SELL = "SELL"

# ---- Order types ----
MARKET = "MARKET"
LIMIT = "LIMIT"
STOP_LOSS = "STOP_LOSS"            # SL (limit)
STOP_LOSS_MARKET = "STOP_LOSS_MARKET"  # SL-M

# ---- Product types ----
INTRADAY = "INTRADAY"   # MIS
CNC = "CNC"             # delivery
MARGIN = "MARGIN"       # carry-forward F&O
MTF = "MTF"
CO = "CO"
BO = "BO"

# ---- Validity ----
DAY = "DAY"
IOC = "IOC"

# ---- Super Order leg names (for modify/cancel of a leg) ----
LEG_ENTRY = "ENTRY_LEG"
LEG_TARGET = "TARGET_LEG"
LEG_STOP = "STOP_LOSS_LEG"

# ---- Scrip master CSVs ----
COMPACT_CSV_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
DETAILED_CSV_URL = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
