"""Generate a performance report (Excel) from the trade journal.

Run:  python run_report.py [state/paper.db]

Writes results/performance_report.xlsx with a Summary, a day-by-day sheet (with
equity-curve and daily-P&L charts), all trades, and a monthly rollup.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gk import reports

ROOT = Path(__file__).resolve().parent


def main():
    db = str(ROOT / "state" / "paper.db")
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 0     # 0 = all history
    all_hist = reports.load_history(db)                     # permanent, survives --reset
    if all_hist.empty:
        print(f"No trade history in {db} yet — it fills in as trades close.")
        return
    # quick week / month headline
    for label, d in (("last 7 days", 7), ("last 30 days", 30), ("all time", 0)):
        h = reports.last_n_days(all_hist, d)
        if not h.empty:
            print(f"  {label:12s}: {h['net'].sum():>10,.0f}  net  ({len(h)} trades)")
    trades = reports.last_n_days(all_hist, days) if days else all_hist
    daily = reports.daily_pnl(trades)
    summ = reports.summary(trades)
    out = ROOT / "results"; out.mkdir(exist_ok=True)
    path = out / "performance_report.xlsx"

    summ_df = pd.DataFrame(list(summ.items()), columns=["metric", "value"])
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        summ_df.to_excel(xl, sheet_name="Summary", index=False)
        daily.to_excel(xl, sheet_name="Daily", index=False)
        reports.monthly(trades).to_excel(xl, sheet_name="Monthly", index=False)
        trades.to_excel(xl, sheet_name="Trades", index=False)

    # add charts to the Daily sheet
    from openpyxl import load_workbook
    from openpyxl.chart import BarChart, LineChart, Reference
    wb = load_workbook(path); ws = wb["Daily"]
    n = len(daily)
    cols = list(daily.columns)                      # date,trades,wins,gross,costs,net,win_rate,cum_net
    net_c, cum_c = cols.index("net") + 1, cols.index("cum_net") + 1
    cats = Reference(ws, min_col=1, min_row=2, max_row=n + 1)

    line = LineChart(); line.title = "Equity curve (cumulative net P&L)"
    line.add_data(Reference(ws, min_col=cum_c, min_row=1, max_row=n + 1), titles_from_data=True)
    line.set_categories(cats); line.height, line.width = 8, 18
    ws.add_chart(line, "K2")

    bar = BarChart(); bar.title = "Daily net P&L"
    bar.add_data(Reference(ws, min_col=net_c, min_row=1, max_row=n + 1), titles_from_data=True)
    bar.set_categories(cats); bar.height, bar.width = 8, 18
    ws.add_chart(bar, "K20")
    wb.save(path)

    print(f"\nsaved {path}")
    print(f"  {summ['n_trades']} trades over {summ['days']} day(s) | "
          f"net Rs.{summ['total_net']:,.0f} | win {summ['win_rate']:.0f}% | "
          f"PF {summ['profit_factor']} | max DD Rs.{summ['max_drawdown']:,.0f}")


if __name__ == "__main__":
    main()
