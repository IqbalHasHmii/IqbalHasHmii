"""H1 higher highs + bearish engulfing, SELL LIMIT at 25% retracement of the engulfing body,
SL at the engulfing high (also high + 50 pips for comparison), TP 1:3.

Entry  : sell limit at close + 25% x (open - close)  (0% = close, 100% = open).
SL     : engulfing high (+ pad). TP = entry - 3 x (SL - entry).
Cancel : the unfilled order is removed when an H1 candle closes below the engulfing low.
Mirror buy: N lower lows, bullish engulfing, buy limit at close - 25% x (close - open), SL at the
engulfing low (- pad), cancelled when an H1 candle closes above the engulfing high.
Signals on H1, fills / exits on the finer candles with spread (M1 ours, M3 Exness). On the
candle where the limit fills only the stop is checked; SL first if SL and TP share a candle.

    python h1_hh_engulf_25.py [level]      # default level 0.25
"""
from __future__ import annotations

import glob
import sys

import numba
import numpy as np
import pandas as pd

import backtest as b
import m3_ha_test as m3
from h1_hh_engulf import PERIODS, PIP, setups
from mass_search import resample


@numba.njit(cache=True)
def limit_trade(fo, fh, fl, fspr, fh1, flast, h1c, j0, e, slv, cancel, side, rr):
    """Returns (status, fill candle, exit candle, R): 1 traded, 2 cancelled, 0 nothing yet at the end."""
    d = (slv - e) if side == -1 else (e - slv)
    if not d > 0:
        return 0, -1, -1, np.nan
    tpv = e - rr * d if side == -1 else e + rr * d
    filled = False
    fill = 0.0
    fj = -1
    for j in range(j0, len(fo)):
        fresh = False
        if not filled:
            if side == -1:
                if fo[j] >= e:
                    fill, filled = fo[j], True
                elif fh[j] >= e:
                    fill, filled, fresh = e, True, True
            else:
                if fo[j] + fspr[j] <= e:
                    fill, filled = fo[j] + fspr[j], True
                elif fl[j] + fspr[j] <= e:
                    fill, filled, fresh = e, True, True
            if not filled:
                if flast[j]:
                    hc = h1c[fh1[j]]
                    if (side == -1 and hc < cancel) or (side == 1 and hc > cancel):
                        return 2, -1, j, np.nan
                continue
            fj = j
        if side == -1:
            if fh[j] + fspr[j] >= slv:
                return 1, fj, j, (fill - (slv if fresh else max(slv, fo[j] + fspr[j]))) / d
            if (not fresh) and fl[j] + fspr[j] <= tpv:
                return 1, fj, j, (fill - min(tpv, fo[j] + fspr[j])) / d
        else:
            if fl[j] <= slv:
                return 1, fj, j, ((slv if fresh else min(slv, fo[j])) - fill) / d
            if (not fresh) and fh[j] >= tpv:
                return 1, fj, j, (max(tpv, fo[j]) - fill) / d
    return 0, fj, len(fo) - 1, np.nan


def analyse(fine: pd.DataFrame, label: str, level: float = 0.25, rr: float = 3.0):
    h1 = resample(fine, 60)
    fh1 = np.searchsorted(h1.index.to_numpy(), fine.index.floor("h").to_numpy())
    flast = np.r_[fh1[1:] != fh1[:-1], True]
    fo, fh, fl, fs = (fine[k].to_numpy(np.float64) for k in ("open", "high", "low", "spread_px"))
    h1o, h1h, h1l, h1c = (h1[k].to_numpy(np.float64) for k in ("open", "high", "low", "close"))
    weeks = (fine.index[-1] - fine.index[0]).days / 7
    print(f"\n===== {label}: {fine.index[0]:%Y-%m-%d} -> {fine.index[-1]:%Y-%m-%d} | limit at {level * 100:.0f}% of the body, TP 1:{rr:g} =====")
    for n in (3, 4):
        sells, buys = setups(h1, n)
        for name, idx, side in (("SELL", sells, -1), ("BUY", buys, 1)):
            for pad_pips in (0, 50):
                rows = []
                for i in idx:
                    j0 = int(np.searchsorted(fh1, i + 1))
                    if j0 >= len(fo):
                        continue
                    o_, h_, l_, c_ = h1o[i], h1h[i], h1l[i], h1c[i]
                    if side == -1:
                        e, slv, cancel = c_ + level * (o_ - c_), h_ + pad_pips * PIP, l_
                    else:
                        e, slv, cancel = c_ - level * (c_ - o_), l_ - pad_pips * PIP, h_
                    st, fj, xj, r = limit_trade(fo, fh, fl, fs, fh1, flast, h1c, j0, e, slv, cancel, side, rr)
                    rows.append((st, fj, xj, r, abs(slv - e) / PIP))
                x = pd.DataFrame(rows, columns=["status", "fj", "xj", "R", "sl_pips"])
                tr = x[x.status == 1].copy()
                what = "higher highs" if side == -1 else "lower lows"
                sl_txt = f"SL at the {'high' if side == -1 else 'low'}{' + 50 pips' if pad_pips else ''}"
                print(f"\n-- {name}, {n} {what}, {sl_txt}: {len(x)} setups -> filled {len(tr)} ({len(tr) / max(len(x), 1) * 100:.0f}%), "
                      f"not filled (cancelled) {(x.status == 2).sum()}, still open/pending {(x.status == 0).sum()}")
                if tr.empty:
                    continue
                tr["fill"] = fine.index[tr.fj.to_numpy()]
                tr["exit"] = fine.index[tr.xj.to_numpy()]
                tr = tr.sort_values("exit")
                eq = tr.R.cumsum()
                tp = (tr.R >= rr - 0.001).sum()
                print(f"   {len(tr)} trades ({len(tr) / weeks:.2f}/wk): TP {tp}, SL {len(tr) - tp} -> TP hit {tp / len(tr) * 100:.1f}%, "
                      f"{tr.R.mean():+.3f}R/trade, net {tr.R.sum():+.1f}R, max drawdown {(eq - eq.cummax()).min():.1f}R, "
                      f"median SL {tr.sl_pips.median():.0f} pips (TP {3 * tr.sl_pips.median():.0f})")
                per = []
                for lab, s, e_ in PERIODS:
                    y = tr[(tr.fill >= s) & (tr.fill < e_)]
                    if len(y):
                        per.append(f"{lab}: {len(y)} tr, TP {(y.R >= rr - 0.001).mean() * 100:.0f}%, {y.R.mean():+.2f}R/t")
                print("   " + " | ".join(per))
                yr = tr.groupby(tr.exit.dt.year).R.agg(["size", "sum"])
                print("   by year: " + ", ".join(f"{yy}: {int(a)} tr {s:+.0f}R" for yy, (a, s) in yr.iterrows()))


if __name__ == "__main__":
    lvl = float(sys.argv[1]) if len(sys.argv) > 1 else 0.25
    files = sorted(glob.glob("data/M3_exness/*.csv"))
    if files:
        analyse(m3.load_mt5(files), "Exness M3 (2020-01..2026-11)", lvl)
    analyse(b.load_data("M1"), "Our data M1 (2021-11..2026-10)", lvl)
