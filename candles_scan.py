"""Pure candlestick patterns on XAUUSD: how accurate is each one, on every timeframe?

No indicators: a pattern closes, the trade opens at the next candle's open (ask for a buy, bid for
a sell), the SL goes at the pattern's extreme (lowest low of its candles for a buy, highest high
for a sell) and the TP at 1, 2 or 3 x that risk. Exits are checked on the same timeframe's
candles, with the real spread; if SL and TP fall in one candle the SL counts (conservative). A
time stop closes after 100 candles. Every signal is its own trade. A risk under 0.1 x ATR(14) or
2 x the spread (too tight to be real) or over 4 x ATR is skipped.

Patterns (bullish / bearish mirror): hammer / shooting star, inverted hammer / hanging man (the
same shapes read the other way), pin bar, dragonfly / gravestone doji, marubozu, belt hold,
engulfing, piercing line / dark cloud cover, harami, tweezer bottom / top, outside bar, kicker,
inside bar breakout, morning / evening star, three white soldiers / black crows, three inside
up / down, three outside up / down, rising / falling three methods.

Context: "any" = the pattern alone; "after a move against" = the 3 candles before the pattern
made lower lows (for a buy) or higher highs (for a sell), as the classic reversal reading wants;
"after a move with" = the opposite (continuation).

Baseline: the same trade after EVERY candle in that direction (SL at the candle's extreme), so a
pattern only means something if it beats it.

Our data: M1 -> M5, M15, M30, H1, H4, D1 (2021-11..2026-10; discovery 2021-11..2024-10, check
2024-11..2026-10). Exness: M3 -> M15 .. D1 (2020-01..2026-11; M5 cannot be built from M3).

    python candles_scan.py      # -> results/candles_scan.txt, results/candles_scan.csv
"""
from __future__ import annotations

import glob

import numba
import numpy as np
import pandas as pd

import backtest as b
import m3_ha_test as m3
from h1_hh_engulf_types import new_highs_ok
from mass_search import resample
from strategy_library import atr

RRS = (1.0, 2.0, 3.0)
MAXH = 100
SPLIT = pd.Timestamp("2024-11-01")


@numba.njit(cache=True)
def simulate(o, h, l, c, spr, a, idx, side, slv, rr, maxh):
    """R of a trade opened at the next open after each signal; nan = skipped or not closed."""
    n = len(o)
    out = np.full(len(idx), np.nan)
    for k in range(len(idx)):
        i = idx[k]
        j0 = i + 1
        if j0 >= n:
            continue
        sl = slv[k]
        if side == 1:
            e = o[j0] + spr[j0]
            d = e - sl
        else:
            e = o[j0]
            d = sl - e
        if not (d > 0.1 * a[i] and d > 2 * spr[j0] and d < 4 * a[i]):
            continue
        tp = e + side * rr * d
        last = min(n - 1, i + maxh)
        r = np.nan
        for j in range(j0, last + 1):
            if side == 1:
                if l[j] <= sl:
                    r = (min(sl, o[j]) - e) / d if j > j0 else (sl - e) / d
                    break
                if h[j] >= tp:
                    r = (max(tp, o[j]) - e) / d if j > j0 else (tp - e) / d
                    break
            else:
                if h[j] + spr[j] >= sl:
                    r = (e - max(sl, o[j] + spr[j])) / d if j > j0 else (e - sl) / d
                    break
                if l[j] + spr[j] <= tp:
                    r = (e - min(tp, o[j] + spr[j])) / d if j > j0 else (e - tp) / d
                    break
        if np.isnan(r) and last == i + maxh:
            px = c[last] if side == 1 else c[last] + spr[last]
            r = side * (px - e) / d
        out[k] = r
    return out


def shift(x, k):
    return np.r_[np.full(k, np.nan), x[:-k]]


def patterns(d: pd.DataFrame) -> dict:
    """name -> (bull mask, bear mask, number of candles in the pattern)."""
    o, h, l, c = (d[k].to_numpy(np.float64) for k in ("open", "high", "low", "close"))
    a = atr(d).to_numpy()
    po, ph, pl, pc = (shift(x, 1) for x in (o, h, l, c))
    o2, h2, l2, c2 = (shift(x, 2) for x in (o, h, l, c))
    body, rng = np.abs(c - o), h - l
    upper, lower = h - np.maximum(o, c), np.minimum(o, c) - l
    pbody, body2 = np.abs(pc - po), np.abs(c2 - o2)
    bull, bear, pbull, pbear = c > o, c < o, pc > po, pc < po
    bull2, bear2 = c2 > o2, c2 < o2
    P = {}
    hammer = (rng > 0) & (lower >= 2 * body) & (upper <= 0.25 * rng)
    star = (rng > 0) & (upper >= 2 * body) & (lower <= 0.25 * rng)
    P["hammer / shooting star"] = (hammer, star, 1)
    P["inverted hammer / hanging man"] = (star, hammer, 1)
    P["pin bar (2/3 wick)"] = ((rng > 0) & (lower >= rng * 2 / 3), (rng > 0) & (upper >= rng * 2 / 3), 1)
    doji = (rng > 0) & (body <= 0.1 * rng)
    P["dragonfly / gravestone doji"] = (doji & (lower >= 0.7 * rng), doji & (upper >= 0.7 * rng), 1)
    maru = (rng > 0) & (body >= 0.9 * rng) & (body >= a)
    P["marubozu"] = (maru & bull, maru & bear, 1)
    P["belt hold"] = (bull & (lower <= 0.05 * rng) & (body >= a), bear & (upper <= 0.05 * rng) & (body >= a), 1)
    P["engulfing"] = (pbear & bull & (c >= po) & (o <= pc), pbull & bear & (c <= po) & (o >= pc), 2)
    mid = (po + pc) / 2
    P["piercing / dark cloud"] = (pbear & (pbody >= 0.5 * a) & bull & (o <= pc) & (c > mid) & (c < po),
                                  pbull & (pbody >= 0.5 * a) & bear & (o >= pc) & (c < mid) & (c > po), 2)
    hb = pbear & (pbody >= 0.5 * a) & bull & (np.maximum(o, c) <= po) & (np.minimum(o, c) >= pc) & (body <= 0.5 * pbody)
    hs = pbull & (pbody >= 0.5 * a) & bear & (np.maximum(o, c) <= pc) & (np.minimum(o, c) >= po) & (body <= 0.5 * pbody)
    P["harami"] = (hb, hs, 2)
    P["tweezer bottom / top"] = (pbear & bull & (np.abs(l - pl) <= 0.05 * a), pbull & bear & (np.abs(h - ph) <= 0.05 * a), 2)
    P["outside bar"] = ((h > ph) & (l < pl) & (c > ph), (h > ph) & (l < pl) & (c < pl), 2)
    P["kicker"] = (pbear & bull & (o >= po) & (body >= 0.5 * a), pbull & bear & (o <= po) & (body >= 0.5 * a), 2)
    inside_prev = (ph <= h2) & (pl >= l2)
    P["inside bar breakout"] = (inside_prev & (c > h2), inside_prev & (c < l2), 3)
    small_mid = pbody <= 0.3 * body2
    P["morning / evening star"] = (bear2 & (body2 >= 0.5 * a) & small_mid & bull & (c > (o2 + c2) / 2),
                                   bull2 & (body2 >= 0.5 * a) & small_mid & bear & (c < (o2 + c2) / 2), 3)
    near_hi = (c - l) >= 0.7 * rng
    near_lo = (h - c) >= 0.7 * rng
    p_near_hi = (pc - pl) >= 0.7 * (ph - pl)
    p_near_lo = (ph - pc) >= 0.7 * (ph - pl)
    c2_near_hi = (c2 - l2) >= 0.7 * (h2 - l2)
    c2_near_lo = (h2 - c2) >= 0.7 * (h2 - l2)
    P["three soldiers / crows"] = (bull & pbull & bull2 & (c > pc) & (pc > c2) & near_hi & p_near_hi & c2_near_hi,
                                   bear & pbear & bear2 & (c < pc) & (pc < c2) & near_lo & p_near_lo & c2_near_lo, 3)
    hb1, hs1 = shift(hb.astype(float), 1) > 0, shift(hs.astype(float), 1) > 0
    P["three inside up / down"] = (hb1 & bull & (c > o2), hs1 & bear & (c < o2), 3)
    eb1 = shift((pbear & bull & (c >= po) & (o <= pc)).astype(float), 1) > 0
    es1 = shift((pbull & bear & (c <= po) & (o >= pc)).astype(float), 1) > 0
    P["three outside up / down"] = (eb1 & bull & (c > pc), es1 & bear & (c < pc), 3)
    o4, h4, l4, c4 = (shift(x, 4) for x in (o, h, l, c))
    body4 = np.abs(c4 - o4)
    small3 = np.ones(len(o), bool)
    inside3 = np.ones(len(o), bool)
    for k in (1, 2, 3):
        small3 &= shift(body, k) <= 0.5 * body4
        inside3 &= (shift(h, k) <= h4) & (shift(l, k) >= l4)
    P["rising / falling three"] = ((c4 > o4) & (body4 >= a) & small3 & inside3 & bull & (c > c4),
                                   (c4 < o4) & (body4 >= a) & small3 & inside3 & bear & (c < c4), 5)
    return P


def run_tf(d: pd.DataFrame, tf: str, data: str) -> list:
    o, h, l, c, s = (d[k].to_numpy(np.float64) for k in ("open", "high", "low", "close", "spread_px"))
    a = atr(d).to_numpy(np.float64)
    hh = new_highs_ok(h, 3, 3)
    ll = new_highs_ok(-l, 3, 3)                       # 3 lower lows in a row before the candle
    t = d.index
    weeks = (t[-1] - t[0]).days / 7
    disc = (t < SPLIT)
    start = 300                                       # ATR warm-up
    rows = []

    def add(name, ctx, side, mask, ncand):
        mask = mask.copy()
        mask[:start] = False
        idx = np.flatnonzero(mask[:-1])
        if len(idx) == 0:
            return
        lows = np.minimum.reduce([shift(l, k) if k else l for k in range(ncand)])
        highs = np.maximum.reduce([shift(h, k) if k else h for k in range(ncand)])
        slv = (lows if side == 1 else highs)[idx]
        for rr in RRS:
            r = simulate(o, h, l, c, s, a, idx, side, slv, rr, MAXH)
            ok = ~np.isnan(r)
            if ok.sum() < 30:
                continue
            ri, di = r[ok], disc[idx[ok]]
            win = ri >= rr - 1e-9
            rows.append({"data": data, "tf": tf, "pattern": name, "side": "buy" if side == 1 else "sell", "context": ctx,
                         "RR": f"1:{rr:g}", "trades": int(ok.sum()), "per week": round(ok.sum() / weeks, 2),
                         "win %": round(win.mean() * 100, 1), "R/trade": round(float(ri.mean()), 3),
                         "net R": round(float(ri.sum()), 1),
                         "disc win %": round(win[di].mean() * 100, 1) if di.any() else np.nan,
                         "disc R/t": round(float(ri[di].mean()), 3) if di.any() else np.nan,
                         "check win %": round(win[~di].mean() * 100, 1) if (~di).any() else np.nan,
                         "check R/t": round(float(ri[~di].mean()), 3) if (~di).any() else np.nan,
                         "check trades": int((~di).sum())})

    bull_c, bear_c = c > o, c < o
    add("baseline: every candle", "any", 1, bull_c | bear_c, 1)
    add("baseline: every candle", "any", -1, bull_c | bear_c, 1)
    for name, (mb, ms, n) in patterns(d).items():
        first_ll = shift(ll.astype(float), n - 1) > 0 if n > 1 else ll
        first_hh = shift(hh.astype(float), n - 1) > 0 if n > 1 else hh
        for ctx, cb, cs in (("any", np.ones(len(o), bool), np.ones(len(o), bool)),
                            ("after a move against", first_ll, first_hh),
                            ("after a move with", first_hh, first_ll)):
            add(name, ctx, 1, mb & cb, n)
            add(name, ctx, -1, ms & cs, n)
    return rows


def main():
    rows = []
    m1 = b.load_data("M1")
    for tf, mins in (("M5", 5), ("M15", 15), ("M30", 30), ("H1", 60), ("H4", 240), ("D1", 1440)):
        rows += run_tf(resample(m1, mins), tf, "ours")
    files = sorted(glob.glob("data/M3_exness/*.csv"))
    if files:
        ex = m3.load_mt5(files)
        ex.index = m3.utc_to_backtest_clock(ex.index)
        for tf, mins in (("M15", 15), ("M30", 30), ("H1", 60), ("H4", 240), ("D1", 1440)):
            rows += run_tf(resample(ex, mins), tf, "exness")
    df = pd.DataFrame(rows)
    df.to_csv("results/candles_scan.csv", index=False)
    pd.set_option("display.width", 250, "display.max_rows", 300)
    cols = ["tf", "pattern", "side", "context", "trades", "per week", "win %", "R/trade", "disc win %", "check win %",
            "check R/t"]

    base = df[df.pattern.str.startswith("baseline")]
    print("Baseline (a trade after every candle, SL at its extreme): win % by timeframe and RR, our data")
    print(base[base.data == "ours"].pivot_table(index=["tf", "side"], columns="RR", values="win %").to_string())

    # a pattern counts only if it beats the baseline of its timeframe/side/RR in BOTH halves of our data
    # and on Exness (where that timeframe exists)
    key = ["tf", "side", "RR"]
    bw = base.set_index(["data"] + key)["win %"]
    pat = df[~df.pattern.str.startswith("baseline")].copy()
    pat["baseline win %"] = [bw.get((r.data, r.tf, r.side, r.RR), np.nan) for r in pat.itertuples()]
    pat["edge"] = pat["win %"] - pat["baseline win %"]
    ours = pat[pat.data == "ours"]
    exn = pat[pat.data == "exness"].set_index(["tf", "pattern", "side", "context", "RR"])
    for rr in ("1:1", "1:2", "1:3"):
        x = ours[(ours.RR == rr) & (ours["trades"] >= 150) & (ours["check trades"] >= 40)].copy()
        x["exness win %"] = [exn["win %"].get((r.tf, r.pattern, r.side, r.context, r.RR), np.nan) for r in x.itertuples()]
        x["exness R/t"] = [exn["R/trade"].get((r.tf, r.pattern, r.side, r.context, r.RR), np.nan) for r in x.itertuples()]
        x = x.sort_values("win %", ascending=False)
        print(f"\n===== RR {rr}: highest win % on our data (>= 150 trades), with the check period and Exness =====")
        print(x[cols + ["baseline win %", "exness win %", "exness R/t"]].head(20).to_string(index=False))
        good = x[(x["R/trade"] > 0) & (x["disc R/t"] > 0) & (x["check R/t"] > 0) &
                 ((x["exness R/t"] > 0) | x["exness R/t"].isna())]
        print(f"\nRR {rr}: profitable in the discovery AND check period AND on Exness: {len(good)} of {len(x)}; "
              "best by R/trade:")
        print(good.sort_values("R/trade", ascending=False)[cols + ["baseline win %", "exness win %", "exness R/t"]]
              .head(15).to_string(index=False))


if __name__ == "__main__":
    main()
