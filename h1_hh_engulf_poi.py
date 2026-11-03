"""H1 higher highs + bearish engulfing SELL, only at a point of interest (POI).

Base strategy (h1_hh_engulf_25.py, strategy 9 of the all-in-one EA): 3 H1 candles in a row make
higher highs, then a bearish engulfing closes. Sell limit at close + 25% of the body, SL at the
engulfing high, TP 1:3, the unfilled order is removed when an H1 candle closes below the
engulfing low. Fills and exits on M3 (Exness) / M1 (our data) with spread.

POI filters (the engulfing candle has to be at one). Days and sessions use the strategy clock
(UTC+2 / UTC+3), as the EA does:
  previous day high  : the engulfing high is above the previous day's high (liquidity sweep)
  previous week high : the engulfing high is above the previous week's high
  5-day high         : the engulfing high is the highest high of the last 120 H1 candles
  bearish order block: the engulfing (with the candle before it) touches an active bearish
                       order block and closes below its top (zones_v4.zone_touch)
  bearish FVG        : the same with an active bearish fair value gap
  round number       : the candle trades through a $50 level and closes below it
  Asian high         : from 10:00 on, the engulfing high is above today's 01:00-09:59 high
  any POI            : at least one of these; "no POI" = none of them
Engulfing types: exact body engulfing, perfect + strong (the EA default) and every type.

    python h1_hh_engulf_poi.py      # -> results/h1_hh_engulf_poi.txt
"""
from __future__ import annotations

import glob

import numpy as np
import pandas as pd

import backtest as b
import m3_ha_test as m3
from h1_hh_engulf import PERIODS
from h1_hh_engulf_25 import limit_trade
from h1_hh_engulf_types import engulf_types, new_highs_ok
from mass_search import resample
from zones_v4 import zone_touch

RR = 3.0
POIS = ["previous day high", "previous week high", "5-day high", "bearish order block", "bearish FVG",
        "round number $50", "Asian high"]


def poi_flags(h1: pd.DataFrame) -> pd.DataFrame:
    h, c = h1.high, h1.close
    day = h1.index.normalize()
    pdh = h.groupby(day).max().shift(1).reindex(day).to_numpy()
    week = h1.index.to_period("W")
    pwh = h.groupby(week).max().shift(1).reindex(week).to_numpy()
    asia = (h1.index.hour >= 1) & (h1.index.hour <= 9)
    asia_hi = h[asia].groupby(day[asia]).max().reindex(day).to_numpy()
    level = np.floor(h.to_numpy() / 50.0) * 50.0
    zt = zone_touch(h1)
    f = pd.DataFrame(index=h1.index)
    f["previous day high"] = h.to_numpy() > pdh
    f["previous week high"] = h.to_numpy() > pwh
    f["5-day high"] = (h >= h.rolling(120).max()).to_numpy()
    f["bearish order block"] = zt["bear_ob"]
    f["bearish FVG"] = zt["bear_fvg"]
    f["round number $50"] = level > c.to_numpy()
    f["Asian high"] = (h1.index.hour >= 10) & (h.to_numpy() > asia_hi)
    f["any POI"] = f[POIS].any(axis=1)
    f["no POI"] = ~f["any POI"]
    return f


def trades(fine: pd.DataFrame) -> pd.DataFrame:
    h1 = resample(fine, 60)
    fh1 = np.searchsorted(h1.index.to_numpy(), fine.index.floor("h").to_numpy())
    flast = np.r_[fh1[1:] != fh1[:-1], True]
    fo, fh, fl, fs = (fine[k].to_numpy(np.float64) for k in ("open", "high", "low", "spread_px"))
    o, h, l, c = (h1[k].to_numpy(np.float64) for k in ("open", "high", "low", "close"))
    ty = engulf_types(h1)
    any_type = ty["body"] | ty["body_tol"] | ty["perfect"] | ty["outside"] | ty["strong"] | ty["multi2"]
    idx = np.flatnonzero(any_type & new_highs_ok(h, 3, 3))
    poi = poi_flags(h1)
    rows = []
    for i in idx:
        st, fj, xj, r = limit_trade(fo, fh, fl, fs, fh1, flast, c, int(np.searchsorted(fh1, i + 1)),
                                    c[i] + 0.25 * (o[i] - c[i]), h[i], l[i], -1, RR)
        if st == 1:
            rows.append({"i": i, "fill": fine.index[fj], "exit": fine.index[xj], "R": r,
                         "body": ty["body"][i], "perfect+strong": ty["perfect"][i] or ty["strong"][i],
                         **{k: bool(poi.iat[i, poi.columns.get_loc(k)]) for k in poi.columns}})
    return pd.DataFrame(rows)


def report(label: str, t: pd.DataFrame):
    weeks = (t.fill.max() - t.fill.min()).days / 7
    print(f"\n===== {label}: {t.fill.min():%Y-%m-%d} -> {t.fill.max():%Y-%m-%d} =====")
    pd.set_option("display.width", 250)
    for group, keep in (("exact body engulfing", t.body), ("perfect + strong (EA default)", t["perfect+strong"]),
                        ("every engulfing type", pd.Series(True, index=t.index))):
        rows = []
        for name in ["all (no POI filter)"] + POIS + ["any POI", "no POI"]:
            m = keep if name.startswith("all") else keep & t[name]
            x = t[m]
            row = {"POI": name, "trades": len(x), "per week": round(len(x) / weeks, 2),
                   "TP %": round(float((x.R >= RR - 0.001).mean() * 100), 1) if len(x) else np.nan,
                   "R/trade": round(float(x.R.mean()), 3) if len(x) else np.nan,
                   "net R": round(float(x.R.sum()), 1)}
            for plab, s_, e_ in PERIODS:
                y = x[(x.fill >= s_) & (x.fill < e_)]
                if ((t.fill >= s_) & (t.fill < e_)).any():
                    row[plab.split()[0]] = f"{y.R.mean():+.2f} ({len(y)})" if len(y) else "-"
            rows.append(row)
        print(f"\n{group} (period columns: R/trade (trades)):")
        print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    files = sorted(glob.glob("data/M3_exness/*.csv"))
    if files:
        ex = m3.load_mt5(files)
        ex.index = m3.utc_to_backtest_clock(ex.index)      # days and sessions on the strategy clock
        report("Exness M3 2020-01..2026-11", trades(ex))
    report("Our data M1 2021-11..2026-10", trades(b.load_data("M1")))
