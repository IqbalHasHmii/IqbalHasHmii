"""Mass strategy search: about 250,000 XAUUSD strategies, 1:3 reward-to-risk, on timeframes from
1 to 60 minutes.

    pip install numba
    python mass_search.py         # ~10-15 minutes -> results/mass_search.csv.gz + summaries

Data: the M1 history in data/M1/ (2021-11..2026-10), resampled to 1, 2, 3, 5, 10, 15, 20, 30,
45 and 60 minutes. Each candle keeps its average spread.

A strategy = timeframe x trigger x trend filter x session x volatility filter x SL size x
direction:
  trigger (21) : engulfing, engulfing with lower volume, RSI(14) back from 20/25/30, close
                 beyond the 10/20/50-candle high/low (breakout), wick beyond it but close back
                 inside (fade), pin bar, inside-bar breakout, EMA20/EMA50 pullback, Bollinger
                 re-entry (2.0/2.5 sd), Bollinger breakout, MACD histogram cross, 3 candles the
                 same colour (momentum) and 3 candles against (reversal)
  trend (5)    : none, close > EMA50, close > EMA200, EMA50 > EMA200, close > "H1 EMA200"
                 (EMA of 200 x 60 / timeframe candles); mirrored for sells
  session (6)  : all, Asia 01-09, London 10-14, New York 15-19, London+NY 10-19, late 20-00
                 (broker server time, hour of the signal candle)
  volatility(3): all, ATR(14) above its ~20-day average, below it
  SL (4)       : 0.5, 1, 1.5, 2 x ATR(14);  TP = 3 x SL
  direction (3): buys and sells, buys only, sells only
Every signal is its own trade: market entry at the next candle's open (buys pay the spread),
exits on bid/ask with that candle's spread, SL first when SL and TP fall in the same candle.
In-sample = before 2024-11-01, out-of-sample = from 2024-11-01. Nothing is chosen on
out-of-sample data.
"""
from __future__ import annotations

import itertools
import time

import numba
import numpy as np
import pandas as pd

import backtest as b
from strategies import atr, ema, rsi

SPLIT = pd.Timestamp("2024-11-01")
TFS = [1, 2, 3, 5, 10, 15, 20, 30, 45, 60]
KS = [0.5, 1.0, 1.5, 2.0]
RR = 3.0
TRENDS = ["none", "c>ema50", "c>ema200", "ema50>ema200", "c>H1ema200"]
# sessions as unions of hour buckets: 0 = Asia 01-09, 1 = London 10-14, 2 = NY 15-19, 3 = late 20-00
SESSIONS = {"all": (0, 1, 2, 3), "asia": (0,), "london": (1,), "ny": (2,), "london+ny": (1, 2), "late": (3,)}
VOLS = {"all": (0, 1), "high_vol": (1,), "low_vol": (0,)}
DIRS = ["both", "buy_only", "sell_only"]


@numba.njit(cache=True)
def outcomes(o, h, l, c, spr, a, k, side, maxh):
    """R multiple of a trade opened at the next candle's open after every candle."""
    n = len(o)
    out = np.full(n, np.nan, dtype=np.float32)
    for i in range(n - 1):
        d = k * a[i]
        if not d > 0:
            continue
        j0 = i + 1
        if side == 1:
            e = o[j0] + spr[j0]
            sl, tp = e - d, e + RR * d
        else:
            e = o[j0]
            sl, tp = e + d, e - RR * d
        r = np.nan
        last = min(n - 1, i + maxh)
        for j in range(j0, last + 1):
            if side == 1:
                if l[j] <= sl:
                    r = (min(sl, o[j]) - e) / d
                    break
                if h[j] >= tp:
                    r = (max(tp, o[j]) - e) / d
                    break
            else:
                if h[j] + spr[j] >= sl:
                    r = (e - max(sl, o[j] + spr[j])) / d
                    break
                if l[j] + spr[j] <= tp:
                    r = (e - min(tp, o[j] + spr[j])) / d
                    break
        if np.isnan(r) and last == i + maxh:          # time stop: close at market
            px = c[last] if side == 1 else c[last] + spr[last]
            r = side * (px - e) / d
        out[i] = r
    return out


def resample(m1: pd.DataFrame, minutes: int) -> pd.DataFrame:
    if minutes == 1:
        return m1
    g = m1.resample(f"{minutes}min")
    d = pd.DataFrame({"open": g.open.first(), "high": g.high.max(), "low": g.low.min(),
                      "close": g.close.last(), "tickvol": g.tickvol.sum(), "spread_px": g.spread_px.mean()})
    return d.dropna()


def triggers(d: pd.DataFrame, tf: int) -> dict:
    o, h, l, c, v = d.open, d.high, d.low, d.close, d.tickvol
    po, pc = o.shift(), c.shift()
    bull, bear = c > o, c < o
    t = {}
    eng_b = (pc < po) & bull & (c >= po) & (o <= pc)
    eng_s = (pc > po) & bear & (c <= po) & (o >= pc)
    t["engulfing"] = (eng_b, eng_s)
    t["engulfing_lowvol"] = (eng_b & (v < v.shift()), eng_s & (v < v.shift()))
    r = rsi(c, 14)
    for lv in (20, 25, 30):
        t[f"rsi_back_{lv}"] = ((r.shift() < lv) & (r >= lv), (r.shift() > 100 - lv) & (r <= 100 - lv))
    for n in (10, 20, 50):
        hh, ll = h.rolling(n).max().shift(), l.rolling(n).min().shift()
        t[f"breakout_{n}"] = (c > hh, c < ll)
        t[f"fade_{n}"] = ((l < ll) & (c > ll), (h > hh) & (c < hh))
    rng = h - l
    body = (c - o).abs()
    lower, upper = np.minimum(o, c) - l, h - np.maximum(o, c)
    t["pinbar"] = ((rng > 0) & (lower >= 2 * body) & (lower >= 0.6 * rng),
                   (rng > 0) & (upper >= 2 * body) & (upper >= 0.6 * rng))
    inside = (h.shift() <= h.shift(2)) & (l.shift() >= l.shift(2))
    t["inside_breakout"] = (inside & (c > h.shift()), inside & (c < l.shift()))
    for p in (20, 50):
        e = ema(c, p)
        t[f"ema{p}_pullback"] = ((l <= e) & (c > e) & bull, (h >= e) & (c < e) & bear)
    mid, sd = c.rolling(20).mean(), c.rolling(20).std()
    for kk in (2.0, 2.5):
        up, lo = mid + kk * sd, mid - kk * sd
        t[f"bb_reentry_{kk}"] = ((pc < lo.shift()) & (c > lo), (pc > up.shift()) & (c < up))
    up, lo = mid + 2 * sd, mid - 2 * sd
    t["bb_breakout"] = ((c > up) & (pc <= up.shift()), (c < lo) & (pc >= lo.shift()))
    macd = ema(c, 12) - ema(c, 26)
    hist = macd - ema(macd, 9)
    t["macd_cross"] = ((hist.shift() <= 0) & (hist > 0), (hist.shift() >= 0) & (hist < 0))
    three_b = bull & bull.shift(fill_value=False) & bull.shift(2, fill_value=False)
    three_s = bear & bear.shift(fill_value=False) & bear.shift(2, fill_value=False)
    t["three_same_momentum"] = (three_b, three_s)
    t["three_against_reversal"] = (three_s, three_b)
    return {k: (np.asarray(x, bool), np.asarray(y, bool)) for k, (x, y) in t.items()}


def search_tf(m1: pd.DataFrame, tf: int) -> tuple[pd.DataFrame, dict]:
    d = resample(m1, tf)
    o, h, l, c, spr = (d[k].to_numpy(np.float64) for k in ("open", "high", "low", "close", "spread_px"))
    a = atr(d, 14).to_numpy(np.float64)
    htf = max(200, 200 * 60 // tf)
    warm = min(3 * htf, len(d) // 10)
    cl = d.close
    e50, e200, eh = ema(cl, 50), ema(cl, 200), ema(cl, htf)
    trend_long = [np.ones(len(d), bool), (cl > e50).to_numpy(), (cl > e200).to_numpy(),
                  (e50 > e200).to_numpy(), (cl > eh).to_numpy()]
    trend_short = [np.ones(len(d), bool), (cl < e50).to_numpy(), (cl < e200).to_numpy(),
                   (e50 < e200).to_numpy(), (cl < eh).to_numpy()]
    hr = d.index.hour.to_numpy()
    bucket = np.select([(hr >= 1) & (hr <= 9), (hr >= 10) & (hr <= 14), (hr >= 15) & (hr <= 19)], [0, 1, 2], 3)
    avg = pd.Series(a, index=d.index).rolling(max(20, int(20 * 1380 / tf))).mean().to_numpy()
    volb = (a >= avg).astype(np.int64)
    is_ = np.asarray(d.index < SPLIT)
    weeks_is = (SPLIT - d.index[0]).days / 7
    weeks_oos = (d.index[-1] - SPLIT).days / 7
    maxh = int(5 * 1380 / tf)                      # time stop after ~5 trading days

    R = {(k, s): outcomes(o, h, l, c, spr, a, k, s, maxh) for k in KS for s in (1, -1)}
    # no-skill baseline: a trade after every candle
    base = {k: float(np.nanmean(np.concatenate([R[(k, 1)][warm:], R[(k, -1)][warm:]]) > 0)) for k in KS}

    rows = []
    for name, (sig_l, sig_s) in triggers(d, tf).items():
        # bins[(side, k, trend)] -> array[is(2), bucket(4), vol(2), stat(3)] of n, wins, sumR
        bins = {}
        for side, sig, trends in ((1, sig_l, trend_long), (-1, sig_s, trend_short)):
            idx = np.flatnonzero(sig)
            idx = idx[idx >= warm]
            for k in KS:
                r = R[(k, side)][idx]
                ok = ~np.isnan(r)
                for ti, tmask in enumerate(trends):
                    sel = ok & tmask[idx]
                    ii = idx[sel]
                    rr = r[sel].astype(np.float64)
                    key = (is_[ii] == 0).astype(np.int64) * 8 + bucket[ii] * 2 + volb[ii]
                    n = np.bincount(key, minlength=16)
                    w = np.bincount(key, weights=(rr > 0).astype(float), minlength=16)
                    s = np.bincount(key, weights=rr, minlength=16)
                    bins[(side, k, ti)] = np.stack([n, w, s], -1).reshape(2, 4, 2, 3)
        for ti, (sname, sb), (vname, vb), k, dname in itertools.product(
                range(len(TRENDS)), SESSIONS.items(), VOLS.items(), KS, DIRS):
            sides = (1, -1) if dname == "both" else ((1,) if dname == "buy_only" else (-1,))
            tot = sum(bins[(sd, k, ti)][:, list(sb)][:, :, list(vb)].sum(axis=(1, 2)) for sd in sides)
            (n_i, w_i, s_i), (n_o, w_o, s_o) = tot[0], tot[1]
            rows.append((tf, name, TRENDS[ti], sname, vname, k, dname,
                         int(n_i), w_i, s_i, int(n_o), w_o, s_o))
    df = pd.DataFrame(rows, columns=["tf", "trigger", "trend", "session", "vol", "sl_atr", "direction",
                                     "IS_n", "IS_w", "IS_R", "OOS_n", "OOS_w", "OOS_R"])
    df["IS_per_week"] = df.IS_n / weeks_is
    df["OOS_per_week"] = df.OOS_n / weeks_oos
    return df, base


if __name__ == "__main__":
    t0 = time.time()
    m1 = b.load_data("M1")
    parts, bases = [], {}
    for tf in TFS:
        df, base = search_tf(m1, tf)
        parts.append(df)
        bases[tf] = base
        print(f"M{tf}: {len(df):,} strategies, no-skill win rate at 1:3 "
              + ", ".join(f"SL {k}xATR {v * 100:.1f}%" for k, v in base.items())
              + f"  [{time.time() - t0:.0f}s]", flush=True)
    res = pd.concat(parts, ignore_index=True)
    for p in ("IS", "OOS"):
        res[f"{p}_win%"] = res[f"{p}_w"] / res[f"{p}_n"].clip(lower=1) * 100
        res[f"{p}_R/trade"] = res[f"{p}_R"] / res[f"{p}_n"].clip(lower=1)
    res.drop(columns=["IS_w", "OOS_w"]).round(4).to_csv("results/mass_search.csv.gz", index=False)
    pd.DataFrame(bases).T.mul(100).round(2).rename_axis("tf").to_csv("results/mass_search_baseline.csv")
    print(f"total {len(res):,} strategies in {time.time() - t0:.0f}s")
