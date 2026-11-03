"""Trade EVERY type of bearish engulfing (the union of the types in h1_hh_engulf_types.py).

Setup: 3 consecutive higher highs, then a candle that is ANY bearish engulfing type:
body, body with 5-cent tolerance, perfect, strong, two-candle (multi2) or outside bar.
Trade: sell limit at 25% of the engulfing body, SL at the engulfing high, TP 1:3, unfilled order
cancelled on an H1 close below the engulfing low. Every setup is its own trade.
Each trade is labelled with its "best" type in this order: perfect, strong, multi2, body,
body_tol (only within the tolerance), outside (wick engulfing only).

    python h1_hh_engulf_all_types.py
"""
from __future__ import annotations

import glob

import numpy as np
import pandas as pd

import backtest as b
import m3_ha_test as m3
from h1_hh_engulf import PERIODS
from h1_hh_engulf_25 import limit_trade
from h1_hh_engulf_split import streak
from h1_hh_engulf_types import engulf_types, new_highs_ok
from mass_search import resample

ORDER = ["perfect", "strong", "multi2", "body", "body_tol", "outside"]


def analyse(fine: pd.DataFrame, label: str, rr: float = 3.0):
    h1 = resample(fine, 60)
    fh1 = np.searchsorted(h1.index.to_numpy(), fine.index.floor("h").to_numpy())
    flast = np.r_[fh1[1:] != fh1[:-1], True]
    fo, fh, fl, fs = (fine[k].to_numpy(np.float64) for k in ("open", "high", "low", "spread_px"))
    o, h, l, c = (h1[k].to_numpy(np.float64) for k in ("open", "high", "low", "close"))
    ty = engulf_types(h1)
    hh = new_highs_ok(h, 3, 3)
    lab = np.full(len(h1), "", dtype=object)
    for name in reversed(ORDER):                    # the first type in ORDER wins
        lab[ty[name]] = name
    idx = np.flatnonzero((lab != "") & hh)
    rows = []
    for i in idx:
        st, fj, xj, r = limit_trade(fo, fh, fl, fs, fh1, flast, c, int(np.searchsorted(fh1, i + 1)),
                                    c[i] + 0.25 * (o[i] - c[i]), h[i], l[i], -1, rr)
        rows.append((lab[i], st, fj, xj, r))
    x = pd.DataFrame(rows, columns=["type", "st", "fj", "xj", "R"])
    t = x[x.st == 1].copy()
    t["fill"] = fine.index[t.fj.to_numpy()]
    t["exit"] = fine.index[t.xj.to_numpy()]
    t = t.sort_values("exit")
    weeks = (fine.index[-1] - fine.index[0]).days / 7
    eq = t.R.cumsum()
    ev = pd.concat([pd.DataFrame({"t": t.fill, "d": 1}), pd.DataFrame({"t": t.exit, "d": -1})]).sort_values(["t", "d"])
    print(f"\n===== {label}: every engulfing type, 3 consecutive higher highs, 25% limit, SL engulfing high, TP 1:{rr:g} =====")
    print(f"ALL TYPES: {len(x)} setups -> {len(t)} trades ({len(t) / weeks:.2f}/wk), TP {(t.R >= rr - 0.001).sum()}, "
          f"TP hit {(t.R >= rr - 0.001).mean() * 100:.1f}%, {t.R.mean():+.3f}R/trade, net {t.R.sum():+.1f}R, "
          f"max drawdown {(eq - eq.cummax()).min():.1f}R, most open at once {ev.d.cumsum().max()}")
    rows = []
    for name in ORDER:
        y = t[t.type == name]
        n_set = (x.type == name).sum()
        rows.append({"type": name, "setups": int(n_set), "trades": len(y),
                     "TP %": round(float((y.R >= rr - 0.001).mean() * 100), 1) if len(y) else np.nan,
                     "R/trade": round(float(y.R.mean()), 3) if len(y) else np.nan, "net R": round(float(y.R.sum()), 1)})
    print(pd.DataFrame(rows).to_string(index=False))
    per = []
    for plab, s, e in PERIODS:
        y = t[(t.fill >= s) & (t.fill < e)]
        if len(y):
            per.append(f"{plab.split()[0]}: {len(y)} tr {y.R.mean():+.2f}R")
    print("by period: " + " | ".join(per))
    print("by year (R): " + ", ".join(f"{yy}: {s:+.0f}" for yy, s in t.groupby(t.exit.dt.year).R.sum().items()))
    # each setup is simulated once, so a group of types is the subset of these trades
    print("\nGroups of types (same trades, subsets):")
    for name, keep in (("perfect + strong", ["perfect", "strong"]),
                       ("exact body (perfect+strong+multi2+body)", ["perfect", "strong", "multi2", "body"]),
                       ("all types", ORDER)):
        y = t[t.type.isin(keep)]
        eq = y.R.cumsum()
        print(f"  {name:40s}: {len(y)} trades ({len(y) / weeks:.2f}/wk), TP {(y.R >= rr - 0.001).mean() * 100:.1f}%, "
              f"{y.R.mean():+.3f}R/trade, net {y.R.sum():+.1f}R, max drawdown {(eq - eq.cummax()).min():.1f}R, "
              f"longest losing run {streak(y.R)}")
        per = [f"{plab.split()[0]}: {len(z)} tr {z.R.mean():+.2f}R" for plab, s, e in PERIODS
               if len(z := y[(y.fill >= s) & (y.fill < e)])]
        print(f"  {'':40s}  {' | '.join(per)}")
        print(f"  {'':40s}  by year (R): " + ", ".join(f"{yy}: {v:+.0f}" for yy, v in y.groupby(y.exit.dt.year).R.sum().items()))


if __name__ == "__main__":
    files = sorted(glob.glob("data/M3_exness/*.csv"))
    if files:
        analyse(m3.load_mt5(files), "Exness M3 2020-01..2026-11")
    analyse(b.load_data("M1"), "Our data M1 2021-11..2026-10")
