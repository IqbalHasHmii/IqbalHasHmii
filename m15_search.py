"""Search for an M15 XAUUSD strategy with >= 40% win rate and 3-5+ trades a week.

Three well-known strategy families, each with a small parameter grid:
  asia_bo  : Asian-range breakout. Range = broker hours 01:00-09:45. The first M15 close beyond
             it between 10:00 and 15:45 -> trade at the next open. SL at the range middle or at
             the other side of the range; TP = R x SL.
  sweep    : Previous-day high/low liquidity sweep. An M15 candle trades above yesterday's high
             but closes back below it -> sell (mirror for the low). SL above the sweep wick
             (+ buffer), TP = R x SL. Hours 09:00-20:45, one trade per side per day.
  pullback : Trend pullback. Trend = M15 EMA200 above EMA800 (about H1 EMA50/200) and close
             above EMA200. A bullish candle whose low touches EMA50 and closes above it -> buy.
             SL below the lowest low of the last 10 candles (+ buffer), TP = R x SL. Mirror for
             sells. Hours 09:00-20:45.

SL / range limits are in units of the average M15 candle range of the last day (atr96), so
they scale with volatility (gold went from ~$1,800 to $4,000+ in the data).

Parameters are picked on 2021-11..2024-10 (in-sample) and then checked on 2024-11..2026-10
(out-of-sample, never used to choose anything). Execution: backtest.run (next-bar-open entry,
real spread, SL first when SL and TP share a candle, one trade at a time).

    python m15_search.py
"""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

import backtest as b
from strategies import ema

SPLIT = pd.Timestamp("2024-11-01")


def first_per_day(mask: pd.Series) -> pd.Series:
    day = mask.index.normalize()
    return mask & (mask.astype(int).groupby(day).cumsum() == 1)


def atr96(d, n=96):
    """Average candle range over the last n candles (M15: 96 = one day) - scales limits with volatility."""
    prev = d.close.shift()
    tr = pd.concat([d.high - d.low, (d.high - prev).abs(), (d.low - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def asia_bo(df, sl_mode="mid", rr=1.5, max_range=10.0, min_range=2.0, atr_n=96, **_):
    """max_range / min_range are in units of the average M15 candle range (atr96)."""
    d = df.copy()
    a = atr96(d, atr_n)
    hr, day = d.index.hour, d.index.normalize()
    asia = (hr >= 1) & (hr <= 9)
    rng = d[asia].groupby(day[asia]).agg(rh=("high", "max"), rl=("low", "min"))
    d = d.join(rng, on=day)
    width = d.rh - d.rl
    ok = (hr >= 10) & (hr <= 15) & (width >= min_range * a) & (width <= max_range * a)
    up = first_per_day(ok & (d.close > d.rh))
    dn = first_per_day(ok & (d.close < d.rl))
    d["signal"] = np.select([up, dn], [1, -1], 0)
    stop = np.where(d.signal == 1, d.rl if sl_mode == "full" else (d.rh + d.rl) / 2,
                    d.rh if sl_mode == "full" else (d.rh + d.rl) / 2)
    d["sl_dist"] = (d.close - stop).abs()
    d["tp_dist"] = d.sl_dist * rr
    return d


def sweep(df, rr=1.5, buffer=0.3, min_sl=1.0, max_sl=4.0, atr_n=96, **_):
    """buffer, min_sl, max_sl in units of the average M15 candle range (atr96)."""
    d = df.copy()
    a = atr96(d, atr_n)
    day = d.index.normalize()
    daily = d.groupby(day).agg(dh=("high", "max"), dl=("low", "min"))
    prev = daily.shift(1).rename(columns={"dh": "pdh", "dl": "pdl"})
    d = d.join(prev, on=day)
    hr = d.index.hour
    win = (hr >= 9) & (hr <= 20)
    sell = first_per_day(win & (d.high > d.pdh) & (d.close < d.pdh))
    buy = first_per_day(win & (d.low < d.pdl) & (d.close > d.pdl))
    d["signal"] = np.select([buy, sell], [1, -1], 0)
    dist = np.where(d.signal == 1, d.close - d.low, d.high - d.close) + buffer * a
    d["sl_dist"] = np.where((dist >= min_sl * a) & (dist <= max_sl * a), dist, np.nan)
    d["tp_dist"] = d.sl_dist * rr
    return d


def pullback(df, rr=1.5, buffer=0.3, min_sl=1.5, max_sl=5.0, atr_n=96, **_):
    """buffer, min_sl, max_sl in units of the average M15 candle range (atr96)."""
    d = df.copy()
    a = atr96(d, atr_n)
    e50, e200, e800 = ema(d.close, 50), ema(d.close, 200), ema(d.close, 800)
    hr = d.index.hour
    win = (hr >= 9) & (hr <= 20)
    bull = (e200 > e800) & (d.close > e200)
    bear = (e200 < e800) & (d.close < e200)
    buy = win & bull & (d.low <= e50) & (d.close > e50) & (d.close > d.open)
    sell = win & bear & (d.high >= e50) & (d.close < e50) & (d.close < d.open)
    d["signal"] = np.select([buy, sell], [1, -1], 0)
    d.iloc[:800, d.columns.get_loc("signal")] = 0
    lo10, hi10 = d.low.rolling(10).min(), d.high.rolling(10).max()
    dist = np.where(d.signal == 1, d.close - lo10, hi10 - d.close) + buffer * a
    d["sl_dist"] = np.where((dist >= min_sl * a) & (dist <= max_sl * a), dist, np.nan)
    d["tp_dist"] = d.sl_dist * rr
    return d


GRIDS = {
    "asia_bo": (asia_bo, {"sl_mode": ["mid", "full"], "rr": [1.0, 1.5, 2.0], "max_range": [6.0, 10.0, 15.0]}),
    "sweep": (sweep, {"rr": [1.0, 1.5, 2.0], "buffer": [0.2, 0.5], "max_sl": [3.0, 5.0]}),
    "pullback": (pullback, {"rr": [1.0, 1.5, 2.0], "buffer": [0.2, 0.5], "max_sl": [4.0, 7.0]}),
}


def stats(t: pd.DataFrame, start, end) -> dict:
    t = t[(pd.to_datetime(t.entry_time) >= start) & (pd.to_datetime(t.entry_time) < end)]
    weeks = (end - start).days / 7
    if t.empty:
        return {"trades": 0}
    yearly = t.groupby(pd.to_datetime(t.exit_time).dt.year).r_multiple.sum()
    return {"trades": len(t), "per_week": round(len(t) / weeks, 1),
            "win%": round((t.r_multiple > 0).mean() * 100, 1),
            "R/trade": round(t.r_multiple.mean(), 3), "net_R": round(t.r_multiple.sum(), 1),
            "losing_yrs": f"{(yearly < 0).sum()}/{len(yearly)}"}


if __name__ == "__main__":
    m = b.load_data("M15")
    start, end = m.index[0], m.index[-1]
    rows = []
    for name, (fn, grid) in GRIDS.items():
        keys = list(grid)
        for vals in itertools.product(*(grid[k] for k in keys)):
            p = dict(zip(keys, vals))
            t, _ = b.run(fn(m, **p), 10_000, 1.0, 0.0, False)
            ins, oos = stats(t, start, SPLIT), stats(t, SPLIT, end)
            rows.append({"strategy": name, "params": p,
                         **{f"IS_{k}": v for k, v in ins.items()}, **{f"OOS_{k}": v for k, v in oos.items()}})
    out = pd.DataFrame(rows)
    pd.set_option("display.width", 250, "display.max_colwidth", 60, "display.max_rows", 200)
    print(out.to_string(index=False))
    out.to_csv("results/m15_search.csv", index=False)


def run_every(df: pd.DataFrame) -> pd.DataFrame:
    """Every signal trades on its own (overlapping trades allowed): market entry at the next
    candle's open, SL / TP fixed from the fill, SL first when both are inside one candle."""
    o, h, l = (df[k].to_numpy() for k in ("open", "high", "low"))
    spr, t = df.spread_px.to_numpy(), df.index
    sig, sd, td = df.signal.to_numpy(), df.sl_dist.to_numpy(), df.tp_dist.to_numpy()
    out = []
    for k in np.flatnonzero(sig != 0):
        if not np.isfinite(sd[k]) or sd[k] <= 0 or k + 1 >= len(df):
            continue
        d, i = int(sig[k]), k + 1
        e = o[i] + spr[i] if d == 1 else o[i]
        sl, tp = e - d * sd[k], e + d * td[k]
        for j in range(i, len(df)):
            if d == 1:
                if l[j] <= sl:
                    r = (min(sl, o[j]) if j > i else sl) - e; break
                if h[j] >= tp:
                    r = max(tp, o[j]) - e; break
            else:
                if h[j] + spr[j] >= sl:
                    r = e - (max(sl, o[j] + spr[j]) if j > i else sl); break
                if l[j] + spr[j] <= tp:
                    r = e - min(tp, o[j] + spr[j]); break
        else:
            continue                                  # still open at the end of the data
        out.append((t[i], t[j], "BUY" if d == 1 else "SELL", r / sd[k]))
    return pd.DataFrame(out, columns=["entry_time", "exit_time", "direction", "r_multiple"])
