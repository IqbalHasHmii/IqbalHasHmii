"""Backtest of the M60 EMA20 pullback (buys and sells), the setup the MT5 EA
mql5/XAUUSD_H1_EMA20_Pullback_EA.mq5 trades.

Rules (H1, every candle, any hour):
  Buy : close > EMA200, the candle's low touches EMA20, it closes above EMA20 and bullish.
  Sell: close < EMA200, the high touches EMA20, it closes below EMA20 and bearish.
  Entry at the next candle's open, SL = 2 x ATR(14), TP = 3 x SL, time stop after 115 candles.
Same execution model as mass_search.py (H1 built from the M1 data, real spread).

    python m60_ema20_pullback.py
"""
import numpy as np
import pandas as pd

import backtest as b
import mass_search as ms
from strategies import atr, ema

m1 = b.load_data("M1")
d = ms.resample(m1, 60)
o, h, l, c, s = (d[k].to_numpy(np.float64) for k in ("open", "high", "low", "close", "spread_px"))
a = atr(d, 14).to_numpy()
e20, e200 = ema(d.close, 20).to_numpy(), ema(d.close, 200).to_numpy()
buy = (l <= e20) & (c > e20) & (c > o) & (c > e200)
sell = (h >= e20) & (c < e20) & (c < o) & (c < e200)
buy[:600] = sell[:600] = False
maxh = 115
rows = []
for side, sig in ((1, buy), (-1, sell)):
    r = ms.outcomes(o, h, l, c, s, a, 2.0, side, maxh)
    for i in np.flatnonzero(sig):
        if np.isnan(r[i]) or i + 1 >= len(d):
            continue
        # exit time: first candle where SL/TP/time stop hit (recomputed for overlap statistics)
        e = o[i + 1] + (s[i + 1] if side == 1 else 0)
        dd = 2 * a[i]
        sl, tp = e - side * dd, e + side * 3 * dd
        j = i + 1
        while j < min(len(d) - 1, i + maxh):
            if side == 1 and (l[j] <= sl or h[j] >= tp):
                break
            if side == -1 and (h[j] + s[j] >= sl or l[j] + s[j] <= tp):
                break
            j += 1
        rows.append((d.index[i + 1], d.index[j], "BUY" if side == 1 else "SELL", float(r[i])))
t = pd.DataFrame(rows, columns=["entry", "exit", "side", "R"]).sort_values("entry").reset_index(drop=True)


def stats(x, label):
    weeks = (x.entry.max() - x.entry.min()).days / 7
    eq = x.sort_values("exit").R.cumsum()
    print(f"{label}: {len(x)} trades, {len(x) / weeks:.1f}/week, win {(x.R > 0).mean() * 100:.1f}%, "
          f"{x.R.mean():+.3f}R/trade, net {x.R.sum():+.1f}R, max drawdown {(eq - eq.cummax()).min():.1f}R")


stats(t, "All signals (overlapping trades)")
for sd in ("BUY", "SELL"):
    stats(t[t.side == sd], f"  {sd}")
stats(t[t.entry < ms.SPLIT], "  2021-11..2024-10")
stats(t[t.entry >= ms.SPLIT], "  2024-11..2026-10")
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
    keep, open_exits = [], []
    for row in t.itertuples():
        open_exits = [x for x in open_exits if x >= row.entry]
        if len(open_exits) < cap:
            keep.append(row.Index)
            open_exits.append(row.exit)
    stats(t.loc[keep], f"Max {cap} open trades")
