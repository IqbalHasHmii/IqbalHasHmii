"""H1 "higher highs + bearish engulfing" sell strategy (and the mirror buy), 1:3.

Rules (as described by the user):
  SELL setup: the N H1 candles before the engulfing each made a higher high than the candle
  before them (N = 3 or 4), then a bearish body engulfing candle closes (previous candle
  bullish, close <= previous open, open >= previous close).
  Entry: SELL LIMIT at the engulfing candle's open (price has to retrace up to it).
  SL: engulfing high + 50 pips ($5.00); TP = 3 x (SL - entry)  -> 1:3.
  The pending order stays until it fills; it is removed only when an H1 candle CLOSES below
  the engulfing candle's low. No other expiry.
  BUY (mirror): N lower lows, bullish engulfing, BUY LIMIT at its open, SL = low - 50 pips,
  removed when an H1 candle closes above the engulfing high.

Execution: signals on H1 candles (built from the finer data), fills and exits on the finer
candles (M1 for our data, M3 for the Exness export) with each candle's spread: sells fill and
take profit on bid, the stop and buy entries use ask. On the candle where a limit fills only the
stop is checked (TP could have come before the fill); SL first if SL and TP share a candle.

    python h1_hh_engulf.py              # our data (M1 2021-11..2026-10) and Exness M3 (2020-01..2026-11)
"""
from __future__ import annotations

import numba
import numpy as np
import pandas as pd

import backtest as b
from mass_search import resample

PIP = 0.10
PERIODS = [("2020-01..2021-10 (new data)", "2000-01-01", "2021-11-01"), ("2021-11..2023-10", "2021-11-01", "2023-11-01"),
           ("2023-11..2024-10", "2023-11-01", "2024-11-01"), ("2024-11..2026-11", "2024-11-01", "2100-01-01")]


def setups(h1: pd.DataFrame, n: int):
    o, h, l, c = (h1[k].to_numpy() for k in ("open", "high", "low", "close"))
    hh = np.ones(len(h1), bool)
    ll = np.ones(len(h1), bool)
    for k in range(1, n + 1):
        hh &= np.r_[np.zeros(k + 1, bool), h[1:-k] > h[:-k - 1]] if k < len(h) else False
        ll &= np.r_[np.zeros(k + 1, bool), l[1:-k] < l[:-k - 1]] if k < len(l) else False
    po, pc = np.r_[np.nan, o[:-1]], np.r_[np.nan, c[:-1]]
    bear = (pc > po) & (c < o) & (c <= po) & (o >= pc)
    bull = (pc < po) & (c > o) & (c >= po) & (o <= pc)
    return np.flatnonzero(hh & bear), np.flatnonzero(ll & bull)


@numba.njit(cache=True)
def simulate(fo, fh, fl, fc, fspr, fh1, flast, h1o, h1h, h1l, h1c, idx, side, pad, rr):
    """For each setup (H1 candle index in idx): status 1 = traded, 2 = cancelled, 0 = still pending
    at the end; fill / end fine-candle index; R multiple."""
    n = len(fo)
    m = len(idx)
    status = np.zeros(m, np.int8)
    fill_j = np.full(m, -1)
    end_j = np.full(m, -1)
    r = np.full(m, np.nan)
    for k in range(m):
        i = idx[k]
        e = h1o[i]
        if side == -1:
            slv = h1h[i] + pad
            d = slv - e
            tpv = e - rr * d
            cancel = h1l[i]
        else:
            slv = h1l[i] - pad
            d = e - slv
            tpv = e + rr * d
            cancel = h1h[i]
        j = np.searchsorted(fh1, i + 1)
        filled = False
        fill = 0.0
        while j < n:
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
                if filled:
                    fill_j[k] = j
                else:
                    if flast[j]:
                        hc = h1c[fh1[j]]
                        if (side == -1 and hc < cancel) or (side == 1 and hc > cancel):
                            status[k], end_j[k] = 2, j
                            break
                    j += 1
                    continue
            # open trade
            if side == -1:
                if fh[j] + fspr[j] >= slv:
                    ex = slv if fresh else max(slv, fo[j] + fspr[j])
                    r[k], status[k], end_j[k] = (fill - ex) / d, 1, j
                    break
                if (not fresh) and fl[j] + fspr[j] <= tpv:
                    ex = min(tpv, fo[j] + fspr[j])
                    r[k], status[k], end_j[k] = (fill - ex) / d, 1, j
                    break
            else:
                if fl[j] <= slv:
                    ex = slv if fresh else min(slv, fo[j])
                    r[k], status[k], end_j[k] = (ex - fill) / d, 1, j
                    break
                if (not fresh) and fh[j] >= tpv:
                    ex = max(tpv, fo[j])
                    r[k], status[k], end_j[k] = (ex - fill) / d, 1, j
                    break
            j += 1
    return status, fill_j, end_j, r


def run(fine: pd.DataFrame, label: str, pad_pips: float = 50, rr: float = 3.0):
    h1 = resample(fine, 60)
    fh1 = np.searchsorted(h1.index.to_numpy(), fine.index.floor("h").to_numpy())
    flast = np.r_[fh1[1:] != fh1[:-1], True]
    fo, fh, fl, fc, fs = (fine[k].to_numpy(np.float64) for k in ("open", "high", "low", "close", "spread_px"))
    h1o, h1h, h1l, h1c = (h1[k].to_numpy(np.float64) for k in ("open", "high", "low", "close"))
    weeks = (fine.index[-1] - fine.index[0]).days / 7
    print(f"\n===== {label}: {fine.index[0]:%Y-%m-%d} -> {fine.index[-1]:%Y-%m-%d}, SL = engulfing extreme +{pad_pips:g} pips, TP 1:{rr:g} =====")
    out = {}
    for n in (3, 4):
        sells, buys = setups(h1, n)
        for name, idx, side in (("SELL", sells, -1), ("BUY", buys, 1)):
            st, fj, ej, r = simulate(fo, fh, fl, fc, fs, fh1, flast, h1o, h1h, h1l, h1c, idx, side, pad_pips * PIP, rr)
            t = pd.DataFrame({"setup": h1.index[idx] + pd.Timedelta(hours=1), "status": st,
                              "fill": [fine.index[j] if j >= 0 else pd.NaT for j in fj],
                              "end": [fine.index[j] if j >= 0 else fine.index[-1] for j in ej], "R": r})
            t["risk_pips"] = np.where(side == -1, h1h[idx] + pad_pips * PIP - h1o[idx], h1o[idx] - (h1l[idx] - pad_pips * PIP)) / PIP
            tr = t[t.status == 1].copy()
            tr["tp"] = tr.R >= rr - 0.001
            wait = (tr.fill - tr.setup).dt.total_seconds() / 3600
            print(f"\n-- {name}, {n} {'higher highs' if side == -1 else 'lower lows'}: {len(t)} setups, "
                  f"filled {len(tr)} ({len(tr) / max(len(t), 1) * 100:.0f}%), cancelled {(t.status == 2).sum()}, "
                  f"median wait {wait.median():.0f} h, median SL {t.risk_pips.median():.0f} pips (TP {3 * t.risk_pips.median():.0f})")
            if tr.empty:
                continue
            # every setup on its own (overlapping) and one order/trade at a time
            for mode in ("every setup", "one at a time"):
                if mode == "every setup":
                    x = tr
                else:
                    keep, busy = [], pd.Timestamp.min
                    for row in t.sort_values("setup").itertuples():
                        if row.setup >= busy:
                            busy = row.end
                            if row.status == 1:
                                keep.append(row.Index)
                    x = tr.loc[tr.index.intersection(keep)]
                x = x.sort_values("end")
                eq = x.R.cumsum()
                ev = pd.concat([pd.DataFrame({"t": x.fill, "d": 1}), pd.DataFrame({"t": x.end, "d": -1})]).sort_values(["t", "d"])
                print(f"   {mode:13s}: {len(x)} trades ({len(x) / weeks:.2f}/wk), TP hit {(x.R >= rr - 0.001).mean() * 100:.1f}%, "
                      f"{x.R.mean():+.3f}R/trade, net {x.R.sum():+.1f}R, max drawdown {(eq - eq.cummax()).min():.1f}R, "
                      f"most open at once {ev.d.cumsum().max()}")
            per = []
            for lab, s, e in PERIODS:
                y = tr[(tr.fill >= s) & (tr.fill < e)]
                if len(y):
                    per.append(f"{lab}: {len(y)} tr, TP {(y.R >= rr - 0.001).mean() * 100:.0f}%, {y.R.mean():+.2f}R/t")
            print("   by period (every setup): " + " | ".join(per))
            yr = tr.groupby(tr.end.dt.year).R.agg(["size", "sum"])
            print("   by year: " + ", ".join(f"{y}: {int(a)} tr {s:+.0f}R" for y, (a, s) in yr.iterrows()))
            out[(name, n)] = t
    return out


if __name__ == "__main__":
    import glob

    import m3_ha_test as m3
    run(b.load_data("M1"), "Our data (H1 from M1, managed on M1)")
    files = sorted(glob.glob("data/M3_exness/*.csv"))
    if files:
        run(m3.load_mt5(files), "Exness M3 export (H1 from M3, managed on M3, UTC+0 clock)")
