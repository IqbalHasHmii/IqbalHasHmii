"""H1 SMC structure + engulfing retracement, SELL entries, SL 50..100 pips at 1:3.

Rules (strategies.engulfing_retrace with volume_filter=False):
  1. H1 structure (swing 3, BOS on close) must be bearish for a sell (bullish for a buy).
  2. A bearish engulfing candle closes on H1 (body covers the previous bullish body).
  3. Sell limit at the engulfing candle's OPEN, valid only for the next candle (retracement).
  4. SL = 50..100 pips (1 pip = $0.10), TP = 3 x SL.

    python sl_sweep.py               # sells only (default)
    python sl_sweep.py --side both   # buys + sells
"""
import argparse

import pandas as pd

import backtest as b
import strategies as s

ap = argparse.ArgumentParser()
ap.add_argument("--side", default="sell", choices=["sell", "buy", "both"])
ap.add_argument("--volume-filter", action="store_true", help="also require engulfing tickvol < previous")
ap.add_argument("--valid-bars", type=int, default=1)
args = ap.parse_args()

h1 = b.load_data("H1")
trading_days = h1.index.normalize().nunique()
rows = []
for sl in (50, 60, 70, 80, 90, 100):
    df = s.engulfing_retrace(h1, h1, "H1", sl_pips=sl, rr=3.0, side=args.side,
                             volume_filter=args.volume_filter, valid_bars=args.valid_bars)
    t, eq = b.run(df, 10_000, 1.0, 0.0, False)
    tp, slh = (t.reason == "TP").sum(), (t.reason == "SL").sum()
    pips = ((t.exit - t.entry) * t.direction.map({"BUY": 1, "SELL": -1}) / 0.10).sum()
    gw, gl = t.pnl[t.pnl > 0].sum(), -t.pnl[t.pnl <= 0].sum()
    rows.append({
        "SL pips": sl, "TP pips": sl * 3,
        "Signals": int((df.signal != 0).sum()), "Trades": len(t),
        "TP hit": int(tp), "SL hit": int(slh),
        "TP %": round(tp / len(t) * 100, 1),
        "Trades/day": round(len(t) / trading_days, 2),
        "Net pips": round(pips),
        "Net R": round(t.r_multiple.sum(), 1),
        "PF": round(gw / gl, 2),
        "Net % (1% risk)": round((eq.iloc[-1] / 10_000 - 1) * 100, 1),
        "Max DD %": round((eq / eq.cummax() - 1).min() * 100, 1),
    })
    t.to_csv(f"results/engulf_{args.side}_sl{sl}_trades.csv", index=False)

out = pd.DataFrame(rows)
print(f"XAUUSD H1 | {h1.index[0]:%Y-%m-%d} -> {h1.index[-1]:%Y-%m-%d} | {trading_days} trading days | "
      f"side={args.side} | volume filter={'on' if args.volume_filter else 'off'} | RR 1:3")
print(out.to_string(index=False))
out.to_csv(f"results/engulf_{args.side}_sl_sweep.csv", index=False)
