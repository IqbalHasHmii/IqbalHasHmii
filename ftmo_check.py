"""FTMO limits for the all-in-one EA (EA defaults, strategy 7 off).

FTMO accounts fail when equity drops a set share of the initial balance in one day (the
standard challenge uses 5%) or in total (10%). This takes the EA-default trades of
all_in_one_backtest.py and finds, in R (1R = the risk of one trade):
  - the worst day and the worst 5 days of closed trades (by close date, strategy clock =
    FTMO server time),
  - the biggest drawdown of closed trades,
  - the largest loss carried by trades still open at the end of a day: at most the number open
    times 1R, so "worst day + open risk" is an upper bound for one day.
Then the same in % of the account for several risk settings.

    python ftmo_check.py      # -> results/ftmo_check.txt
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from all_in_one_backtest import EXNESS, OURS, build, drawdown, exness_data, ours_data


def run(label: str, data: dict, start: pd.Timestamp, end: pd.Timestamp):
    parts = build(data, with7=False)
    t = pd.concat(parts.values())
    t = t[(t.entry >= start) & (t.entry < end)].sort_values("exit")
    day = t.groupby(t.exit.dt.normalize()).R.sum()
    worst5 = day.rolling(5).sum().min()
    dd = drawdown(t.R.cumsum(), t.exit)[0]
    # trades open over each day end (an upper bound for the extra floating loss: 1R each)
    ends = pd.date_range(start.normalize(), end.normalize(), freq="D") + pd.Timedelta(hours=23, minutes=59)
    ent, ext = t.entry.to_numpy(), t.exit.to_numpy()
    open_at = np.array([int(((ent <= e) & (ext > e)).sum()) for e in ends.to_numpy()])
    years = (end - start).days / 365.25
    print(f"\n===== {label}: {start:%Y-%m-%d} -> {end:%Y-%m-%d}, {len(t)} trades =====")
    print(f"worst day {day.min():+.1f}R ({day.idxmin():%Y-%m-%d}), days below -8R: {(day <= -8).sum()}, "
          f"below -12R: {(day <= -12).sum()}; worst 5 days {worst5:+.1f}R; max drawdown {dd:.1f}R; "
          f"most trades open over a day end {open_at.max()}; profit {t.R.sum() / years:+.0f}R a year")
    rows = []
    for risk in (0.05, 0.10, 0.15, 0.20, 0.25):
        rows.append({"risk per trade": f"{risk:.2f}%", "worst day": f"{day.min() * risk:.1f}%",
                     "worst day + open trades": f"{(day.min() - open_at.max()) * risk:.1f}%",
                     "max drawdown": f"{dd * risk:.1f}%", "profit a year": f"{t.R.sum() / years * risk:+.0f}%",
                     "FTMO 5% day / 10% total": "ok" if (day.min() - open_at.max()) * risk > -5 and dd * risk > -10
                     else "breached"})
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    data = ours_data()
    run("Our data (strategies 1-6, 8, 9)", data, *OURS)
    data = exness_data()
    if data is not None:
        run("Exness data (strategies 1-3, 8, 9)", data, *EXNESS)
