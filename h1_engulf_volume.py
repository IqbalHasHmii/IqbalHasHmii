"""H1 bearish engulfing SELL: with or without the higher-highs rule, with or without a low-volume
engulfing.

Entry and exits as in h1_hh_engulf_25.py: sell limit at close + 25% of the body, SL at the
engulfing high, TP 1:3, the unfilled order is removed when an H1 candle closes below the
engulfing low. Fills and exits on M3 (Exness) / M1 (our data) with spread.

Rules compared:
  higher highs : "3 HH" = 3 H1 candles in a row made higher highs before the engulfing (current)
                 "none" = every bearish engulfing (the higher-highs rule removed)
  volume       : "any", "low" = engulfing tick volume below the previous candle's, or "high" =
                 at or above it
Engulfing groups: perfect + strong (the EA default), exact body, every type; also with the
"any POI" filter of h1_hh_engulf_poi.py.

    python h1_engulf_volume.py      # -> results/h1_engulf_volume.txt
"""
from __future__ import annotations

import glob

import numpy as np
import pandas as pd

import backtest as b
import m3_ha_test as m3
from h1_hh_engulf import PERIODS
from h1_hh_engulf_25 import limit_trade
from h1_hh_engulf_poi import poi_flags
from h1_hh_engulf_types import engulf_types, new_highs_ok
from mass_search import resample

RR = 3.0


def trades(fine: pd.DataFrame) -> pd.DataFrame:
    h1 = resample(fine, 60)
    fh1 = np.searchsorted(h1.index.to_numpy(), fine.index.floor("h").to_numpy())
    flast = np.r_[fh1[1:] != fh1[:-1], True]
    fo, fh, fl, fs = (fine[k].to_numpy(np.float64) for k in ("open", "high", "low", "spread_px"))
    o, h, l, c = (h1[k].to_numpy(np.float64) for k in ("open", "high", "low", "close"))
    v = h1.tickvol.to_numpy(np.float64)
    ty = engulf_types(h1)
    any_type = ty["body"] | ty["body_tol"] | ty["perfect"] | ty["outside"] | ty["strong"] | ty["multi2"]
    hh = new_highs_ok(h, 3, 3)
    low_vol = v < np.r_[np.nan, v[:-1]]
    poi = poi_flags(h1)["any POI"].to_numpy()
    rows = []
    for i in np.flatnonzero(any_type):
        if i < 200:
            continue
        st, fj, xj, r = limit_trade(fo, fh, fl, fs, fh1, flast, c, int(np.searchsorted(fh1, i + 1)),
                                    c[i] + 0.25 * (o[i] - c[i]), h[i], l[i], -1, RR)
        if st == 1:
            rows.append({"fill": fine.index[fj], "exit": fine.index[xj], "R": r, "hh": hh[i], "low_vol": low_vol[i],
                         "poi": poi[i], "body": ty["body"][i], "ps": ty["perfect"][i] or ty["strong"][i]})
    return pd.DataFrame(rows)


def stats(x: pd.DataFrame, weeks: float, periods) -> dict:
    x = x.sort_values("exit")
    eq = x.R.cumsum()
    yr = x.groupby(x.exit.dt.year).R.sum()
    row = {"trades": len(x), "per week": round(len(x) / weeks, 2),
           "TP %": round(float((x.R >= RR - 0.001).mean() * 100), 1) if len(x) else np.nan,
           "R/trade": round(float(x.R.mean()), 3) if len(x) else np.nan, "net R": round(float(x.R.sum()), 1),
           "max DD R": round(float((eq - eq.cummax()).min()), 1) if len(x) else 0.0,
           "losing years": int((yr < 0).sum())}
    for plab, s_, e_ in periods:
        y = x[(x.fill >= s_) & (x.fill < e_)]
        row[plab.split()[0]] = f"{y.R.mean():+.2f}" if len(y) else "-"
    return row


def report(label: str, t: pd.DataFrame):
    weeks = (t.fill.max() - t.fill.min()).days / 7
    periods = [p for p in PERIODS if ((t.fill >= p[1]) & (t.fill < p[2])).any()]
    print(f"\n===== {label}: {t.fill.min():%Y-%m-%d} -> {t.fill.max():%Y-%m-%d} =====")
    pd.set_option("display.width", 250)
    for gname, g in (("perfect + strong", t.ps), ("exact body", t.body), ("every type", pd.Series(True, index=t.index))):
        for pname, pm in (("all setups", pd.Series(True, index=t.index)), ("any POI", t.poi)):
            rows = []
            for hname, hm in (("3 HH (now)", t.hh), ("none (removed)", pd.Series(True, index=t.index))):
                for vname, vm in (("any", pd.Series(True, index=t.index)), ("low", t.low_vol), ("high", ~t.low_vol)):
                    rows.append({"higher highs": hname, "volume": vname, **stats(t[g & pm & hm & vm], weeks, periods)})
            print(f"\n{gname} engulfing, {pname} (period columns: R/trade)")
            print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    files = sorted(glob.glob("data/M3_exness/*.csv"))
    if files:
        ex = m3.load_mt5(files)
        ex.index = m3.utc_to_backtest_clock(ex.index)
        report("Exness M3 2020-01..2026-11", trades(ex))
    report("Our data M1 2021-11..2026-10", trades(b.load_data("M1")))
