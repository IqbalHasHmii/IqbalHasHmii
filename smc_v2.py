"""SMC engulfing strategy v2 (H1 only): proper swings, longer-lived limit, H1-close stop.

Rules
-----
1. Structure: Swing High = High strictly higher than the 5 candles to its left and the 2 to its
   right (Swing Low mirrored). A swing is confirmed only after its 2 right-hand candles close.
   Bullish (buys only) once an H1 candle CLOSES above the last confirmed Swing High,
   bearish (sells only) once it closes below the last confirmed Swing Low.
2. Setup: body engulfing candle in the trend direction (bearish engulfing in a bearish
   structure -> sell, bullish engulfing in a bullish structure -> buy).
   Limit order at the engulfing OPEN, valid for the next `valid` H1 candles. It is cancelled
   earlier if the structure flips the other way, and replaced if a new setup forms.
3. SL level = engulfing wick (High for sells, Low for buys); SL distance = |open - wick|.
   No hard stop: the trade is closed in loss only when an H1 candle CLOSES beyond the SL level
   (at that close). Wicks beyond it (stop hunts) are ignored. TP = 3 x SL distance, a normal
   take-profit order.

Modelling: prices are BID; sells fill on bid and exit on ask (bid + spread), buys the reverse.
On the fill candle TP is not counted (order inside the candle is unknown). If one candle both
touches TP and closes beyond SL, the loss is counted. One trade at a time; setups that appear
while a trade is open are ignored. P/L in $ uses a fixed 0.10 lot (= $1 per pip, 1 pip = $0.10).

    python smc_v2.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest import load_data
from smc_ob import smc_structure

PIP = 0.10
LOT_USD_PER_PRICE = 10.0   # 0.10 lot x 100 oz -> $10 per $1 move ($1 per pip)


def setups(h1: pd.DataFrame, side: str = "both", floor_pips: float = 0.0) -> pd.DataFrame:
    """floor_pips > 0 (variant, not in the rules): SL distance = max(wick distance, floor)."""
    df = h1.copy()
    df["trend"] = smc_structure(h1, 5, 2)
    po, pc = df.open.shift(), df.close.shift()
    bull = (pc < po) & (df.close > df.open) & (df.close >= po) & (df.open <= pc)
    bear = (pc > po) & (df.close < df.open) & (df.close <= po) & (df.open >= pc)
    sig = np.select([bull & (df.trend == 1) & (side != "sell"),
                     bear & (df.trend == -1) & (side != "buy")], [1, -1], 0)
    wick = np.where(sig == 1, df.open - df.low, df.high - df.open)
    dist = np.maximum(wick, floor_pips * PIP)
    df["sl_level"] = np.where(sig == 1, df.open - dist, df.open + dist)
    # setups with no wick on the entry side have no stop distance, so they cannot be traded
    df["signal"] = np.where(dist > 0, sig, 0)
    df["skipped"] = (sig != 0) & (df.signal == 0)
    df["sl_dist"] = dist
    return df


def simulate(df: pd.DataFrame, valid: int = 5, rr: float = 3.0, hard_sl: bool = False) -> pd.DataFrame:
    """hard_sl=True is for comparison only: a normal stop that any wick can hit."""
    t_idx = df.index
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    spr = df.spread_px.to_numpy()
    sig, trend = df.signal.to_numpy(), df.trend.to_numpy()
    sl_lv, dist = df.sl_level.to_numpy(), df.sl_dist.to_numpy()
    trades, pos, pend = [], None, None
    stats = {"orders": 0, "expired": 0, "cancel_structure": 0, "replaced": 0}

    def close(i, price, reason):
        nonlocal pos
        d = pos["dir"]
        move = (price - pos["entry"]) * d
        trades.append({"signal_time": pos["signal_time"], "entry_time": pos["entry_time"],
                       "exit_time": t_idx[i], "direction": "BUY" if d == 1 else "SELL",
                       "entry": round(pos["entry"], 2), "sl_level": round(pos["sl"], 2),
                       "tp": round(pos["tp"], 2), "exit": round(price, 2),
                       "sl_pips": round(pos["dist"] / PIP, 1), "pips": round(move / PIP, 1),
                       "r_multiple": round(move / pos["dist"], 2),
                       "pnl_0.1lot": round(move * LOT_USD_PER_PRICE, 2),
                       "bars_to_fill": pos["wait"], "reason": reason})
        pos = None

    for i in range(len(df)):
        fresh = False
        # 1) fill the pending limit order (it was placed at an earlier candle's close)
        if pend is not None and pos is None:
            if i > pend["last"]:
                pend, stats["expired"] = None, stats["expired"] + 1
            else:
                d, p = pend["dir"], pend["price"]
                fill = None
                if d == -1:   # sell limit on bid
                    if o[i] >= p:
                        fill = o[i]
                    elif h[i] >= p:
                        fill, fresh = p, True
                else:         # buy limit on ask
                    if o[i] + spr[i] <= p:
                        fill = o[i] + spr[i]
                    elif l[i] + spr[i] <= p:
                        fill, fresh = p, True
                if fill is not None:
                    pos = {"dir": d, "entry": fill, "sl": pend["sl"], "dist": pend["dist"],
                           "tp": p + d * rr * pend["dist"], "entry_time": t_idx[i],
                           "signal_time": pend["signal_time"], "wait": i - pend["k"]}
                    pend = None

        # 2) manage the open trade: TP intrabar, SL only on the H1 close
        if pos is not None:
            d = pos["dir"]
            if d == -1:
                tp_hit = not fresh and l[i] + spr[i] <= pos["tp"]
                tp_gap = o[i] + spr[i] <= pos["tp"]
                sl_hit = (h[i] + spr[i] >= pos["sl"]) if hard_sl else c[i] > pos["sl"]
                if hard_sl and sl_hit:
                    close(i, pos["sl"] if fresh else max(pos["sl"], o[i] + spr[i]), "SL (hard)")
                elif tp_hit and (tp_gap or not sl_hit):
                    close(i, min(pos["tp"], o[i] + spr[i]), "TP")
                elif sl_hit:
                    close(i, c[i] + spr[i], "SL (H1 close)")
            else:
                tp_hit = not fresh and h[i] >= pos["tp"]
                tp_gap = o[i] >= pos["tp"]
                sl_hit = (l[i] <= pos["sl"]) if hard_sl else c[i] < pos["sl"]
                if hard_sl and sl_hit:
                    close(i, pos["sl"] if fresh else min(pos["sl"], o[i]), "SL (hard)")
                elif tp_hit and (tp_gap or not sl_hit):
                    close(i, max(pos["tp"], o[i]), "TP")
                elif sl_hit:
                    close(i, c[i], "SL (H1 close)")

        # 3) at this candle's close: structure-break cancel, then new setups
        if pend is not None and trend[i] == -pend["dir"]:
            pend, stats["cancel_structure"] = None, stats["cancel_structure"] + 1
        if pos is None and sig[i] != 0:
            if pend is not None:
                stats["replaced"] += 1
            pend = {"dir": int(sig[i]), "price": o[i], "sl": sl_lv[i], "dist": dist[i],
                    "k": i, "last": i + valid, "signal_time": t_idx[i]}
            stats["orders"] += 1

    if pos is not None:
        close(len(df) - 1, c[-1] + (spr[-1] if pos["dir"] == -1 else 0), "end of data")
    t = pd.DataFrame(trades)
    t.attrs.update(stats)
    return t


def summary(t: pd.DataFrame, days: int) -> dict:
    tp = (t.reason == "TP").sum()
    eq = t["pnl_0.1lot"].cumsum()
    win, loss = t.pips[t.pips > 0].sum(), -t.pips[t.pips <= 0].sum()
    yearly = t.groupby(pd.to_datetime(t.exit_time).dt.year)["pnl_0.1lot"].sum()
    return {"Trades": len(t), "TP hit": int(tp), "SL hit": int((t.reason != "TP").sum()),
            "TP %": round(tp / len(t) * 100, 1), "Trades/day": round(len(t) / days, 2),
            "Avg SL pips": round(t.sl_pips.mean(), 1),
            "Avg loss pips": round(t.pips[t.reason != "TP"].mean(), 1),
            "Net pips": round(t.pips.sum()), "PF": round(win / loss, 2),
            "Net $ 0.1 lot": round(t["pnl_0.1lot"].sum()),
            "Max DD $": round((eq - eq.cummax().clip(lower=0)).min()),
            "Losing yrs": f"{(yearly < 0).sum()}/{len(yearly)}"}


if __name__ == "__main__":
    h1 = load_data("H1")
    days = h1.index.normalize().nunique()
    rows = []
    for side in ("sell", "both"):
        for floor in (0, 30, 50, 70, 100):
            df = setups(h1, side, floor)
            for valid in (5, 10):
                for hard in (False, True):
                    if hard and (floor not in (0, 50) or valid != 5):
                        continue
                    t = simulate(df, valid, hard_sl=hard)
                    tag = f"{side}_floor{floor}_valid{valid}{'_hardsl' if hard else ''}"
                    t.to_csv(f"results/smc_v2_{tag}_trades.csv", index=False)
                    rows.append({"Side": side, "SL": "wick" if floor == 0 else f"max(wick,{floor}p)",
                                 "Exit": "hard SL" if hard else "H1 close", "Valid": valid,
                                 "Orders": t.attrs["orders"],
                                 "Fill %": round(len(t) / t.attrs["orders"] * 100), **summary(t, days)})
    out = pd.DataFrame(rows)
    print(f"XAUUSD H1 {h1.index[0]:%Y-%m-%d} -> {h1.index[-1]:%Y-%m-%d} | {days} trading days | RR 1:3")
    pd.set_option("display.width", 250)
    print(out.to_string(index=False))
    out.to_csv("results/smc_v2_summary.csv", index=False)
