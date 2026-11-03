"""Split the position in two: same entry and SL, one half with TP 1:1, the other with TP 1:3.

Strategy (h1_hh_engulf_25.py): 3 consecutive higher highs + bearish body engulfing on H1, sell
limit at 25% of the body, SL at the engulfing high (kept there for both halves), unfilled order
cancelled on an H1 close below the engulfing low. Each half is simulated on its own on the same
price path (M3 Exness / M1 ours, with spread). Total risk per setup = 1R (0.5R per half), so:
  1:3 reached              -> +0.5 + 1.5 = +2R
  1:1 reached, then the SL -> +0.5 - 0.5 =  0R
  SL before 1:1            -> -0.5 - 0.5 = -1R
Compared with one position: TP 1:3 only, and TP 1:1 only.

    python h1_hh_engulf_split.py
"""
from __future__ import annotations

import glob

import numpy as np
import pandas as pd

import backtest as b
import m3_ha_test as m3
from h1_hh_engulf import PERIODS, setups
from h1_hh_engulf_25 import limit_trade
from mass_search import resample


def streak(r):
    s = m = 0
    for v in r:
        s = s + 1 if v < 0 else 0
        m = max(m, s)
    return m


def analyse(fine: pd.DataFrame, label: str, small_rr=1.0, big_rr=3.0, small_share=0.5):
    h1 = resample(fine, 60)
    fh1 = np.searchsorted(h1.index.to_numpy(), fine.index.floor("h").to_numpy())
    flast = np.r_[fh1[1:] != fh1[:-1], True]
    fo, fh, fl, fs = (fine[k].to_numpy(np.float64) for k in ("open", "high", "low", "spread_px"))
    o, h, l, c = (h1[k].to_numpy(np.float64) for k in ("open", "high", "low", "close"))
    rows = []
    for i in setups(h1, 3)[0]:
        j0 = int(np.searchsorted(fh1, i + 1))
        e = c[i] + 0.25 * (o[i] - c[i])
        a = limit_trade(fo, fh, fl, fs, fh1, flast, c, j0, e, h[i], l[i], -1, small_rr)
        bb = limit_trade(fo, fh, fl, fs, fh1, flast, c, j0, e, h[i], l[i], -1, big_rr)
        if a[0] == 1 and bb[0] == 1:
            rows.append((fine.index[bb[1]], fine.index[max(a[2], bb[2])], a[3], bb[3]))
    t = pd.DataFrame(rows, columns=["fill", "exit", "R_small", "R_big"]).sort_values("exit").reset_index(drop=True)
    t["split"] = small_share * t.R_small + (1 - small_share) * t.R_big
    weeks = (fine.index[-1] - fine.index[0]).days / 7
    big_tp = t.R_big >= big_rr - 0.001
    small_tp = t.R_small >= small_rr - 0.001
    print(f"\n===== {label}: {len(t)} trades ({len(t) / weeks:.2f}/wk), split {small_share * 100:.0f}% at 1:{small_rr:g} + "
          f"{(1 - small_share) * 100:.0f}% at 1:{big_rr:g}, same SL =====")
    print(f"  outcomes: 1:{big_rr:g} reached {big_tp.sum()} | 1:{small_rr:g} reached then SL {(small_tp & ~big_tp).sum()} | "
          f"SL before 1:{small_rr:g} {(~small_tp).sum()}")
    res = []
    for name, col in ((f"one position, TP 1:{big_rr:g}", "R_big"), (f"one position, TP 1:{small_rr:g}", "R_small"),
                      (f"split 1:{small_rr:g} + 1:{big_rr:g}", "split")):
        r = t[col]
        eq = r.cumsum()
        res.append({"version": name, "winning setups %": round((r > 0.001).mean() * 100, 1),
                    "breakeven %": round((r.abs() <= 0.05).mean() * 100, 1),
                    "losing setups %": round((r < -0.05).mean() * 100, 1),
                    "R/trade": round(r.mean(), 3), "net R": round(r.sum(), 1),
                    "max drawdown R": round((eq - eq.cummax()).min(), 1), "longest losing run": streak(r)})
    print(pd.DataFrame(res).to_string(index=False))
    per = []
    for lab, s, e in PERIODS:
        y = t[(t.fill >= s) & (t.fill < e)]
        if len(y):
            per.append(f"{lab.split()[0]}: split {y.split.mean():+.2f}R vs 1:3 {y.R_big.mean():+.2f}R")
    print("  by period (R/trade): " + " | ".join(per))


if __name__ == "__main__":
    files = sorted(glob.glob("data/M3_exness/*.csv"))
    if files:
        analyse(m3.load_mt5(files), "Exness M3 2020-01..2026-11")
    analyse(b.load_data("M1"), "Our data M1 2021-11..2026-10")
