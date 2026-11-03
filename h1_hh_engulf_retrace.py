"""How far did price retrace into the engulfing candle (h1_hh_engulf.py setups)?

1) For the setups whose sell limit at the engulfing OPEN never filled but whose planned TP was
   reached first, the highest price between the engulfing close and that TP touch, as a
   percentage of the engulfing body (0% = close, 100% = open = the limit price) and of the whole
   candle (0% = low, 100% = high).
2) The same strategy with the sell limit placed at other retracement levels of the body
   (SL still engulfing high + 50 pips, TP = 3 x the SL distance from the new entry, same
   cancel rule: an H1 close below the engulfing low).

    python h1_hh_engulf_retrace.py
"""
from __future__ import annotations

import contextlib
import glob
import io

import numba
import numpy as np
import pandas as pd

import backtest as b
import m3_ha_test as m3
from h1_hh_engulf import PIP, run, setups
from h1_hh_engulf_unfilled import first_touch
from mass_search import resample


@numba.njit(cache=True)
def max_high_until_tp(fo, fh, fl, fspr, j0, slv, tpv):
    """Highest high from j0 until the candle where the TP level is touched (sell side)."""
    mx = -1.0
    for j in range(j0, len(fh)):
        if fh[j] + fspr[j] >= slv:
            return -1.0                      # SL level first: not a TP case
        if fl[j] + fspr[j] <= tpv:
            return max(mx, fo[j])            # the TP candle: only its open is surely before the TP touch
        mx = max(mx, fh[j])
    return -1.0


@numba.njit(cache=True)
def sell_limit(fo, fh, fl, fspr, fh1, flast, h1c, j0, e, slv, cancel, rr):
    """Sell limit at e with a fixed SL level; returns (status, R): 1 traded, 2 cancelled, 0 open at the end."""
    d = slv - e
    if not d > 0:
        return 0, np.nan
    tpv = e - rr * d
    filled = False
    fill = 0.0
    for j in range(j0, len(fo)):
        fresh = False
        if not filled:
            if fo[j] >= e:
                fill, filled = fo[j], True
            elif fh[j] >= e:
                fill, filled, fresh = e, True, True
            if not filled:
                if flast[j] and h1c[fh1[j]] < cancel:
                    return 2, np.nan
                continue
        if fh[j] + fspr[j] >= slv:
            return 1, (fill - (slv if fresh else max(slv, fo[j] + fspr[j]))) / d
        if (not fresh) and fl[j] + fspr[j] <= tpv:
            return 1, (fill - min(tpv, fo[j] + fspr[j])) / d
    return 0, np.nan


def analyse(fine: pd.DataFrame, label: str, n: int = 3, pad_pips: float = 50, rr: float = 3.0):
    with contextlib.redirect_stdout(io.StringIO()):
        out = run(fine, label, pad_pips, rr)
    t = out[("SELL", n)]
    h1 = resample(fine, 60)
    fh1 = np.searchsorted(h1.index.to_numpy(), fine.index.floor("h").to_numpy())
    flast = np.r_[fh1[1:] != fh1[:-1], True]
    fo, fh, fl, fs = (fine[k].to_numpy(np.float64) for k in ("open", "high", "low", "spread_px"))
    h1o, h1h, h1l, h1c = (h1[k].to_numpy(np.float64) for k in ("open", "high", "low", "close"))
    sells, _ = setups(h1, n)
    pad = pad_pips * PIP
    print(f"\n===== {label}: SELL after {n} higher highs, {len(sells)} setups =====")

    # 1) retracement of the unfilled setups that reached the planned TP first
    body, rng = [], []
    for k, i in enumerate(sells):
        if t.status.iat[k] != 2:
            continue
        j0 = int(np.searchsorted(fh1, i + 1))
        o_, h_, l_, c_ = h1o[i], h1h[i], h1l[i], h1c[i]
        slv = h_ + pad
        tpv = o_ - rr * (slv - o_)
        if first_touch(fh, fl, fs, j0, slv, tpv, -1) != 1:
            continue
        mx = max_high_until_tp(fo, fh, fl, fs, j0, slv, tpv)
        body.append(max(mx - c_, 0) / (o_ - c_) * 100)
        rng.append((max(mx, l_) - l_) / (h_ - l_) * 100)
    body, rng = np.array(body), np.array(rng)
    print(f"Not filled but planned TP reached first: {len(body)} setups. Highest retracement before the TP:")
    print(f"  as % of the engulfing BODY (0% = close, 100% = open):  median {np.median(body):.0f}%, "
          f"average {body.mean():.0f}%")
    bins = [0, 10, 25, 38.2, 50, 61.8, 78.6, 100, 1e9]
    labels = ["0-10%", "10-25%", "25-38%", "38-50%", "50-62%", "62-79%", "79-100%", "above the open"]
    cnt = pd.cut(body, bins, labels=labels, right=False).value_counts().reindex(labels)
    print("  " + " | ".join(f"{k}: {v}" for k, v in cnt.items()))
    print("  reached at least: " + " | ".join(f"{p}%: {(body >= p).sum()}" for p in (10, 25, 38.2, 50, 61.8)))
    print(f"  as % of the WHOLE candle (0% = low, 100% = high):    median {np.median(rng):.0f}%, average {rng.mean():.0f}%")

    # 2) the limit at other retracement levels of the body, all setups
    print("\nSell limit at other retracement levels of the body (all setups, SL high + 50 pips, TP 1:3):")
    rows = []
    for lvl in (0.0, 0.1, 0.25, 0.382, 0.5, 0.618, 0.786, 1.0):
        res = []
        for i in sells:
            j0 = int(np.searchsorted(fh1, i + 1))
            if j0 >= len(fo):
                continue
            e = h1c[i] + lvl * (h1o[i] - h1c[i])
            res.append(sell_limit(fo, fh, fl, fs, fh1, flast, h1c, j0, e, h1h[i] + pad, h1l[i], rr))
        st = np.array([x[0] for x in res])
        r = np.array([x[1] for x in res])
        x = r[st == 1]
        rows.append({"entry (% of body)": f"{lvl * 100:.1f}%", "setups": len(res), "filled": int((st == 1).sum()),
                     "not filled": int((st == 2).sum()), "TP hit %": round(float((x >= rr - 0.001).mean() * 100), 1),
                     "R/trade": round(float(x.mean()), 3), "net R": round(float(x.sum()), 1)})
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    files = sorted(glob.glob("data/M3_exness/*.csv"))
    if files:
        analyse(m3.load_mt5(files), "Exness (2020-01..2026-11)")
    analyse(b.load_data("M1"), "Our data (2021-11..2026-10)")
