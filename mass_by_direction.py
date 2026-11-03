"""Buy vs sell vs both, per timeframe, from the two mass-search runs.

    python mass_by_direction.py      # -> results/mass_search_by_direction.csv, results/mass_search_best_by_direction.csv
"""
import numpy as np
import pandas as pd

KEY = ["tf", "trigger", "trend", "session", "vol", "sl_atr", "direction"]
res = pd.concat([pd.read_csv("results/mass_search.csv.gz"), pd.read_csv("results/mass_search_m1_m10.csv.gz")])
res = res.drop_duplicates(KEY)
el = res[(res.IS_n >= 150) & (res.OOS_n >= 50)].copy()
p = el["IS_win%"] / 100
el["IS_t"] = el["IS_R/trade"] / (4 * np.sqrt(p * (1 - p)).clip(lower=1e-6)) * np.sqrt(el.IS_n)

rows, best = [], []
for (tf, d), g in el.groupby(["tf", "direction"]):
    top = g.nlargest(20, "IS_t")
    rows.append({"tf": tf, "direction": d, "strategies": len(g),
                 "% profitable both periods": round(((g["IS_R/trade"] > 0) & (g["OOS_R/trade"] > 0)).mean() * 100, 1),
                 "top20 IS win%": round(top["IS_win%"].mean(), 1), "top20 IS R/trade": round(top["IS_R/trade"].mean(), 3),
                 "top20 OOS win%": round(top["OOS_win%"].mean(), 1), "top20 OOS R/trade": round(top["OOS_R/trade"].mean(), 3),
                 "top20 % OOS profitable": round((top["OOS_R/trade"] > 0).mean() * 100)})
    best.append(g.nlargest(1, "IS_t"))
summary = pd.DataFrame(rows)
summary.to_csv("results/mass_search_by_direction.csv", index=False)
cols = KEY + ["IS_per_week", "IS_win%", "IS_R/trade", "OOS_per_week", "OOS_win%", "OOS_R/trade"]
bestdf = pd.concat(best)[cols].round(3)
bestdf.to_csv("results/mass_search_best_by_direction.csv", index=False)
pd.set_option("display.width", 250, "display.max_rows", 200)
for d in ("buy_only", "sell_only", "both"):
    print(f"\n=== {d} ===")
    print(summary[summary.direction == d].drop(columns="direction").to_string(index=False))
    print(bestdf[bestdf.direction == d].drop(columns="direction").to_string(index=False))
