"""Test of the M3 Heikin Ashi strategy from the 5-million-strategy search on any MT5 M3 export.

Strategy (picked in mass5m on 2021-11..2024-10 data):
  BUY when two Heikin Ashi candles in a row are bullish with no lower wick, the close is above
  the "H1 EMA200" (EMA 4000 on M3), the candle's hour is 20:00-00:59 on the backtest clock
  (UTC+2 winter / UTC+3 summer) and ATR(14) is above its ~20-day average (9200 M3 candles).
  Entry at the next candle's open, SL = 2 x ATR(14), TP = 3 x SL, time stop after ~5 days.
  Every signal is its own trade (as in the search); one-at-a-time and capped versions too.

    python m3_ha_test.py --clock utc0 file1.csv [file2.csv ...]   # Exness export (UTC+0 server)
    python m3_ha_test.py --clock backtest file.csv                   # UTC+2/+3 server (FTMO, our data)
    python m3_ha_test.py --ours                                      # our M1 data resampled to M3

Spreads: the CSV <SPREAD> column is in points; the point size is read from the price decimals.
"""
from __future__ import annotations

import argparse

import numba
import numpy as np
import pandas as pd

from strategy_library import atr, ema, ha_open

RR = 3.0
PERIODS = [("2020-01..2021-10  NEW data, never used", "2000-01-01", "2021-11-01"),
           ("2021-11..2023-10  P1 (chosen on)", "2021-11-01", "2023-11-01"),
           ("2023-11..2024-10  P2 (confirmed on)", "2023-11-01", "2024-11-01"),
           ("2024-11..2026-10  P3 (test)", "2024-11-01", "2026-11-01"),
           ("2026-11  newest days", "2026-11-01", "2100-01-01")]


def load_mt5(paths: list[str]) -> pd.DataFrame:
    frames = []
    for p in paths:
        with open(p) as f:
            f.readline()
            first_open = f.readline().split("\t")[2]
        point = 10.0 ** -len(first_open.split(".")[1])
        df = pd.read_csv(p, sep="\t")
        df.columns = [c.strip("<>").lower() for c in df.columns]
        df["time"] = pd.to_datetime(df["date"] + " " + df["time"], format="%Y.%m.%d %H:%M:%S")
        df["spread_px"] = df["spread"] * point
        frames.append(df[["time", "open", "high", "low", "close", "tickvol", "spread_px"]])
    return pd.concat(frames).drop_duplicates("time").sort_values("time").set_index("time")


def utc_to_backtest_clock(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """UTC -> UTC+3 during European summer time, UTC+2 otherwise."""
    def last_sunday_0100(y, m):
        d = pd.Timestamp(year=y, month=m, day=31)
        return d - pd.Timedelta(days=(d.weekday() + 1) % 7) + pd.Timedelta(hours=1)
    s = pd.Series(idx)
    yrs = s.dt.year
    start = yrs.map({y: last_sunday_0100(y, 3) for y in yrs.unique()})
    end = yrs.map({y: last_sunday_0100(y, 10) for y in yrs.unique()})
    off = np.where((s >= start) & (s < end), 3, 2)
    return pd.DatetimeIndex(idx + pd.to_timedelta(off, unit="h"))


@numba.njit(cache=True)
def trade_outcomes(o, h, l, c, spr, dist, idx, maxh):
    """R multiple and exit candle of a buy opened at the next open after each signal candle."""
    n = len(o)
    r = np.full(len(idx), np.nan)
    ex = np.full(len(idx), -1)
    for k in range(len(idx)):
        i = idx[k]
        d = dist[i]
        if not d > 0 or i + 1 >= n:
            continue
        j0 = i + 1
        e = o[j0] + spr[j0]
        sl, tp = e - d, e + RR * d
        last = min(n - 1, i + maxh)
        for j in range(j0, last + 1):
            if l[j] <= sl:
                r[k], ex[k] = (min(sl, o[j]) - e) / d, j
                break
            if h[j] >= tp:
                r[k], ex[k] = (max(tp, o[j]) - e) / d, j
                break
        if ex[k] < 0 and last == i + maxh:
            r[k], ex[k] = (c[last] - e) / d, last
    return r, ex


def run(d: pd.DataFrame, label: str) -> pd.DataFrame:
    o, h, l, c, spr = (d[k].to_numpy(np.float64) for k in ("open", "high", "low", "close", "spread_px"))
    a = atr(d)
    hac = (o + h + l + c) / 4
    hao = ha_open(o, hac)
    hal = np.minimum(l, np.minimum(hao, hac))
    strong = (hac > hao) & (hal >= np.minimum(hao, hac) - 1e-9)
    two = strong & np.r_[False, strong[:-1]]
    trend = (d.close > ema(d.close, 4000)).to_numpy()
    hv = (a >= a.rolling(9200).mean()).to_numpy()
    late = np.isin(d.index.hour, [20, 21, 22, 23, 0])
    sig = two & trend & hv & late
    sig[:min(12000, len(d) // 10)] = False
    idx = np.flatnonzero(sig)
    r, ex = trade_outcomes(o, h, l, c, spr, 2 * a.to_numpy(np.float64), idx, 2300)
    ok = ex >= 0
    t = pd.DataFrame({"entry": d.index[idx[ok] + 1], "exit": d.index[ex[ok]], "R": r[ok]})
    t["tp_hit"] = t.R >= RR - 0.001
    print(f"\n===== {label}: {d.index[0]:%Y-%m-%d} -> {d.index[-1]:%Y-%m-%d} (strategy clock), "
          f"median spread ${d.spread_px.median():.3f} =====")
    rows = []
    for name, s, e in PERIODS:
        x = t[(t.entry >= s) & (t.entry < e)]
        if x.empty:
            continue
        wk = max((min(pd.Timestamp(e), d.index[-1]) - max(pd.Timestamp(s), d.index[0])).days / 7, 1)
        rows.append({"period": name, "trades": len(x), "per week": round(len(x) / wk, 1),
                     "TP hit %": round(x.tp_hit.mean() * 100, 1), "R/trade": round(x.R.mean(), 3),
                     "net R": round(x.R.sum(), 1)})
    print(pd.DataFrame(rows).to_string(index=False))
    y = t.groupby(t.exit.dt.year)
    print("per year:", {k: f"{len(g)} tr, TP {g.tp_hit.mean() * 100:.0f}%, {g.R.sum():+.0f}R" for k, g in y})
    weeks = (t.entry.max() - t.entry.min()).days / 7
    for cap in (0, 1, 3, 5):
        keep, open_exits = [], []
        for row in t.itertuples():
            open_exits = [x for x in open_exits if x > row.entry]
            if cap == 0 or len(open_exits) < cap:
                keep.append(row.Index)
                open_exits.append(row.exit)
        x = t.loc[keep].sort_values("exit")
        eq = x.R.cumsum()
        ev = pd.concat([pd.DataFrame({"t": x.entry, "d": 1}), pd.DataFrame({"t": x.exit, "d": -1})]).sort_values(["t", "d"])
        print(f"  {'every signal' if cap == 0 else f'max {cap} open':12s}: {len(x)} trades ({len(x) / weeks:.1f}/wk), "
              f"TP {x.tp_hit.mean() * 100:.1f}%, {x.R.mean():+.3f}R/trade, net {x.R.sum():+.0f}R, "
              f"max drawdown {(eq - eq.cummax()).min():.1f}R, most open at once {ev.d.cumsum().max()}")
    return t


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--clock", choices=["utc0", "backtest"], default="utc0")
    ap.add_argument("--ours", action="store_true", help="our M1 data resampled to M3 (backtest clock)")
    args = ap.parse_args()
    if args.ours:
        import backtest as b
        from mass_search import resample
        run(resample(b.load_data("M1"), 3), "our data (M1 -> M3, UTC+2/+3 broker)")
    if args.files:
        d = load_mt5(args.files)
        if args.clock == "utc0":
            d.index = utc_to_backtest_clock(d.index)
        run(d, f"{', '.join(f.split('/')[-1] for f in args.files)} ({args.clock} clock)")
