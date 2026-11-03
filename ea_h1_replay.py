"""Replay of the H1 EA (mql5/XAUUSD_Extreme_OB_EA.mq5) on the history.

    python ea_h1_replay.py

Part 1 replays v2.00 exactly as it was written, on M15 candles (H1 setups):
  * tradeArmed is never reset after an entry, so after the trade closes the same setup is
    entered again whenever price is back at the engulfing open, and when the wick SL is already
    on the wrong side of the price the order is rejected and re-sent on every tick
  * a setup only goes away when a newer setup replaces it, so entries can come days later
  * a hard SL sits on the wick, and the "H1 close" check runs at minute 45 on the PREVIOUS
    H1 candle
Part 2 replays the v2.10 logic on H1 candles (setup valid 10 H1 candles, SL 5-50 pips, exit
on the H1 close beyond the wick), using replay_v210 from ea_m15_replay.py.
"""
from __future__ import annotations

from collections import Counter

import numpy as np
import pandas as pd

from backtest import load_data
from ea_m15_replay import PIP, replay_v210, setup


def replay_h1_v200(h1, m15, struct=5, max_sl=50, rr=3.0):
    ho, hh, hl, hc, hv = (h1[k].to_numpy() for k in ("open", "high", "low", "close", "tickvol"))
    h1_pos = {t: k for k, t in enumerate(h1.index)}
    mo, mh, ml = (m15[k].to_numpy() for k in ("open", "high", "low"))
    spr, mt = m15.spread_px.to_numpy(), m15.index
    hour = mt.floor("h")
    armed = pos = None
    st = Counter()
    per_setup = Counter()
    pips = []
    last_hour = None
    for j in range(len(m15)):
        # new H1 candle -> CheckH1Setup() (skipped while a position is open, overwrites an armed setup)
        if hour[j] != last_hour:
            last_hour = hour[j]
            k = h1_pos.get(hour[j])
            if k is not None and k - 1 > struct + 1 and pos is None:
                kk = k - 1
                d, wick = setup(ho, hh, hl, hc, hv, kk, struct)
                if d and 0 < abs(ho[kk] - wick) <= max_sl * PIP:
                    armed = {"dir": d, "entry": ho[kk], "hi": hh[kk], "lo": hl[kk], "id": st["setups"], "t": h1.index[kk]}
                    st["setups"] += 1
        # ticks: entry at the engulfing open (tradeArmed stays true after an entry)
        fresh = False
        if armed is not None and pos is None:
            a, s = armed, spr[j]
            if a["dir"] == 1 and ml[j] + s <= a["entry"]:
                lo_, hi_ = max(ml[j], a["lo"] + 0.01), min(mh[j], a["entry"] - s)
                if mo[j] < lo_:
                    st["spam_candles"] += 1          # ask <= entry but bid <= SL: rejected on every tick
                if lo_ <= hi_:
                    fb = hi_ if mo[j] > hi_ else max(mo[j], lo_)
                    pos = {"dir": 1, "fill": fb + s, "sl": a["lo"], "tp": a["entry"] + rr * (a["entry"] - a["lo"])}
                elif mo[j] >= lo_:
                    st["spam_candles"] += 1
            elif a["dir"] == -1 and mh[j] >= a["entry"]:
                lo_, hi_ = max(ml[j], a["entry"]), min(mh[j], a["hi"] - s - 0.01)
                if mo[j] > hi_:
                    st["spam_candles"] += 1
                if lo_ <= hi_:
                    fb = lo_ if mo[j] < lo_ else min(mo[j], hi_)
                    pos = {"dir": -1, "fill": fb, "sl": a["hi"], "tp": a["entry"] - rr * (a["hi"] - a["entry"])}
                elif mo[j] <= hi_:
                    st["spam_candles"] += 1
            if pos is not None:
                fresh = True
                st["trades"] += 1
                per_setup[a["id"]] += 1
                if per_setup[a["id"]] > 1:
                    st["re_entries"] += 1
                if mt[j] - a["t"] > pd.Timedelta(hours=11):
                    st["late_entries"] += 1          # more than 10 H1 candles after the setup
        # broker-side hard SL at the wick / TP
        if pos is not None:
            p = pos
            if p["dir"] == 1:
                if ml[j] <= p["sl"]:
                    pips.append((p["sl"] - p["fill"]) / PIP); st["sl"] += 1; pos = None
                elif not fresh and mh[j] >= p["tp"]:
                    pips.append((p["tp"] - p["fill"]) / PIP); st["tp"] += 1; pos = None
            else:
                if mh[j] + spr[j] >= p["sl"]:
                    pips.append((p["fill"] - p["sl"]) / PIP); st["sl"] += 1; pos = None
                elif not fresh and ml[j] + spr[j] <= p["tp"]:
                    pips.append((p["fill"] - p["tp"]) / PIP); st["tp"] += 1; pos = None
        # "H1 close" rule: at minute 45, on the previous (already closed) H1 candle
        if pos is not None and mt[j].minute == 45:
            k = h1_pos.get(hour[j])
            if k is not None and ((pos["dir"] == 1 and hc[k - 1] < pos["sl"]) or
                                  (pos["dir"] == -1 and hc[k - 1] > pos["sl"])):
                px = mo[j] if pos["dir"] == 1 else mo[j] + spr[j]
                pips.append((px - pos["fill"]) * pos["dir"] / PIP); st["h1_rule"] += 1
                pos = armed = None
    st["max_trades_one_setup"] = max(per_setup.values()) if per_setup else 0
    return st, np.array(pips)


if __name__ == "__main__":
    h1, m15 = load_data("H1"), load_data("M15")
    days = h1.index.normalize().nunique()
    print(f"XAUUSD {h1.index[0]:%Y-%m-%d} -> {h1.index[-1]:%Y-%m-%d}, {days} trading days\n")

    st, p = replay_h1_v200(h1, m15)
    print("H1 EA v2.00 as written (replayed on M15 candles):")
    print(f"  setups {st['setups']} | trades {st['trades']} = {st['trades'] / days:.2f} per day")
    print(f"  re-entries of an already traded setup: {st['re_entries']} "
          f"({st['re_entries'] / st['trades'] * 100:.0f}% of all trades), up to {st['max_trades_one_setup']} trades on one setup")
    print(f"  entries more than 10 H1 candles after their setup: {st['late_entries']}")
    print(f"  M15 candles in which the order is rejected and re-sent on every tick: {st['spam_candles']}")
    print(f"  exits: TP {st['tp']}, hard SL at the wick {st['sl']}, 'H1 close' rule {st['h1_rule']} | "
          f"TP {st['tp'] / max(len(p), 1) * 100:.1f}% | net {p.sum():.0f} pips\n")

    rows = []
    for name, kw in [("hard SL at the wick (v2.00 exit)", {"close_based": False}),
                     ("H1-close exit + 500-pip emergency SL (v2.10 default)", {"emergency_pips": 500}),
                     ("H1-close exit, no broker SL", {"emergency_pips": 0})]:
        t = replay_v210(h1, expiry=10, min_sl=5, max_sl=50, struct=5, **kw)
        tp = (t.reason == "TP").sum()
        rows.append({"Exit": name, "Trades": len(t), "Per day": round(len(t) / days, 2),
                     "TP %": round(tp / len(t) * 100, 1), "Avg loss pips": round(t.pips[t.reason != "TP"].mean(), 1),
                     "Worst pips": round(t.pips.min()), "Net pips (= $ at 0.1 lot)": round(t.pips.sum())})
    pd.set_option("display.width", 200)
    print("H1 EA v2.10 logic (setup valid 10 H1 candles, SL 5-50 pips, trend = close vs 5 candles ago, TP 1:3):")
    print(pd.DataFrame(rows).to_string(index=False))
