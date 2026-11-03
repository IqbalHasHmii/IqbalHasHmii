"""Backtest of the M60 EMA20 pullback (buys and sells), the setup the MT5 EA
mql5/XAUUSD_H1_EMA20_Pullback_EA.mq5 trades.

Rules (H1, every candle, any hour):
  Buy : close > EMA200, the candle's low touches EMA20, it closes above EMA20 and bullish.
  Sell: close < EMA200, the high touches EMA20, it closes below EMA20 and bearish.
  Entry at the next candle's open, SL = 2 x ATR(14), TP = 3 x SL, time stop after 115 candles.
Same execution model as mass_search.py (H1 built from the finer candles, real spread).
"win" = the trade closed in profit (TP or a time stop above the entry), "TP hit" = the TP was reached.

Runs on our data (H1 from M1) and, if data/M3_exness/ exists, on the Exness export (H1 from M3,
2020-01..2026-11, UTC+0 server; the hours do not matter here because every hour is traded).

    python m60_ema20_pullback.py
"""
import glob

import numpy as np
import pandas as pd

import backtest as b
import m3_ha_test as m3
import mass_search as ms
from h1_hh_engulf import PERIODS
from strategies import atr, ema

MAXH = 115


def trades(fine: pd.DataFrame) -> pd.DataFrame:
    d = ms.resample(fine, 60)
    o, h, l, c, s = (d[k].to_numpy(np.float64) for k in ("open", "high", "low", "close", "spread_px"))
    a = atr(d, 14).to_numpy()
    e20, e200 = ema(d.close, 20).to_numpy(), ema(d.close, 200).to_numpy()
    buy = (l <= e20) & (c > e20) & (c > o) & (c > e200)
    sell = (h >= e20) & (c < e20) & (c < o) & (c < e200)
    buy[:600] = sell[:600] = False
    rows = []
    for side, sig in ((1, buy), (-1, sell)):
        r = ms.outcomes(o, h, l, c, s, a, 2.0, side, MAXH)
        for i in np.flatnonzero(sig):
            if np.isnan(r[i]) or i + 1 >= len(d):
                continue
            # exit time: first candle where SL/TP/time stop hit (recomputed for overlap statistics)
            e = o[i + 1] + (s[i + 1] if side == 1 else 0)
            dd = 2 * a[i]
            sl, tp = e - side * dd, e + side * 3 * dd
            j = i + 1
            while j < min(len(d) - 1, i + MAXH):
                if side == 1 and (l[j] <= sl or h[j] >= tp):
                    break
                if side == -1 and (h[j] + s[j] >= sl or l[j] + s[j] <= tp):
                    break
                j += 1
            rows.append((d.index[i + 1], d.index[j], "BUY" if side == 1 else "SELL", float(r[i]), dd))
    return (pd.DataFrame(rows, columns=["entry", "exit", "side", "R", "sl"])   # sl = SL distance in $
            .sort_values("entry").reset_index(drop=True))


def stats(x, label):
    weeks = (x.entry.max() - x.entry.min()).days / 7
    eq = x.sort_values("exit").R.cumsum()
    print(f"{label}: {len(x)} trades, {len(x) / weeks:.1f}/week, win {(x.R > 0).mean() * 100:.1f}%, "
          f"TP hit {(x.R >= ms.RR - 0.001).mean() * 100:.1f}%, "
          f"{x.R.mean():+.3f}R/trade, net {x.R.sum():+.1f}R, max drawdown {(eq - eq.cummax()).min():.1f}R")


def capped(t, cap):
    keep, open_exits = [], []
    for row in t.itertuples():
        open_exits = [x for x in open_exits if x >= row.entry]
        if len(open_exits) < cap:
            keep.append(row.Index)
            open_exits.append(row.exit)
    return t.loc[keep]


def run(fine: pd.DataFrame, label: str):
    t = trades(fine)
    print(f"\n===== {label} =====")
    stats(t, "All signals (overlapping trades)")
    for sd in ("BUY", "SELL"):
        stats(t[t.side == sd], f"  {sd}")
    for plab, s_, e_ in PERIODS:
        y = t[(t.entry >= s_) & (t.entry < e_)]
        if len(y):
            stats(y, f"  {plab}")
    ev = pd.concat([pd.DataFrame({"t": t.entry, "d": 1}), pd.DataFrame({"t": t.exit, "d": -1})]).sort_values(["t", "d"])
    print(f"  most trades open at once: {ev.d.cumsum().max()}")
    print("  yearly R:", t.groupby(t.exit.dt.year).R.sum().round(1).to_dict())
    # one trade at a time
    keep, busy = [], pd.Timestamp.min
    for row in t.itertuples():
        if row.entry > busy:
            keep.append(row.Index)
            busy = row.exit
    stats(t.loc[keep], "One trade at a time")
    for cap in (3, 5):
        x = capped(t, cap)
        stats(x, f"Max {cap} open trades")
        print(f"  yearly R:", x.groupby(x.exit.dt.year).R.sum().round(1).to_dict())
    x = capped(t[t.side == "BUY"].reset_index(drop=True), 5)
    stats(x, "Buys only, max 5 open")
    print(f"  yearly R:", x.groupby(x.exit.dt.year).R.sum().round(1).to_dict())


if __name__ == "__main__":
    run(b.load_data("M1"), "Our data: H1 from M1, 2021-11..2026-10")
    files = sorted(glob.glob("data/M3_exness/*.csv"))
    if files:
        run(m3.load_mt5(files), "Exness: H1 from M3, 2020-01..2026-11")
