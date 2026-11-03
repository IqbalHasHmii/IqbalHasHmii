"""Engulfing types x "higher highs" definitions for the H1 sell (25% retracement entry, SL at the
engulfing high, TP 1:3, cancelled on an H1 close below the engulfing low - see h1_hh_engulf_25.py).

Higher highs before the engulfing candle (window = the W candles right before it):
  a candle counts as a "new high" when its high is above every earlier high of the run
  (the run starts with the candle just before the window). M new highs are needed.
    W = M      -> consecutive higher highs (the earlier tests)
    W = M + 1  -> one pause allowed (e.g. HH, HH, no, HH)
    W = M + 2  -> two pauses allowed
Bearish engulfing types:
  body      : previous candle bullish, body covers its body (close <= prev open, open >= prev close)
  body_tol  : same with a 5-cent tolerance on both edges (3-decimal brokers rarely open exactly
              at the previous close)
  perfect   : body + high above the previous high and low below the previous low
  outside   : high above the previous high, low below the previous low, bearish close (wick engulfing)
  strong    : body + close below the previous candle's low
  multi2    : the body covers the bodies of the previous TWO candles (previous candle bullish)

    python h1_hh_engulf_types.py
"""
from __future__ import annotations

import glob

import numba
import numpy as np
import pandas as pd

import backtest as b
import m3_ha_test as m3
from h1_hh_engulf_25 import limit_trade
from mass_search import resample


@numba.njit(cache=True)
def new_highs_ok(h, m, w):
    n = len(h)
    ok = np.zeros(n, np.bool_)
    for i in range(w + 1, n):
        ref = h[i - w - 1]
        cnt = 0
        for k in range(i - w, i):
            if h[k] > ref:
                cnt += 1
                ref = h[k]
        ok[i] = cnt >= m
    return ok


def engulf_types(h1: pd.DataFrame) -> dict:
    o, h, l, c = (h1[k].to_numpy() for k in ("open", "high", "low", "close"))
    po, pc, ph, pl = (np.r_[np.nan, x[:-1]] for x in (o, c, h, l))
    po2, pc2 = np.r_[np.nan, np.nan, o[:-2]], np.r_[np.nan, np.nan, c[:-2]]
    tol = 0.05
    body = (pc > po) & (c < o) & (c <= po) & (o >= pc)
    return {
        "body": body,
        "body_tol": (pc > po) & (c < o) & (c <= po + tol) & (o >= pc - tol),
        "perfect": body & (h > ph) & (l < pl),
        "outside": (h > ph) & (l < pl) & (c < o),
        "strong": body & (c < pl),
        "multi2": (pc > po) & (c < o) & (o >= np.fmax(np.fmax(po, pc), np.fmax(po2, pc2)))
                  & (c <= np.fmin(np.fmin(po, pc), np.fmin(po2, pc2))),
    }


def run(fine: pd.DataFrame, label: str, level=0.25, rr=3.0):
    h1 = resample(fine, 60)
    fh1 = np.searchsorted(h1.index.to_numpy(), fine.index.floor("h").to_numpy())
    flast = np.r_[fh1[1:] != fh1[:-1], True]
    fo, fh, fl, fs = (fine[k].to_numpy(np.float64) for k in ("open", "high", "low", "spread_px"))
    h1o, h1h, h1l, h1c = (h1[k].to_numpy(np.float64) for k in ("open", "high", "low", "close"))
    weeks = (fine.index[-1] - fine.index[0]).days / 7
    types = engulf_types(h1)
    hh = {}
    for m_ in (3, 4):
        for extra, lab in ((0, "consecutive"), (1, "1 pause ok"), (2, "2 pauses ok")):
            hh[f"{m_} HH, {lab}"] = new_highs_ok(h1h, m_, m_ + extra)
    rows = []
    for tname, eng in types.items():
        for hname, ok in hh.items():
            idx = np.flatnonzero(eng & ok)
            res = [limit_trade(fo, fh, fl, fs, fh1, flast, h1c, int(np.searchsorted(fh1, i + 1)),
                               h1c[i] + level * (h1o[i] - h1c[i]), h1h[i], h1l[i], -1, rr) for i in idx]
            st = np.array([x[0] for x in res])
            r = np.array([x[3] for x in res])
            x = r[st == 1]
            rows.append({"engulfing": tname, "higher highs": hname, "setups": len(idx), "trades": len(x),
                         "per week": round(len(x) / weeks, 2),
                         "TP %": round(float((x >= rr - 0.001).mean() * 100), 1) if len(x) else np.nan,
                         "R/trade": round(float(x.mean()), 3) if len(x) else np.nan,
                         "net R": round(float(x.sum()), 1)})
    df = pd.DataFrame(rows)
    print(f"\n===== {label} ({fine.index[0]:%Y-%m-%d} -> {fine.index[-1]:%Y-%m-%d}) | SELL, limit at 25% of the body, SL at the engulfing high, TP 1:3 =====")
    pd.set_option("display.width", 220)
    print(df.to_string(index=False))
    piv = df.pivot(index="engulfing", columns="higher highs", values="R/trade").reindex(list(types))
    print("\nR per trade (rows = engulfing type, columns = higher-high rule):")
    print(piv[list(hh)].to_string())
    return df


if __name__ == "__main__":
    out = []
    files = sorted(glob.glob("data/M3_exness/*.csv"))
    if files:
        out.append(run(m3.load_mt5(files), "Exness M3").assign(data="Exness 2020-26"))
    out.append(run(b.load_data("M1"), "Our data M1").assign(data="Ours 2021-26"))
    pd.concat(out).to_csv("results/h1_hh_engulf_types.csv", index=False)
