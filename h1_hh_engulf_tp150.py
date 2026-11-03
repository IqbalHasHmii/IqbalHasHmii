"""H1 higher highs + bearish engulfing SELL with a fixed 150-pip TP.

Same setup and entry as h1_hh_engulf_poi.py (3 higher highs, bearish engulfing, sell limit at
close + 25% of the body, removed on an H1 close below the engulfing low). Exits compared:
  A  now          : SL at the engulfing high, TP 1:3 (3 x the SL distance)
  B  TP 150 pips  : SL at the engulfing high, TP 150 pips ($15) below the entry
  C  50 / 150     : SL 50 pips ($5) above the entry, TP 150 pips (1:3 in pips)
1 pip = $0.10, so at 0.01 lot (1 oz) one pip is $0.10 and 150 pips are $15.
Results in pips (= $ per 0.01 lot / 0.10) and in R (profit / SL distance of the trade).

    python h1_hh_engulf_tp150.py      # -> results/h1_hh_engulf_tp150.txt
"""
from __future__ import annotations

import glob

import numba
import numpy as np
import pandas as pd

import backtest as b
import m3_ha_test as m3
from h1_hh_engulf import PERIODS
from h1_hh_engulf_poi import poi_flags
from h1_hh_engulf_types import engulf_types, new_highs_ok
from mass_search import resample

PIP = 0.10


@numba.njit(cache=True)
def sell_limit(fo, fh, fl, fspr, fh1, flast, h1c, j0, e, slv, tpv, cancel):
    """Sell limit at e, stop slv, target tpv. Returns (status 1 traded / 2 cancelled / 0, fill
    candle, exit candle, profit per oz). On the fill candle only the stop is checked; the stop
    comes first when both are hit in one candle."""
    fill = 0.0
    fj = -1
    filled = False
    for j in range(j0, len(fo)):
        fresh = False
        if not filled:
            if fo[j] >= e:
                fill, filled = fo[j], True
            elif fh[j] >= e:
                fill, filled, fresh = e, True, True
            if not filled:
                if flast[j] and h1c[fh1[j]] < cancel:
                    return 2, -1, j, np.nan
                continue
            fj = j
        if fh[j] + fspr[j] >= slv:
            return 1, fj, j, fill - (slv if fresh else max(slv, fo[j] + fspr[j]))
        if (not fresh) and fl[j] + fspr[j] <= tpv:
            return 1, fj, j, fill - min(tpv, fo[j] + fspr[j])
    return 0, fj, len(fo) - 1, np.nan


def trades(fine: pd.DataFrame) -> pd.DataFrame:
    h1 = resample(fine, 60)
    fh1 = np.searchsorted(h1.index.to_numpy(), fine.index.floor("h").to_numpy())
    flast = np.r_[fh1[1:] != fh1[:-1], True]
    fo, fh, fl, fs = (fine[k].to_numpy(np.float64) for k in ("open", "high", "low", "spread_px"))
    o, h, l, c = (h1[k].to_numpy(np.float64) for k in ("open", "high", "low", "close"))
    ty = engulf_types(h1)
    any_type = ty["body"] | ty["body_tol"] | ty["perfect"] | ty["outside"] | ty["strong"] | ty["multi2"]
    poi = poi_flags(h1)["any POI"].to_numpy()
    rows = []
    for i in np.flatnonzero(any_type & new_highs_ok(h, 3, 3)):
        e = c[i] + 0.25 * (o[i] - c[i])
        d = h[i] - e
        if not d > 0:
            continue
        j0 = int(np.searchsorted(fh1, i + 1))
        row = {"i": i, "body": ty["body"][i], "perfect+strong": ty["perfect"][i] or ty["strong"][i],
               "any POI": poi[i], "sl_pips": d / PIP}
        for v, slv, tpv in (("A", h[i], e - 3 * d), ("B", h[i], e - 150 * PIP), ("C", e + 50 * PIP, e - 150 * PIP)):
            st, fj, xj, p = sell_limit(fo, fh, fl, fs, fh1, flast, c, j0, e, slv, tpv, l[i])
            row[f"{v}_st"], row[f"{v}_fill"], row[f"{v}_exit"] = st, (fine.index[fj] if st == 1 else pd.NaT), \
                (fine.index[xj] if st == 1 else pd.NaT)
            row[f"{v}_pips"] = p / PIP if st == 1 else np.nan
            row[f"{v}_R"] = p / (slv - e) if st == 1 else np.nan
            row[f"{v}_tp"] = bool(st == 1 and p >= (e - tpv) - 1e-6)
        rows.append(row)
    return pd.DataFrame(rows)


def report(label: str, t: pd.DataFrame):
    print(f"\n===== {label} =====")
    pd.set_option("display.width", 250)
    years = (t.A_fill.max() - t.A_fill.min()).days / 365.25
    for group, keep in (("perfect + strong engulfing", t["perfect+strong"]), ("exact body engulfing", t.body),
                        ("every engulfing type", pd.Series(True, index=t.index))):
        for poi_name, pm in (("all setups", pd.Series(True, index=t.index)), ("any POI", t["any POI"])):
            rows = []
            for v, name in (("A", "now: SL high, TP 1:3"), ("B", "SL high, TP 150 pips"), ("C", "SL 50, TP 150 pips")):
                x = t[keep & pm & (t[f"{v}_st"] == 1)].sort_values(f"{v}_exit")
                win, loss = x[x[f"{v}_pips"] > 0], x[x[f"{v}_pips"] <= 0]
                eq = x[f"{v}_pips"].cumsum()
                yr = x.groupby(x[f"{v}_exit"].dt.year)[f"{v}_pips"].sum()
                row = {"version": name, "trades": len(x), "TP %": round(float(x[f"{v}_tp"].mean() * 100), 1),
                       "avg win pips": round(float(win[f"{v}_pips"].mean()), 0),
                       "avg loss pips": round(float(loss[f"{v}_pips"].mean()), 0),
                       "net pips": round(float(x[f"{v}_pips"].sum()), 0),
                       "pips a year": round(float(x[f"{v}_pips"].sum() / years), 0),
                       "max DD pips": round(float((eq - eq.cummax()).min()), 0),
                       "R/trade": round(float(x[f"{v}_R"].mean()), 3),
                       "losing years": int((yr < 0).sum())}
                for plab, s_, e_ in PERIODS:
                    y = x[(x[f"{v}_fill"] >= s_) & (x[f"{v}_fill"] < e_)]
                    if ((t.A_fill >= s_) & (t.A_fill < e_)).any():
                        row[plab.split()[0]] = f"{y[f'{v}_pips'].sum():+.0f}"
                rows.append(row)
            print(f"\n{group}, {poi_name} (period columns: net pips)")
            print(pd.DataFrame(rows).to_string(index=False))
    pc = t[t["perfect+strong"] & t["any POI"] & (t.A_st == 1)]
    print(f"\nSL size of the perfect + strong POI trades (pips): median {pc.sl_pips.median():.0f}, "
          f"25-75% {pc.sl_pips.quantile(0.25):.0f}-{pc.sl_pips.quantile(0.75):.0f}; by year: " +
          ", ".join(f"{y} {g.median():.0f}" for y, g in pc.groupby(pc.A_fill.dt.year).sl_pips))


if __name__ == "__main__":
    files = sorted(glob.glob("data/M3_exness/*.csv"))
    if files:
        ex = m3.load_mt5(files)
        ex.index = m3.utc_to_backtest_clock(ex.index)
        report("Exness M3 2020-01..2026-11", trades(ex))
    report("Our data M1 2021-11..2026-10", trades(b.load_data("M1")))
