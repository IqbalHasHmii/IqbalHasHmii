"""The last 6 months only: the H1 engulfing sell trade by trade, and the all-in-one EA's totals.

Engulfing sell (current rules, strategy 9 of the all-in-one EA, with the "any POI" filter of
h1_hh_engulf_poi.py): 3 H1 candles in a row make higher highs, then a perfect or strong bearish
engulfing at a point of interest; sell limit at close + 25% of the body, SL at the engulfing
high, TP 1:3; the unfilled order is removed when an H1 candle closes below the engulfing low.
Each trade also shows whether the engulfing had more tick volume than the candle before it.

All-in-one EA: its default strategies (7 off), trades from all_in_one_backtest.py.

Money: at 0.25% risk per trade of a $10,000 account ($25 per trade, no compounding), and pips
(1 pip = $0.10; profit at 0.01 lot = pips x $0.10).

    python last6m.py      # -> results/last6m.txt
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from all_in_one_backtest import EXNESS, NAMES, OURS, build, exness_data, ours_data
from h1_hh_engulf_poi import poi_flags
from h1_hh_engulf_tp150 import sell_limit
from h1_hh_engulf_types import engulf_types, new_highs_ok
from mass_search import resample

RR, PIP = 3.0, 0.10
MONTHS = 6


def engulf_trades(fine: pd.DataFrame, start: pd.Timestamp) -> pd.DataFrame:
    h1 = resample(fine, 60)
    fh1 = np.searchsorted(h1.index.to_numpy(), fine.index.floor("h").to_numpy())
    flast = np.r_[fh1[1:] != fh1[:-1], True]
    fo, fh, fl, fs = (fine[k].to_numpy(np.float64) for k in ("open", "high", "low", "spread_px"))
    o, h, l, c = (h1[k].to_numpy(np.float64) for k in ("open", "high", "low", "close"))
    v = h1.tickvol.to_numpy(np.float64)
    ty = engulf_types(h1)
    poi = poi_flags(h1)
    pois = [k for k in poi.columns if k not in ("any POI", "no POI")]
    setup = (ty["perfect"] | ty["strong"]) & new_highs_ok(h, 3, 3) & poi["any POI"].to_numpy()
    rows = []
    for i in np.flatnonzero(setup & (h1.index >= start)):
        e = c[i] + 0.25 * (o[i] - c[i])
        d = h[i] - e
        tp = e - RR * d
        st, fj, xj, p = sell_limit(fo, fh, fl, fs, fh1, flast, c, int(np.searchsorted(fh1, i + 1)), e, h[i], tp, l[i])
        rows.append({"engulfing (H1)": h1.index[i].strftime("%Y-%m-%d %H:%M"),
                     "type": "perfect" if ty["perfect"][i] else "strong",
                     "volume": "higher" if v[i] >= v[i - 1] else "lower",
                     "POI": ", ".join(k for k in pois if poi[k].iat[i]),
                     "entry": round(e, 2), "SL": round(h[i], 2), "TP": round(tp, 2), "SL pips": round(d / PIP),
                     "result": {1: "TP" if st == 1 and p >= RR * d - 1e-6 else "SL", 2: "cancelled", 0: "open"}[st],
                     "filled": fine.index[fj].strftime("%m-%d %H:%M") if st == 1 else "-",
                     "closed": fine.index[xj].strftime("%m-%d %H:%M") if st in (1, 2) else "-",
                     "R": round(p / d, 2) if st == 1 else np.nan,
                     "pips": round(p / PIP) if st == 1 else np.nan})
    return pd.DataFrame(rows)


def summary(t: pd.DataFrame, label: str):
    x = t[t.result.isin(["TP", "SL"])]
    print(f"{label}: {len(t)} setups -> {len(x)} trades (cancelled {(t.result == 'cancelled').sum()}, "
          f"still open {(t.result == 'open').sum()}): TP {(x.result == 'TP').sum()}, SL {(x.result == 'SL').sum()}, "
          f"TP {(x.result == 'TP').mean() * 100:.0f}%, net {x.R.sum():+.1f}R = ${x.R.sum() * 25:+,.0f} at $25 risk a trade, "
          f"{x.pips.sum():+,.0f} pips = ${x.pips.sum() * PIP:+,.0f} at 0.01 lot")


def run(label: str, fine: pd.DataFrame, data: dict, end: pd.Timestamp):
    start = end - pd.DateOffset(months=MONTHS)
    print(f"\n===== {label}: last {MONTHS} months, {start:%Y-%m-%d} -> {end:%Y-%m-%d} =====")
    t = engulf_trades(fine, start)
    pd.set_option("display.width", 250, "display.max_colwidth", 60)
    print("H1 engulfing sell, every setup:")
    print(t.to_string(index=False))
    summary(t, "  all")
    summary(t[t.volume == "higher"], "  only higher-volume engulfings")

    parts = build(data, with7=False)
    rows = []
    for k, x in parts.items():
        x = x[(x.entry >= start) & (x.entry < end)]
        rows.append({"#": k, "strategy": NAMES[k], "trades": len(x), "TP": int(x.tp.sum()),
                     "TP %": round(float(x.tp.mean() * 100), 1) if len(x) else np.nan,
                     "net R": round(float(x.R.sum()), 1)})
    df = pd.DataFrame(rows)
    allx = pd.concat([x[(x.entry >= start) & (x.entry < end)] for x in parts.values()]).sort_values("exit")
    eq = allx.R.cumsum()
    mo = allx.groupby(allx.exit.dt.to_period("M")).R.sum()
    print("\nAll-in-one EA (defaults, strategy 7 off):")
    print(df.to_string(index=False))
    print(f"  total: {len(allx)} trades ({len(allx) / (MONTHS * 4.35):.1f}/week), TP {allx.tp.mean() * 100:.1f}%, "
          f"net {allx.R.sum():+.1f}R = {allx.R.sum() * 0.25:+.0f}% at 0.25% risk, "
          f"max drawdown {(eq - eq.cummax()).min():.1f}R")
    print("  by month (R): " + ", ".join(f"{m.strftime('%b %y')} {r:+.0f}" for m, r in mo.items()))


if __name__ == "__main__":
    data = exness_data()
    if data is not None:
        run("Exness data", data["m3"], data, EXNESS[1])
    data = ours_data()
    run("Our data", data["m1"], data, OURS[1])
