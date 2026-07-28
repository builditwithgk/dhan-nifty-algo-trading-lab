"""Self-contained tests for the execution + risk spine.

Run:  python tests/test_spine.py     (no pytest needed)
Each check prints PASS/FAIL; exit code is non-zero if anything fails.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gk import costs, instruments
from gk.brokers.paper import PaperBroker
from gk.config import load
from gk.execution import OrderManager
from gk.journal import Journal
from gk.models import Side, Signal
from gk.risk import RiskManager, size_position

_fails = []


def check(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        _fails.append(name)


def _fresh(mode_overrides=None):
    """A fresh journal + broker + managers in a temp dir."""
    tmp = tempfile.mkdtemp()
    j = Journal(Path(tmp) / "gk.db")
    s = load()
    if mode_overrides:
        for k, v in mode_overrides.items():
            setattr(s, k, v)
    broker = PaperBroker(j, starting_capital=s.capital,
                         equity_slippage_pct=s.equity_slippage_pct)
    risk = RiskManager(s, j)
    om = OrderManager(s, broker, risk, j)
    return s, j, broker, risk, om


# ----------------------------------------------------------------------
def test_costs():
    print("test_costs")
    # Equity intraday round trip on ~1L turnover should be a few hundred rupees.
    rt = costs.round_trip_equity(1000, 1010, 100, intraday=True)
    check("equity round-trip charges are positive and sane (<0.3%)",
          0 < rt < 0.003 * 100000)
    # Option SELL side pays 0.1% STT; a sell of 50 units @ 200 => >= 10 rupees STT.
    ch = costs.option_charges(200, 50, is_buy=False)
    check("option sell STT is 0.1% of premium (>=10 on 10k premium)",
          abs(ch.stt - 0.001 * 200 * 50) < 1e-6)
    check("option buy pays no STT", costs.option_charges(200, 50, is_buy=True).stt == 0)


def test_sizing():
    print("test_sizing")
    inst = instruments.equity("RELIANCE")
    # risk 2500, stop distance 10 -> 250 units, but notional cap 125000 -> 125.
    r = size_position(inst, entry_price=1000, stop=990,
                      risk_rupees=2500, max_notional=125000)
    check("sizing respects notional cap (125 not 250)", r.quantity == 125 and r.ok)
    # Impossibly tight notional -> returns 0, NOT max(1,...).
    r2 = size_position(inst, entry_price=5000, stop=4999,
                       risk_rupees=2500, max_notional=1000)
    check("oversized single unit -> qty 0 (never forced to 1)",
          r2.quantity == 0 and not r2.ok)
    # NIFTY option lot rounding: lot 65, must be a multiple of 65.
    opt = instruments.option("NIFTY", 24000, "CE", security_id="99999")
    r3 = size_position(opt, entry_price=100, stop=70,
                       risk_rupees=5000, max_notional=500000)
    check("option qty is a whole multiple of the lot (65)",
          r3.quantity % 65 == 0 and r3.quantity > 0)


def test_signal_requires_valid_stop():
    print("test_signal_requires_valid_stop")
    inst = instruments.equity("RELIANCE")
    raised = False
    try:
        Signal(inst, Side.BUY, stop=1010, entry_ref_price=1000)  # stop above entry for a long
    except ValueError:
        raised = True
    check("a BUY signal with stop above entry is rejected", raised)


def test_paper_target_win():
    print("test_paper_target_win")
    s, j, broker, risk, om = _fresh()
    inst = instruments.equity("RELIANCE")
    broker.set_price(inst.security_id, 1000)
    sig = Signal(inst, Side.BUY, stop=990, entry_ref_price=1000, target=1020,
                 strategy="test")
    out = om.open_from_signal(sig)
    check("entry opened", out.ok)
    check("one live position", len(broker.get_positions()) == 1)
    pos = broker.get_positions()[0]
    check("entry fill includes slippage (>1000)", pos.entry_price > 1000)
    # Move to target.
    broker.feed(inst.security_id, 1020)
    check("position closed at target", len(broker.get_positions()) == 0)
    check("realized P&L is positive after costs", broker.realized_pnl > 0)


def test_paper_stop_loss():
    print("test_paper_stop_loss")
    s, j, broker, risk, om = _fresh()
    inst = instruments.equity("SBIN")
    broker.set_price(inst.security_id, 800)
    sig = Signal(inst, Side.BUY, stop=792, entry_ref_price=800, target=820,
                 strategy="test")
    out = om.open_from_signal(sig)
    check("entry opened", out.ok)
    broker.feed(inst.security_id, 792)   # hit stop
    check("position closed at stop", len(broker.get_positions()) == 0)
    check("realized P&L is negative (loss + costs)", broker.realized_pnl < 0)


def test_max_positions_enforced_per_position():
    print("test_max_positions_enforced_per_position")
    s, j, broker, risk, om = _fresh({"max_equity_positions": 1, "max_open_positions": 10})
    a = instruments.equity("RELIANCE"); broker.set_price(a.security_id, 1000)
    b = instruments.equity("INFY"); broker.set_price(b.security_id, 1500)
    o1 = om.open_from_signal(Signal(a, Side.BUY, stop=990, entry_ref_price=1000, target=1020))
    o2 = om.open_from_signal(Signal(b, Side.BUY, stop=1485, entry_ref_price=1500, target=1530))
    check("first entry accepted", o1.ok)
    check("second equity entry BLOCKED at equity cap of 1 (per-position enforcement)",
          not o2.ok and "equity" in o2.reason)


def test_daily_loss_kill():
    print("test_daily_loss_kill")
    # Tiny daily loss budget so one losing trade trips it.
    s, j, broker, risk, om = _fresh({"max_daily_loss_pct": 0.05})  # 0.05% = 250 on 5L
    inst = instruments.equity("TATASTEEL")
    broker.set_price(inst.security_id, 150)
    om.open_from_signal(Signal(inst, Side.BUY, stop=147, entry_ref_price=150, target=156,
                               strategy="test"))
    broker.feed(inst.security_id, 147)   # loss
    killed = risk.check_daily_loss(broker)
    check("kill switch engaged after daily-loss breach", killed and j.is_killed())
    # Further entries are blocked.
    nxt = om.open_from_signal(Signal(inst, Side.BUY, stop=147, entry_ref_price=150, target=156))
    check("no new entries after kill", not nxt.ok)


def test_kill_switch_persists():
    print("test_kill_switch_persists")
    tmp = tempfile.mkdtemp()
    db = Path(tmp) / "gk.db"
    j1 = Journal(db)
    j1.kill("manual")
    j1.close()
    j2 = Journal(db)   # reopen same db (simulates restart)
    check("kill switch survives restart (comes back frozen)", j2.is_killed())
    j2.close()


def test_kill_flattens():
    print("test_kill_flattens")
    s, j, broker, risk, om = _fresh()
    inst = instruments.equity("MARUTI")
    broker.set_price(inst.security_id, 11000)
    om.open_from_signal(Signal(inst, Side.BUY, stop=10900, entry_ref_price=11000,
                               target=11200, strategy="test"))
    check("position open before kill", len(broker.get_positions()) == 1)
    om.engage_kill("panic", flatten=True)
    check("kill switch actually flattened the position",
          len(broker.get_positions()) == 0 and j.is_killed())


def main():
    for fn in [test_costs, test_sizing, test_signal_requires_valid_stop,
               test_paper_target_win, test_paper_stop_loss,
               test_max_positions_enforced_per_position, test_daily_loss_kill,
               test_kill_switch_persists, test_kill_flattens]:
        fn()
    print()
    if _fails:
        print(f"FAILED: {len(_fails)} check(s): {_fails}")
        sys.exit(1)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
