"""Engulfing strategy v4 (H1): engulfing only inside an Order Block or a Fair Value Gap.

Zones (H1, built only from candles that have closed, no look-ahead)
  Bullish FVG : low[i] > high[i-2]  -> zone [high[i-2], low[i]]
  Bearish FVG : high[i] < low[i-2]  -> zone [high[i], low[i-2]]
  Bullish OB  : when a bullish FVG forms (displacement up), the last bearish candle within the
                5 candles before it; zone = that candle's [low, high]
  Bearish OB  : mirror (last bullish candle before a bearish FVG displacement)
  A zone stays active until an H1 candle CLOSES through it (bullish zone: close below its
  bottom, bearish zone: close above its top) or it is older than `max_age` candles.

Setup
  Buy : bullish engulfing whose two-candle range (engulfing + previous) touches an active
        bullish zone and closes above the zone bottom, with H1 close above EMA(200).
  Sell: bearish engulfing touching an active bearish zone, closing below the zone top, with
        H1 close below EMA(200).
  Optional: engulfing tick volume < previous candle's (volume filter).
Entry / exit as in ema_v3.py: limit at the engulfing open valid 5 candles (cancelled if the
close crosses the EMA the other way), every setup trades on its own, TP = 3 x SL.

    python zones_v4.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest import load_data
from ema_v3 import SL_VERSIONS, setups as ema_setups, simulate_every
from smc_v2 import summary


def zone_touch(h1: pd.DataFrame, max_age: int = 100, ob_lookback: int = 5) -> dict[str, np.ndarray]:
    """For every bar: does the (bar, previous bar) range touch an active zone of each kind?
    Only zones created before the bar are used."""
    o, h, l, c = (h1[k].to_numpy() for k in ("open", "high", "low", "close"))
    n = len(h1)
    out = {k: np.zeros(n, bool) for k in ("bull_ob", "bull_fvg", "bear_ob", "bear_fvg")}
    zones = []   # dicts: kind, dir, bottom, top, born
    for i in range(1, n):
        lo2, hi2 = min(l[i], l[i - 1]), max(h[i], h[i - 1])
        # 1) touch test against zones that existed before this candle
        for z in zones:
            if hi2 >= z["bottom"] and lo2 <= z["top"]:
                if z["dir"] == 1 and c[i] > z["bottom"]:
                    out[f"bull_{z['kind']}"][i] = True
                elif z["dir"] == -1 and c[i] < z["top"]:
                    out[f"bear_{z['kind']}"][i] = True
        # 2) this candle's close invalidates zones it closed through, and old zones expire
        zones = [z for z in zones if i - z["born"] <= max_age and
                 not (z["dir"] == 1 and c[i] < z["bottom"]) and not (z["dir"] == -1 and c[i] > z["top"])]
        # 3) new zones formed by this candle
        if i >= 2:
            if l[i] > h[i - 2]:                                   # bullish FVG
                zones.append({"kind": "fvg", "dir": 1, "bottom": h[i - 2], "top": l[i], "born": i})
                for j in range(i - 1, max(i - 1 - ob_lookback, -1), -1):
                    if c[j] < o[j]:
                        zones.append({"kind": "ob", "dir": 1, "bottom": l[j], "top": h[j], "born": i})
                        break
            if h[i] < l[i - 2]:                                   # bearish FVG
                zones.append({"kind": "fvg", "dir": -1, "bottom": h[i], "top": l[i - 2], "born": i})
                for j in range(i - 1, max(i - 1 - ob_lookback, -1), -1):
                    if c[j] > o[j]:
                        zones.append({"kind": "ob", "dir": -1, "bottom": l[j], "top": h[j], "born": i})
                        break
    return out


def setups(h1, zt, zone: str, side: str, sl_mode: str, fixed_pips: float, volume_filter: bool):
    df = ema_setups(h1, side, sl_mode, fixed_pips, volume_filter)
    kinds = ("ob", "fvg") if zone == "OB or FVG" else (zone.lower(),)
    bull_ok = np.any([zt[f"bull_{k}"] for k in kinds], axis=0)
    bear_ok = np.any([zt[f"bear_{k}"] for k in kinds], axis=0)
    keep = ((df.signal == 1) & bull_ok) | ((df.signal == -1) & bear_ok)
    df["signal"] = np.where(keep, df.signal, 0)
    return df


if __name__ == "__main__":
    h1 = load_data("H1")
    days = h1.index.normalize().nunique()
    zt = zone_touch(h1)
    rows = []
    for zone in ("OB", "FVG", "OB or FVG"):
        for vf in (True, False):
            for side in ("sell", "both"):
                for sl_name, v in SL_VERSIONS.items():
                    df = setups(h1, zt, zone, side, v["sl_mode"], v.get("fixed_pips", 50), vf)
                    t = simulate_every(df, 5, hard_sl=v["hard"])
                    tag = f"{zone.replace(' ', '')}_{'vol' if vf else 'novol'}_{side}_{sl_name.replace(' ', '').replace('+', '_')}"
                    if zone == "OB or FVG" and vf:   # trade lists for the main rule set only
                        t.to_csv(f"results/zones_v4_{tag}_trades.csv", index=False)
                    rows.append({"Zone": zone, "Vol<prev": "yes" if vf else "no", "Side": side, "SL": sl_name,
                                 "Setups": int((df.signal != 0).sum()),
                                 "Fill %": round(len(t) / t.attrs["orders"] * 100), **summary(t, days)})
    out = pd.DataFrame(rows)
    print(f"XAUUSD H1 {h1.index[0]:%Y-%m-%d} -> {h1.index[-1]:%Y-%m-%d} | {days} trading days | "
          "EMA200 + engulfing in OB/FVG | limit valid 5 | every setup | RR 1:3")
    pd.set_option("display.width", 250)
    print(out.drop(columns=["Max DD $"]).to_string(index=False))
    out.to_csv("results/zones_v4_summary.csv", index=False)
