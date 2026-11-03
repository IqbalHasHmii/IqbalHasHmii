"""What happened to the setups whose sell limit never filled (h1_hh_engulf.py)?

For every cancelled setup (price closed below the engulfing low before coming back to the
engulfing open) it checks, from the moment the engulfing candle closed, which price level was
touched first: the planned TP (open - 3 x (SL - open)) or the planned SL (high + 50 pips).
SL first when both fall in the same small candle. These are not trades - the order never filled.

It also tests the obvious alternative: SELL AT MARKET right after the engulfing candle closes
(next candle's open), same SL level (high + 50 pips), TP = 3 x the new, larger SL distance.

    python h1_hh_engulf_unfilled.py
"""
from __future__ import annotations

import glob
import io
import contextlib

import numba
import numpy as np
import pandas as pd

import backtest as b
import m3_ha_test as m3
from h1_hh_engulf import PIP, run
from mass_search import resample


@numba.njit(cache=True)
def first_touch(fh, fl, fspr, j0, slv, tpv, side):
    """1 = TP level touched first, -1 = SL level first, 0 = neither before the data ends."""
    for j in range(j0, len(fh)):
        if side == -1:
            if fh[j] + fspr[j] >= slv:
                return -1
            if fl[j] + fspr[j] <= tpv:
                return 1
        else:
            if fl[j] <= slv:
                return -1
            if fh[j] >= tpv:
                return 1
    return 0


@numba.njit(cache=True)
def market_trade(fo, fh, fl, fspr, j0, slv, side, rr):
    """Market entry at the open of fine candle j0, fixed SL level, TP = rr x SL distance. Returns R."""
    if side == -1:
        e = fo[j0]
        d = slv - e
        tpv = e - rr * d
    else:
        e = fo[j0] + fspr[j0]
        d = e - slv
        tpv = e + rr * d
    if not d > 0:
        return np.nan
    for j in range(j0, len(fo)):
        if side == -1:
            if fh[j] + fspr[j] >= slv:
                return (e - max(slv, fo[j] + fspr[j])) / d
            if fl[j] + fspr[j] <= tpv:
                return (e - min(tpv, fo[j] + fspr[j])) / d
        else:
            if fl[j] <= slv:
                return (min(slv, fo[j]) - e) / d
            if fh[j] >= tpv:
                return (max(tpv, fo[j]) - e) / d
    return np.nan


def analyse(fine: pd.DataFrame, label: str, pad_pips: float = 50, rr: float = 3.0):
    with contextlib.redirect_stdout(io.StringIO()):
        out = run(fine, label, pad_pips, rr)
    h1 = resample(fine, 60)
    fh1 = np.searchsorted(h1.index.to_numpy(), fine.index.floor("h").to_numpy())
    fo, fh, fl, fs = (fine[k].to_numpy(np.float64) for k in ("open", "high", "low", "spread_px"))
    pos = {t: k for k, t in enumerate(h1.index)}
    print(f"\n===== {label} =====")
    for name, n in (("SELL", 3), ("SELL", 4), ("BUY", 3), ("BUY", 4)):
        t = out[(name, n)]
        side = -1 if name == "SELL" else 1
        rows = []
        for row in t.itertuples():
            i = pos[row.setup - pd.Timedelta(hours=1)]
            j0 = int(np.searchsorted(fh1, i + 1))
            o_, h_, l_ = h1.open.iat[i], h1.high.iat[i], h1.low.iat[i]
            slv = h_ + pad_pips * PIP if side == -1 else l_ - pad_pips * PIP
            d = abs(slv - o_)
            tpv = o_ - rr * d if side == -1 else o_ + rr * d          # planned TP of the limit order
            touch = first_touch(fh, fl, fs, j0, slv, tpv, side) if j0 < len(fo) else 0
            mkt = market_trade(fo, fh, fl, fs, j0, slv, side, rr) if j0 < len(fo) else np.nan
            rows.append((row.status, touch, mkt))
        x = pd.DataFrame(rows, columns=["status", "touch", "mkt"])
        c = x[x.status == 2]
        tag = f"{name} {n} {'higher highs' if side == -1 else 'lower lows'}"
        print(f"\n-- {tag}: {len(t)} setups, {(x.status == 1).sum()} filled, {len(c)} NOT filled")
        print(f"   NOT filled -> price reached the planned TP first: {(c.touch == 1).sum()} ({(c.touch == 1).mean() * 100:.0f}%), "
              f"planned SL first: {(c.touch == -1).sum()} ({(c.touch == -1).mean() * 100:.0f}%), neither: {(c.touch == 0).sum()}")
        f = x[x.status == 1]
        print(f"   (filled ones for comparison: TP {(t[t.status == 1].R >= rr - 0.001).sum()}, SL {(t[t.status == 1].R < rr - 0.001).sum()})")
        for lab, sub in (("all setups", x), ("the filled ones", f), ("the NOT filled ones", c)):
            m = sub.mkt.dropna()
            print(f"   market entry at the engulfing close, {lab:20s}: {len(m)} trades, TP {(m >= rr - 0.001).mean() * 100:.1f}%, "
                  f"{m.mean():+.3f}R/trade, net {m.sum():+.1f}R")


if __name__ == "__main__":
    analyse(b.load_data("M1"), "Our data (2021-11..2026-10)")
    files = sorted(glob.glob("data/M3_exness/*.csv"))
    if files:
        analyse(m3.load_mt5(files), "Exness (2020-01..2026-11)")
