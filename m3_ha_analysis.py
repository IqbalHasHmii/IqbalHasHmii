"""M3 Heikin Ashi buy: what is different between the trades that reach the TP and the ones that hit
the SL, and does a filter built on that difference hold up on data it was not found on?

Strategy (m3_ha_test.py): two strong bullish Heikin Ashi candles, close above EMA(4000) on M3,
ATR(14) at or above its 9200-candle average, candle hour 20:00-00:59 on the strategy clock.
Entry at the next open, SL 2 x ATR, TP 1:3, time stop 2300 candles. Every signal is a trade.

Each trade gets a set of "conditions at the signal candle" (trend, momentum, volatility, time,
position in the day's range, ...). They are compared between TP and SL trades.

  Discovery : Exness 2021-11..2024-10 (the period the strategy was picked on).
  Check     : Exness 2020-01..2021-10 (never used) and 2024-11..2026-11 (P3), plus our data.

A filter counts only if it also improves the check periods.

    python m3_ha_analysis.py      # -> results/m3_ha_analysis.txt
"""
from __future__ import annotations

import glob

import numpy as np
import pandas as pd

import backtest as b
import m3_ha_test as m3
from mass_search import resample
from strategy_library import atr, ema, ha_open, rsi

RR = 3.0
DISC = (pd.Timestamp("2021-11-01"), pd.Timestamp("2024-11-01"))
CHECKS = [("2020-01..2021-10 never used", pd.Timestamp("2000-01-01"), pd.Timestamp("2021-11-01")),
          ("2024-11..2026-11 P3", pd.Timestamp("2024-11-01"), pd.Timestamp("2100-01-01"))]

NAMES = {
    "hour": "signal hour (strategy clock)",
    "weekday": "weekday (0 = Monday)",
    "atr_ratio": "ATR / its 20-day average",
    "ema_dist": "close above EMA4000, in ATRs",
    "ema_slope": "EMA4000 rise over 5 hours, in ATRs",
    "trend_42d": "close above EMA20000 (~42 days), in ATRs",
    "ha_body": "last HA candle body, in ATRs",
    "candle_body": "last real candle body, in ATRs",
    "ret_1h": "move over the last hour, in ATRs",
    "ret_5h": "move over the last 5 hours, in ATRs",
    "ret_1d": "move over the last day, in ATRs",
    "day_range_pos": "position in the last 24 h range (0 = low, 1 = high)",
    "below_day_high": "distance below the 24 h high, in ATRs",
    "rsi": "RSI(14) on M3",
    "sl_pct": "SL size, % of price",
    "open_before": "trades of this strategy already open",
    "prev_R": "R of the previous closed trade",
}


def features(d: pd.DataFrame, t: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c = (d[k] for k in ("open", "high", "low", "close"))
    a = atr(d)
    e4, e20 = ema(c, 4000), ema(c, 20000)
    hac = ((o + h + l + c) / 4).to_numpy()
    hao = ha_open(o.to_numpy(), hac)
    hi, lo = h.rolling(480).max(), l.rolling(480).min()
    i = t.i.to_numpy()
    av = a.to_numpy()
    f = pd.DataFrame(index=t.index)
    f["hour"] = d.index.hour[i]
    f["weekday"] = d.index.weekday[i]
    f["atr_ratio"] = (a / a.rolling(9200).mean()).to_numpy()[i]
    f["ema_dist"] = ((c - e4) / a).to_numpy()[i]
    f["ema_slope"] = ((e4 - e4.shift(100)) / a).to_numpy()[i]
    f["trend_42d"] = ((c - e20) / a).to_numpy()[i]
    f["ha_body"] = (hac - hao)[i] / av[i]
    f["candle_body"] = ((c - o) / a).to_numpy()[i]
    f["ret_1h"] = ((c - c.shift(20)) / a).to_numpy()[i]
    f["ret_5h"] = ((c - c.shift(100)) / a).to_numpy()[i]
    f["ret_1d"] = ((c - c.shift(480)) / a).to_numpy()[i]
    f["day_range_pos"] = ((c - lo) / (hi - lo)).to_numpy()[i]
    f["below_day_high"] = ((hi - c) / a).to_numpy()[i]
    f["rsi"] = rsi(c, 14).to_numpy()[i]
    f["sl_pct"] = (2 * a / c * 100).to_numpy()[i]
    ent, ext = t.entry.to_numpy(), t.exit.to_numpy()
    f["open_before"] = [int(((ent[:k] <= ent[k]) & (ext[:k] > ent[k])).sum()) for k in range(len(t))]
    prev = []
    for k in range(len(t)):
        done = np.flatnonzero(ext[:k] <= ent[k])
        prev.append(t.R.iat[done[np.argmax(ext[done])]] if len(done) else np.nan)
    f["prev_R"] = prev
    return f


def paths(d: pd.DataFrame, t: pd.DataFrame) -> pd.DataFrame:
    """Best and worst price before the exit candle, in R, and the time in the trade."""
    o, h, l, spr = (d[k].to_numpy(np.float64) for k in ("open", "high", "low", "spread_px"))
    rows = []
    for i, x, dist in zip(t.i.to_numpy(), t.exit_i.to_numpy(), t.sl.to_numpy()):
        e = o[i + 1] + spr[i + 1]
        if x > i + 1:
            mfe, mae = (h[i + 1:x].max() - e) / dist, (e - l[i + 1:x].min()) / dist
        else:
            mfe = mae = 0.0
        rows.append((max(mfe, 0.0), max(mae, 0.0), (x - i) * 3 / 60))
    return pd.DataFrame(rows, columns=["mfe", "mae", "hours"], index=t.index)


def stats(r: pd.Series) -> str:
    if r.empty:
        return "no trades"
    return f"{len(r):4d} tr, TP {(r >= RR - 0.001).mean() * 100:4.1f}%, {r.mean():+.3f}R/t, net {r.sum():+6.0f}R"


def analyse(label: str, d: pd.DataFrame):
    t = m3.ha_trades(d).reset_index(drop=True)
    f = features(d, t)
    p = paths(d, t)
    tp = t.R >= RR - 0.001
    disc = ((t.entry >= DISC[0]) & (t.entry < DISC[1])).to_numpy()
    print(f"\n======== {label}: {len(t)} trades (every signal), {stats(t.R)} ========")
    for name, s_, e_ in [("discovery 2021-11..2024-10", *DISC)] + CHECKS:
        m = (t.entry >= s_) & (t.entry < e_)
        print(f"  {name:28s}: {stats(t.R[m])}")

    print("\nHow the trades moved (all periods):")
    sl_tr = ~tp & (t.R < 0)
    print(f"  TP trades: median {p.hours[tp].median():.0f} h to the TP; {(p.mae[tp] >= 0.5).mean() * 100:.0f}% went "
          f"-0.5R against first, {(p.mae[tp] >= 0.8).mean() * 100:.0f}% went -0.8R against first")
    print(f"  SL trades: median {p.hours[sl_tr].median():.0f} h to the SL; best point before the SL: "
          f"{(p.mfe[sl_tr] < 0.5).mean() * 100:.0f}% never reached +0.5R, {(p.mfe[sl_tr] >= 1).mean() * 100:.0f}% "
          f"reached +1R, {(p.mfe[sl_tr] >= 2).mean() * 100:.0f}% reached +2R")
    print(f"  time stop: {(~tp & (t.R >= 0)).sum()} closed in profit, {((t.R < 0) & (t.R > -0.999)).sum()} in loss before the SL")

    print("\nConditions at the signal: median for TP trades vs SL trades (discovery period)")
    rows = []
    for k in NAMES:
        a_, b_ = f.loc[disc & tp.to_numpy(), k], f.loc[disc & sl_tr.to_numpy(), k]
        rows.append({"condition": NAMES[k], "TP trades": round(float(a_.median()), 2), "SL trades": round(float(b_.median()), 2)})
    print(pd.DataFrame(rows).to_string(index=False))

    print("\nR per trade by fifth of each condition (edges from the discovery period):")
    summary = []
    for k in NAMES:
        x = f[k]
        edges = np.unique(np.nanquantile(x[disc], [0, 0.2, 0.4, 0.6, 0.8, 1]))
        if len(edges) < 3:
            continue
        edges[0], edges[-1] = -np.inf, np.inf
        bk = pd.cut(x, edges, labels=False)
        rd = [t.R[disc & (bk == j).to_numpy()].mean() for j in range(len(edges) - 1)]
        chk = ~disc & (t.entry < pd.Timestamp("2100-01-01")).to_numpy()
        rc = [t.R[chk & (bk == j).to_numpy()].mean() for j in range(len(edges) - 1)]
        corr = float(pd.Series(rd).corr(pd.Series(rc)))
        summary.append((k, max(rd) - min(rd), corr))
        lab = [f"<{edges[1]:.2f}"] + [f"{edges[j]:.2f}-{edges[j + 1]:.2f}" for j in range(1, len(edges) - 2)] + [f">{edges[-2]:.2f}"]
        print(f"  {NAMES[k]}")
        print("     " + " | ".join(f"{lb}: {u:+.2f} / {v:+.2f}" for lb, u, v in zip(lab, rd, rc)) + "   (discovery / check)")
    print("\nConditions ranked by how much R/trade changes across the fifths, and whether the check periods agree "
          "(correlation of the fifths, 1 = same pattern):")
    for k, spread, corr in sorted(summary, key=lambda z: -z[1]):
        print(f"  {NAMES[k]:52s} spread {spread:.2f}R, agreement {corr:+.2f}")
    return t, f


def filters(label: str, t: pd.DataFrame, f: pd.DataFrame, rules: dict):
    print(f"\n-------- {label}: candidate filters (every signal / max 3 open as in the EA) --------")
    for name, keep in rules.items():
        x = t[keep(f).to_numpy()]
        capped = m3.cap_open(x, 3)
        cells = []
        for pname, s_, e_ in [("disc", *DISC)] + [(c[0].split()[0], c[1], c[2]) for c in CHECKS]:
            m = (x.entry >= s_) & (x.entry < e_)
            if m.any():
                cells.append(f"{pname}: {x.R[m].mean():+.2f}R/t ({m.sum()})")
        eq = capped.sort_values("exit").R.cumsum()
        print(f"  {name:44s} {' | '.join(cells)}")
        print(f"  {'':44s} all: {stats(x.R)} | max 3 open: {stats(capped.R)}, DD {(eq - eq.cummax()).min():.0f}R")


RULES = {
    "no filter (current strategy)": lambda f: pd.Series(True, index=f.index),
    "skip hour 0 (00:00-00:59)": lambda f: f.hour != 0,
    "only 20:00-22:59": lambda f: f.hour.isin([20, 21, 22]),
    "close at most 6 ATR above EMA4000": lambda f: f.ema_dist <= 6,
    "close at least 2 ATR above EMA4000": lambda f: f.ema_dist >= 2,
    "ATR at most 1.6x its average": lambda f: f.atr_ratio <= 1.6,
    "last hour move up at most 4 ATR": lambda f: f.ret_1h <= 4,
    "at least 1 ATR below the 24 h high": lambda f: f.below_day_high >= 1,
    "above EMA20000 (~42 days)": lambda f: f.trend_42d > 0,
    "no other trade of the strategy open": lambda f: f.open_before == 0,
}


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    ex = m3.load_mt5(sorted(glob.glob("data/M3_exness/*.csv")))
    ex.index = m3.utc_to_backtest_clock(ex.index)
    te, fe = analyse("Exness M3 2020-01..2026-11", ex)
    filters("Exness", te, fe, RULES)
    to, fo = analyse("Our data, M1 -> M3, 2021-11..2026-10", resample(b.load_data("M1"), 3))
    filters("Our data", to, fo, RULES)
