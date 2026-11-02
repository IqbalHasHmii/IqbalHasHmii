"""XAUUSD backtester for MT5-exported CSV data.

Usage:
    python backtest.py --strategy ema_cross --tf H1 --balance 10000 --risk 1

Data lives in data/<TF>/ (H1, M15, M5) as tab-separated MT5 exports.

Execution model (kept deliberately conservative):
  * Signals are computed on a bar's CLOSE; the trade opens at the NEXT bar's OPEN.
  * MT5 prices are BID. Buys fill at ask (bid + spread), sells at bid.
    A buy closes at bid, a sell closes at ask (bid + spread).
  * The spread for each bar comes from the CSV's <SPREAD> column (points, 1 point = 0.01).
  * If stop loss and take profit are both inside the same bar, the stop loss is assumed
    to have been hit first (we cannot know the intrabar order on H1 data).
  * One position at a time. Lot size = (equity * risk%) / (stop distance * contract size).
"""

from __future__ import annotations

import argparse
import glob
import os

import numpy as np
import pandas as pd

import strategies

HERE = os.path.dirname(os.path.abspath(__file__))
POINT = 0.01          # XAUUSD point size
CONTRACT = 100        # 1 lot = 100 oz -> $100 per $1 price move
MIN_LOT, LOT_STEP = 0.01, 0.01


def load_data(tf: str = "H1", folder: str = os.path.join(HERE, "data")) -> pd.DataFrame:
    folder = os.path.join(folder, tf)
    frames = []
    for path in sorted(glob.glob(os.path.join(folder, "*.csv"))):
        df = pd.read_csv(path, sep="\t")
        df.columns = [c.strip("<>").lower() for c in df.columns]
        df["time"] = pd.to_datetime(df["date"] + " " + df["time"], format="%Y.%m.%d %H:%M:%S")
        frames.append(df[["time", "open", "high", "low", "close", "tickvol", "spread"]])
    if not frames:
        raise SystemExit(f"No CSV files found in {folder}")
    df = pd.concat(frames).drop_duplicates("time").sort_values("time").set_index("time")
    df["spread_px"] = df["spread"] * POINT
    return df


def run(df: pd.DataFrame, balance: float, risk_pct: float, commission_per_lot: float,
        exit_on_opposite: bool) -> tuple[pd.DataFrame, pd.Series]:
    """Simulate trades.

    Required columns: signal, sl_dist, tp_dist.
    Optional columns: entry_price + valid_bars. When entry_price is set on a signal bar, a
    LIMIT order is placed at that (bid-chart) price and stays active for `valid_bars` bars;
    otherwise the trade opens at market on the next bar's open.
    """
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    spr = df["spread_px"].to_numpy()
    sig = df["signal"].fillna(0).to_numpy()
    sl_d = df["sl_dist"].to_numpy()
    tp_d = df["tp_dist"].to_numpy()
    lim = df["entry_price"].to_numpy() if "entry_price" in df else np.full(len(df), np.nan)
    valid = df["valid_bars"].to_numpy() if "valid_bars" in df else np.ones(len(df))
    times = df.index

    equity = balance
    eq_curve = np.full(len(df), np.nan)
    trades = []
    pos = None      # open trade
    pending = None  # unfilled limit order
    n_orders = n_filled = 0

    def close(i, price, reason):
        nonlocal equity, pos
        d = pos["dir"]
        pnl = (price - pos["entry"]) * d * pos["lots"] * CONTRACT - pos["lots"] * commission_per_lot
        equity += pnl
        trades.append({
            "signal_time": pos["signal_time"], "entry_time": pos["time"], "exit_time": times[i],
            "direction": "BUY" if d == 1 else "SELL",
            "entry": round(pos["entry"], 2), "exit": round(price, 2), "sl": round(pos["sl"], 2),
            "tp": round(pos["tp"], 2), "lots": pos["lots"], "pnl": round(pnl, 2),
            "r_multiple": round(pnl / pos["risk_usd"], 2), "reason": reason, "equity": round(equity, 2),
        })
        pos = None

    def open_pos(i, d, entry, sl_dist, tp_dist, signal_time):
        nonlocal pos
        risk_usd = equity * risk_pct / 100
        lots = np.floor(risk_usd / (sl_dist * CONTRACT) / LOT_STEP) * LOT_STEP
        lots = round(max(lots, MIN_LOT), 2)
        pos = {"dir": d, "entry": entry, "lots": lots, "time": times[i], "signal_time": signal_time,
               "sl": entry - d * sl_dist, "tp": entry + d * tp_dist,
               "risk_usd": lots * sl_dist * CONTRACT}

    for i in range(1, len(df)):
        s, k = sig[i - 1], i - 1
        fresh = False  # True when the position was opened inside this bar (not at its open)

        # 1) act on the previous bar's signal
        if pos is not None and exit_on_opposite and s == -pos["dir"]:
            close(i, o[i] if pos["dir"] == 1 else o[i] + spr[i], "opposite signal")
        if pos is None and s != 0 and np.isfinite(sl_d[k]) and sl_d[k] > 0 and equity > 0:
            if np.isfinite(lim[k]):
                pending = {"dir": int(s), "price": lim[k], "last_bar": k + int(valid[k]),
                           "sl": sl_d[k], "tp": tp_d[k], "signal_time": times[k]}
                n_orders += 1
            else:
                d = int(s)
                open_pos(i, d, o[i] + spr[i] if d == 1 else o[i], sl_d[k], tp_d[k], times[k])

        # 2) try to fill a pending limit order on this bar
        if pending is not None and pos is None:
            if i > pending["last_bar"]:
                pending = None
            else:
                d, p = pending["dir"], pending["price"]
                fill = None
                if d == 1:   # buy limit triggers on ask
                    if o[i] + spr[i] <= p:
                        fill = o[i] + spr[i]
                    elif l[i] + spr[i] <= p:
                        fill, fresh = p, True
                else:        # sell limit triggers on bid
                    if o[i] >= p:
                        fill = o[i]
                    elif h[i] >= p:
                        fill, fresh = p, True
                if fill is not None:
                    open_pos(i, d, fill, pending["sl"], pending["tp"], pending["signal_time"])
                    pending = None
                    n_filled += 1

        # 3) manage the open trade on this bar. On a bar where a limit filled mid-bar we
        #    only check the stop (we cannot know whether TP came after the fill).
        if pos is not None:
            if pos["dir"] == 1:   # long exits at bid
                if l[i] <= pos["sl"]:
                    close(i, min(pos["sl"], o[i]) if not fresh else pos["sl"], "SL")
                elif not fresh and h[i] >= pos["tp"]:
                    close(i, max(pos["tp"], o[i]), "TP")
            else:                 # short exits at ask = bid + spread
                if h[i] + spr[i] >= pos["sl"]:
                    close(i, max(pos["sl"], o[i] + spr[i]) if not fresh else pos["sl"], "SL")
                elif not fresh and l[i] + spr[i] <= pos["tp"]:
                    close(i, min(pos["tp"], o[i] + spr[i]), "TP")

        # mark-to-market equity
        if pos is not None:
            px = c[i] if pos["dir"] == 1 else c[i] + spr[i]
            eq_curve[i] = equity + (px - pos["entry"]) * pos["dir"] * pos["lots"] * CONTRACT
        else:
            eq_curve[i] = equity

    if pos is not None:
        close(len(df) - 1, c[-1] if pos["dir"] == 1 else c[-1] + spr[-1], "end of data")
        eq_curve[-1] = equity
    eq_curve[0] = balance
    t = pd.DataFrame(trades)
    t.attrs["orders"], t.attrs["filled"] = n_orders, n_filled
    return t, pd.Series(eq_curve, index=times, name="equity")


def report(trades: pd.DataFrame, equity: pd.Series, balance: float) -> str:
    if trades.empty:
        return "No trades were taken."
    wins, losses = trades[trades.pnl > 0], trades[trades.pnl <= 0]
    gross_win, gross_loss = wins.pnl.sum(), -losses.pnl.sum()
    dd = equity / equity.cummax() - 1
    streak = max_streak = 0
    for p in trades.pnl:
        streak = streak + 1 if p <= 0 else 0
        max_streak = max(max_streak, streak)
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    final = equity.iloc[-1]
    cagr = (final / balance) ** (1 / years) - 1 if final > 0 else -1

    lines = [
        f"Period            : {equity.index[0]:%Y-%m-%d} -> {equity.index[-1]:%Y-%m-%d} ({years:.1f} years)",
        f"Starting balance  : ${balance:,.2f}",
        f"Final balance     : ${final:,.2f}",
        f"Net profit        : ${final - balance:,.2f} ({(final / balance - 1) * 100:.1f}%)",
        f"CAGR              : {cagr * 100:.1f}% per year",
        f"Max drawdown      : {dd.min() * 100:.1f}%",
        *([f"Limit orders      : {trades.attrs['orders']} placed, {trades.attrs['filled']} filled "
           f"({trades.attrs['filled'] / trades.attrs['orders'] * 100:.0f}%)"] if trades.attrs.get("orders") else []),
        f"Total trades      : {len(trades)} (BUY {sum(trades.direction == 'BUY')}, SELL {sum(trades.direction == 'SELL')})",
        f"Win rate          : {len(wins) / len(trades) * 100:.1f}%",
        f"Profit factor     : {gross_win / gross_loss:.2f}" if gross_loss else "Profit factor     : inf",
        f"Avg win / loss    : ${wins.pnl.mean() if len(wins) else 0:,.2f} / ${-losses.pnl.mean() if len(losses) else 0:,.2f}",
        f"Expectancy        : {trades.r_multiple.mean():.2f}R per trade",
        f"Max losing streak : {max_streak} trades",
        "",
        "Year-by-year:",
    ]
    t = trades.copy()
    t["year"] = pd.to_datetime(t.exit_time).dt.year
    for y, g in t.groupby("year"):
        wr = (g.pnl > 0).mean() * 100
        lines.append(f"  {y}: {len(g):4d} trades | win {wr:5.1f}% | P/L ${g.pnl.sum():>11,.2f} | {g.r_multiple.sum():+7.1f}R")
    return "\n".join(lines)


def plot(equity: pd.Series, title: str, path: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    dd = (equity / equity.cummax() - 1) * 100
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(12, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    a1.plot(equity.index, equity, color="#2a6fdb", lw=1.2)
    a1.set_title(title)
    a1.set_ylabel("Equity ($)")
    a1.grid(alpha=0.3)
    a2.fill_between(dd.index, dd, 0, color="#d9534f", alpha=0.5)
    a2.set_ylabel("Drawdown (%)")
    a2.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description="Backtest a strategy on XAUUSD H1 data")
    ap.add_argument("--strategy", default="ema_cross", choices=sorted(strategies.REGISTRY))
    ap.add_argument("--tf", default="H1", help="timeframe folder under data/: H1, M15, M5")
    ap.add_argument("--balance", type=float, default=10_000)
    ap.add_argument("--risk", type=float, default=1.0, help="risk per trade, % of equity")
    ap.add_argument("--commission", type=float, default=0.0, help="round-turn commission, $ per lot")
    ap.add_argument("--exit-on-opposite", action="store_true", help="close a trade on an opposite signal")
    ap.add_argument("--out", default=os.path.join(HERE, "results"))
    # parameters for the engulfing strategy (ignored by others)
    ap.add_argument("--pip", type=float, default=0.10, help="price value of 1 pip for gold (0.10 = $0.10)")
    ap.add_argument("--sl-pips", type=float, default=50)
    ap.add_argument("--rr", type=float, default=3.0, help="take profit as a multiple of the stop")
    ap.add_argument("--valid-bars", type=int, default=1, help="bars the limit order stays active")
    ap.add_argument("--swing", type=int, default=3, help="bars each side that confirm an H1 swing point")
    ap.add_argument("--structure", default="bos", choices=["bos", "hhhl"],
                    help="bos = trend flips on a close beyond the last swing; hhhl = HH+HL / LH+LL")
    ap.add_argument("--min-body-atr", type=float, default=0.0,
                    help="optional: skip engulfing candles with body < this x ATR(14)")
    ap.add_argument("--tag", default="", help="suffix for output file names")
    args = ap.parse_args()

    params = dict(pip=args.pip, sl_pips=args.sl_pips, rr=args.rr, valid_bars=args.valid_bars,
                  swing=args.swing, structure=args.structure, min_body_atr=args.min_body_atr)
    df = strategies.REGISTRY[args.strategy](load_data(args.tf), h1=load_data("H1"), tf=args.tf, **params)
    trades, equity = run(df, args.balance, args.risk, args.commission, args.exit_on_opposite)

    os.makedirs(args.out, exist_ok=True)
    name = f"{args.strategy}_{args.tf}{args.tag}"
    text = f"Strategy: {args.strategy} | {args.tf} | risk {args.risk}% | commission ${args.commission}/lot\n"
    if args.strategy != "ema_cross":
        text += (f"SL {args.sl_pips:g} pips (${args.sl_pips * args.pip:g}) | TP 1:{args.rr:g} | "
                 f"structure {args.structure}, swing {args.swing} | limit valid {args.valid_bars} bar(s)"
                 + (f" | min body {args.min_body_atr:g} ATR" if args.min_body_atr else "") + "\n")
    text += "\n"
    text += report(trades, equity, args.balance)
    print(text)
    with open(os.path.join(args.out, f"{name}_report.txt"), "w") as f:
        f.write(text + "\n")
    trades.to_csv(os.path.join(args.out, f"{name}_trades.csv"), index=False)
    plot(equity, f"XAUUSD {args.tf} - {args.strategy}", os.path.join(args.out, f"{name}_equity.png"))


if __name__ == "__main__":
    main()
