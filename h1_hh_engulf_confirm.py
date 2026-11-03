"""H1 higher highs + bearish engulfing, entry on CONFIRMATION instead of a retracement.

Setup as in h1_hh_engulf.py (N higher highs, then a bearish body engulfing). Then:
  ENTRY: wait for the first H1 candle that CLOSES below the engulfing low -> sell at market at the
         next candle's open.
  SL:    above the engulfing high (pad = 0 or 50 pips); TP = 3 x (SL - entry)  -> 1:3.
  The setup is dropped if price trades up to the SL level before the confirming close.
Mirror buy: N lower lows, bullish engulfing, buy when an H1 candle closes above the engulfing high,
SL below the engulfing low.
Signals on H1, the waiting and the trade on the finer candles (M1 ours, M3 Exness), with spread.

    python h1_hh_engulf_confirm.py
"""
from __future__ import annotations

import glob

import numba
import numpy as np
import pandas as pd

import backtest as b
import m3_ha_test as m3
from h1_hh_engulf import PERIODS, PIP, setups
from mass_search import resample


@numba.njit(cache=True)
def confirm_trade(fo, fh, fl, fspr, fh1, flast, h1c, j0, slv, trig, side, rr):
    """Returns (status, entry candle, exit candle, R, SL distance): status 1 traded,
    2 dropped (SL level touched before the confirming close), 0 nothing before the data ended."""
    n = len(fo)
    j = j0
    while j < n:                                   # waiting for the confirming close
        if side == -1 and fh[j] + fspr[j] >= slv:
            return 2, -1, j, np.nan, np.nan
        if side == 1 and fl[j] <= slv:
            return 2, -1, j, np.nan, np.nan
        if flast[j]:
            hc = h1c[fh1[j]]
            if (side == -1 and hc < trig) or (side == 1 and hc > trig):
                break
        j += 1
    j += 1                                         # entry at the open of the next candle
    if j >= n:
        return 0, -1, n - 1, np.nan, np.nan
    if side == -1:
        e = fo[j]
        d = slv - e
        tpv = e - rr * d
    else:
        e = fo[j] + fspr[j]
        d = e - slv
        tpv = e + rr * d
    if not d > 0:
        return 2, -1, j, np.nan, np.nan
    for k in range(j, n):
        if side == -1:
            if fh[k] + fspr[k] >= slv:
                return 1, j, k, (e - max(slv, fo[k] + fspr[k])) / d, d
            if fl[k] + fspr[k] <= tpv:
                return 1, j, k, (e - min(tpv, fo[k] + fspr[k])) / d, d
        else:
            if fl[k] <= slv:
                return 1, j, k, (min(slv, fo[k]) - e) / d, d
            if fh[k] >= tpv:
                return 1, j, k, (max(tpv, fo[k]) - e) / d, d
    return 0, j, n - 1, np.nan, d


def analyse(fine: pd.DataFrame, label: str, rr: float = 3.0):
    h1 = resample(fine, 60)
    fh1 = np.searchsorted(h1.index.to_numpy(), fine.index.floor("h").to_numpy())
    flast = np.r_[fh1[1:] != fh1[:-1], True]
    fo, fh, fl, fs = (fine[k].to_numpy(np.float64) for k in ("open", "high", "low", "spread_px"))
    h1h, h1l, h1c = (h1[k].to_numpy(np.float64) for k in ("high", "low", "close"))
    weeks = (fine.index[-1] - fine.index[0]).days / 7
    print(f"\n===== {label}: {fine.index[0]:%Y-%m-%d} -> {fine.index[-1]:%Y-%m-%d}, entry on the close beyond the engulfing, TP 1:{rr:g} =====")
    for n in (3, 4):
        sells, buys = setups(h1, n)
        for name, idx, side in (("SELL", sells, -1), ("BUY", buys, 1)):
            for pad_pips in (0, 50):
                rows = []
                for i in idx:
                    j0 = int(np.searchsorted(fh1, i + 1))
                    if j0 >= len(fo):
                        continue
                    slv = h1h[i] + pad_pips * PIP if side == -1 else h1l[i] - pad_pips * PIP
                    trig = h1l[i] if side == -1 else h1h[i]
                    rows.append(confirm_trade(fo, fh, fl, fs, fh1, flast, h1c, j0, slv, trig, side, rr))
                x = pd.DataFrame(rows, columns=["status", "ej", "xj", "R", "d"])
                tr = x[x.status == 1].copy()
                tr["entry"] = fine.index[tr.ej.to_numpy()]
                tr["exit"] = fine.index[tr.xj.to_numpy()]
                tr = tr.sort_values("exit")
                eq = tr.R.cumsum()
                ev = pd.concat([pd.DataFrame({"t": tr.entry, "d": 1}), pd.DataFrame({"t": tr.exit, "d": -1})]).sort_values(["t", "d"])
                what = "higher highs" if side == -1 else "lower lows"
                sl_txt = f"SL {'high' if side == -1 else 'low'}{' + 50 pips' if pad_pips else ''}"
                print(f"\n-- {name}, {n} {what}, {sl_txt}: {len(x)} setups -> traded {len(tr)}, "
                      f"dropped (SL level touched first) {(x.status == 2).sum()}, still waiting {(x.status == 0).sum()}")
                if tr.empty:
                    continue
                print(f"   {len(tr)} trades ({len(tr) / weeks:.2f}/wk), TP hit {(tr.R >= rr - 0.001).mean() * 100:.1f}%, "
                      f"{tr.R.mean():+.3f}R/trade, net {tr.R.sum():+.1f}R, max drawdown {(eq - eq.cummax()).min():.1f}R, "
                      f"median SL {tr.d.median() / PIP:.0f} pips (TP {3 * tr.d.median() / PIP:.0f}), most open at once {ev.d.cumsum().max()}")
                per = []
                for lab, s, e in PERIODS:
                    y = tr[(tr.entry >= s) & (tr.entry < e)]
                    if len(y):
                        per.append(f"{lab}: {len(y)} tr, TP {(y.R >= rr - 0.001).mean() * 100:.0f}%, {y.R.mean():+.2f}R/t")
                print("   " + " | ".join(per))
                yr = tr.groupby(tr.exit.dt.year).R.agg(["size", "sum"])
                print("   by year: " + ", ".join(f"{yy}: {int(a)} tr {s:+.0f}R" for yy, (a, s) in yr.iterrows()))


if __name__ == "__main__":
    files = sorted(glob.glob("data/M3_exness/*.csv"))
    if files:
        analyse(m3.load_mt5(files), "Exness M3 (2020-01..2026-11)")
    analyse(b.load_data("M1"), "Our data M1 (2021-11..2026-10)")
