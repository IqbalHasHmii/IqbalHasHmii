"""Exit and entry changes for the M3 Heikin Ashi buy, checked on data they were not found on.

Same signals as m3_ha_test.py. Variants (TP stays 3 x the SL distance):
  SL size      : 1.5 / 2 (current) / 2.5 / 3 x ATR(14)
  breakeven    : SL moved to the entry once the bid reaches +1R or +2R (from the next candle)
  early cut    : close the trade at market after 1 h (20 candles) or 2 h if it is below the entry
  entry filters: ATR at least 1.15x its average (instead of 1x); last hour's move up at most 4 ATR
Each variant is shown for every signal and for the EA setting (max 3 open), on Exness
(2021-11..2024-10 discovery, 2020-01..2021-10 never used, 2024-11..2026-11 P3) and our data.

    python m3_ha_improve.py      # -> results/m3_ha_improve.txt
"""
from __future__ import annotations

import glob

import numba
import numpy as np
import pandas as pd

import backtest as b
import m3_ha_test as m3
from mass_search import resample
from strategy_library import atr

RR = 3.0
PERIODS = [("disc", "2021-11-01", "2024-11-01"), ("2020-21", "2000-01-01", "2021-11-01"),
           ("P3", "2024-11-01", "2100-01-01")]


@numba.njit(cache=True)
def outcomes(o, h, l, c, spr, a, idx, maxh, slm, be_at, cut_after):
    n = len(o)
    r = np.full(len(idx), np.nan)
    ex = np.full(len(idx), -1)
    for k in range(len(idx)):
        i = idx[k]
        d = slm * a[i]
        if not d > 0 or i + 1 >= n:
            continue
        j0 = i + 1
        e = o[j0] + spr[j0]
        sl, tp = e - d, e + RR * d
        moved = False
        last = min(n - 1, i + maxh)
        for j in range(j0, last + 1):
            if l[j] <= sl:
                r[k], ex[k] = (min(sl, o[j]) - e) / d, j
                break
            if h[j] >= tp:
                r[k], ex[k] = (max(tp, o[j]) - e) / d, j
                break
            if cut_after > 0 and j == i + cut_after and c[j] < e:
                r[k], ex[k] = (c[j] - e) / d, j
                break
            if be_at > 0 and not moved and h[j] - e >= be_at * d:
                sl = e                     # breakeven from the next candle on
                moved = True
        if ex[k] < 0 and last == i + maxh:
            r[k], ex[k] = (c[last] - e) / d, last
    return r, ex


def variants(d: pd.DataFrame) -> dict:
    o, h, l, c, spr = (d[k].to_numpy(np.float64) for k in ("open", "high", "low", "close", "spread_px"))
    a_s = atr(d)
    a = a_s.to_numpy(np.float64)
    ratio = (a_s / a_s.rolling(9200).mean()).to_numpy()
    ret1h = ((d.close - d.close.shift(20)) / a_s).to_numpy()
    sig = m3.ha_trades(d).i.to_numpy()

    def run(slm=2.0, be_at=0.0, cut_after=0, keep=None):
        idx = sig if keep is None else sig[keep[sig]]
        r, ex = outcomes(o, h, l, c, spr, a, idx, 2300, slm, be_at, cut_after)
        ok = ex >= 0
        return pd.DataFrame({"entry": d.index[idx[ok] + 1], "exit": d.index[ex[ok]], "R": r[ok]})

    return {
        "current: SL 2 ATR": run(),
        "SL 1.5 ATR": run(slm=1.5),
        "SL 2.5 ATR": run(slm=2.5),
        "SL 3 ATR": run(slm=3.0),
        "breakeven at +1R": run(be_at=1.0),
        "breakeven at +2R": run(be_at=2.0),
        "cut after 1 h if below entry": run(cut_after=20),
        "cut after 2 h if below entry": run(cut_after=40),
        "entry: ATR >= 1.15x average": run(keep=ratio >= 1.15),
        "entry: last hour up <= 4 ATR": run(keep=ret1h <= 4),
        "entry: both filters": run(keep=(ratio >= 1.15) & (ret1h <= 4)),
    }


def show(label: str, d: pd.DataFrame):
    print(f"\n===== {label} =====")
    rows = []
    for name, t in variants(d).items():
        row = {"variant": name}
        for p, s_, e_ in PERIODS:
            m = (t.entry >= s_) & (t.entry < e_)
            if m.any():
                row[f"{p} R/t"] = round(float(t.R[m].mean()), 3)
        row["TP %"] = round(float((t.R >= RR - 0.001).mean() * 100), 1)
        cap = m3.cap_open(t.sort_values("entry").reset_index(drop=True), 3).sort_values("exit")
        eq = cap.R.cumsum()
        row["max3: trades"] = len(cap)
        row["max3: R/t"] = round(float(cap.R.mean()), 3)
        row["max3: net R"] = round(float(cap.R.sum()), 0)
        row["max3: DD R"] = round(float((eq - eq.cummax()).min()), 0)
        for p, s_, e_ in PERIODS:
            m = (cap.entry >= s_) & (cap.entry < e_)
            if m.any():
                row[f"max3 {p}"] = round(float(cap.R[m].sum()), 0)
        rows.append(row)
    pd.set_option("display.width", 250)
    print(pd.DataFrame(rows).to_string(index=False))


def sweep(label: str, d: pd.DataFrame):
    """ATR filter threshold sweep: is the gain a plateau or one lucky number?"""
    o, h, l, c, spr = (d[k].to_numpy(np.float64) for k in ("open", "high", "low", "close", "spread_px"))
    a_s = atr(d)
    a = a_s.to_numpy(np.float64)
    ratio = (a_s / a_s.rolling(9200).mean()).to_numpy()
    sig = m3.ha_trades(d).i.to_numpy()
    weeks = (d.index[-1] - d.index[0]).days / 7
    rows = []
    for slm in (2.0, 2.5):
        for thr in (1.0, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30, 1.40, 1.50):
            idx = sig[ratio[sig] >= thr]
            r, ex = outcomes(o, h, l, c, spr, a, idx, 2300, slm, 0.0, 0)
            ok = ex >= 0
            t = pd.DataFrame({"entry": d.index[idx[ok] + 1], "exit": d.index[ex[ok]], "R": r[ok]})
            row = {"SL": f"{slm:g} ATR", "ATR >= x avg": thr}
            for p, s_, e_ in PERIODS:
                m = (t.entry >= s_) & (t.entry < e_)
                if m.any():
                    row[f"{p} R/t"] = round(float(t.R[m].mean()), 3)
            for cap in (3, 5):
                x = m3.cap_open(t, cap).sort_values("exit")
                eq = x.R.cumsum()
                row[f"max{cap}: /wk"] = round(len(x) / weeks, 1)
                row[f"max{cap}: R/t"] = round(float(x.R.mean()), 3)
                row[f"max{cap}: net"] = round(float(x.R.sum()), 0)
                row[f"max{cap}: DD"] = round(float((eq - eq.cummax()).min()), 0)
            rows.append(row)
    print(f"\n===== {label}: ATR filter sweep =====")
    print(pd.DataFrame(rows).to_string(index=False))

def compare(label: str, d: pd.DataFrame):
    """The EA change: ATR >= 1.15x average with max 5 open, against v1.00 (1x, max 3 open)."""
    o, h, l, c, spr = (d[k].to_numpy(np.float64) for k in ("open", "high", "low", "close", "spread_px"))
    a_s = atr(d)
    a = a_s.to_numpy(np.float64)
    ratio = (a_s / a_s.rolling(9200).mean()).to_numpy()
    sig = m3.ha_trades(d).i.to_numpy()
    out = {}
    for name, thr, cap in (("v1.00: ATR >= 1x, max 3 open", 1.0, 3), ("v1.10: ATR >= 1.15x, max 5 open", 1.15, 5)):
        idx = sig[ratio[sig] >= thr]
        r, ex = outcomes(o, h, l, c, spr, a, idx, 2300, 2.0, 0.0, 0)
        ok = ex >= 0
        t = pd.DataFrame({"entry": d.index[idx[ok] + 1], "exit": d.index[ex[ok]], "R": r[ok]})
        out[name] = m3.cap_open(t, cap).sort_values("exit")
    print(f"\n===== {label}: v1.00 vs v1.10 (the EA settings) =====")
    for name, x in out.items():
        eq = x.R.cumsum()
        weeks = (d.index[-1] - d.index[0]).days / 7
        print(f"  {name}: {len(x)} trades ({len(x) / weeks:.1f}/wk), TP {(x.R >= RR - 0.001).mean() * 100:.1f}%, "
              f"{x.R.mean():+.3f}R/t, net {x.R.sum():+.0f}R, max drawdown {(eq - eq.cummax()).min():.0f}R")
        per = [f"{p}: {(m := (x.entry >= s_) & (x.entry < e_)).sum()} tr {x.R[m].mean():+.2f}R/t {x.R[m].sum():+.0f}R"
               for p, s_, e_ in PERIODS if ((x.entry >= s_) & (x.entry < e_)).any()]
        print("     " + " | ".join(per))
        print("     by year: " + ", ".join(f"{y}: {v:+.0f}R" for y, v in x.groupby(x.exit.dt.year).R.sum().items()))



if __name__ == "__main__":
    ex = m3.load_mt5(sorted(glob.glob("data/M3_exness/*.csv")))
    ex.index = m3.utc_to_backtest_clock(ex.index)
    show("Exness M3 2020-01..2026-11 (R/t = every signal; max3 = EA setting, net R per period)", ex)
    ours = resample(b.load_data("M1"), 3)
    show("Our data M1 -> M3 2021-11..2026-10", ours)
    sweep("Exness", ex)
    sweep("Our data", ours)
    compare("Exness", ex)
    compare("Our data", ours)
