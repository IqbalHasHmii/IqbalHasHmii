"""M5 strategy search: the m15_search.py families plus three new ones.

Old families on M5 (limits in units of the average M5 candle range of the last day, 288 candles):
  asia_bo, sweep, pullback (see m15_search.py)
New:
  rsi_pb  : trend + RSI pullback. Trend = close above EMA(2400) on M5 (about the H1 EMA200).
            Uptrend: RSI(14) was below `level` and closes back above it -> buy. Downtrend mirror
            (RSI back below 100 - level -> sell). SL beyond the lowest low / highest high of the
            last 12 candles + 0.3x average range. Hours 09:00-20:55.
  bb_rev  : Bollinger(20, 2) mean reversion in the quiet Asian session (02:00-08:55). The
            previous candle closed outside a band and this one closes back inside -> fade it.
            SL beyond the extreme of the last 5 candles + 0.3x average range.
  ny_orb  : New York opening-range breakout. Range = 16:30-16:55 candles (NY 09:30-10:00 in
            broker time). 17:00-19:55: first close beyond it -> trade, SL at the other side
            (full) or the middle of the range. One trade per side per day.
TP = R x SL for all. Parameters are judged on 2020-11..2024-10 (in-sample) and checked on
2024-11..2026-10 (out-of-sample). Execution: backtest.run (one trade at a time).

    python m5_search.py      # -> results/m5_search.csv
"""
import itertools

import numpy as np
import pandas as pd

import backtest as b
from m15_search import SPLIT, asia_bo, atr96, first_per_day, pullback, stats, sweep
from strategies import ema, rsi

N = 288   # M5 candles per day


def _limits(d, dist, a, min_sl, max_sl):
    d["sl_dist"] = np.where((dist >= min_sl * a) & (dist <= max_sl * a), dist, np.nan)


def rsi_pb(df, rr=2.0, level=30, min_sl=1.0, max_sl=6.0, **_):
    d = df.copy()
    a = atr96(d, N)
    r = rsi(d.close, 14)
    trend = ema(d.close, 2400)
    hr = d.index.hour
    win = (hr >= 9) & (hr <= 20)
    buy = win & (d.close > trend) & (r.shift() < level) & (r >= level)
    sell = win & (d.close < trend) & (r.shift() > 100 - level) & (r <= 100 - level)
    d["signal"] = np.select([buy, sell], [1, -1], 0)
    d.iloc[:2400, d.columns.get_loc("signal")] = 0
    dist = np.where(d.signal == 1, d.close - d.low.rolling(12).min(), d.high.rolling(12).max() - d.close) + 0.3 * a
    _limits(d, dist, a, min_sl, max_sl)
    d["tp_dist"] = d.sl_dist * rr
    return d


def bb_rev(df, rr=1.5, k=2.0, min_sl=1.0, max_sl=5.0, **_):
    d = df.copy()
    a = atr96(d, N)
    mid = d.close.rolling(20).mean()
    sd = d.close.rolling(20).std()
    up, lo = mid + k * sd, mid - k * sd
    hr = d.index.hour
    win = (hr >= 2) & (hr <= 8)
    buy = win & (d.close.shift() < lo.shift()) & (d.close > lo)
    sell = win & (d.close.shift() > up.shift()) & (d.close < up)
    d["signal"] = np.select([buy, sell], [1, -1], 0)
    dist = np.where(d.signal == 1, d.close - d.low.rolling(5).min(), d.high.rolling(5).max() - d.close) + 0.3 * a
    _limits(d, dist, a, min_sl, max_sl)
    d["tp_dist"] = d.sl_dist * rr
    return d


def ny_orb(df, rr=2.0, sl_mode="full", min_range=2.0, max_range=12.0, **_):
    d = df.copy()
    a = atr96(d, N)
    t = d.index.hour * 60 + d.index.minute
    day = d.index.normalize()
    rmask = (t >= 16 * 60 + 30) & (t <= 16 * 60 + 55)
    rng = d[rmask].groupby(day[rmask]).agg(rh=("high", "max"), rl=("low", "min"))
    d = d.join(rng, on=day)
    width = d.rh - d.rl
    ok = (t >= 17 * 60) & (t <= 19 * 60 + 55) & (width >= min_range * a) & (width <= max_range * a)
    up = first_per_day(ok & (d.close > d.rh))
    dn = first_per_day(ok & (d.close < d.rl))
    d["signal"] = np.select([up, dn], [1, -1], 0)
    mid = (d.rh + d.rl) / 2
    stop = np.where(d.signal == 1, d.rl if sl_mode == "full" else mid, d.rh if sl_mode == "full" else mid)
    d["sl_dist"] = (d.close - stop).abs()
    d["tp_dist"] = d.sl_dist * rr
    return d


GRIDS = {
    # old families (multipliers ~1.7x the M15 ones: one M5 candle is ~0.6x an M15 candle)
    "asia_bo": (asia_bo, {"sl_mode": ["mid", "full"], "rr": [1.5, 2.0, 3.0], "max_range": [17.0, 25.0]},
                {"min_range": 3.5, "atr_n": N}),
    "sweep": (sweep, {"rr": [1.5, 2.0, 3.0], "buffer": [0.3, 0.8], "max_sl": [5.0, 8.0]}, {"min_sl": 1.5, "atr_n": N}),
    "pullback": (pullback, {"rr": [1.5, 2.0, 3.0], "buffer": [0.3, 0.8], "max_sl": [7.0, 12.0]}, {"min_sl": 2.5, "atr_n": N}),
    # new
    "rsi_pb": (rsi_pb, {"rr": [1.5, 2.0, 3.0], "level": [30, 25], "max_sl": [6.0, 10.0]}, {}),
    "bb_rev": (bb_rev, {"rr": [1.0, 1.5, 2.0], "k": [2.0, 2.5], "max_sl": [4.0, 7.0]}, {}),
    "ny_orb": (ny_orb, {"rr": [1.5, 2.0, 3.0], "sl_mode": ["full", "mid"], "max_range": [8.0, 15.0]}, {}),
}

if __name__ == "__main__":
    m = b.load_data("M5")
    start, end = m.index[0], m.index[-1]
    rows = []
    for name, (fn, grid, fixed) in GRIDS.items():
        keys = list(grid)
        for vals in itertools.product(*(grid[k] for k in keys)):
            p = dict(zip(keys, vals))
            t, _ = b.run(fn(m, **fixed, **p), 10_000, 1.0, 0.0, False)
            ins, oos = stats(t, start, SPLIT), stats(t, SPLIT, end)
            rows.append({"strategy": name, "params": p,
                         **{f"IS_{k}": v for k, v in ins.items()}, **{f"OOS_{k}": v for k, v in oos.items()}})
    out = pd.DataFrame(rows)
    out.to_csv("results/m5_search.csv", index=False)
    pd.set_option("display.width", 250, "display.max_colwidth", 60, "display.max_rows", 300)
    print(out.to_string(index=False))
