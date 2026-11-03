"""TP and SL trades of the all-in-one EA (EA defaults, strategy 7 off) by trading session.

Sessions on the strategy clock (UTC+2 winter / UTC+3 European summer), as in mass_search.py:
  Asia     01:00-09:59
  London   10:00-14:59
  New York 15:00-19:59
  Late     20:00-00:59
Pakistan time (UTC+5) = strategy clock + 3 h in winter, + 2 h in summer.
Exness server time (UTC+0) = strategy clock - 2 h in winter, - 3 h in summer.

A trade belongs to the session in which it was opened. The second table shows in which session
the SL or TP was actually hit. The last table re-runs the EA with some sessions switched off (no
new trades opened in them; a limit order that fills there is dropped too).

    python sessions.py      # -> results/sessions.txt
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from all_in_one_backtest import EXNESS, NAMES, OURS, build, drawdown, exness_data, ours_data

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


def without(label: str, data: dict, start: pd.Timestamp, end: pd.Timestamp):
    weeks, years = (end - start).days / 7, (end - start).days / 365.25
    rows = []
    for name, drop in (("all sessions (now)", []), ("without London", ["London"]), ("without Late", ["Late"]),
                       ("without London + Late", ["London", "Late"]), ("without Asia", ["Asia"])):
        hours = None if not drop else [h for h in range(24) if session(np.array([h]))[0] not in drop]
        parts = build(data, hours, with7=False)
        t = pd.concat([x.assign(s=k) for k, x in parts.items()])
        t = t[(t.entry >= start) & (t.entry < end)].sort_values("exit")
        dd = drawdown(t.R.cumsum(), t.exit)[0]
        yr = t.groupby(t.exit.dt.year).R.sum()
        rows.append({"version": name, "trades/week": round(len(t) / weeks, 1), "TP %": round(float(t.tp.mean() * 100), 1),
                     "R/trade": round(float(t.R.mean()), 3), "net R a year": round(float(t.R.sum() / years), 0),
                     "max DD R": round(float(dd), 0), "losing years": int((yr < 0).sum()),
                     "worst year R": round(float(yr.min()), 0),
                     "at 0.25%: a year": f"{t.R.sum() / years * 0.25:+.0f}%", "at 0.25%: max DD": f"{dd * 0.25:.0f}%"})
    print(f"\n===== {label}: sessions switched off (EA defaults otherwise) =====")
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    data = ours_data()
    run("Our data (strategies 1-6, 8, 9)", build(data), *OURS)
    without("Our data", data, *OURS)
    data = exness_data()
    if data is not None:
        run("Exness data (strategies 1-3, 8, 9)", build(data), *EXNESS)
        without("Exness data", data, *EXNESS)
