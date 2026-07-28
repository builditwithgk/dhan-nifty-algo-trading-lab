"""Live PAPER-trading engine — watch the whole machine operate on fake money.

Run (during market hours):  python run_paper.py --strategy orb
Smoke test (any time):      python run_paper.py --once

SAFETY: built on build_broker(confirm_live=False), which ALWAYS returns the
paper broker. This program cannot place a real order — there is no code path to
real money here. It reads live prices, generates signals, and books fake trades
with simulated broker-side stops, exactly mirroring how live would behave.

Note: no strategy has passed our backtests, so paper P&L will likely be negative
— that is expected. The point of this run is to validate the live machine
(data -> signal -> sized order -> stop/target -> square-off -> journal), not to
make money.
"""
import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gk import clock, constants as C, costs, instruments
from gk.config import load
from gk.control import read_control, write_control, write_heartbeat
from gk.execution import OrderManager
from gk.journal import Journal
from gk.marketdata import DhanLive
from gk.models import AssetKind, Instrument, Side, Signal
from gk.options_study import nifty_index_instrument
from gk.risk import RiskManager
from gk.runtime import build_broker
from gk.strategies import (MomentumMover, NiftyIntradayBreakout,
                           OpeningRangeBreakout, VWAPReversion)
from dhanhq import DhanContext, dhanhq

STRATS = {"orb": OpeningRangeBreakout, "momentum": MomentumMover, "vwap_rev": VWAPReversion}

_AUTH_MARKERS = ("dh-901", "901", "invalid token", "invalid_token", "unauthorized",
                 "authentication", "expired", "token")

TOKEN_MSG = """
============================================================
  DHAN TOKEN EXPIRED (or invalid).
  Your access token has lapsed - this is normal (they last ~24h).
  Fix (takes about a minute):
    1. Open Dhan -> Generate Access Token -> copy the new token.
    2. Paste it into the .env file:  DHAN_ACCESS_TOKEN=<new token>
    3. Restart:  python run_paper.py --strategy orb
  No harm done - this is paper mode, nothing real was touched.
============================================================
"""


class TokenExpired(Exception):
    pass


def _looks_like_auth_error(resp) -> bool:
    if isinstance(resp, dict) and resp.get("status") == "failure":
        rem = str(resp.get("remarks", "")).lower()
        return any(m in rem for m in _AUTH_MARKERS)
    return False


def ensure_token(api) -> None:
    """Raise TokenExpired if the token is dead. Uses a cheap read-only call."""
    try:
        r = api.get_fund_limits()
    except Exception as e:                      # noqa: BLE001
        if any(m in str(e).lower() for m in _AUTH_MARKERS):
            raise TokenExpired(str(e))
        return                                   # a transient/other error, not auth
    if _looks_like_auth_error(r):
        raise TokenExpired(str(r.get("remarks")))


def active_signal(sig_df, df, catch_up: bool):
    """The most-recent STILL-VALID signal for today, or None.

    Returns (side, stop, target, bar_ts, mode) where mode is 'fresh' (signal on
    the latest bar) or 'catchup' (an earlier signal today that hasn't yet hit its
    stop or target — safe to join). Without catch_up, only the latest bar counts.
    """
    today = df.index[-1].normalize()
    sb = sig_df[(sig_df.index.normalize() == today) & (sig_df["signal"] != 0)]
    if sb.empty:
        return None
    if not catch_up:
        last = sig_df.iloc[-1]
        if last["signal"] == 0:
            return None
        return (int(last["signal"]), float(last["stop"]), float(last["target"]),
                sig_df.index[-1], "fresh")
    ts = sb.index[-1]
    row = sig_df.loc[ts]
    side, stop, tgt = int(row["signal"]), float(row["stop"]), float(row["target"])
    after = df[df.index > ts]
    for _, b in after.iterrows():                # replay: did it already resolve?
        if side == 1 and (b["low"] <= stop or b["high"] >= tgt):
            return None
        if side == -1 and (b["high"] >= stop or b["low"] <= tgt):
            return None
    return (side, stop, tgt, ts, "fresh" if len(after) == 0 else "catchup")


def nifty_active_signal(nsig, ndf, catch_up: bool):
    """Most-recent still-valid NIFTY breakout for options, or None.

    Returns (bullish, bar_ts, mode). For catch-up, 'still valid' means the trend
    HASN'T reversed past the signal bar's spot — i.e. the breakout is still in
    play — since an option trade's own stop/target live on the premium, not on a
    NIFTY level, so we re-validate direction rather than replay the premium.
    """
    today = ndf.index[-1].normalize()
    sb = nsig[(nsig.index.normalize() == today) & (nsig["signal"] != 0)]
    if sb.empty:
        return None
    if not catch_up:
        last = nsig.iloc[-1]
        if last["signal"] == 0:
            return None
        return (int(last["signal"]) == 1, nsig.index[-1], "fresh")
    ts = sb.index[-1]
    side = int(nsig.loc[ts, "signal"])
    if ts == nsig.index[-1]:
        return (side == 1, ts, "fresh")
    sig_spot = float(ndf.loc[ts, "close"])
    now_spot = float(ndf["close"].iloc[-1])
    valid = (now_spot >= sig_spot) if side == 1 else (now_spot <= sig_spot)
    if not valid:                                # breakout reversed -> don't join
        return None
    return (side == 1, ts, "catchup")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="orb", choices=list(STRATS))
    ap.add_argument("--once", action="store_true", help="one cycle then exit (smoke test)")
    ap.add_argument("--demo", action="store_true",
                    help="simulated market so you can watch the UI anytime (no live data needed)")
    ap.add_argument("--reset", action="store_true", help="wipe the journal for a fresh start")
    ap.add_argument("--poll", type=int, default=60, help="seconds between cycles")
    args = ap.parse_args()

    s = load()
    if not args.demo and not (s.dhan_client_id and s.dhan_access_token):
        print("No creds in .env. (Tip: run with --demo for a fully offline simulation.)")
        return
    j = Journal(s.state_dir / "paper.db")
    if args.reset:
        j.reset_all()
        print("  journal reset — clean slate")
    broker = build_broker(s, j, confirm_live=False)   # ALWAYS paper
    assert broker.name == "paper", "refusing: broker is not paper"
    stale = j.abandon_open_orders()      # clear orphans from any previous run
    if stale:
        print(f"  cleared {stale} stale position(s) left by a previous run")
    risk = RiskManager(s, j)
    om = OrderManager(s, broker, risk, j)
    strat = STRATS[args.strategy]()
    # In --demo the market is simulated, so no live data feed (and no creds) is needed.
    feed = None if args.demo else DhanLive(dhanhq(DhanContext(s.dhan_client_id, s.dhan_access_token)))
    insts = [instruments.equity(sym) for sym in s.equity_universe]
    nifty = nifty_index_instrument()            # for the NIFTY options signal
    opt_strat = NiftyIntradayBreakout()         # active NIFTY breakouts -> ATM CE/PE
    acted = {}
    opt_state = {"last_entry": None, "last_spread": None, "spreads": {}}

    def _open_spread(chain, bullish):
        """Open a defined-risk credit spread (bull-put if bullish, else bear-call).
        Modelled as a single SHORT position on the spread's net value; loss is
        capped at the strike width. Full 4-leg round-trip cost is front-loaded."""
        step = 50
        atm = chain.atm_strike()
        if bullish:                      # bull-put: sell OTM put, buy further-OTM put
            short_k = atm - s.spread_short_otm * step
            long_k = atm - (s.spread_short_otm + s.spread_width) * step
            typ, tag = "PE", "BULL-PUT-SPREAD"
        else:                            # bear-call: sell OTM call, buy further-OTM call
            short_k = atm + s.spread_short_otm * step
            long_k = atm + (s.spread_short_otm + s.spread_width) * step
            typ, tag = "CE", "BEAR-CALL-SPREAD"
        sq, lq = chain.quote(short_k, typ), chain.quote(long_k, typ)
        if not sq or not lq or sq.ltp <= 0:
            return None
        credit = round(sq.ltp - lq.ltp, 2)
        width = float(abs(short_k - long_k))
        if credit <= 0:
            return None
        qty = s.option_lots * 65
        rt = 2 * (costs.option_charges(sq.ltp, qty, is_buy=False).total
                  + costs.option_charges(lq.ltp, qty, is_buy=True).total)   # 4-leg round trip
        spread_inst = Instrument(f"NIFTY {tag} {int(short_k)}/{int(long_k)}",
                                 f"SPRD-{int(short_k)}-{int(long_k)}-{typ}",
                                 C.NSE_FNO, AssetKind.OPTION, 65)
        broker.set_price(spread_inst.security_id, credit)
        stop = min(s.spread_sl_mult * credit, width)      # loss capped at the width
        target = s.spread_tp_frac * credit
        try:
            sig = Signal(spread_inst, Side.SELL, stop=round(stop, 2), entry_ref_price=credit,
                         target=round(target, 2), strategy="nifty_spread")
        except ValueError:
            return None
        out = om.open_from_signal(sig, fixed_qty=qty, charges_override=round(rt, 2), is_spread=True)
        if out.ok:
            opt_state["spreads"][spread_inst.security_id] = {
                "legs": [chain.to_instrument(sq), chain.to_instrument(lq)], "width": width}
            # enriched log: both legs, credit, and if-target/if-stop projections
            max_prof = round((credit - target) * qty - rt)
            max_loss = round((credit - stop) * qty - rt)
            j.event("SPREAD",
                    f"{tag} | SELL {int(short_k)} {typ} @ {sq.ltp} + BUY {int(long_k)} {typ} "
                    f"@ {lq.ltp} | credit {credit} (Rs.{credit * qty:.0f}) width {int(width)} "
                    f"| if TARGET +Rs.{max_prof} / if STOP Rs.{max_loss} "
                    f"| exit both legs: buyback <= {round(target, 2)} (target) or "
                    f">= {round(stop, 2)} (stop)")
        return out

    # Fail fast with a friendly message if the token is already dead (live data only).
    if feed is not None:
        try:
            ensure_token(feed.api)
        except TokenExpired:
            print(TOKEN_MSG)
            return

    opt_on = s.options_enabled
    _od = []
    if s.option_buy_enabled:
        _od.append("buy ATM")
    if s.option_sell_enabled:
        _od.append(f"sell spreads(IV>={s.sell_min_iv:.0f}%)")
    opt_desc = ("+".join(_od) + f" max {s.max_option_positions}") if (opt_on and _od) else "off"
    print(f"\nPAPER engine | equity={strat.name} (max {s.max_equity_positions}) | "
          f"options={opt_desc} | capital Rs.{s.capital:,.0f} | NO REAL ORDERS POSSIBLE")

    def cycle():
        # 0) read the dashboard control file and apply it live
        ctl = read_control(s.state_dir)
        if ctl["capital"] is not None:
            s.capital = float(ctl["capital"])
        if ctl["risk_per_trade_pct"] is not None:
            s.risk_per_trade_pct = float(ctl["risk_per_trade_pct"])
        s.daily_loss_override = float(ctl["daily_loss_limit"]) if ctl["daily_loss_limit"] else 0.0
        s.daily_profit_target = float(ctl["daily_profit_target"]) if ctl["daily_profit_target"] else 0.0
        if ctl["max_equity_positions"] is not None:
            s.max_equity_positions = int(ctl["max_equity_positions"])
        if ctl["max_option_positions"] is not None:
            s.max_option_positions = int(ctl["max_option_positions"])
        eq_day_cap = ctl["max_equity_trades_day"] if ctl["max_equity_trades_day"] is not None \
            else s.max_equity_trades_per_day
        op_day_cap = ctl["max_option_trades_day"] if ctl["max_option_trades_day"] is not None \
            else s.max_option_trades_per_day
        if ctl["kill"] and not j.is_killed():
            om.engage_kill("dashboard kill switch", flatten=True)
            print("  kill switch engaged from dashboard")
        if ctl["reset_kill"]:
            j.reset_kill()
            write_control(s.state_dir, {"reset_kill": False, "kill": False})
            print("  kill switch reset from dashboard")
        if ctl["flatten_now"]:
            closed = om.flatten_all("dashboard flatten")
            print(f"  flattened {len(closed)} position(s) from dashboard")
            write_control(s.state_dir, {"flatten_now": False})   # one-shot
        paused = bool(ctl["paused"])

        # 1) refresh EQUITY prices, trigger any paper stops/targets
        ltps = feed.ltp_batch(insts)
        if not ltps:
            # No prices during market hours usually means the token just died.
            ensure_token(feed.api)      # raises TokenExpired -> handled in the loop
        for inst in insts:
            px = ltps.get(inst.security_id)
            if px:
                broker.feed(inst.security_id, px)

        # 1b) mark open option positions to trigger stops/targets:
        #     single legs via their own LTP; spreads via (short leg - long leg).
        opt_pos = [p for p in broker.get_positions() if p.instrument.kind is AssetKind.OPTION]
        singles = [p for p in opt_pos if not p.is_spread]
        spreads = [p for p in opt_pos if p.is_spread]
        if singles:
            lt = feed.ltp_batch([p.instrument for p in singles])
            for p in singles:
                px = lt.get(p.instrument.security_id)
                if px:
                    broker.feed(p.instrument.security_id, px)
        if spreads:
            legs = []
            for p in spreads:
                legs += opt_state["spreads"].get(p.instrument.security_id, {}).get("legs", [])
            leg_lt = feed.ltp_batch(legs) if legs else {}
            for p in spreads:
                info = opt_state["spreads"].get(p.instrument.security_id)
                if not info:
                    continue
                si, li = info["legs"]
                sp, lp = leg_lt.get(si.security_id), leg_lt.get(li.security_id)
                if sp is not None and lp is not None:
                    broker.feed(p.instrument.security_id,
                                max(0.0, min(info["width"], round(sp - lp, 2))))

        # 2) square off after the cutoff, then stop entering
        if clock.past(s.square_off):
            closed = om.square_off()
            print(f"  square-off: flattened {len(closed)} position(s)")
            write_heartbeat(s.state_dir, {"ts": clock.now_ist().isoformat(),
                            "open_equity": 0, "open_option": 0,
                            "day_pnl": j.day_realized_pnl(), "killed": j.is_killed(),
                            "paused": paused, "eq_today": j.entries_today("EQUITY"),
                            "opt_today": j.entries_today("OPTION")})
            return

        # 3) look for entries (before the entry cutoff, and only if not paused)
        if clock.before(s.entry_cutoff) and not paused:
            equity_ok = ctl["equity_enabled"] and j.entries_today("EQUITY") < eq_day_cap
            for inst in insts if equity_ok else []:
                if j.entries_today("EQUITY") >= eq_day_cap:
                    break                                     # per-day equity cap reached
                if any(p.instrument.security_id == inst.security_id for p in broker.get_positions()):
                    continue
                df = feed.intraday(inst, interval=5, days=2)
                if len(df) < 20:
                    continue
                sig_df = strat.generate_signals(df)
                a = active_signal(sig_df, df, s.catch_up)
                if a is None:
                    continue
                side, stop, tgt, bar_ts, mode = a
                if acted.get(inst.symbol) == bar_ts:
                    continue
                acted[inst.symbol] = bar_ts
                px = ltps.get(inst.security_id) or float(df["close"].iloc[-1])
                risk_now = abs(px - stop)
                if risk_now <= 0:
                    continue
                # catch-up guard: don't chase a stale signal with little reward left
                if mode == "catchup" and (abs(tgt - px) / risk_now) < s.catchup_min_rr:
                    print(f"  skip {inst.symbol}: catch-up reward too small")
                    continue
                broker.set_price(inst.security_id, px)
                try:
                    sig = Signal(inst, Side.BUY if side == 1 else Side.SELL,
                                 stop=stop, entry_ref_price=float(px),
                                 target=tgt, strategy=strat.name)
                except ValueError:
                    continue
                out = om.open_from_signal(sig)
                tag = " [catch-up]" if mode == "catchup" else ""
                print(f"  {'OPEN ' if out.ok else 'skip '} {inst.symbol}{tag}: {out.reason}")

            # 3b) NIFTY OPTIONS — on a fresh breakout: BUY a directional ATM option
            #     and/or SELL a defined-risk credit spread (only when IV is rich).
            if opt_on and ctl["options_enabled"] and j.entries_today("OPTION") < op_day_cap:
                try:
                    now = clock.now_ist()
                    n_opt = sum(1 for p in broker.get_positions()
                                if p.instrument.kind is AssetKind.OPTION)
                    if n_opt < s.max_option_positions:
                        ndf = feed.intraday(nifty, interval=5, days=2)
                        if len(ndf) >= 25:
                            nsig = opt_strat.generate_signals(ndf)
                            na = nifty_active_signal(nsig, ndf, s.catch_up)
                            if na is not None and acted.get("__nifty_opt__") != na[1]:
                                bullish, nbar, nmode = na
                                acted["__nifty_opt__"] = nbar
                                cutag = " [catch-up]" if nmode == "catchup" else ""
                                chain = feed.option_chain("NIFTY")

                                # BUY leg — directional ATM option
                                le = opt_state["last_entry"]
                                buy_cooled = le is None or (now - le).total_seconds() >= s.option_cooldown_min * 60
                                if s.option_buy_enabled and buy_cooled:
                                    q = chain.quote(chain.atm_strike(), "CE" if bullish else "PE")
                                    if q and q.ltp > 0:
                                        oi = chain.to_instrument(q); broker.set_price(oi.security_id, q.ltp)
                                        osig = Signal(oi, Side.BUY, stop=q.ltp * (1 - s.option_sl_pct / 100),
                                                      entry_ref_price=q.ltp, target=q.ltp * (1 + s.option_tp_pct / 100),
                                                      strategy="nifty_opt")
                                        out = om.open_from_signal(osig, fixed_qty=s.option_lots * oi.lot_size)
                                        print(f"  {'OPEN ' if out.ok else 'skip '} {oi.symbol}{cutag}: {out.reason}")
                                        if out.ok:
                                            opt_state["last_entry"] = now

                                # SELL leg — credit spread, ONLY when ATM IV is rich
                                ls = opt_state["last_spread"]
                                sell_cooled = ls is None or (now - ls).total_seconds() >= s.option_cooldown_min * 60
                                ce, pe = chain.quote(chain.atm_strike(), "CE"), chain.quote(chain.atm_strike(), "PE")
                                atm_iv = ((ce.iv if ce else 0) + (pe.iv if pe else 0)) / 2
                                still_room = sum(1 for p in broker.get_positions()
                                                 if p.instrument.kind is AssetKind.OPTION) < s.max_option_positions
                                if s.option_sell_enabled and sell_cooled and still_room:
                                    if atm_iv >= s.sell_min_iv:
                                        out = _open_spread(chain, bullish)
                                        if out:
                                            print(f"  {'OPEN ' if out.ok else 'skip '} spread{cutag}: {out.reason}")
                                            if out.ok:
                                                opt_state["last_spread"] = now
                                    else:
                                        print(f"  skip spread: IV {atm_iv:.1f}% < {s.sell_min_iv}% (not rich enough)")
                except Exception as e:                 # noqa: BLE001 — never kill the loop
                    print(f"  option path error: {e}")

        # 4) status line + heartbeat (so the dashboard knows we're alive)
        pos = broker.get_positions()
        n_opt = sum(1 for p in pos if p.instrument.kind is AssetKind.OPTION)
        n_eq = len(pos) - n_opt
        flag = " [PAUSED]" if paused else ""
        print(f"  [{clock.now_ist():%H:%M}]{flag} open {len(pos)} ({n_eq} eq, {n_opt} opt) | "
              f"today {j.entries_today('EQUITY')}eq/{j.entries_today('OPTION')}opt | "
              f"day P&L Rs.{j.day_realized_pnl():,.0f} | killed={j.is_killed()}")
        write_heartbeat(s.state_dir, {
            "ts": clock.now_ist().isoformat(), "open_equity": n_eq, "open_option": n_opt,
            "day_pnl": j.day_realized_pnl(), "killed": j.is_killed(), "paused": paused,
            "eq_today": j.entries_today("EQUITY"), "opt_today": j.entries_today("OPTION"),
        })

    # ---- DEMO MODE: simulate a live market so the whole UI is watchable anytime ----
    BASE = {"RELIANCE": 1290, "HDFCBANK": 755, "ICICIBANK": 1441, "SBIN": 1025,
            "AXISBANK": 1239, "INFY": 1600, "TCS": 3400, "BHARTIARTL": 1900,
            "LT": 3600, "BAJFINANCE": 950, "TATASTEEL": 165, "MARUTI": 11000}

    def _new_demo_trade():
        held = {p.instrument.security_id for p in broker.get_positions()}
        if random.random() < 0.35:                     # a NIFTY option
            strike = 24000 + random.choice([-100, -50, 0, 50, 100])
            typ = random.choice(["CE", "PE"])
            oi = instruments.option("NIFTY", strike, typ, f"DEMO{strike}{typ}")
            if oi.security_id in held:
                return
            px = round(random.uniform(60, 200), 1)
            broker.set_price(oi.security_id, px)
            om.open_from_signal(Signal(oi, Side.BUY, stop=px * 0.65, entry_ref_price=px,
                                       target=px * 1.6, strategy="nifty_opt"), fixed_qty=65)
        else:                                          # an equity trade
            sym = random.choice(list(BASE)); inst = instruments.equity(sym)
            if inst.security_id in held:
                return
            px = round(BASE[sym] * (1 + random.gauss(0, 0.005)), 2)
            side = Side.BUY if random.random() < 0.6 else Side.SELL
            stop = px * 0.99 if side is Side.BUY else px * 1.01
            tgt = px * 1.02 if side is Side.BUY else px * 0.98
            broker.set_price(inst.security_id, px)
            try:
                om.open_from_signal(Signal(inst, side, stop=round(stop, 2),
                                           entry_ref_price=px, target=round(tgt, 2), strategy="orb"))
            except ValueError:
                pass

    if args.demo:
        j.reset_all()
        print("DEMO MODE — simulated market, fake money. Open the dashboard and watch.")
        print("Ctrl-C to stop.\n")
        tick = 0
        try:
            while True:
                ctl = read_control(s.state_dir)
                if ctl["kill"] and not j.is_killed():
                    om.engage_kill("dashboard kill switch", flatten=True)
                if ctl["reset_kill"]:
                    j.reset_kill(); write_control(s.state_dir, {"reset_kill": False, "kill": False})
                if ctl["flatten_now"]:
                    om.flatten_all("dashboard flatten"); write_control(s.state_dir, {"flatten_now": False})
                paused = bool(ctl["paused"])
                # random-walk open positions (options move more than stocks)
                for p in list(broker.get_positions()):
                    vol = 0.012 if p.instrument.kind is AssetKind.OPTION else 0.0025
                    broker.feed(p.instrument.security_id, max(0.05, round(p.ltp * (1 + random.gauss(0, vol)), 2)))
                # keep a few positions alive; open replacements as trades close
                if not paused and not j.is_killed() and len(broker.get_positions()) < 5:
                    _new_demo_trade()
                pos = broker.get_positions()
                n_opt = sum(1 for x in pos if x.instrument.kind is AssetKind.OPTION)
                write_heartbeat(s.state_dir, {
                    "ts": clock.now_ist().isoformat(), "open_equity": len(pos) - n_opt,
                    "open_option": n_opt, "day_pnl": j.day_realized_pnl(),
                    "killed": j.is_killed(), "paused": paused,
                    "eq_today": j.entries_today("EQUITY"), "opt_today": j.entries_today("OPTION")})
                tick += 1
                print(f"  demo {tick:3d}{' [PAUSED]' if paused else ''} | open {len(pos)} "
                      f"({len(pos)-n_opt} eq/{n_opt} opt) | day P&L Rs.{j.day_realized_pnl():,.0f}")
                if args.once:
                    print("\n(demo smoke test — one tick done)"); break
                time.sleep(2)
        except KeyboardInterrupt:
            print("\ndemo stopped.")
        return

    if args.once:
        print("(smoke test — one cycle)\n")
        cycle()
        return

    print("Live paper loop started. Press Ctrl-C to stop.\n")
    try:
        while True:
            if clock.is_market_open(s.market_open, s.market_close):
                cycle()
            else:
                print(f"  [{clock.now_ist():%H:%M}] market closed — waiting")
            if clock.past(s.market_close):
                print("session over — paper engine stopping."); break
            time.sleep(args.poll)
    except TokenExpired:
        print(TOKEN_MSG)
    except KeyboardInterrupt:
        print("\nstopped by user.")


if __name__ == "__main__":
    main()
