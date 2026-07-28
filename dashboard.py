"""Algo Trading Lab — paper-trading dashboard with live controls.

Run:  streamlit run dashboard.py   (open http://localhost:8501)

Reads the engine's journal (state/paper.db) and its heartbeat, and WRITES a
control file the engine obeys — so you can pause/resume, flatten, flip the kill
switch, toggle equity/options, and change caps and per-day limits without
restarting the engine. It never places orders itself.
"""
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytz
import streamlit as st
import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from gk.control import read_control, write_control, read_heartbeat  # noqa: E402
from gk import reports  # noqa: E402

STATE = ROOT / "state"
IST = pytz.timezone("Asia/Kolkata")

st.set_page_config(page_title="Algo Trading Lab", page_icon="📈", layout="wide")


def cfg():
    with open(ROOT / "config.yaml") as fh:
        return yaml.safe_load(fh)


# v1 is PAPER ONLY — the dashboard always reads the paper engine's journal.
DB = STATE / "paper.db"


def q(sql):
    if not DB.exists():
        return pd.DataFrame()
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        return pd.read_sql_query(sql, con)
    except Exception:
        return pd.DataFrame()
    finally:
        con.close()


def kv():
    df = q("SELECT key, value FROM kv")
    return dict(zip(df.key, df.value)) if not df.empty else {}


def money(x):
    try:
        return f"₹{float(x):,.0f}"
    except Exception:
        return "₹0"


def is_option(sym: str) -> bool:
    s = str(sym)
    return " CE" in s or " PE" in s or "SPREAD" in s


c = cfg()
today = datetime.now(IST).date().isoformat()
state = kv()
ctl = read_control(STATE)
hb = read_heartbeat(STATE)
killed = state.get("killed", "0") == "1"
day_pnl = float(state.get("day_realized_pnl", "0")) if state.get("day_date") == today else 0.0
eff_capital = ctl["capital"] if ctl["capital"] is not None else c["capital"]
loss_limit = ctl["daily_loss_limit"] or (eff_capital * c["max_daily_loss_pct"] / 100)
profit_target = ctl["daily_profit_target"] or 0

# ---- engine heartbeat status ----
if hb.get("ts"):
    try:
        age = (datetime.now(IST) - datetime.fromisoformat(hb["ts"])).total_seconds()
    except Exception:
        age = 9e9
    engine_live = age < 150
    engine_txt = (f"🟢 Engine live · {int(age)}s ago" if engine_live
                  else f"🔴 Engine stale · {int(age)}s ago")
else:
    engine_live, engine_txt = False, "🔴 Engine not running"

# ============================ SIDEBAR: CONTROLS ============================
st.sidebar.title("Algo Trading Lab")
st.sidebar.caption("Paper — fake money · controls below")
st.sidebar.markdown(f"**{engine_txt}**")
if ctl["paused"]:
    st.sidebar.warning("Trading is PAUSED")

st.sidebar.subheader("Controls")
b1, b2 = st.sidebar.columns(2)
if b1.button("▶ Resume" if ctl["paused"] else "⏸ Pause", use_container_width=True):
    write_control(STATE, {"paused": not ctl["paused"]}); st.rerun()
if b2.button("🔻 Flatten all", use_container_width=True):
    write_control(STATE, {"flatten_now": True}); st.rerun()
if killed:
    if st.sidebar.button("♻ Reset kill & resume", use_container_width=True):
        write_control(STATE, {"reset_kill": True, "paused": False}); st.rerun()
else:
    if st.sidebar.button("🛑 KILL (stop + flatten)", use_container_width=True):
        write_control(STATE, {"kill": True}); st.rerun()

with st.sidebar.form("settings"):
    st.caption("Settings (engine picks these up live)")
    eq_en = st.checkbox("Equity enabled", value=ctl["equity_enabled"])
    op_en = st.checkbox("Options enabled", value=ctl["options_enabled"])
    eqp = st.number_input("Max equity positions", 1, 10,
                          int(ctl["max_equity_positions"] or c["max_equity_positions"]))
    opp = st.number_input("Max option positions", 1, 10,
                          int(ctl["max_option_positions"] or c["max_option_positions"]))
    eqd = st.number_input("Max equity trades / day", 1, 20,
                          int(ctl["max_equity_trades_day"] or c.get("max_equity_trades_per_day", 5)))
    opd = st.number_input("Max option trades / day", 1, 20,
                          int(ctl["max_option_trades_day"] or c.get("max_option_trades_per_day", 5)))
    if st.form_submit_button("Apply settings"):
        write_control(STATE, {"equity_enabled": eq_en, "options_enabled": op_en,
                              "max_equity_positions": int(eqp), "max_option_positions": int(opp),
                              "max_equity_trades_day": int(eqd), "max_option_trades_day": int(opd)})
        st.success("Applied — live next cycle")

with st.sidebar.form("moneyrisk"):
    st.caption("💰 Money & risk (change per day)")
    cap = st.number_input("Capital ₹ (allocation)", 10000, 20000000, int(eff_capital), step=50000)
    rpt = st.number_input("Risk per trade %", 0.1, 5.0,
                          float(ctl["risk_per_trade_pct"] or c["risk_per_trade_pct"]), step=0.1)
    dll = st.number_input("Daily loss limit ₹ (0 = auto %)", 0, 2000000,
                          int(ctl["daily_loss_limit"] or 0), step=1000)
    dpt = st.number_input("Daily profit target ₹ (0 = off)", 0, 2000000,
                          int(ctl["daily_profit_target"] or 0), step=1000)
    if st.form_submit_button("Apply money & risk"):
        write_control(STATE, {"capital": int(cap), "risk_per_trade_pct": float(rpt),
                              "daily_loss_limit": int(dll), "daily_profit_target": int(dpt)})
        st.success("Applied — live next cycle")

auto = st.sidebar.checkbox("Auto-refresh (off while editing)", value=True)
every = st.sidebar.slider("Refresh (sec)", 3, 30, 6)

# ============================ MAIN ============================
st.title("📈 Dhan NIFTY Algo Trading Lab — Paper Trading")
st.markdown(f"**🟢 PAPER MODE — no real orders possible**  ·  {engine_txt}  ·  "
            f"{datetime.now(IST):%H:%M:%S} IST")

orders = q("SELECT * FROM orders WHERE status='OPEN'")
fills = q("SELECT * FROM fills ORDER BY id")
fills_today = fills[fills.ts.str.startswith(today)] if not fills.empty else fills

# completed trades today, tagged by asset class
comp = []
if not fills_today.empty:
    for oid, g in fills_today.groupby("order_id"):
        e = g[g.kind == "ENTRY"]; x = g[g.kind == "EXIT"]
        if e.empty or x.empty:
            continue
        e = e.iloc[0]; x = x.iloc[0]
        sign = 1 if e.side == "BUY" else -1
        net = (x.price - e.price) * e.quantity * sign - e.charges - x.charges
        comp.append(dict(symbol=e.symbol, side=e.side, qty=int(e.quantity),
                         entry=round(e.price, 2), exit=round(x.price, 2), net=round(net, 2),
                         opt=is_option(e.symbol), exit_time=str(x.ts)[11:16]))
comp = pd.DataFrame(comp)
eq_pnl = comp[~comp.opt].net.sum() if not comp.empty else 0.0
op_pnl = comp[comp.opt].net.sum() if not comp.empty else 0.0

open_eq = orders[~orders.symbol.map(is_option)] if not orders.empty else pd.DataFrame()
open_op = orders[orders.symbol.map(is_option)] if not orders.empty else pd.DataFrame()

# entry-charge per order (used so spread projections include the front-loaded cost)
entry_ch = {}
if not fills.empty:
    for _, f in fills[fills.kind == "ENTRY"].iterrows():
        entry_ch[f.order_id] = f.charges


def with_projection(df):
    """Add 'If Target ₹' and 'If Stop ₹' columns (net-of-cost projections)."""
    if df.empty:
        return df
    d = df.copy()
    proj = d.apply(lambda r: reports.project_pnl(
        r["entry_price"], r["stop"], r["target"], r["quantity"], r["side"],
        r["symbol"], entry_ch.get(r["order_id"], 0.0)), axis=1)
    d["if_target"] = [p[0] for p in proj]
    d["if_stop"] = [p[1] for p in proj]
    return d

# ---- metric tiles ----
m = st.columns(6)
m[0].metric("Capital (allocated)", money(eff_capital))
m[1].metric("Day P&L", money(day_pnl))
m[2].metric("Equity P&L (today)", money(eq_pnl))
m[3].metric("Options P&L (today)", money(op_pnl))
m[4].metric("Open (eq / opt)", f"{len(open_eq)} / {len(open_op)}")
m[5].metric("Kill switch", "ENGAGED 🔴" if killed else "OK 🟢")
tgt_txt = money(profit_target) if profit_target else "off"
st.caption(f"Guardrails today → stop at loss {money(loss_limit)} · profit target {tgt_txt} · "
           f"risk/trade {ctl['risk_per_trade_pct'] or c['risk_per_trade_pct']}%")
if killed:
    st.error("Kill switch ENGAGED — trading halted. Use 'Reset kill & resume' in the sidebar.")

# ---- two columns: EQUITY | OPTIONS ----
colE, colO = st.columns(2)

with colE:
    st.subheader("📊 Equity (intraday)")
    if open_eq.empty:
        st.info("No open equity positions.")
    else:
        v = with_projection(open_eq)[["symbol", "side", "quantity", "entry_price", "stop",
                                      "target", "if_target", "if_stop", "strategy"]]
        v.columns = ["Symbol", "Side", "Qty", "Entry", "Stop", "Target",
                     "If Target ₹", "If Stop ₹", "Strat"]
        st.dataframe(v, use_container_width=True, hide_index=True)
    ce = comp[~comp.opt] if not comp.empty else pd.DataFrame()
    st.caption("Today's equity trades")
    if ce.empty:
        st.write("—")
    else:
        d = ce[["symbol", "side", "entry", "exit", "net", "exit_time"]]
        d.columns = ["Symbol", "Side", "Entry", "Exit", "Net ₹", "Time"]
        st.dataframe(d.iloc[::-1], use_container_width=True, hide_index=True)

with colO:
    st.subheader("🎯 Options (NIFTY)")
    st.caption("Spreads (…-SPREAD name shows both strikes): Entry = credit received; "
               "Stop/Target = buy-back value; both legs exit together; loss is capped.")
    if open_op.empty:
        st.info("No open option positions.")
    else:
        v = with_projection(open_op)[["symbol", "side", "quantity", "entry_price", "stop",
                                      "target", "if_target", "if_stop", "strategy"]]
        v.columns = ["Contract", "Side", "Qty", "Entry", "Stop", "Target",
                     "If Target ₹", "If Stop ₹", "Strat"]
        st.dataframe(v, use_container_width=True, hide_index=True)
    co = comp[comp.opt] if not comp.empty else pd.DataFrame()
    st.caption("Today's option trades")
    if co.empty:
        st.write("—")
    else:
        d = co[["symbol", "side", "entry", "exit", "net", "exit_time"]]
        d.columns = ["Contract", "Side", "Entry", "Exit", "Net ₹", "Time"]
        st.dataframe(d.iloc[::-1], use_container_width=True, hide_index=True)

# ---- activity log ----
st.subheader("Activity log")
ev = q("SELECT ts, kind, message FROM events ORDER BY id DESC LIMIT 25")
if ev.empty:
    st.caption("No activity yet. Start:  python run_paper.py --demo")
else:
    ev["ts"] = ev["ts"].str[11:19]
    st.dataframe(ev.rename(columns={"ts": "Time", "kind": "Event", "message": "Detail"}),
                 use_container_width=True, hide_index=True)

# ---- performance / daily P&L report ----
st.divider()
with st.expander("📈 Performance & daily P&L report (all history)", expanded=False):
    trades = reports.load_history(DB)      # permanent, survives --reset
    if trades.empty:
        st.info("No trade history yet — it accumulates across days as trades close "
                "(and survives the daily --reset).")
    else:
        w = st.columns(3)
        w[0].metric("Last 7 days", money(reports.last_n_days(trades, 7)["net"].sum()))
        w[1].metric("Last 30 days", money(reports.last_n_days(trades, 30)["net"].sum()))
        w[2].metric("All time", money(trades["net"].sum()))
        summ = reports.summary(trades)
        daily = reports.daily_pnl(trades).set_index("date")
        r = st.columns(5)
        r[0].metric("Total net", money(summ["total_net"]))
        r[1].metric("Trades / days", f"{summ['n_trades']} / {summ['days']}")
        r[2].metric("Win rate", f"{summ['win_rate']:.0f}%")
        r[3].metric("Profit factor", f"{summ['profit_factor']}")
        r[4].metric("Max drawdown", money(summ["max_drawdown"]))
        r2 = st.columns(5)
        r2[0].metric("Best day", money(summ["best_day"]))
        r2[1].metric("Worst day", money(summ["worst_day"]))
        r2[2].metric("Avg win", money(summ["avg_win"]))
        r2[3].metric("Avg loss", money(summ["avg_loss"]))
        r2[4].metric("Total costs paid", money(summ["total_costs"]))

        st.caption("Equity curve (cumulative net P&L)")
        st.line_chart(daily["cum_net"], height=200)
        st.caption("Daily P&L")
        st.bar_chart(daily["net"], height=200)

        st.caption("Day-by-day")
        tbl = daily.reset_index()[["date", "trades", "win_rate", "gross", "costs", "net", "cum_net"]]
        tbl.columns = ["Date", "Trades", "Win%", "Gross ₹", "Costs ₹", "Net ₹", "Cumulative ₹"]
        st.dataframe(tbl.iloc[::-1], use_container_width=True, hide_index=True)

        c1, c2 = st.columns(2)
        with c1:
            st.caption("By asset class")
            st.dataframe(reports.by_class(trades), use_container_width=True, hide_index=True)
        with c2:
            st.caption("By strategy")
            st.dataframe(reports.by_strategy(trades), use_container_width=True, hide_index=True)

if auto:
    time.sleep(every)
    st.rerun()
