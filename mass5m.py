"""5-million-strategy search on XAUUSD, 1 to 5 minute candles, every trade 1:3.

    pip install numba
    python mass5m.py            # ~15-30 minutes -> results/mass5m/tf{N}.npz (local, not committed)
    python mass5m_analyze.py    # summaries -> results/mass5m_*.csv / .txt

A strategy = timeframe (1-5 min) x entry rule (83, strategy_library.py) x trend filter (6) x
SL type (5) x direction (3) x session (8) x volatility (3) x ADX (3) x days (2):
  trend     : none, close > EMA50, close > EMA200, EMA50 > EMA200, close > "H1 EMA200"
              (EMA of 200 x 60 / tf candles), Supertrend(10, 3) up  (mirrored for sells)
  SL        : 0.5 / 1 / 1.5 / 2 x ATR(14), or beyond the 5-candle swing low/high + 0.1 ATR
              (at least 0.5 ATR, skipped above 4 ATR);  TP = 3 x SL always
  direction : buys and sells, buys only, sells only
  session   : all, Asia 01-09, early Asia 01-04, late Asia 05-09, London 10-14, New York 15-19,
              London + New York 10-19, late 20-00  (backtest clock, UTC+2 / UTC+3)
  volatility: all, ATR(14) above its ~20-day average, below it
  ADX(14)   : all, above 25 (trending), below 20 (ranging)
  days      : all, Tuesday-Thursday only
Every signal is its own trade: market entry at the next candle's open (buys pay the spread),
exits on bid / ask with the candle's spread, SL first when SL and TP share a candle, time stop
after ~5 trading days. Win rate = share of trades that hit the 1:3 take-profit; R/trade includes
the trades closed by the time stop.

The data is split in three periods and every number is kept per period:
  P1 2021-11 .. 2023-10 (choose), P2 2023-11 .. 2024-10 (confirm), P3 2024-11 .. 2026-10 (test).
"""
from __future__ import annotations

import os
import time

import numba
import numpy as np
import pandas as pd

import backtest as b
from mass_search import resample
from strategy_library import adx_di, atr, ema, library, supertrend_dir

TFS = [1, 2, 3, 4, 5]
EDGES = [pd.Timestamp("2023-11-01"), pd.Timestamp("2024-11-01")]
RR = 3.0
TP_HIT = RR - 0.001          # a "win" = the take-profit was hit (a trade closed by the time stop is not a win)
SLS = ["0.5xATR", "1xATR", "1.5xATR", "2xATR", "swing5"]
TRENDS = ["none", "c>ema50", "c>ema200", "ema50>ema200", "c>H1ema200", "supertrend_up"]
# base buckets -> options (unions)
SESS_BUCKETS = 6   # 0: 00h, 1: 01-04, 2: 05-09, 3: 10-14, 4: 15-19, 5: 20-23
SESSIONS = {"all": [0, 1, 2, 3, 4, 5], "asia": [1, 2], "asia_early": [1], "asia_late": [2], "london": [3],
            "ny": [4], "london+ny": [3, 4], "late": [5, 0]}
VOLS = {"all": [0, 1], "high_vol": [1], "low_vol": [0]}
ADXS = {"all": [0, 1, 2], "trending": [2], "ranging": [0]}
DOWS = {"all": [0, 1, 2], "tue-thu": [1]}
OUT = "results/mass5m"


def member(opts: dict, nb: int) -> np.ndarray:
    m = np.zeros((len(opts), nb))
    for i, bs in enumerate(opts.values()):
        m[i, bs] = 1
    return m


M_SESS, M_VOL, M_ADX, M_DOW = member(SESSIONS, 6), member(VOLS, 2), member(ADXS, 3), member(DOWS, 3)


@numba.njit(cache=True)
def outcomes(o, h, l, c, spr, dist, side, maxh):
    """R multiple of a trade opened at the next candle's open after every candle (TP = 3 x SL)."""
    n = len(o)
    out = np.full(n, np.nan, dtype=np.float32)
    for i in range(n - 1):
        d = dist[i]
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
        if np.isnan(r) and last == i + maxh:
            px = c[last] if side == 1 else c[last] + spr[last]
            r = side * (px - e) / d
        out[i] = r
    return out


def run_tf(m1: pd.DataFrame, tf: int) -> None:
    t0 = time.time()
    d = resample(m1, tf)
    n = len(d)
    o, h, l, c, spr = (d[k].to_numpy(np.float64) for k in ("open", "high", "low", "close", "spread_px"))
    a_s = atr(d)
    a = a_s.to_numpy(np.float64)

    # filters known at the close of every candle
    cl = d.close
    htf = max(200, 200 * 60 // tf)
    e50, e200, eh = ema(cl, 50), ema(cl, 200), ema(cl, htf)
    st = supertrend_dir(h, l, c, a, 3.0)
    tl = [np.ones(n, bool), (cl > e50).to_numpy(), (cl > e200).to_numpy(), (e50 > e200).to_numpy(),
          (cl > eh).to_numpy(), st == 1]
    ts = [np.ones(n, bool), (cl < e50).to_numpy(), (cl < e200).to_numpy(), (e50 < e200).to_numpy(),
          (cl < eh).to_numpy(), st == -1]
    hr = d.index.hour.to_numpy()
    sess = np.select([hr == 0, hr <= 4, hr <= 9, hr <= 14, hr <= 19], [0, 1, 2, 3, 4], 5)
    avg = a_s.rolling(max(20, int(20 * 1380 / tf))).mean().to_numpy()
    vol = (a >= avg).astype(np.int64)
    adx = adx_di(d)[0].to_numpy()
    adxb = np.select([adx < 20, adx <= 25], [0, 1], 2)
    wd = d.index.weekday.to_numpy()
    dow = np.select([(wd == 0) | (wd >= 5), wd <= 3], [0, 1], 2)
    per = np.searchsorted(np.array(EDGES, dtype="datetime64[ns]"), d.index.to_numpy(), side="right")
    key = ((((per * 6 + sess) * 2 + vol) * 3 + adxb) * 3 + dow).astype(np.int64)
    warm = min(3 * htf, n // 10)

    # outcome of a 1:3 trade after every candle, per SL type and side
    low5 = d.low.rolling(5).min().to_numpy()
    high5 = d.high.rolling(5).max().to_numpy()
    maxh = int(5 * 1380 / tf)
    R, base = {}, {}
    for si, sl in enumerate(SLS):
        for side in (1, -1):
            if sl == "swing5":
                dist = (c - low5 + 0.1 * a) if side == 1 else (high5 - c + 0.1 * a)
                dist = np.maximum(dist, 0.5 * a)
                dist = np.where(dist <= 4 * a, dist, np.nan)
            else:
                dist = float(sl.split("x")[0]) * a
            R[(si, side)] = outcomes(o, h, l, c, spr, dist, side, maxh)
        both = np.concatenate([R[(si, 1)][warm:], R[(si, -1)][warm:]])
        both = both[np.isfinite(both)]
        base[sl] = float(np.mean(both >= TP_HIT)) if both.size else np.nan
    t1 = time.time()

    trig = library(d)
    names = list(trig)
    t2 = time.time()
    # A[trigger, trend, sl, side, period, sess, vol, adx, dow, stat(n, wins, sumR)]
    A = np.zeros((len(names), len(TRENDS), len(SLS), 2, 3, len(SESSIONS), len(VOLS), len(ADXS), len(DOWS), 3),
                 np.float32)
    for ti, name in enumerate(names):
        for sdi, (sig, masks, side) in enumerate(((trig[name][0], tl, 1), (trig[name][1], ts, -1))):
            idx = np.flatnonzero(sig)
            idx = idx[idx >= warm]
            if idx.size == 0:
                continue
            kk = key[idx]
            for si in range(len(SLS)):
                r = R[(si, side)][idx]
                ok = ~np.isnan(r)
                for tri, tm in enumerate(masks):
                    sel = ok & tm[idx]
                    k2, rr = kk[sel], r[sel].astype(np.float64)
                    bins = np.stack([np.bincount(k2, minlength=324),
                                     np.bincount(k2, weights=(rr >= TP_HIT).astype(np.float64), minlength=324),
                                     np.bincount(k2, weights=rr, minlength=324)], -1).reshape(3, 6, 2, 3, 3, 3)
                    A[ti, tri, si, sdi] = np.einsum("psvadk,Ss,Vv,Aa,Dd->pSVADk", bins, M_SESS, M_VOL, M_ADX, M_DOW)
    os.makedirs(OUT, exist_ok=True)
    np.savez_compressed(f"{OUT}/tf{tf}.npz", A=A, names=np.array(names), base=np.array([base[s] for s in SLS]),
                        start=str(d.index[0]), end=str(d.index[-1]))
    per_tf = len(names) * len(TRENDS) * len(SLS) * 3 * len(SESSIONS) * len(VOLS) * len(ADXS) * len(DOWS)
    print(f"M{tf}: {n:,} candles, {len(names)} rules, {per_tf:,} strategies | no-skill win at 1:3: "
          + ", ".join(f"{s} {base[s] * 100:.1f}%" for s in SLS)
          + f" | outcomes {t1 - t0:.0f}s, rules {t2 - t1:.0f}s, total {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    import sys
    tfs = [int(x) for x in sys.argv[1].split(",")] if len(sys.argv) > 1 else TFS
    m1 = b.load_data("M1")
    for tf in tfs:
        run_tf(m1, tf)
