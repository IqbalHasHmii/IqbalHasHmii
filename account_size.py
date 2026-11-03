"""How big the account has to be for the all-in-one EA (EA defaults, strategy 7 off).

The EA sizes every trade at InpRiskPercent of the account and skips a trade when that lot is
below the broker's minimum:
  normal account: 0.01 lot = 1 oz of gold (10 pips = $1);
  cent account:   0.01 cent lot = 0.01 oz.
Gold's SL distances in $ grew with its price and volatility, so this uses the trades of the last
12 months of each dataset (today's sizes), with the EA's lot rule on a fixed balance:

  ounces = floor(balance x risk / SL $ / step) x step   (skipped below one step)

The trades come from all_in_one_backtest.py. One year is a short sample; the long-run drawdown of
the EA defaults was 45R (our data) and 66R (Exness), i.e. 11% / 17% at 0.25% risk.

    python account_size.py      # -> results/account_size.txt
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from all_in_one_backtest import EXNESS, OURS, drawdown, exness_parts, ours_parts


def sized(t: pd.DataFrame, balance: float, risk: float, step_oz: float) -> dict:
    oz = np.floor(balance * risk / t.sl.to_numpy() / step_oz + 1e-9) * step_oz
    take = oz >= step_oz
    x = t[take].assign(pnl=t.move[take] * oz[take]).sort_values("exit")
    dd = drawdown(x.pnl.cumsum(), x.exit)[0] if len(x) else 0.0
    by_s = (t.assign(taken=take).groupby("s")["taken"].mean() * 100).round(0).astype(int)
    return {"balance": f"${balance:,.0f}", "trades taken": f"{take.mean() * 100:.0f}%",
            "per week": round(len(x) / 52.18, 1), "profit in 12 months": f"${x.pnl.sum():,.0f}",
            "% of balance": f"{x.pnl.sum() / balance * 100:+.0f}%",
            "max drawdown": f"${dd:,.0f} ({dd / balance * 100:.0f}%)",
            "taken by strategy": " ".join(f"S{k}:{v}%" for k, v in by_s.items())}


def run(label: str, parts: dict, end: pd.Timestamp):
    start = end - pd.Timedelta(days=365)
    t = pd.concat([x.assign(s=k) for k, x in parts.items() if k != 7])      # EA defaults: 7 off
    t = t[(t.entry >= start) & (t.entry < end)].reset_index(drop=True)
    print(f"\n===== {label}: trades of {start:%Y-%m-%d} -> {end:%Y-%m-%d} ({len(t)} trades, "
          f"{t.R.sum():+.0f}R at full size) =====")
    print("SL in $ per 0.01 lot (median / 90th percentile): " + ", ".join(
        f"S{k} {g.median():.0f}/{g.quantile(0.9):.0f}" for k, g in t.groupby("s").sl))
    pd.set_option("display.width", 250, "display.max_colwidth", 80)
    for name, risk, step, balances in (
            ("normal account, 0.25% risk (EA default)", 0.0025, 1.0, (1000, 2000, 3000, 5000, 7500, 10000, 15000, 25000, 50000)),
            ("normal account, 0.5% risk", 0.005, 1.0, (1000, 2000, 3000, 5000, 10000, 25000)),
            ("cent account, 0.25% risk (EA default)", 0.0025, 0.01, (100, 250, 500, 1000))):
        print(f"\n{name}:")
        print(pd.DataFrame([sized(t, bal, risk, step) for bal in balances]).to_string(index=False))
    # month by month for $100 on a cent account (fixed balance)
    oz = np.floor(100 * 0.0025 / t.sl.to_numpy() / 0.01 + 1e-9) * 0.01
    x = t[oz >= 0.01].assign(pnl=(t.move * oz)[oz >= 0.01])
    mo = x.groupby(x.exit.dt.to_period("M")).agg(trades=("pnl", "size"), profit=("pnl", "sum"))
    mo = mo[mo.index >= start.to_period("M")]
    print(f"\n$100 cent account, 0.25% risk, month by month ($): " +
          ", ".join(f"{m.strftime('%b %y')} {v:+.2f}" for m, v in mo.profit.items()))
    print(f"   average {mo.profit.mean():+.2f}/month, best {mo.profit.max():+.2f}, worst {mo.profit.min():+.2f}, "
          f"losing months {(mo.profit < 0).sum()} of {len(mo)}")
    # trades per month, by strategy: every trade (balance big enough) and $100 on a cent account
    months = 12.0
    full = t.groupby("s").size() / months
    small = x.groupby("s").size().reindex(full.index).fillna(0) / months
    print("trades per month (last 12 months), every trade / $100 cent account: " +
          ", ".join(f"S{k} {a:.1f}/{b:.1f}" for k, a, b in zip(full.index, full, small)) +
          f" | total {full.sum():.0f} / {small.sum():.0f}")
    per_m = t.groupby(t.entry.dt.to_period("M")).size()
    per_m = per_m[(per_m.index > start.to_period("M")) & (per_m.index < end.to_period("M"))]
    print(f"   whole months: fewest {per_m.min()}, most {per_m.max()} trades (every trade)")


if __name__ == "__main__":
    parts, _ = ours_parts()
    run("Our data", parts, OURS[1])
    parts, _ = exness_parts()
    if parts:
        run("Exness data (no M5 strategies)", parts, EXNESS[1])
