"""Summaries of results/mass_search.csv.gz (run mass_search.py first).

    python mass_analyze.py     # -> results/mass_search_by_tf.csv, results/mass_search_top.csv

Eligible = at least 150 in-sample trades (about 1 a week) and 50 out-of-sample trades.
Strategies are ranked ONLY on in-sample numbers (t-stat of the average R); the out-of-sample
columns show how the picks did on data that was not used to pick them.
"""
import numpy as np
import pandas as pd

res = pd.read_csv("results/mass_search.csv.gz")
el = res[(res.IS_n >= 150) & (res.OOS_n >= 50)].copy()
p = el["IS_win%"] / 100
el["IS_t"] = el["IS_R/trade"] / (4 * np.sqrt(p * (1 - p)).clip(lower=1e-6)) * np.sqrt(el.IS_n)

rows = []
for tf, g in el.groupby("tf"):
    top = g.nlargest(20, "IS_t")
    rows.append({"tf": f"M{tf}", "eligible": len(g),
                 "median IS win%": round(g["IS_win%"].median(), 1),
                 "% IS profitable": round((g["IS_R/trade"] > 0).mean() * 100, 1),
                 "% IS and OOS profitable": round(((g["IS_R/trade"] > 0) & (g["OOS_R/trade"] > 0)).mean() * 100, 1),
                 "top20 IS R/trade": round(top["IS_R/trade"].mean(), 3),
                 "top20 OOS R/trade": round(top["OOS_R/trade"].mean(), 3),
                 "top20 OOS win%": round(top["OOS_win%"].mean(), 1),
                 "top20 % OOS profitable": round((top["OOS_R/trade"] > 0).mean() * 100)})
by_tf = pd.DataFrame(rows)
by_tf.to_csv("results/mass_search_by_tf.csv", index=False)

cols = ["tf", "trigger", "trend", "session", "vol", "sl_atr", "direction", "IS_per_week", "IS_win%",
        "IS_R/trade", "IS_t", "OOS_per_week", "OOS_win%", "OOS_R/trade"]
top = el.nlargest(50, "IS_t")[cols].round(3)
top.to_csv("results/mass_search_top.csv", index=False)

pd.set_option("display.width", 250, "display.max_rows", 100)
print(f"{len(res):,} strategies tested, {len(el):,} eligible\n")
print(by_tf.to_string(index=False))
print("\nTop 50 by in-sample t-stat (all timeframes):")
print(top.to_string(index=False))
print(f"\nTop 50: {(top['OOS_R/trade'] > 0).mean() * 100:.0f}% profitable out-of-sample, "
      f"average OOS {top['OOS_R/trade'].mean():+.3f}R/trade vs IS {top['IS_R/trade'].mean():+.3f}")
