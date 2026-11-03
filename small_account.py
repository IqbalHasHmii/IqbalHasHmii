"""What the all-in-one EA (EA defaults, strategy 7 off) would have done on a $100 account.

It uses the trades of all_in_one_backtest.py. The profit of a trade in $ is its price move per
ounce (after the spread) times the ounces traded. One 0.01 lot of gold = 1 oz, so at 0.02 lot
10 pips ($1.00) = $2.

Scenarios:
  A  normal USD account, fixed 0.02 lot (InpRiskPercent = 0, InpFixedLots = 0.02)
  B  normal USD account, fixed 0.01 lot
  C  the EA default, 0.25% risk per trade, on a normal USD account: the lot rounds below 0.01,
     so every trade is skipped
  D  cent account: $100 = 10,000 USC, the EA default 0.25% risk. One cent lot is 1/100 of a
     standard lot (0.01 cent lot of gold = 0.01 oz), so the EA can size the trades. A trade whose
     lot still rounds below 0.01 cent lot is skipped, as the EA does.

Fixed lots: the account is wiped out when the balance of the closed trades reaches $0. The
floating losses of open trades come on top of that, so in MT5 the stop-out would come at least
as early. Every month start is tried as the start date.

    python small_account.py      # -> results/small_account.txt
"""
from __future__ import annotations

import heapq

import numpy as np
import pandas as pd

from all_in_one_backtest import EXNESS, OURS, exness_parts, ours_parts

START = 100.0


def fixed_lot(t: pd.DataFrame, oz: float, start: pd.Timestamp, end: pd.Timestamp) -> str:
    t = t.sort_values("exit")
    pnl = t.move * oz
    out = []
    starts = pd.date_range(start, end - pd.DateOffset(years=1), freq="MS")
    ruined, days, after_year = 0, [], []
    for s in starts:
        x = pnl[t.entry.to_numpy() >= np.datetime64(s)]
        bal = START + x.cumsum()
        hit = np.flatnonzero(bal.to_numpy() <= 0)
        if len(hit):
            ruined += 1
            days.append((t.exit.loc[bal.index[hit[0]]] - s).days)
        else:
            yr = t.exit.loc[bal.index] < s + pd.DateOffset(years=1)
            after_year.append(START + x[yr.to_numpy()].sum())
    eq = pnl.cumsum().to_numpy()
    dd = (eq - np.maximum.accumulate(eq)).min()
    first = START + pnl[t.entry >= start].cumsum()
    hit = np.flatnonzero(first.to_numpy() <= 0)
    last = t[t.entry >= end - pd.Timedelta(days=365)]
    med = (last.groupby("s").sl.median() * oz).round(0).astype(int)
    out.append(f"    one SL loses (last 12 months): median ${(last.sl * oz).median():.0f}; by strategy "
               + ", ".join(f"S{k} ${v}" for k, v in med.items()))
    out.append(f"    started on {start:%Y-%m-%d}: " + (f"wiped out on {t.exit.loc[first.index[hit[0]]]:%Y-%m-%d} "
               f"after {hit[0] + 1} closed trades" if len(hit) else f"never wiped out, ended at ${first.iloc[-1]:,.0f}"))
    out.append(f"    {len(starts)} start months tried: wiped out in {ruined} ({ruined / len(starts) * 100:.0f}%)"
               + (f", median {np.median(days):.0f} days after the start, fastest {min(days)} days" if days else ""))
    if after_year:
        out.append(f"    the {len(after_year)} that survived had a median ${np.median(after_year):,.0f} after one year")
    out.append(f"    biggest drop from a high at this lot size: ${-dd:,.0f}, so the account needs more than "
               f"that to survive it")
    return "\n".join(out)


def percent_risk(t: pd.DataFrame, risk: float, min_oz: float, start: pd.Timestamp, end: pd.Timestamp) -> str:
    """Lots from the balance at each entry (compounding); min_oz = smallest position in ounces."""
    x = t.sort_values("entry")
    bal, peak, dd = START, START, 0.0
    heap, taken, skipped = [], 0, 0
    yearly, month_end = {}, {}

    def close_until(when):
        nonlocal bal, peak, dd
        while heap and heap[0][0] <= when:
            et, p = heapq.heappop(heap)
            bal += p
            peak = max(peak, bal)
            dd = min(dd, bal / peak - 1)
            yearly[et.year] = bal
            month_end[et.to_period("M")] = bal

    for row in x.itertuples():
        close_until(row.entry)
        oz = np.floor(bal * risk / row.sl / min_oz + 1e-9) * min_oz
        if oz < min_oz:
            skipped += 1
            continue
        taken += 1
        heapq.heappush(heap, (row.exit, row.move * oz))
    close_until(pd.Timestamp.max)
    weeks = (end - start).days / 7
    years = (end - start).days / 365.25
    out = [f"    trades taken {taken} ({taken / weeks:.1f}/wk), skipped (lot below the minimum) {skipped}"]
    if taken:
        out.append(f"    ${START:.0f} -> ${bal:,.0f} after {years:.1f} years "
                   f"(about {((bal / START) ** (1 / years) - 1) * 100:+.0f}% a year compounded), "
                   f"max drawdown {dd * 100:.0f}%")
        out.append("    balance at the end of each year: " + ", ".join(f"{y}: ${v:,.0f}" for y, v in yearly.items()))
        months = pd.period_range(start, end - pd.Timedelta(days=1), freq="M")
        eom = pd.Series(month_end).reindex(months).ffill().fillna(START)
        ret = eom / eom.shift(1).fillna(START) - 1
        first = (eom.diff().fillna(eom.iloc[0] - START)).iloc[:12]
        out.append(f"    monthly return: average {ret.mean() * 100:+.1f}%, median {ret.median() * 100:+.1f}%, "
                   f"best {ret.max() * 100:+.1f}%, worst {ret.min() * 100:+.1f}%, losing months {(ret < 0).sum()} of "
                   f"{len(ret)} ({(ret < 0).mean() * 100:.0f}%)")
        out.append("    first 12 months in $: " + ", ".join(f"{m.strftime('%b %y')} {v:+.1f}" for m, v in first.items()))
    return "\n".join(out)


def run(label: str, parts: dict, start: pd.Timestamp, end: pd.Timestamp):
    t = pd.concat([x.assign(s=k) for k, x in parts.items() if k != 7])      # EA defaults: 7 off
    t = t[(t.entry >= start) & (t.entry < end)].reset_index(drop=True)
    print(f"\n===== {label}: {start:%Y-%m-%d} -> {end:%Y-%m-%d}, strategies {sorted(int(k) for k in t.s.unique())}, start ${START:.0f} =====")
    print("A) normal account, fixed 0.02 lot (10 pips = $2):")
    print(fixed_lot(t, 2.0, start, end))
    print("B) normal account, fixed 0.01 lot (10 pips = $1):")
    print(fixed_lot(t, 1.0, start, end))
    print("C) normal account, EA default 0.25% risk:")
    print(percent_risk(t, 0.0025, 1.0, start, end))
    print("D) cent account ($100 = 10,000 USC), EA default 0.25% risk (smallest trade 0.01 oz):")
    print(percent_risk(t, 0.0025, 0.01, start, end))


if __name__ == "__main__":
    parts, _ = ours_parts()
    run("Our data", parts, *OURS)
    parts, _ = exness_parts()
    if parts:
        run("Exness data (no M5 strategies)", parts, *EXNESS)
