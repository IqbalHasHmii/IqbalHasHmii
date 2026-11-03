"""Liquidity-sweep reversal, built from what turning_points.py found at gold's tops and bottoms.

Tops form most often where a candle takes out a known high (the Asian-session high after 10:00,
the previous day's or week's high) and closes back below it, on a volume spike, in the New York
session; bottoms mirror that. So:

  SELL when a candle's high is above such a level and it closes back below it (BUY mirrored),
       the first time each level is swept that day.
  Entry at the next candle's open, SL at the sweep candle's extreme (+ an optional buffer),
  TP 1:3, time stop after 100 candles; checked on the signal timeframe with the real spread, SL
  first when both are hit in one candle (candles_scan.simulate).

Confirmed entry (the SMC way): after the sweep candle, wait up to W candles for a close beyond the
sweep candle's other end (below its low for a sell); enter at the next open with the SL at the
sweep extreme; cancelled if price makes a new extreme first.

Variants: entry immediate / confirmed (W = 4 or 8); signal timeframe M15 / H1; levels (Asian + previous day, + previous week); tick volume
filter (none, 1.5x or 2x the average of the previous day of candles); hours (any, 10:00-19:59
London + New York, 15:00-19:59 New York); SL buffer 0 / 0.25 ATR. Discovery 2021-11..2024-10,
check 2024-11..2026-10 (our data) and every period of the Exness data.

    python sweep_reversal.py      # -> results/sweep_reversal.txt, results/sweep_reversal.csv
"""
from __future__ import annotations

import glob
import itertools

import numpy as np
import pandas as pd

import backtest as b
import m3_ha_test as m3
from candles_scan import simulate
from h1_hh_engulf import PERIODS
from mass_search import resample
from strategy_library import atr

RR = 3.0
SPLIT = pd.Timestamp("2024-11-01")


def levels(d: pd.DataFrame) -> dict:
    h, l = d.high, d.low
    day = d.index.normalize()
    hr = d.index.hour
    asia = (hr >= 1) & (hr <= 9)
    week = d.index.to_period("W")
    lv = {
        "Asian": (h[asia].groupby(day[asia]).max().reindex(day).to_numpy(),
                  l[asia].groupby(day[asia]).min().reindex(day).to_numpy(), hr >= 10),
        "prev day": (h.groupby(day).max().shift(1).reindex(day).to_numpy(),
                     l.groupby(day).min().shift(1).reindex(day).to_numpy(), np.ones(len(d), bool)),
        "prev week": (h.groupby(week).max().shift(1).reindex(week).to_numpy(),
                      l.groupby(week).min().shift(1).reindex(week).to_numpy(), np.ones(len(d), bool)),
    }
    return lv


def first_per_day(mask: np.ndarray, day: pd.DatetimeIndex) -> np.ndarray:
    s = pd.Series(mask.astype(int), index=day)
    return mask & (s.groupby(level=0).cumsum().to_numpy() == 1)


def signals(d: pd.DataFrame, level_set, vol_x, hours):
    o, h, l, c, v = (d[k].to_numpy(np.float64) for k in ("open", "high", "low", "close", "tickvol"))
    n_day = int(round(1440 / ((d.index[1] - d.index[0]).total_seconds() / 60)))
    vavg = pd.Series(v).shift(1).rolling(n_day).mean().to_numpy()
    vol_ok = np.ones(len(d), bool) if vol_x == 0 else v >= vol_x * vavg
    hr = d.index.hour
    hr_ok = {"any": np.ones(len(d), bool), "10-19 London+NY": (hr >= 10) & (hr <= 19),
             "15-19 New York": (hr >= 15) & (hr <= 19)}[hours]
    day = d.index.normalize()
    lv = levels(d)
    sell = np.zeros(len(d), bool)
    buy = np.zeros(len(d), bool)
    for name in level_set:
        hi, lo, when = lv[name]
        s_ = when & (h > hi) & (c < hi)
        b_ = when & (l < lo) & (c > lo)
        sell |= first_per_day(s_, day)
        buy |= first_per_day(b_, day)
    return buy & vol_ok & hr_ok, sell & vol_ok & hr_ok


def confirm(h, l, c, idx, side, w):
    """For each sweep candle: the candle that confirms it (close beyond its other end within w
    candles, before a new extreme) and the SL (the sweep extreme); -1 = not confirmed."""
    out_j = np.full(len(idx), -1)
    out_sl = np.full(len(idx), np.nan)
    n = len(c)
    for k, i in enumerate(idx):
        for j in range(i + 1, min(n - 1, i + w + 1)):
            if side == -1:
                if h[j] > h[i]:
                    break
                if c[j] < l[i]:
                    out_j[k], out_sl[k] = j, h[i]
                    break
            else:
                if l[j] < l[i]:
                    break
                if c[j] > h[i]:
                    out_j[k], out_sl[k] = j, l[i]
                    break
    return out_j, out_sl


def run(d: pd.DataFrame, tf: str, data: str) -> list:
    o, h, l, c, s = (d[k].to_numpy(np.float64) for k in ("open", "high", "low", "close", "spread_px"))
    a = atr(d).to_numpy(np.float64)
    t = d.index
    days = len(np.unique(t.normalize()))
    rows = []
    for entry, lset, vol_x, hours, buf in itertools.product(("immediate", "confirmed W4", "confirmed W8"),
                                                            (("Asian", "prev day"), ("Asian", "prev day", "prev week")),
                                                            (0, 1.5, 2.0), ("any", "10-19 London+NY", "15-19 New York"),
                                                            (0.0, 0.25)):
        mb, ms = signals(d, lset, vol_x, hours)
        res = []
        for side, m in ((1, mb), (-1, ms)):
            m = m.copy()
            m[:300] = False
            idx = np.flatnonzero(m[:-1])
            if entry == "immediate":
                slv = (l[idx] - buf * a[idx]) if side == 1 else (h[idx] + buf * a[idx])
            else:
                j, sl0 = confirm(h, l, c, idx, side, 4 if entry.endswith("W4") else 8)
                keep = j >= 0
                idx, sl0, sw = j[keep], sl0[keep], idx[keep]
                slv = (sl0 - buf * a[sw]) if side == 1 else (sl0 + buf * a[sw])
            r = simulate(o, h, l, c, s, a, idx, side, slv, RR, 100)
            ok = ~np.isnan(r)
            res.append(pd.DataFrame({"time": t[idx[ok]], "R": r[ok], "side": side}))
        x = pd.concat(res)
        if len(x) < 50:
            continue
        win = x.R >= RR - 1e-9
        disc = x.time < SPLIT
        row = {"data": data, "entry": entry, "tf": tf, "levels": "+".join(lset), "volume": f"{vol_x:g}x" if vol_x else "any",
               "hours": hours, "SL buffer": f"{buf:g} ATR", "trades": len(x), "per day": round(len(x) / days, 2),
               "TP %": round(win.mean() * 100, 1), "R/trade": round(float(x.R.mean()), 3),
               "buy TP %": round(win[x.side == 1].mean() * 100, 1), "sell TP %": round(win[x.side == -1].mean() * 100, 1),
               "disc R/t": round(float(x.R[disc].mean()), 3) if disc.any() else np.nan,
               "check R/t": round(float(x.R[~disc].mean()), 3) if (~disc).any() else np.nan}
        for plab, s_, e_ in PERIODS:
            m_ = (x.time >= s_) & (x.time < e_)
            if m_.any() and data == "exness":
                row[plab.split()[0]] = round(float(x.R[m_].mean()), 2)
        rows.append(row)
    return rows


def main():
    rows = []
    m1 = b.load_data("M1")
    for tf, mins in (("M15", 15), ("H1", 60)):
        rows += run(resample(m1, mins), tf, "ours")
    files = sorted(glob.glob("data/M3_exness/*.csv"))
    if files:
        ex = m3.load_mt5(files)
        ex.index = m3.utc_to_backtest_clock(ex.index)
        for tf, mins in (("M15", 15), ("H1", 60)):
            rows += run(resample(ex, mins), tf, "exness")
    df = pd.DataFrame(rows)
    df.to_csv("results/sweep_reversal.csv", index=False)
    pd.set_option("display.width", 250, "display.max_rows", 200)
    key = ["entry", "tf", "levels", "volume", "hours", "SL buffer"]
    ours = df[df.data == "ours"].set_index(key)
    exn = df[df.data == "exness"].set_index(key)
    both = ours.join(exn, rsuffix=" ex", how="left")
    cols = ["trades", "per day", "TP %", "R/trade", "disc R/t", "check R/t", "buy TP %", "sell TP %", "TP % ex", "R/trade ex",
            "per day ex"] + [c for c in both.columns if c.startswith("20") and c.endswith(" ex")]
    print("Best 40 variants by TP %, our data with the Exness result next to it:")
    print(both.sort_values("TP %", ascending=False)[cols].head(40).to_string())
    print("\nBy entry type (median over the variants): TP %, R/trade, trades a day")
    print(both.groupby(level="entry")[["TP %", "R/trade", "per day", "TP % ex", "R/trade ex"]].median().to_string())
    good = both[(both["per day"] >= 1.0) & (both["disc R/t"] > 0) & (both["check R/t"] > 0) & (both["R/trade ex"] > 0)]
    print("\nAt least 1 trade a day and profitable in both halves of our data and on Exness:")
    print(good.sort_values("TP %", ascending=False)[cols].to_string() if len(good) else "none")
    good2 = both[(both["disc R/t"] > 0) & (both["check R/t"] > 0) & (both["R/trade ex"] > 0)]
    print("\nAny number of trades, profitable in both halves of our data and on Exness:")
    print(good2.sort_values("R/trade", ascending=False)[cols].head(15).to_string() if len(good2) else "none")


if __name__ == "__main__":
    main()
