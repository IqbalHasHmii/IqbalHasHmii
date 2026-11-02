"""Engulfing strategy v3 (H1): 200 EMA trend instead of SMC structure + volume filter.

Rules
-----
1. Trend: H1 close above EMA(200) -> buys only, close below EMA(200) -> sells only.
2. Setup: body engulfing in the trend direction AND the engulfing candle's tick volume is
   LOWER than the previous candle's tick volume.
3. Entry: limit order at the engulfing OPEN, valid for the next 5 H1 candles; cancelled if
   the close crosses to the other side of the EMA before it fills.
4. SL / TP (several versions are compared):
     wick + H1 close : SL level at the engulfing wick, closed in loss only on an H1 close
                       beyond it (the v2 rule)
     wick + hard SL  : SL at the engulfing wick as a normal stop
     fixed N pips    : SL N pips from entry as a normal stop
   TP = 3 x SL distance.

Two ways of taking the setups:
  every       : every engulfing gets its own order and trade (trades can overlap)
  one-at-time : one order/trade at a time; setups while a trade is open are ignored and a new
                setup replaces an unfilled order (same as smc_v2.py)

Fill/exit modelling is the same as smc_v2.py (bid prices + real spread, no TP on the fill
candle, loss counted when TP and SL happen in the same candle). P/L in $ is for 0.10 lot.

    python ema_v3.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest import load_data
from smc_v2 import LOT_USD_PER_PRICE, PIP, simulate, summary
from strategies import ema


def setups(h1: pd.DataFrame, side: str = "both", sl_mode: str = "wick", fixed_pips: float = 50,
           volume_filter: bool = True, ema_len: int = 200) -> pd.DataFrame:
    df = h1.copy()
    e = ema(df.close, ema_len)
    df["trend"] = np.where(df.close > e, 1, np.where(df.close < e, -1, 0))
    df.iloc[:ema_len, df.columns.get_loc("trend")] = 0           # EMA warm-up
    po, pc = df.open.shift(), df.close.shift()
    vol_ok = df.tickvol < df.tickvol.shift() if volume_filter else True
    bull = (pc < po) & (df.close > df.open) & (df.close >= po) & (df.open <= pc) & vol_ok
    bear = (pc > po) & (df.close < df.open) & (df.close <= po) & (df.open >= pc) & vol_ok
    sig = np.select([bull & (df.trend == 1) & (side != "sell"),
                     bear & (df.trend == -1) & (side != "buy")], [1, -1], 0)
    if sl_mode == "wick":
        dist = np.where(sig == 1, df.open - df.low, df.high - df.open)
    else:
        dist = np.full(len(df), fixed_pips * PIP)
    df["sl_dist"] = dist
    df["sl_level"] = np.where(sig == 1, df.open - dist, df.open + dist)
    df["signal"] = np.where(dist > 0, sig, 0)      # no wick on the entry side -> no stop
    return df


def simulate_every(df: pd.DataFrame, valid: int = 5, rr: float = 3.0, hard_sl: bool = False) -> pd.DataFrame:
    """Every setup trades on its own (overlapping trades allowed)."""
    t_idx = df.index
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    spr = df.spread_px.to_numpy()
    trend = df.trend.to_numpy()
    n = len(df)
    trades, orders = [], 0
    for k in np.flatnonzero(df.signal.to_numpy() != 0):
        orders += 1
        d, p = int(df.signal.iat[k]), o[k]
        sl, dist = df.sl_level.iat[k], df.sl_dist.iat[k]
        tp = p + d * rr * dist
        # wait for the fill
        fill_i = entry = None
        for j in range(k + 1, min(k + valid, n - 1) + 1):
            if d == -1:
                if o[j] >= p:
                    fill_i, entry, fresh = j, o[j], False
                elif h[j] >= p:
                    fill_i, entry, fresh = j, p, True
            else:
                if o[j] + spr[j] <= p:
                    fill_i, entry, fresh = j, o[j] + spr[j], False
                elif l[j] + spr[j] <= p:
                    fill_i, entry, fresh = j, p, True
            if fill_i is not None or trend[j] == -d:
                break
        if fill_i is None:
            continue
        # manage the trade
        exit_i = exit_px = reason = None
        for i in range(fill_i, n):
            fr = fresh and i == fill_i
            if d == -1:
                tp_hit = not fr and l[i] + spr[i] <= tp
                tp_gap = o[i] + spr[i] <= tp
                sl_hit = (h[i] + spr[i] >= sl) if hard_sl else c[i] > sl
                if hard_sl and sl_hit:
                    exit_px, reason = (sl if fr else max(sl, o[i] + spr[i])), "SL (hard)"
                elif tp_hit and (tp_gap or not sl_hit):
                    exit_px, reason = min(tp, o[i] + spr[i]), "TP"
                elif sl_hit:
                    exit_px, reason = c[i] + spr[i], "SL (H1 close)"
            else:
                tp_hit = not fr and h[i] >= tp
                tp_gap = o[i] >= tp
                sl_hit = (l[i] <= sl) if hard_sl else c[i] < sl
                if hard_sl and sl_hit:
                    exit_px, reason = (sl if fr else min(sl, o[i])), "SL (hard)"
                elif tp_hit and (tp_gap or not sl_hit):
                    exit_px, reason = max(tp, o[i]), "TP"
                elif sl_hit:
                    exit_px, reason = c[i], "SL (H1 close)"
            if reason:
                exit_i = i
                break
        if exit_i is None:
            exit_i, exit_px, reason = n - 1, c[-1] + (spr[-1] if d == -1 else 0), "end of data"
        move = (exit_px - entry) * d
        trades.append({"signal_time": t_idx[k], "entry_time": t_idx[fill_i], "exit_time": t_idx[exit_i],
                       "direction": "BUY" if d == 1 else "SELL", "entry": round(entry, 2),
                       "sl_level": round(sl, 2), "tp": round(tp, 2), "exit": round(exit_px, 2),
                       "sl_pips": round(dist / PIP, 1), "pips": round(move / PIP, 1),
                       "r_multiple": round(move / dist, 2), "pnl_0.1lot": round(move * LOT_USD_PER_PRICE, 2),
                       "bars_to_fill": fill_i - k, "reason": reason})
    t = pd.DataFrame(trades).sort_values("exit_time", kind="stable").reset_index(drop=True)
    t.attrs["orders"] = orders
    return t


SL_VERSIONS = {
    "wick + H1 close": dict(sl_mode="wick", hard=False),
    "wick + hard SL": dict(sl_mode="wick", hard=True),
    "fixed 50p hard SL": dict(sl_mode="fixed", fixed_pips=50, hard=True),
    "fixed 70p hard SL": dict(sl_mode="fixed", fixed_pips=70, hard=True),
    "fixed 100p hard SL": dict(sl_mode="fixed", fixed_pips=100, hard=True),
}

if __name__ == "__main__":
    h1 = load_data("H1")
    days = h1.index.normalize().nunique()
    rows = []
    for side in ("sell", "both"):
        for sl_name, v in SL_VERSIONS.items():
            df = setups(h1, side, v["sl_mode"], v.get("fixed_pips", 50))
            for mode in ("every", "one-at-time"):
                if mode == "every":
                    t = simulate_every(df, 5, hard_sl=v["hard"])
                else:
                    t = simulate(df, 5, hard_sl=v["hard"])
                tag = f"{side}_{sl_name.replace(' ', '_').replace('+', '')}_{mode}".replace("__", "_")
                t.to_csv(f"results/ema_v3_{tag}_trades.csv", index=False)
                rows.append({"Side": side, "SL": sl_name, "Mode": mode,
                             "Setups": int((df.signal != 0).sum()),
                             "Fill %": round(len(t) / t.attrs["orders"] * 100), **summary(t, days)})
    out = pd.DataFrame(rows)
    print(f"XAUUSD H1 {h1.index[0]:%Y-%m-%d} -> {h1.index[-1]:%Y-%m-%d} | {days} trading days | "
          "EMA200 trend + engulfing vol < prev | limit valid 5 | RR 1:3")
    pd.set_option("display.width", 250)
    print(out.to_string(index=False))
    out.to_csv("results/ema_v3_summary.csv", index=False)
