"""Compare the strict SMC Extreme OB rules with a few one-change variations (fixed 0.10 lot)."""
import pandas as pd

from backtest import load_data
from smc_ob import signals, simulate

h1, m15 = load_data("H1"), load_data("M15")
sig = signals(h1)
VARIANTS = {
    "Strict rules (limit valid 1 H1 candle)": {},
    "Limit valid 3 H1 candles": {"valid_hours": 3},
    "Limit valid until filled (24 H1 candles)": {"valid_hours": 24},
    "COMPARE: hard SL at wick (no stop-hunt rule)": {"hard_sl": True},
    "COMPARE: hard SL + limit valid 3": {"hard_sl": True, "valid_hours": 3},
}
rows = []
for name, p in VARIANTS.items():
    t, eq = simulate(sig, m15, sizing="fixed", fixed_lots=0.10, **p)
    gw, gl = t.pnl[t.pnl > 0].sum(), -t.pnl[t.pnl <= 0].sum()
    yearly = t.groupby(pd.to_datetime(t.exit_time).dt.year).pnl.sum()
    rows.append({"Variant": name, "Trades": len(t), "Win%": round((t.pnl > 0).mean() * 100, 1),
                 "PF": round(gw / gl, 2), "Net $ (0.1 lot)": round(t.pnl.sum(), 0),
                 "MaxDD $": round((eq - eq.cummax()).min(), 0),
                 "Losing years": f"{(yearly < 0).sum()}/{len(yearly)}"})
out = pd.DataFrame(rows)
print(out.to_string(index=False))
out.to_csv("results/smc_ob_variants.csv", index=False)
