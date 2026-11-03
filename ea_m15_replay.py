"""Replay of mql5/XAUUSD_M15_Extreme_OB_EA.mq5 on the M15 history, candle by candle.

    python ea_m15_replay.py

Part 1 replays v2.00 exactly as it was written, to show why it took so few trades:
  * an armed setup never expires, and new setups are only looked for when nothing is armed
  * the order is sent when price touches the engulfing open; if the wick SL is already on the
    wrong side of the price (wick smaller than the spread) the broker rejects it, and the EA
    drops the setup anyway
  * a hard SL sits on the wick, so the M15-close exit can never fire
Part 2 replays the v2.10 logic (setup valid 10 candles, replaced by newer setups, cancelled on
a trend flip, SL 5-30 pips, SL checked before sending) with several exit settings.

Modelling: M15 bid prices with each candle's spread. Buys trigger on ask and exit on bid,
sells the reverse. On the entry candle only the stop is checked. If stop and TP fall in the
same candle, the stop is counted. P/L in pips (1 pip = $0.10, $1 per pip at 0.10 lot).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest import load_data

PIP = 0.10


def setup(o, h, l, c, v, k, struct=20):
    """Direction (1/-1/0) and wick of an EA setup on the candle k that just closed."""
    po, pc = o[k - 1], c[k - 1]
    bull = po > pc and c[k] > o[k] and c[k] >= po and o[k] <= pc
    bear = pc > po and o[k] > c[k] and c[k] <= po and o[k] >= pc
    vol = v[k] <= v[k - 1]
    if vol and bull and c[k] > c[k - struct]:
        return 1, l[k]
    if vol and bear and c[k] < c[k - struct]:
        return -1, h[k]
    return 0, 0.0


def replay_v200(m, start=0, stop=None, first_trade_only=False):
    o, h, l, c, v = (m[k].to_numpy() for k in ("open", "high", "low", "close", "tickvol"))
    spr, t = m.spread_px.to_numpy(), m.index
    armed = pos = None
    st = {"armed": 0, "rejected": 0, "opened": 0, "tp": 0, "hard_sl": 0, "close_sl": 0, "waits": []}
    for i in range(max(start, 23), len(m) if stop is None else stop):
        # new candle: CheckM15Setup() (only when nothing is armed), then CheckM15ExitRule()
        if pos is None and armed is None:
            d, wick = setup(o, h, l, c, v, i - 1)
            if d and 0 < abs(o[i - 1] - wick) <= 30 * PIP:
                armed = {"dir": d, "entry": o[i - 1], "sl": wick, "at": i}
                st["armed"] += 1
        if pos is not None and ((pos["dir"] == 1 and c[i - 1] < pos["sl"]) or
                                (pos["dir"] == -1 and c[i - 1] > pos["sl"])):
            st["close_sl"] += 1
            pos = None
        # ticks: MonitorLimitEntry()
        fresh = False
        if armed is not None and pos is None:
            a, ok = armed, None
            if a["dir"] == 1 and l[i] + spr[i] <= a["entry"]:
                bid = min(a["entry"], o[i] + spr[i]) - spr[i]
                ok = a["sl"] < bid
            elif a["dir"] == -1 and h[i] >= a["entry"]:
                ask = max(a["entry"], o[i]) + spr[i]
                ok = a["sl"] > ask
            if ok is not None:
                st["waits"].append((i - a["at"], t[a["at"]]))
                if ok:
                    risk = abs(a["entry"] - a["sl"])
                    pos = {"dir": a["dir"], "sl": a["sl"], "tp": a["entry"] + a["dir"] * 3 * risk}
                    st["opened"] += 1
                    fresh = True
                    if first_trade_only:
                        return st, t[i]
                else:
                    st["rejected"] += 1
                armed = None                   # dropped whether or not the order went through
        # broker-side hard SL / TP
        if pos is not None:
            if pos["dir"] == 1:
                if l[i] <= pos["sl"]:
                    st["hard_sl"] += 1; pos = None
                elif not fresh and h[i] >= pos["tp"]:
                    st["tp"] += 1; pos = None
            else:
                if h[i] + spr[i] >= pos["sl"]:
                    st["hard_sl"] += 1; pos = None
                elif not fresh and l[i] + spr[i] <= pos["tp"]:
                    st["tp"] += 1; pos = None
    return st, None


def replay_v210(m, expiry=10, min_sl=5, max_sl=30, rr=3.0, close_based=True, emergency_pips=300.0):
    o, h, l, c, v = (m[k].to_numpy() for k in ("open", "high", "low", "close", "tickvol"))
    spr = m.spread_px.to_numpy()
    armed = pos = None
    trades = []

    def close(px, why):
        nonlocal pos
        mv = (px - pos["fill"]) * pos["dir"]
        trades.append((mv / PIP, why))
        pos = None

    for i in range(23, len(m)):
        # new candle: M15-close exit first, then the setup check
        if pos is not None and close_based:
            if pos["dir"] == 1 and c[i - 1] < pos["wick"]:
                close(o[i], "M15 close beyond wick")
            elif pos["dir"] == -1 and c[i - 1] > pos["wick"]:
                close(o[i] + spr[i], "M15 close beyond wick")
        if pos is None:
            d, wick = setup(o, h, l, c, v, i - 1)
            new = bool(d) and min_sl * PIP <= abs(o[i - 1] - wick) <= max_sl * PIP
            if new:
                armed = {"dir": d, "entry": o[i - 1], "wick": wick, "left": expiry}
            elif armed is not None:
                k = i - 1
                flipped = (c[k] < c[k - 20]) if armed["dir"] == 1 else (c[k] > c[k - 20])
                armed["left"] -= 1
                if flipped or armed["left"] <= 0:
                    armed = None
        # ticks: entry when price comes back to the engulfing open
        fresh = False
        if armed is not None and pos is None:
            a = armed
            if a["dir"] == 1 and l[i] + spr[i] <= a["entry"]:
                ask = min(a["entry"], o[i] + spr[i])
                if a["wick"] < ask - spr[i] - 0.02:
                    risk = a["entry"] - a["wick"]
                    sl = a["wick"] if not close_based else (a["entry"] - emergency_pips * PIP if emergency_pips else -np.inf)
                    pos = {"dir": 1, "fill": ask, "wick": a["wick"], "sl": sl, "tp": a["entry"] + rr * risk}
                    fresh = True
                armed = None
            elif a["dir"] == -1 and h[i] >= a["entry"]:
                bid = max(a["entry"], o[i])
                if a["wick"] > bid + spr[i] + 0.02:
                    risk = a["wick"] - a["entry"]
                    sl = a["wick"] if not close_based else (a["entry"] + emergency_pips * PIP if emergency_pips else np.inf)
                    pos = {"dir": -1, "fill": bid, "wick": a["wick"], "sl": sl, "tp": a["entry"] - rr * risk}
                    fresh = True
                armed = None
        # broker-side SL / TP
        if pos is not None:
            if pos["dir"] == 1:
                if l[i] <= pos["sl"]:
                    close(pos["sl"] if fresh else min(pos["sl"], o[i]), "broker SL")
                elif not fresh and h[i] >= pos["tp"]:
                    close(max(pos["tp"], o[i]), "TP")
            else:
                if h[i] + spr[i] >= pos["sl"]:
                    close(pos["sl"] if fresh else max(pos["sl"], o[i] + spr[i]), "broker SL")
                elif not fresh and l[i] + spr[i] <= pos["tp"]:
                    close(min(pos["tp"], o[i] + spr[i]), "TP")
    return pd.DataFrame(trades, columns=["pips", "reason"])


if __name__ == "__main__":
    m = load_data("M15")
    days = m.index.normalize().nunique()
    print(f"XAUUSD M15 {m.index[0]:%Y-%m-%d} -> {m.index[-1]:%Y-%m-%d}, {days} trading days\n")

    st, _ = replay_v200(m)
    w = np.array([x[0] for x in st["waits"]])
    print("v2.00 as written:")
    print(f"  setups armed {st['armed']} | orders sent {len(w)} | rejected (wick SL already beyond the price) "
          f"{st['rejected']} | trades opened {st['opened']} = {st['opened'] / days:.2f} per day")
    print(f"  exits: TP {st['tp']}, hard SL at the wick {st['hard_sl']}, M15-close exit {st['close_sl']}")
    print(f"  M15 candles waited for the retrace: median {np.median(w):.0f}, max {w.max()}; "
          f"waits longer than a week: {(w > 96 * 5).sum()}")
    for bars, armed_at in sorted(st["waits"], key=lambda x: -x[0])[:3]:
        end = m.index[m.index.get_loc(armed_at) + bars]
        print(f"    armed {armed_at:%Y-%m-%d %H:%M}, touched {end:%Y-%m-%d}: "
              f"no new setup for {(end - armed_at).days} calendar days")
    starts = np.flatnonzero(m.index >= m.index[-1] - pd.Timedelta(days=365))[::96]
    hours = []
    for s in starts:
        _, first = replay_v200(m, start=s, stop=min(s + 96 * 40, len(m)), first_trade_only=True)
        hours.append((first - m.index[s]).total_seconds() / 3600 if first is not None else np.inf)
    hours = np.array(hours)
    print(f"  started on any day of the last 12 months ({len(hours)} starts), first trade after: median "
          f"{np.median(hours):.0f} h | none within 1 day {np.mean(hours > 24) * 100:.0f}% | "
          f"none within a week {np.mean(hours > 24 * 7) * 100:.0f}%\n")

    rows = []
    for name, kw in [("hard SL at the wick (v2.00 exit)", {"close_based": False}),
                     ("M15-close exit + 300-pip emergency SL (v2.10 default)", {}),
                     ("M15-close exit, no broker SL", {"emergency_pips": 0})]:
        t = replay_v210(m, **kw)
        tp = (t.reason == "TP").sum()
        rows.append({"Exit": name, "Trades": len(t), "Per day": round(len(t) / days, 2),
                     "TP %": round(tp / len(t) * 100, 1), "Avg loss pips": round(t.pips[t.reason != "TP"].mean(), 1),
                     "Worst pips": round(t.pips.min()), "Net pips (= $ at 0.1 lot)": round(t.pips.sum())})
    pd.set_option("display.width", 200)
    print("v2.10 logic (setup valid 10 candles, SL 5-30 pips, TP 1:3):")
    print(pd.DataFrame(rows).to_string(index=False))
