"""How far did the losing trades go into profit before the stop, and does a breakeven stop help?

Strategy (h1_hh_engulf_25.py): 3 consecutive higher highs + bearish body engulfing on H1, sell
limit at 25% of the body, SL at the engulfing high, TP 1:3, unfilled order cancelled on an H1
close below the engulfing low. Fills and exits on M3 (Exness) / M1 (our data) with spread.

Max favourable excursion (MFE) of a trade = the best price it reached before its exit, in R
(1R = the SL distance), measured on the ask for a sell so that the profit could really have been
taken there. Candles where the order filled inside the candle are not counted (their low may
have come before the fill), and neither is the exit candle.

Breakeven variants: once the trade reaches +X R, the stop is moved to the entry price.

    python h1_hh_engulf_be.py
"""
from __future__ import annotations

import glob

import numba
import numpy as np
import pandas as pd

import backtest as b
import m3_ha_test as m3
from h1_hh_engulf import setups
from mass_search import resample


@numba.njit(cache=True)
def sell_limit_be(fo, fh, fl, fspr, fh1, flast, h1c, j0, e, slv, cancel, rr, be_at):
    """Returns (status, R, MFE in R, moved_to_breakeven). be_at <= 0: no breakeven stop."""
    d = slv - e
    if not d > 0:
        return 0, np.nan, np.nan, False
    tpv = e - rr * d
    filled = False
    fill = 0.0
    stop = slv
    best = np.inf                       # lowest ask reached while in the trade
    moved = False
    for j in range(j0, len(fo)):
        fresh = False
        if not filled:
            if fo[j] >= e:
                fill, filled = fo[j], True
            elif fh[j] >= e:
                fill, filled, fresh = e, True, True
            if not filled:
                if flast[j] and h1c[fh1[j]] < cancel:
                    return 2, np.nan, np.nan, False
                continue
        # stop (original or breakeven) first, then TP
        if fh[j] + fspr[j] >= stop:
            ex = stop if fresh else max(stop, fo[j] + fspr[j])
            mfe = (fill - best) / d if best < np.inf else 0.0
            return 1, (fill - ex) / d, max(mfe, 0.0), moved
        if (not fresh) and fl[j] + fspr[j] <= tpv:
            return 1, (fill - min(tpv, fo[j] + fspr[j])) / d, rr, moved
        if not fresh:
            best = min(best, fl[j] + fspr[j])
            if be_at > 0 and (not moved) and fill - best >= be_at * d:
                stop = fill                 # move the stop to the entry price
                moved = True
    return 0, np.nan, np.nan, moved


def analyse(fine: pd.DataFrame, label: str, rr: float = 3.0):
    h1 = resample(fine, 60)
    fh1 = np.searchsorted(h1.index.to_numpy(), fine.index.floor("h").to_numpy())
    flast = np.r_[fh1[1:] != fh1[:-1], True]
    fo, fh, fl, fs = (fine[k].to_numpy(np.float64) for k in ("open", "high", "low", "spread_px"))
    o, h, l, c = (h1[k].to_numpy(np.float64) for k in ("open", "high", "low", "close"))
    sells, _ = setups(h1, 3)

    def run(be_at):
        out = [sell_limit_be(fo, fh, fl, fs, fh1, flast, c, int(np.searchsorted(fh1, i + 1)),
                             c[i] + 0.25 * (o[i] - c[i]), h[i], l[i], rr, be_at) for i in sells]
        x = pd.DataFrame(out, columns=["st", "R", "mfe", "moved"])
        return x[x.st == 1]

    base = run(0.0)
    tp = base[base.R >= rr - 0.001]
    sl = base[base.R < rr - 0.001]
    print(f"\n===== {label}: {len(base)} trades -> TP {len(tp)}, SL {len(sl)} =====")
    print("How far the SL trades went into profit first (on the ask):")
    bins = [-1, 0.5, 1.0, 1.5, 2.0, 2.5, rr]
    names = ["below 0.5R", "0.5-1R", "1-1.5R", "1.5-2R", "2-2.5R", "2.5-3R"]
    cnt = pd.cut(sl.mfe, bins, labels=names, right=False).value_counts().reindex(names)
    for k, v in cnt.items():
        print(f"   {k:10s}: {v:3d} ({v / len(sl) * 100:4.1f}%)")
    for lv in (1.0, 1.5, 2.0):
        n_ = (sl.mfe >= lv).sum()
        print(f"   reached at least 1:{lv:g} and then hit the SL: {n_} of {len(sl)} SL trades ({n_ / len(sl) * 100:.0f}%), "
              f"{n_ / len(base) * 100:.0f}% of all trades")
    print("\nMove the stop to the entry (breakeven) once the trade reaches +X R:")
    rows = [{"rule": "no breakeven", "trades": len(base), "TP": len(tp), "breakeven exits": 0,
             "SL (-1R)": len(sl), "TP %": round(len(tp) / len(base) * 100, 1),
             "R/trade": round(base.R.mean(), 3), "net R": round(base.R.sum(), 1)}]
    for be in (1.0, 1.5, 2.0):
        x = run(be)
        tpx = (x.R >= rr - 0.001).sum()
        bex = ((x.R > -0.5) & (x.R < rr - 0.001)).sum()
        rows.append({"rule": f"breakeven at 1:{be:g}", "trades": len(x), "TP": int(tpx), "breakeven exits": int(bex),
                     "SL (-1R)": int(len(x) - tpx - bex), "TP %": round(tpx / len(x) * 100, 1),
                     "R/trade": round(x.R.mean(), 3), "net R": round(x.R.sum(), 1)})
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    files = sorted(glob.glob("data/M3_exness/*.csv"))
    if files:
        analyse(m3.load_mt5(files), "Exness M3 2020-01..2026-11")
    analyse(b.load_data("M1"), "Our data M1 2021-11..2026-10")
