"""A plain-English walkthrough of the safe execution + risk spine.

Run:  python demo_spine.py

No real money, no internet, no API keys. It drives the PaperBroker through a few
scenarios and prints what the machine does, so you can see the safety behaviour
before any strategy or live data is attached.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gk import instruments
from gk.brokers.paper import PaperBroker
from gk.config import load
from gk.execution import OrderManager
from gk.journal import Journal
from gk.models import Side, Signal
from gk.risk import RiskManager


def line(c="-"):
    print(c * 64)


def money(x):
    return f"Rs.{x:,.0f}"


def show_funds(broker, label):
    f = broker.get_funds()
    print(f"  {label}: available {money(f.available_balance)} | "
          f"margin blocked {money(f.utilized)} | "
          f"realized P&L {money(broker.realized_pnl)}")


def main():
    s = load()
    s.capital = 500000
    s.max_open_positions = 2
    tmp = tempfile.mkdtemp()
    j = Journal(Path(tmp) / "gk.db")
    broker = PaperBroker(j, starting_capital=s.capital,
                         equity_slippage_pct=s.equity_slippage_pct)
    risk = RiskManager(s, j)
    om = OrderManager(s, broker, risk, j)

    print()
    line("=")
    print("Algo Trading Lab - execution + risk spine demo (paper money)")
    line("=")
    print(f"Capital {money(s.capital)} | risk/trade {money(s.risk_per_trade)} "
          f"({s.risk_per_trade_pct}%) | daily-loss halt {money(s.max_daily_loss)} "
          f"({s.max_daily_loss_pct}%) | max {s.max_open_positions} positions")
    show_funds(broker, "start")

    # -- Scenario 1: a winning trade that hits its target --------------------
    print("\n1) A trade that goes right (RELIANCE long, target hit)")
    rel = instruments.equity("RELIANCE")
    broker.set_price(rel.security_id, 1000)
    out = om.open_from_signal(Signal(rel, Side.BUY, stop=990, entry_ref_price=1000,
                                     target=1020, strategy="demo"))
    print(f"   -> {out.reason}")
    pos = broker.get_positions()[0]
    print(f"   entry filled @ {money(pos.entry_price)} (incl. slippage), "
          f"stop {money(pos.stop)} & target {money(pos.target)} rest at the broker")
    show_funds(broker, "after entry")
    broker.feed(rel.security_id, 1020)          # price reaches target
    print("   price touches 1020 -> broker-side target fires")
    show_funds(broker, "after exit")

    # -- Scenario 2: a losing trade that hits its stop -----------------------
    print("\n2) A trade that goes wrong (SBIN long, stop hit)")
    sbin = instruments.equity("SBIN")
    broker.set_price(sbin.security_id, 800)
    om.open_from_signal(Signal(sbin, Side.BUY, stop=792, entry_ref_price=800,
                               target=820, strategy="demo"))
    print("   opened; price falls to 792 -> broker-side stop fires (capped loss)")
    broker.feed(sbin.security_id, 792)
    show_funds(broker, "after stop")

    # -- Scenario 3: position cap blocks a 3rd trade -------------------------
    print(f"\n3) Position cap (max {s.max_open_positions}) blocks over-trading")
    for name, px in [("INFY", 1500), ("TCS", 3400), ("LT", 3600)]:
        inst = instruments.equity(name)
        broker.set_price(inst.security_id, px)
        r = om.open_from_signal(Signal(inst, Side.BUY, stop=px * 0.99,
                                       entry_ref_price=px, target=px * 1.02,
                                       strategy="demo"))
        print(f"   {name:9s} -> {'OPENED' if r.ok else 'BLOCKED: ' + r.reason}")

    # -- Scenario 4: kill switch flattens everything -------------------------
    print("\n4) Panic kill switch (actually flattens, then blocks new entries)")
    print(f"   live positions before: {len(broker.get_positions())}")
    om.engage_kill("owner hit the panic button", flatten=True)
    print(f"   live positions after:  {len(broker.get_positions())}  (all closed)")
    blk = om.open_from_signal(Signal(rel, Side.BUY, stop=990, entry_ref_price=1000,
                                     target=1020, strategy="demo"))
    print(f"   try to open again -> {'OPENED' if blk.ok else 'BLOCKED: ' + blk.reason}")

    line("=")
    print(f"End-of-day realized P&L: {money(broker.realized_pnl)} "
          f"(net of all Indian charges)")
    print("Everything above happened with broker-side stops, real fills, and a")
    print("kill switch that survives a restart. No strategy or live data yet -")
    print("that is Step 2.")
    line("=")
    j.close()


if __name__ == "__main__":
    main()
