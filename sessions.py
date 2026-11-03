"""TP and SL trades of the all-in-one EA (EA defaults, strategy 7 off) by trading session.

Sessions on the strategy clock (UTC+2 winter / UTC+3 European summer), as in mass_search.py:
  Asia     01:00-09:59
  London   10:00-14:59
  New York 15:00-19:59
  Late     20:00-00:59
Pakistan time (UTC+5) = strategy clock + 3 h in winter, + 2 h in summer.
Exness server time (UTC+0) = strategy clock - 2 h in winter, - 3 h in summer.

A trade belongs to the session in which it was opened. The second table shows in which session
the SL or TP was actually hit.

    python sessions.py      # -> results/sessions.txt
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from all_in_one_backtest import EXNESS, NAMES, OURS, exness_parts, ours_parts

ORDER = ["Asia", "London", "New York", "Late"]
PKT = {"Asia": "04:00-12:59", "London": "13:00-17:59", "New York": "18:00-22:59", "Late": "23:00-03:59"}


def session(hours: np.ndarray) -> np.ndarray:
    return np.select([(hours >= 1) & (hours <= 9), (hours >= 10) & (hours <= 14), (hours >= 15) & (hours <= 19)],
                     ["Asia", "London", "New York"], "Late")


def table(t: pd.DataFrame, col: str, weeks: float) -> pd.DataFrame:
    rows = []
    for s_ in ORDER:
        x = t[t[col] == s_]
        sl = (~x.tp & (x.R < 0)).sum()
        rows.append({"session": s_, "Pakistan time (winter)": PKT[s_], "trades": len(x),
                     "per week": round(len(x) / weeks, 1), "TP": int(x.tp.sum()), "SL": int(sl),
                     "TP %": round(float(x.tp.mean() * 100), 1) if len(x) else np.nan,
                     "R/trade": round(float(x.R.mean()), 3) if len(x) else np.nan,
                     "net R": round(float(x.R.sum()), 0)})
    return pd.DataFrame(rows)


def run(label: str, parts: dict, start: pd.Timestamp, end: pd.Timestamp):
    t = pd.concat([x.assign(s=k) for k, x in parts.items() if k != 7])      # EA defaults: 7 off
    t = t[(t.entry >= start) & (t.entry < end)].reset_index(drop=True)
    t["open_session"] = session(t.entry.dt.hour.to_numpy())
    t["exit_session"] = session(t.exit.dt.hour.to_numpy())
    weeks = (end - start).days / 7
    pd.set_option("display.width", 220)
    print(f"\n===== {label}: {start:%Y-%m-%d} -> {end:%Y-%m-%d}, {len(t)} trades, TP {t.tp.mean() * 100:.1f}% =====")
    print("By the session the trade was OPENED in:")
    print(table(t, "open_session", weeks).to_string(index=False))
    print("\nBy the session the SL / TP was HIT in:")
    ex = table(t, "exit_session", weeks)[["session", "Pakistan time (winter)", "TP", "SL"]]
    print(ex.to_string(index=False))
    print("\nTP % (trades) by strategy and opening session:")
    rows = []
    for k, g in t.groupby("s"):
        row = {"strategy": f"{k} {NAMES[k]}"}
        for s_ in ORDER:
            x = g[g.open_session == s_]
            row[s_] = f"{x.tp.mean() * 100:.0f}% ({len(x)})" if len(x) >= 20 else ("-" if len(x) == 0 else f"({len(x)})")
        rows.append(row)
    print(pd.DataFrame(rows).to_string(index=False))
    hr = t.groupby(t.entry.dt.hour).agg(trades=("R", "size"), tp=("tp", "mean"), r=("R", "mean"))
    print("\nBy opening hour (strategy clock): " + ", ".join(
        f"{h:02d}h {int(v.trades)} tr {v.tp * 100:.0f}% {v.r:+.2f}R" for h, v in hr.iterrows()))


if __name__ == "__main__":
    parts, _ = ours_parts()
    run("Our data (strategies 1-6, 8, 9)", parts, *OURS)
    parts, _ = exness_parts()
    if parts:
        run("Exness data (strategies 1-3, 8, 9)", parts, *EXNESS)
