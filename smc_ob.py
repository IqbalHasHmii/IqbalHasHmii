"""SMC Extreme Order Block strategy (H1 signals, M15 trade monitoring).

Strict rules
------------
1. Body engulfing on H1
   BUY : previous candle red, current green, Close >= prev Open AND Open <= prev Close.
   SELL: previous candle green, current red, Close <= prev Open AND Open >= prev Close.
   The engulfing candle's body must be bigger than its wicks (upper + lower combined).
2. Volume exhaustion: engulfing tick volume <= previous candle's tick volume.
3. SMC structure on H1
   Swing High: High strictly higher than the 5 candles to the left and the 2 to the right
   (Swing Low mirrored). A swing is confirmed only after its 2 right-hand candles have closed.
   Bullish once an H1 candle closes above the most recent confirmed Swing High -> buys only.
   Bearish once an H1 candle closes below the most recent confirmed Swing Low -> sells only.
4. Extreme OB entry and exit
   Entry: limit order exactly at the engulfing candle's OPEN (never at market).
   SL   : engulfing candle's wick (Low for buys, High for sells).
          Setup skipped if |entry - wick| > 50 pips (1 pip = $0.10 -> $5).
   Stop-hunt protection: no hard stop at the wick. The trade is closed in loss when an H1
          candle CLOSES beyond the SL wick, at that H1 close price.
   Liquidity sweep: if an H1 candle takes the wick's liquidity (trades beyond it) but closes
          back inside, then after that candle closes the SL is placed at that candle's wick
          (its Low for buys, High for sells) as a normal stop.
   TP   : fixed 1:3 of the entry-to-wick distance, a normal take-profit order.

Settings that the rules leave open (all can be changed from the command line)
  * The limit order is valid for the next H1 candle only (--valid-hours).
  * One trade or pending order at a time. New signals are ignored while a trade is open.
  * A setup whose wick distance is 0 (engulfing open == wick) cannot be sized and is skipped.
  * Position size (--sizing):
      wick  : --risk % of equity over the entry-to-wick distance (1 lot = 100 oz)
      max   : --risk % of equity over the 50-pip max SL distance (smaller, steadier lots)
      fixed : always --fixed-lots

Fill and exit modelling on M15 bars (prices in the CSV are BID)
  * Buy limit fills when ask (bid + spread) reaches the price; sell limit when bid does.
  * TP is checked on every M15 bar after the fill bar (on the fill bar itself we cannot know
    whether TP came after the fill, so it is not counted).
  * At every H1 close the close is compared with the SL wick.

Usage:
    python smc_ob.py                     # strict rules
    python smc_ob.py --valid-hours 3     # keep the limit order for 3 H1 candles
"""

from __future__ import annotations

import argparse
import os

import numpy as np
import pandas as pd

from backtest import CONTRACT, HERE, LOT_STEP, MIN_LOT, load_data, plot, report


# ----------------------------------------------------------------- signals (H1)
def swing_points(h1: pd.DataFrame, left: int = 5, right: int = 2):
    """Boolean arrays: is the bar a swing high / swing low (strictly beyond neighbours)."""
    hi, lo = h1.high.to_numpy(), h1.low.to_numpy()
    n = len(h1)
    sh = np.zeros(n, bool)
    sl = np.zeros(n, bool)
    for j in range(left, n - right):
        nb_hi = np.r_[hi[j - left:j], hi[j + 1:j + 1 + right]]
        nb_lo = np.r_[lo[j - left:j], lo[j + 1:j + 1 + right]]
        sh[j] = hi[j] > nb_hi.max()
        sl[j] = lo[j] < nb_lo.min()
    return sh, sl


def smc_structure(h1: pd.DataFrame, left: int = 5, right: int = 2) -> np.ndarray:
    """+1 bullish / -1 bearish / 0 unknown, as known at the close of each H1 bar."""
    sh, sl = swing_points(h1, left, right)
    hi, lo, cl = h1.high.to_numpy(), h1.low.to_numpy(), h1.close.to_numpy()
    trend = np.zeros(len(h1), int)
    last_sh = last_sl = np.nan
    t = 0
    for i in range(len(h1)):
        j = i - right                      # swing at j is confirmed when bar i closes
        if j >= 0:
            if sh[j]:
                last_sh = hi[j]
            if sl[j]:
                last_sl = lo[j]
        if not np.isnan(last_sh) and cl[i] > last_sh:
            t = 1
        elif not np.isnan(last_sl) and cl[i] < last_sl:
            t = -1
        trend[i] = t
    return trend


def signals(h1: pd.DataFrame, pip: float = 0.10, max_sl_pips: float = 50,
            left: int = 5, right: int = 2, body_filter: bool = True) -> pd.DataFrame:
    df = h1.copy()
    df["trend"] = smc_structure(h1, left, right)
    po, pc, pv = df.open.shift(), df.close.shift(), df.tickvol.shift()
    vol_ok = df.tickvol <= pv
    bull = (pc < po) & (df.close > df.open) & (df.close >= po) & (df.open <= pc) & vol_ok
    bear = (pc > po) & (df.close < df.open) & (df.close <= po) & (df.open >= pc) & vol_ok
    if body_filter:   # engulfing body must be bigger than its wicks (upper + lower combined)
        body = (df.close - df.open).abs()
        wicks = (df.high - df.low) - body
        bull &= body > wicks
        bear &= body > wicks
    df["raw"] = np.select([bull & (df.trend == 1), bear & (df.trend == -1)], [1, -1], 0)
    df["entry"] = df.open
    df["sl"] = np.where(df.raw == 1, df.low, df.high)
    df["sl_dist"] = (df.entry - df.sl).abs()
    too_wide = df.sl_dist > max_sl_pips * pip
    zero = df.sl_dist <= 0
    df["signal"] = np.where(too_wide | zero, 0, df.raw)
    df["skip_reason"] = np.select([(df.raw != 0) & too_wide, (df.raw != 0) & zero], ["SL > max", "SL = 0"], "")
    return df


# ----------------------------------------------------------------- simulation (M15)
def simulate(sig: pd.DataFrame, m15: pd.DataFrame, balance: float = 10_000, risk_pct: float = 1.0,
             rr: float = 3.0, valid_hours: int = 1, commission: float = 0.0, max_lots: float = 100.0,
             sizing: str = "wick", size_dist: float = 5.0, fixed_lots: float = 0.10,
             hard_sl: bool = False, sweep_sl: bool = True):
    h1_times = sig.index
    h1_pos = {t: k for k, t in enumerate(h1_times)}
    h1_close = sig.close.to_numpy()
    s_sig, s_entry, s_sl, s_dist = (sig[c].to_numpy() for c in ("signal", "entry", "sl", "sl_dist"))

    mt = m15.index
    hour = mt.floor("h")
    o, h, l, c = (m15[k].to_numpy() for k in ("open", "high", "low", "close"))
    spr = m15["spread_px"].to_numpy()
    last_in_hour = np.r_[hour[1:] != hour[:-1], True]

    equity = balance
    eq = np.empty(len(m15))
    trades, pos, pending = [], None, None
    stats = {"orders": 0, "filled": 0}

    def close_trade(i, price, reason):
        nonlocal equity, pos
        d = pos["dir"]
        pnl = (price - pos["entry"]) * d * pos["lots"] * CONTRACT - pos["lots"] * commission
        equity += pnl
        trades.append({
            "signal_time": pos["signal_time"], "entry_time": pos["entry_time"], "exit_time": mt[i],
            "direction": "BUY" if d == 1 else "SELL", "entry": round(pos["entry"], 2),
            "sl_wick": round(pos["sl"], 2), "tp": round(pos["tp"], 2), "sl_pips": round(pos["dist"] / 0.1, 1),
            "sweep_sl": round(pos["moved_sl"], 2) if np.isfinite(pos["moved_sl"]) else None,
            "exit": round(price, 2), "lots": pos["lots"], "pnl": round(pnl, 2),
            "r_multiple": round(pnl / pos["risk_usd"], 2), "reason": reason, "equity": round(equity, 2),
        })
        pos = None

    for i in range(len(m15)):
        k = h1_pos.get(hour[i])
        fresh = False

        # fill a pending limit order
        if pending is not None and pos is None:
            if k is None or k > pending["last_h1"]:
                if k is not None:
                    pending = None
            elif k > pending["signal_h1"]:
                d, p = pending["dir"], pending["entry"]
                fill = None
                if d == 1:
                    if o[i] + spr[i] <= p:
                        fill = o[i] + spr[i]
                    elif l[i] + spr[i] <= p:
                        fill, fresh = p, True
                else:
                    if o[i] >= p:
                        fill = o[i]
                    elif h[i] >= p:
                        fill, fresh = p, True
                if fill is not None:
                    dist = pending["dist"]
                    if sizing == "fixed":
                        lots = fixed_lots
                    else:
                        basis = dist if sizing == "wick" else size_dist
                        lots = np.floor(equity * risk_pct / 100 / (basis * CONTRACT) / LOT_STEP) * LOT_STEP
                        lots = round(min(max(lots, MIN_LOT), max_lots), 2)
                    # R is always measured against the wick distance (the rule's 1R)
                    pos = {"dir": d, "entry": fill, "sl": pending["sl"], "dist": dist,
                           "swept": False, "sweep_ext": np.nan, "moved_sl": np.nan,
                           "tp": p + d * rr * dist, "lots": lots, "risk_usd": lots * dist * CONTRACT,
                           "entry_time": mt[i], "signal_time": pending["signal_time"]}
                    pending = None
                    stats["filled"] += 1

        # COMPARISON ONLY (--hard-sl): a normal broker stop at the wick, which the strict
        # rules do NOT use. Checked before TP (worst case when both are inside one M15 bar).
        if hard_sl and pos is not None:
            if pos["dir"] == 1 and l[i] <= pos["sl"]:
                close_trade(i, pos["sl"] if fresh else min(pos["sl"], o[i]), "SL (hard)")
            elif pos["dir"] == -1 and h[i] + spr[i] >= pos["sl"]:
                close_trade(i, pos["sl"] if fresh else max(pos["sl"], o[i] + spr[i]), "SL (hard)")

        # Liquidity-sweep stop: once a candle has taken the engulfing wick's liquidity and
        # closed, the SL sits at that candle's wick and works as a normal stop.
        if sweep_sl and pos is not None and np.isfinite(pos["moved_sl"]):
            ms = pos["moved_sl"]
            if pos["dir"] == 1 and l[i] <= ms:
                close_trade(i, ms if fresh else min(ms, o[i]), "SL (sweep candle)")
            elif pos["dir"] == -1 and h[i] + spr[i] >= ms:
                close_trade(i, ms if fresh else max(ms, o[i] + spr[i]), "SL (sweep candle)")
        # track whether this H1 candle is taking the engulfing wick's liquidity
        if sweep_sl and pos is not None and not np.isfinite(pos["moved_sl"]):
            if pos["dir"] == 1 and l[i] < pos["sl"]:
                pos["swept"] = True
                pos["sweep_ext"] = np.nanmin([pos["sweep_ext"], l[i]])
            elif pos["dir"] == -1 and h[i] > pos["sl"]:
                pos["swept"] = True
                pos["sweep_ext"] = np.nanmax([pos["sweep_ext"], h[i]])

        # take profit (intrabar, M15)
        if pos is not None and not fresh:
            if pos["dir"] == 1 and h[i] >= pos["tp"]:
                close_trade(i, max(pos["tp"], o[i]), "TP")
            elif pos["dir"] == -1 and l[i] + spr[i] <= pos["tp"]:
                close_trade(i, min(pos["tp"], o[i] + spr[i]), "TP")

        # H1 close: stop-hunt-protected stop loss, then new signals
        if last_in_hour[i] and k is not None:
            hc = h1_close[k]
            if pos is not None:
                if pos["dir"] == 1 and hc < pos["sl"]:
                    close_trade(i, hc, "SL (H1 close)")
                elif pos["dir"] == -1 and hc > pos["sl"]:
                    close_trade(i, hc + spr[i], "SL (H1 close)")
                elif sweep_sl and pos["swept"] and not np.isfinite(pos["moved_sl"]):
                    pos["moved_sl"] = pos["sweep_ext"]   # sweep candle closed back inside
            if pos is None and s_sig[k] != 0 and equity > 0:
                pending = {"dir": int(s_sig[k]), "entry": s_entry[k], "sl": s_sl[k], "dist": s_dist[k],
                           "signal_h1": k, "last_h1": k + valid_hours, "signal_time": h1_times[k]}
                stats["orders"] += 1

        if pos is not None:
            px = c[i] if pos["dir"] == 1 else c[i] + spr[i]
            eq[i] = equity + (px - pos["entry"]) * pos["dir"] * pos["lots"] * CONTRACT
        else:
            eq[i] = equity

    if pos is not None:
        close_trade(len(m15) - 1, c[-1] if pos["dir"] == 1 else c[-1] + spr[-1], "end of data")
        eq[-1] = equity
    t = pd.DataFrame(trades)
    t.attrs.update(stats)
    return t, pd.Series(eq, index=mt, name="equity")


def main() -> None:
    ap = argparse.ArgumentParser(description="SMC Extreme OB strategy backtest (H1 + M15)")
    ap.add_argument("--balance", type=float, default=10_000)
    ap.add_argument("--risk", type=float, default=1.0, help="risk per trade, % of equity")
    ap.add_argument("--rr", type=float, default=3.0)
    ap.add_argument("--pip", type=float, default=0.10)
    ap.add_argument("--max-sl-pips", type=float, default=50)
    ap.add_argument("--valid-hours", type=int, default=1, help="H1 candles the limit order stays active")
    ap.add_argument("--commission", type=float, default=0.0, help="round-turn $ per lot")
    ap.add_argument("--max-lots", type=float, default=100.0, help="broker max volume per order")
    ap.add_argument("--sizing", default="wick", choices=["wick", "max", "fixed"])
    ap.add_argument("--fixed-lots", type=float, default=0.10)
    ap.add_argument("--hard-sl", action="store_true",
                    help="COMPARISON ONLY: normal stop at the wick instead of the H1-close rule")
    ap.add_argument("--no-body-filter", action="store_true", help="old rule 1 (no body > wick check)")
    ap.add_argument("--no-sweep-sl", action="store_true", help="old rule 4 (H1-close stop only)")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    h1, m15 = load_data("H1"), load_data("M15")
    sig = signals(h1, args.pip, args.max_sl_pips, body_filter=not args.no_body_filter)
    trades, equity = simulate(sig, m15, args.balance, args.risk, args.rr, args.valid_hours,
                              args.commission, args.max_lots, args.sizing, args.max_sl_pips * args.pip,
                              args.fixed_lots, args.hard_sl, not args.no_sweep_sl)

    raw = sig[sig.raw != 0]
    head = (f"Strategy: SMC Extreme OB | H1 signals, M15 monitoring | risk {args.risk}% | "
            f"sizing {args.sizing}{' | HARD SL (comparison)' if args.hard_sl else ''} | TP 1:{args.rr:g} | max SL {args.max_sl_pips:g} pips | limit valid {args.valid_hours} H1 candle(s)\n"
            f"Setups found: {len(raw)} | skipped SL > {args.max_sl_pips:g} pips: {(raw.skip_reason == 'SL > max').sum()}"
            f" | skipped SL = 0: {(raw.skip_reason == 'SL = 0').sum()}\n\n")
    text = head + report(trades, equity, args.balance)
    if not trades.empty:
        sl = trades[trades.reason.str.startswith("SL")]
        text += ("\n\nExit reasons: " + ", ".join(f"{k} {v}" for k, v in trades.reason.value_counts().items())
                 + f"\nAverage loss on SL exits: {sl.r_multiple.mean():.2f}R | worst trade: {trades.r_multiple.min():.2f}R"
                 + f"\nLots used: median {trades.lots.median():.2f}, max {trades.lots.max():.2f}")
    print(text)

    out = os.path.join(HERE, "results")
    os.makedirs(out, exist_ok=True)
    name = f"smc_ob{args.tag}"
    with open(os.path.join(out, f"{name}_report.txt"), "w") as f:
        f.write(text + "\n")
    trades.to_csv(os.path.join(out, f"{name}_trades.csv"), index=False)
    plot(equity.resample("1h").last().dropna(), "XAUUSD SMC Extreme OB (H1 + M15)",
         os.path.join(out, f"{name}_equity.png"))


if __name__ == "__main__":
    main()
