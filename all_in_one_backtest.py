"""Backtest of the all-in-one EA (mql5/exness/XAUUSD_All_In_One_EA_Exness.mq5).

The EA runs nine strategies side by side, each with its own magic number and its own limit on
open trades. This script rebuilds each strategy's trades with the same rules and the EA's
default limits, then adds them up. TP = 3 x SL everywhere.

  #  strategy                                     limit         code
  1  M15 Asian range breakout                     1 at a time   m15_search.asia_bo (SL at the other side, range 2-10x)
  2  M15 previous-day high/low sweep              1 at a time   m15_search.sweep (wick + 0.2x, SL 1-5x)
  3  H1 EMA200 engulfing, limit at the open       1 at a time   ema_v3.setups (SL 100 pips, no volume filter) + smc_v2.simulate
  4  M5 RSI pullback                              1 at a time   m5_search.rsi_pb (level 25, SL 1-10x)
  5  M5 New York opening-range breakout           1 at a time   m5_search.ny_orb (SL at the other side, range 2-15x)
  6  M5 Asian range breakout                      1 at a time   m15_search.asia_bo on M5 (range 3.5-25x)
  7  H1 EMA20 pullback, buys and sells            max 5 open    m60_ema20_pullback
  8  M3 Heikin Ashi, buy only                     max 3 open    m3_ha_test
  9  H1 3 higher highs + perfect/strong bearish   no limit      h1_hh_engulf_all_types
     engulfing, sell limit at 25% of the body

R = the risk of one trade. Every trade risks the same % of the account, so the sum of R is the
result without compounding (at 0.25% risk per trade, +100R = +25%).

Data:
  ours   : S1-S2 on data/M15, S3 on data/H1, S4-S6 on data/M5, S7-S9 on data/M1,
           common period 2021-11-01..2026-10-30.
  Exness : the M3 export converted to the strategy clock (UTC+2 / UTC+3), as the EA does, with
           M15 and H1 built from it. M5 candles cannot be built from M3 candles, so S4-S6 are
           left out. 2020-01..2026-11.

    python all_in_one_backtest.py      # -> results/all_in_one_backtest.txt
"""
from __future__ import annotations

import glob

import numpy as np
import pandas as pd

import backtest as b
import m3_ha_test as m3
from ema_v3 import setups as ema200_setups
from h1_hh_engulf import PERIODS
from h1_hh_engulf_25 import limit_trade
from h1_hh_engulf_split import streak
from h1_hh_engulf_types import engulf_types, new_highs_ok
from m15_search import asia_bo, sweep
from m5_search import ny_orb, rsi_pb
from m60_ema20_pullback import capped
from m60_ema20_pullback import trades as ema20_trades
from mass_search import resample
from smc_v2 import simulate as one_order_at_a_time

RR = 3.0
NAMES = {1: "M15 Asian breakout", 2: "M15 prev-day sweep", 3: "H1 EMA200 engulfing", 4: "M5 RSI pullback",
         5: "M5 NY opening range", 6: "M5 Asian breakout", 7: "H1 EMA20 pullback", 8: "M3 Heikin Ashi buy",
         9: "H1 HH engulfing sell"}


# Every trade list has: entry, exit (times), R, tp (the TP was hit) and sl (SL distance in $).
COLS = ["entry", "exit", "R", "tp", "sl"]


def from_run(sig: pd.DataFrame) -> pd.DataFrame:
    """backtest.run: market entry at the next candle's open, one trade at a time."""
    t, _ = b.run(sig, 10_000, 1.0, 0.0, False)
    return pd.DataFrame({"entry": pd.to_datetime(t.entry_time), "exit": pd.to_datetime(t.exit_time),
                         "R": t.r_multiple.astype(float), "tp": t.reason == "TP", "sl": (t.entry - t.sl).abs()})


def s3(h1: pd.DataFrame) -> pd.DataFrame:
    t = one_order_at_a_time(ema200_setups(h1, "both", "fixed", 100, volume_filter=False), 5, hard_sl=True)
    return pd.DataFrame({"entry": pd.to_datetime(t.entry_time), "exit": pd.to_datetime(t.exit_time),
                         "R": t.r_multiple.astype(float), "tp": t.reason == "TP", "sl": t.sl_pips * 0.10})


def s7(fine: pd.DataFrame, cap: int = 5) -> pd.DataFrame:
    t = capped(ema20_trades(fine), cap)
    return t.assign(tp=t.R >= RR - 0.001)[COLS]


def s8(m3d: pd.DataFrame) -> pd.DataFrame:
    t = m3.cap_open(m3.ha_trades(m3d), 3)
    return t.assign(tp=t.tp_hit)[COLS]


def s9(fine: pd.DataFrame) -> pd.DataFrame:
    h1 = resample(fine, 60)
    fh1 = np.searchsorted(h1.index.to_numpy(), fine.index.floor("h").to_numpy())
    flast = np.r_[fh1[1:] != fh1[:-1], True]
    fo, fh, fl, fs = (fine[k].to_numpy(np.float64) for k in ("open", "high", "low", "spread_px"))
    o, h, l, c = (h1[k].to_numpy(np.float64) for k in ("open", "high", "low", "close"))
    ty = engulf_types(h1)
    rows = []
    for i in np.flatnonzero((ty["perfect"] | ty["strong"]) & new_highs_ok(h, 3, 3)):
        st, fj, xj, r = limit_trade(fo, fh, fl, fs, fh1, flast, c, int(np.searchsorted(fh1, i + 1)),
                                    c[i] + 0.25 * (o[i] - c[i]), h[i], l[i], -1, RR)
        if st == 1:
            rows.append((fine.index[fj], fine.index[xj], r, r >= RR - 0.001, h[i] - (c[i] + 0.25 * (o[i] - c[i]))))
    return pd.DataFrame(rows, columns=COLS)


def m15_strategies(m15: pd.DataFrame) -> dict:
    return {1: from_run(asia_bo(m15, sl_mode="full", rr=RR, max_range=10.0)),
            2: from_run(sweep(m15, rr=RR, buffer=0.2, max_sl=5.0))}


def m5_strategies(m5: pd.DataFrame) -> dict:
    return {4: from_run(rsi_pb(m5, rr=RR, level=25, max_sl=10.0)),
            5: from_run(ny_orb(m5, rr=RR, sl_mode="full", max_range=15.0)),
            6: from_run(asia_bo(m5, sl_mode="full", rr=RR, max_range=25.0, min_range=3.5, atr_n=288))}


def drawdown(eq: pd.Series, times: pd.Series):
    eq = eq.to_numpy()
    peak = np.maximum.accumulate(eq)
    k = int((eq - peak).argmin())
    p = int(eq[:k + 1].argmax())
    return eq[k] - peak[k], times.iloc[p], times.iloc[k]


def summary(t: pd.DataFrame, weeks: float, years: float) -> str:
    t = t.sort_values("exit")
    dd, a, z = drawdown(t.R.cumsum(), t.exit)
    ev = pd.concat([pd.DataFrame({"t": t.entry, "d": 1}), pd.DataFrame({"t": t.exit, "d": -1})]).sort_values(["t", "d"])
    return (f"{len(t)} trades ({len(t) / weeks:.1f}/wk), TP {t.tp.mean() * 100:.1f}%, "
            f"{t.R.mean():+.3f}R/trade, net {t.R.sum():+.1f}R ({t.R.sum() / years:+.1f}R a year), "
            f"max drawdown {dd:.1f}R ({a:%Y-%m-%d} -> {z:%Y-%m-%d}), longest losing run {streak(t.R)}, "
            f"most open at once {ev.d.cumsum().max()}")


def report(label: str, parts: dict, start: pd.Timestamp, end: pd.Timestamp, s7_one: pd.DataFrame | None = None):
    """s7_one: strategy 7 with one trade at a time, for the comparison line."""
    weeks = (end - start).days / 7
    years = (end - start).days / 365.25
    parts = {k: t[(t.entry >= start) & (t.entry < end)].sort_values("exit").reset_index(drop=True)
             for k, t in parts.items()}
    print(f"\n===== {label}: {start:%Y-%m-%d} -> {end:%Y-%m-%d} ({years:.1f} years) =====")
    rows = []
    for k, t in parts.items():
        dd, _, _ = drawdown(t.R.cumsum(), t.exit)
        last = t[t.entry >= end - pd.Timedelta(days=365)]
        rows.append({"#": k, "strategy": NAMES[k], "trades": len(t), "per week": round(len(t) / weeks, 1),
                     "TP %": round(float(t.tp.mean() * 100), 1), "R/trade": round(float(t.R.mean()), 3),
                     "net R": round(float(t.R.sum()), 1), "R a year": round(float(t.R.sum() / years), 1),
                     "max DD R": round(float(dd), 1), "SL $ (last year)": round(float(last.sl.median()), 1),
                     "balance for 0.01 lot at 0.25%": int(round(float(last.sl.median()) * 1.0 / 0.0025, -2))})
    print(pd.DataFrame(rows).to_string(index=False))
    print("(SL $ = median SL distance of the last 12 months' trades. 0.01 lot of gold = 1 oz, so a $1 move is $1:\n"
          " below that balance the EA's lot size at 0.25% risk rounds under 0.01 and the trade is skipped.)")
    allt = pd.concat([t.assign(s=k) for k, t in parts.items()]).sort_values("exit").reset_index(drop=True)
    dflt = allt[allt.s != 7]                               # the EA default: strategy 7 off
    print(f"\nEA DEFAULTS (7 off)   : {summary(dflt, weeks, years)}")
    if 7 in parts:
        print(f"7 ON, max 5 open      : {summary(allt, weeks, years)}")
    if 7 in parts and s7_one is not None:
        one = s7_one[(s7_one.entry >= start) & (s7_one.entry < end)].assign(s=7)[COLS + ["s"]]
        print(f"7 ON, max 1 open      : {summary(pd.concat([dflt, one]), weeks, years)}")
    for name, x in (("EA defaults", dflt), ("7 on, max 5", allt)):
        per = [f"{plab.split()[0]}: {len(y)} tr {y.R.mean():+.3f}R/t {y.R.sum():+.0f}R" for plab, s_, e_ in PERIODS
               if len(y := x[(x.entry >= s_) & (x.entry < e_)])]
        print(f"by period ({name}): " + " | ".join(per))
    yr = allt.pivot_table(index=allt.exit.dt.year, columns="s", values="R", aggfunc="sum").fillna(0).round(0)
    yr.columns = [f"S{k}" for k in yr.columns]
    yr["EA default"] = dflt.groupby(dflt.exit.dt.year).R.sum().reindex(yr.index).fillna(0).round(0)
    if 7 in parts:
        yr["7 on"] = yr["EA default"] + yr["S7"]
    yr.index.name = "year"
    print("\nnet R by year (exit year):")
    print(yr.astype(int).to_string())
    mo = dflt.groupby(dflt.exit.dt.to_period("M")).R.sum()
    print(f"\nEA defaults: {len(mo)} months, losing months {(mo < 0).sum()} ({(mo < 0).mean() * 100:.0f}%), "
          f"worst month {mo.min():+.1f}R ({mo.idxmin()}), best month {mo.max():+.1f}R ({mo.idxmax()})")
    dd, _, _ = drawdown(dflt.R.cumsum(), dflt.exit)
    for risk in (0.1, 0.25, 0.5):
        print(f"EA defaults at {risk:.2f}% risk per trade: about {dflt.R.sum() / years * risk:+.0f}% a year, "
              f"max drawdown about {dd * risk:.0f}% (no compounding)")


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    m1 = b.load_data("M1")
    ours = {**m15_strategies(b.load_data("M15")), 3: s3(b.load_data("H1")), **m5_strategies(b.load_data("M5")),
            7: s7(m1), 8: s8(resample(m1, 3)), 9: s9(m1)}
    report("Our data, all 9 strategies", dict(sorted(ours.items())), pd.Timestamp("2021-11-01"), pd.Timestamp("2026-10-31"),
           s7(m1, 1))

    files = sorted(glob.glob("data/M3_exness/*.csv"))
    if files:
        ex = m3.load_mt5(files)
        ex.index = m3.utc_to_backtest_clock(ex.index)      # Exness UTC+0 -> strategy clock, as the EA does
        exn = {**m15_strategies(resample(ex, 15)), 3: s3(resample(ex, 60)), 7: s7(ex), 8: s8(ex), 9: s9(ex)}
        report("Exness M3 data, strategies 1-3 and 7-9 (no M5 candles)", exn,
               pd.Timestamp("2020-01-02"), pd.Timestamp("2026-11-03"), s7(ex, 1))
