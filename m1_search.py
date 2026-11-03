"""The m15_search.py strategy families on M1 candles.

Same three families (Asian-range breakout, previous-day high/low sweep, EMA pullback), but
the signals and the exits run on 1-minute candles. Limits are in units of the average M1
candle range of the last day (1,440 candles). Because one M1 candle is about a quarter of an
M15 candle, the range / SL multipliers are about 4x the M15 ones.

Parameters are judged on 2021-11..2024-10 (in-sample) and checked on 2024-11..2026-10
(out-of-sample), with real spread, next-candle-open entries and SL first when SL and TP share
a candle (backtest.run). M1 data goes in data/M1/ (MT5 export, not committed: ~100 MB).

    python m1_search.py      # about 5 minutes -> results/m1_search.csv
"""
import itertools

import pandas as pd

import backtest as b
from m15_search import SPLIT, asia_bo, pullback, stats, sweep

GRIDS = {
    "asia_bo": (asia_bo, {"sl_mode": ["mid", "full"], "rr": [1.5, 2.0, 3.0], "max_range": [25.0, 40.0, 60.0]},
                {"min_range": 8.0}),
    "sweep": (sweep, {"rr": [1.5, 2.0, 3.0], "buffer": [0.5, 1.5], "max_sl": [5.0, 10.0]}, {"min_sl": 1.5}),
    "pullback": (pullback, {"rr": [1.5, 2.0, 3.0], "buffer": [0.5, 1.5], "max_sl": [6.0, 12.0]}, {"min_sl": 2.0}),
}

if __name__ == "__main__":
    m = b.load_data("M1")
    start, end = m.index[0], m.index[-1]
    rows = []
    for name, (fn, grid, fixed) in GRIDS.items():
        keys = list(grid)
        for vals in itertools.product(*(grid[k] for k in keys)):
            p = dict(zip(keys, vals))
            t, _ = b.run(fn(m, atr_n=1440, **fixed, **p), 10_000, 1.0, 0.0, False)
            ins, oos = stats(t, start, SPLIT), stats(t, SPLIT, end)
            rows.append({"strategy": name, "params": p,
                         **{f"IS_{k}": v for k, v in ins.items()}, **{f"OOS_{k}": v for k, v in oos.items()}})
            print(rows[-1], flush=True)
    out = pd.DataFrame(rows)
    out.to_csv("results/m1_search.csv", index=False)
    pd.set_option("display.width", 250, "display.max_colwidth", 60, "display.max_rows", 200)
    print(out.to_string(index=False))
