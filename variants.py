"""Run the engulfing strategy with several settings on every timeframe and print one table."""
import pandas as pd

import backtest as b
import strategies as s

VARIANTS = {
    "Base (aap ke rules)":         {},
    "Limit 3 candles tak valid":   {"valid_bars": 3},
    "Structure = HH/HL":           {"structure": "hhhl"},
    "Swing 5 (bada structure)":    {"swing": 5},
    "Engulfing body >= 0.5 ATR":   {"min_body_atr": 0.5},
    "SL 100 pips, TP 1:3":         {"sl_pips": 100},
    "SL 50 pips, TP 1:2":          {"rr": 2},
}

h1 = b.load_data("H1")
rows = []
for tf in ("H1", "M15", "M5"):
    data = b.load_data(tf)
    for name, p in VARIANTS.items():
        df = s.engulfing_retrace(data, h1, tf, **p)
        t, eq = b.run(df, 10_000, 1.0, 0.0, False)
        gw, gl = t.pnl[t.pnl > 0].sum(), -t.pnl[t.pnl <= 0].sum()
        rows.append({"TF": tf, "Variant": name, "Trades": len(t),
                     "Win%": round((t.pnl > 0).mean() * 100, 1), "PF": round(gw / gl, 2),
                     "Net%": round((eq.iloc[-1] / 10_000 - 1) * 100, 1),
                     "MaxDD%": round((eq / eq.cummax() - 1).min() * 100, 1),
                     "Exp(R)": round(t.r_multiple.mean(), 3)})
out = pd.DataFrame(rows)
print(out.to_string(index=False))
out.to_csv("results/engulfing_variants.csv", index=False)
