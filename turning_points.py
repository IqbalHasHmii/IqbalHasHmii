"""Where does gold turn? A study of the highs it falls from and the lows it is bought at.

1. Daily highs and lows: in which hour (strategy clock, UTC+2 / UTC+3) does each day's high and
   low form, and how often does the day's high take out the previous day's high?
2. Swing tops and bottoms on H1: a top is the highest high of the 12 candles on each side, after
   which price falls at least 2 x ATR(14) within 24 candles (bottoms mirrored). For conditions
   known when the candle closes, compare how often they occur at tops/bottoms with how often
   they occur at any candle:
     lift      = share at tops / share at all candles  (> 1: tops like this condition)
     hit rate  = share of candles with the condition that are tops
Conditions for a top (bottom mirrored): its high is above the previous day's / week's / Asian
session's high and it closes back below it, a $50 level was traded through and the close is
below it, the close is 3+ ATR above EMA(50), it rose 3+ ATR in the last 6 hours, RSI(14) >= 70,
an upper wick of half the candle or more, tick volume 2x its 24-candle average, 3 higher highs
in a row, and the session.

    python turning_points.py      # -> results/turning_points.txt
"""
from __future__ import annotations

import glob

import numpy as np
import pandas as pd

import backtest as b
import m3_ha_test as m3
from h1_hh_engulf_types import new_highs_ok
from mass_search import resample
from strategy_library import atr, ema, rsi

K = 12            # candles on each side of a swing point
MOVE = 2.0        # ATRs it must travel away within 24 candles


def session(hr):
    return np.select([(hr >= 1) & (hr <= 9), (hr >= 10) & (hr <= 14), (hr >= 15) & (hr <= 19)],
                     ["Asia 01-09", "London 10-14", "New York 15-19"], "Late 20-00")


def features(h1: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    o, h, l, c, v = (h1[k] for k in ("open", "high", "low", "close", "tickvol"))
    a = atr(h1)
    day = h1.index.normalize()
    pdh = h.groupby(day).max().shift(1).reindex(day).to_numpy()
    pdl = l.groupby(day).min().shift(1).reindex(day).to_numpy()
    week = h1.index.to_period("W")
    pwh = h.groupby(week).max().shift(1).reindex(week).to_numpy()
    pwl = l.groupby(week).min().shift(1).reindex(week).to_numpy()
    hr = h1.index.hour
    asia = (hr >= 1) & (hr <= 9)
    ash = h[asia].groupby(day[asia]).max().reindex(day).to_numpy()
    asl = l[asia].groupby(day[asia]).min().reindex(day).to_numpy()
    e50 = ema(c, 50)
    r = rsi(c, 14)
    rng = (h - l).replace(0, np.nan)
    hv, lv, cv, ov = h.to_numpy(), l.to_numpy(), c.to_numpy(), o.to_numpy()
    lvl_up = np.floor(hv / 50) * 50
    lvl_dn = np.ceil(lv / 50) * 50
    vol_spike = (v >= 2 * v.rolling(24).mean()).to_numpy()
    sess = session(hr)
    top = pd.DataFrame(index=h1.index)
    bot = pd.DataFrame(index=h1.index)
    top["swept previous day high, closed below"] = (hv > pdh) & (cv < pdh)
    bot["swept previous day low, closed above"] = (lv < pdl) & (cv > pdl)
    top["above previous day high"] = hv > pdh
    bot["below previous day low"] = lv < pdl
    top["swept previous week high, closed below"] = (hv > pwh) & (cv < pwh)
    bot["swept previous week low, closed above"] = (lv < pwl) & (cv > pwl)
    top["swept Asian high, closed below (10:00+)"] = (hr >= 10) & (hv > ash) & (cv < ash)
    bot["swept Asian low, closed above (10:00+)"] = (hr >= 10) & (lv < asl) & (cv > asl)
    top["traded through $50 level, closed below"] = lvl_up > cv
    bot["traded through $50 level, closed above"] = lvl_dn < cv
    top["close 3+ ATR above EMA50"] = ((c - e50) / a >= 3).to_numpy()
    bot["close 3+ ATR below EMA50"] = ((e50 - c) / a >= 3).to_numpy()
    top["rose 3+ ATR in 6 hours"] = ((c - c.shift(6)) / a >= 3).to_numpy()
    bot["fell 3+ ATR in 6 hours"] = ((c.shift(6) - c) / a >= 3).to_numpy()
    top["RSI >= 70"] = (r >= 70).to_numpy()
    bot["RSI <= 30"] = (r <= 30).to_numpy()
    top["upper wick >= half the candle"] = ((h - np.maximum(o, c)) / rng >= 0.5).to_numpy()
    bot["lower wick >= half the candle"] = ((np.minimum(o, c) - l) / rng >= 0.5).to_numpy()
    top["volume 2x average"] = vol_spike
    bot["volume 2x average"] = vol_spike
    top["3 higher highs in a row"] = new_highs_ok(hv, 3, 3)
    bot["3 lower lows in a row"] = new_highs_ok(-lv, 3, 3)
    for s_ in ("Asia 01-09", "London 10-14", "New York 15-19", "Late 20-00"):
        top[f"session {s_}"] = sess == s_
        bot[f"session {s_}"] = sess == s_
    return top, bot


def swings(h1: pd.DataFrame):
    h, l = h1.high.to_numpy(), h1.low.to_numpy()
    a = atr(h1).to_numpy()
    n = len(h)
    is_top = np.zeros(n, bool)
    is_bot = np.zeros(n, bool)
    for i in range(K, n - K - 1):
        if h[i] == h[i - K:i + K + 1].max() and h[i] - l[i + 1:i + 25].min() >= MOVE * a[i]:
            is_top[i] = True
        if l[i] == l[i - K:i + K + 1].min() and h[i + 1:i + 25].max() - l[i] >= MOVE * a[i]:
            is_bot[i] = True
    return is_top, is_bot


def lift_table(feat: pd.DataFrame, target: np.ndarray, valid: np.ndarray) -> pd.DataFrame:
    rows = []
    base = target[valid].mean()
    for k in feat.columns:
        f = feat[k].to_numpy(bool) & valid
        share_at = (f & target).sum() / max(target[valid].sum(), 1)
        share_all = f.sum() / valid.sum()
        rows.append({"condition": k, "at tops/bottoms": f"{share_at * 100:.0f}%", "at all candles": f"{share_all * 100:.1f}%",
                     "lift": round(share_at / share_all, 2) if share_all > 0 else np.nan,
                     "hit rate": f"{(f & target).sum() / max(f.sum(), 1) * 100:.1f}%", "_lift": share_at / max(share_all, 1e-9)})
    df = pd.DataFrame(rows).sort_values("_lift", ascending=False).drop(columns="_lift")
    print(f"(base rate: {base * 100:.1f}% of candles are a {'top' if 'top' in df.condition.iloc[0] or True else ''} point)")
    return df


def daily_extremes(h1: pd.DataFrame):
    day = h1.index.normalize()
    hi_idx = h1.high.groupby(day).idxmax()
    lo_idx = h1.low.groupby(day).idxmin()
    hi_hr = pd.Series(pd.DatetimeIndex(hi_idx.values).hour).value_counts(normalize=True).sort_index() * 100
    lo_hr = pd.Series(pd.DatetimeIndex(lo_idx.values).hour).value_counts(normalize=True).sort_index() * 100
    t = pd.DataFrame({"day high %": hi_hr.round(1), "day low %": lo_hr.round(1)}).fillna(0)
    t.index.name = "hour"
    dh = h1.high.groupby(day).max()
    dl = h1.low.groupby(day).min()
    took = (dh > dh.shift(1)).mean() * 100
    took_l = (dl < dl.shift(1)).mean() * 100
    return t, took, took_l


def run(label: str, fine: pd.DataFrame):
    h1 = resample(fine, 60)
    print(f"\n===== {label}: {h1.index[0]:%Y-%m-%d} -> {h1.index[-1]:%Y-%m-%d}, {len(h1)} H1 candles =====")
    t, took, took_l = daily_extremes(h1)
    print("Hour (strategy clock; Pakistan time = +3 h in winter, +2 h in summer) in which each day's high / low formed:")
    print(t.T.to_string())
    print(f"days whose high is above the previous day's high: {took:.0f}%, whose low is below the previous day's low: {took_l:.0f}%")
    is_top, is_bot = swings(h1)
    top, bot = features(h1)
    valid = np.zeros(len(h1), bool)
    valid[300:len(h1) - K - 25] = True
    print(f"\nswing tops: {is_top[valid].sum()} ({is_top[valid].sum() / (valid.sum() / 24 / 5.2 * 5):.0f} per year-ish), "
          f"bottoms: {is_bot[valid].sum()}; share of all candles: tops {is_top[valid].mean() * 100:.1f}%, "
          f"bottoms {is_bot[valid].mean() * 100:.1f}%")
    pd.set_option("display.width", 220)
    print("\nWhat is true at the TOPS (the highs price fell from):")
    print(lift_table(top, is_top, valid).to_string(index=False))
    print("\nWhat is true at the BOTTOMS (the lows price was bought from):")
    print(lift_table(bot, is_bot, valid).to_string(index=False))
    # the best two-condition combinations
    for name, feat, tgt in (("TOPS", top, is_top), ("BOTTOMS", bot, is_bot)):
        cols = [k for k in feat.columns if not k.startswith("session")]
        rows = []
        for i, a_ in enumerate(cols):
            for b_ in cols[i + 1:]:
                f = feat[a_].to_numpy(bool) & feat[b_].to_numpy(bool) & valid
                if f.sum() < 100:
                    continue
                rows.append({"conditions": f"{a_} + {b_}", "candles": int(f.sum()),
                             "hit rate": round((f & tgt).sum() / f.sum() * 100, 1)})
        print(f"\nBest pairs of conditions at the {name} (>= 100 candles), hit rate = share that were a {name[:-1].lower()}:")
        print(pd.DataFrame(rows).sort_values("hit rate", ascending=False).head(8).to_string(index=False))


if __name__ == "__main__":
    run("Our data", b.load_data("M1"))
    files = sorted(glob.glob("data/M3_exness/*.csv"))
    if files:
        ex = m3.load_mt5(files)
        ex.index = m3.utc_to_backtest_clock(ex.index)
        run("Exness data", ex)
