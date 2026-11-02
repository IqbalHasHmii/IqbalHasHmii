"""Strategies. Each one takes the OHLC DataFrame and returns it with three extra columns:

    signal   :  1 = buy, -1 = sell, 0 = nothing (decided on the bar's close)
    sl_dist  :  stop-loss distance in price ($), e.g. 15.0 = $15 away from entry
    tp_dist  :  take-profit distance in price ($)

To add your own strategy, write a function like the ones below and add it to REGISTRY.
"""

import numpy as np
import pandas as pd


# ---------- indicators ----------
def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["close"].shift()
    tr = pd.concat([df.high - df.low, (df.high - prev).abs(), (df.low - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


# ---------- strategies ----------
def ema_cross(df: pd.DataFrame, **_) -> pd.DataFrame:
    """EXAMPLE: EMA 20/50 crossover in the direction of the EMA 200 trend.
    BUY  when EMA20 crosses above EMA50 and close > EMA200.
    SELL when EMA20 crosses below EMA50 and close < EMA200.
    SL = 1.5 x ATR(14), TP = 3 x ATR(14)  (1:2 risk/reward)."""
    df = df.copy()
    f, s, t = ema(df.close, 20), ema(df.close, 50), ema(df.close, 200)
    a = atr(df, 14)
    up = (f > s) & (f.shift() <= s.shift())
    dn = (f < s) & (f.shift() >= s.shift())
    df["signal"] = np.select([up & (df.close > t), dn & (df.close < t)], [1, -1], 0)
    df.loc[df.index[:200], "signal"] = 0   # indicator warm-up
    df["sl_dist"] = 1.5 * a
    df["tp_dist"] = 3.0 * a
    return df


def h1_structure(h1: pd.DataFrame, swing: int = 3, mode: str = "bos") -> pd.Series:
    """Market structure on H1: +1 bullish, -1 bearish, 0 unknown.

    A swing high is a bar whose high is the highest of `swing` bars on each side (same for
    lows). It is only known `swing` bars later, so it is used from that bar onward (no look-ahead).
      bos  : bullish once a candle CLOSES above the last swing high, bearish once it closes
             below the last swing low (break of structure).
      hhhl : bullish when the last two swing highs AND lows are rising (HH + HL),
             bearish when both are falling (LH + LL), otherwise 0.
    """
    hi, lo, cl = h1.high.to_numpy(), h1.low.to_numpy(), h1.close.to_numpy()
    n, w = len(h1), 2 * swing + 1
    roll_hi = h1.high.rolling(w, center=True).max().to_numpy()
    roll_lo = h1.low.rolling(w, center=True).min().to_numpy()
    is_sh = hi == roll_hi
    is_sl = lo == roll_lo

    trend = np.zeros(n, dtype=int)
    highs, lows = [], []   # confirmed swing prices, oldest -> newest
    t = 0
    for i in range(n):
        j = i - swing      # the pivot candidate that becomes confirmed at bar i
        if j >= swing:
            if is_sh[j]:
                highs.append(hi[j])
            if is_sl[j]:
                lows.append(lo[j])
        if mode == "bos":
            if highs and cl[i] > highs[-1]:
                t = 1
            elif lows and cl[i] < lows[-1]:
                t = -1
        else:
            if len(highs) >= 2 and len(lows) >= 2:
                if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
                    t = 1
                elif highs[-1] < highs[-2] and lows[-1] < lows[-2]:
                    t = -1
                else:
                    t = 0
        trend[i] = t
    return pd.Series(trend, index=h1.index, name="structure")


TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240}


def engulfing_retrace(df: pd.DataFrame, h1: pd.DataFrame, tf: str = "H1", pip: float = 0.10,
                      sl_pips: float = 50, rr: float = 3.0, valid_bars: int = 1, swing: int = 3,
                      structure: str = "bos", min_body_atr: float = 0.0, **_) -> pd.DataFrame:
    """User strategy:
    1. H1 structure decides direction (bullish -> only buys, bearish -> only sells).
    2. On the trading timeframe an engulfing candle forms in that direction AND its tick
       volume is LOWER than the previous candle's tick volume.
    3. Place a limit order at the engulfing candle's OPEN; it fills only if price retraces
       there within `valid_bars` candle(s) (default: the very next candle).
    4. SL = `sl_pips` pips, TP = `rr` x SL.
    Optional (off by default): `min_body_atr` ignores engulfing candles whose body is
    smaller than that fraction of ATR(14) on the trading timeframe.
    """
    df = df.copy()
    st = h1_structure(h1, swing, structure)
    # H1 bar opened at T is complete at T+1h. Attach to each trading bar the structure known
    # when that bar closes.
    st_avail = pd.DataFrame({"avail": st.index + pd.Timedelta(hours=1), "structure": st.to_numpy()})
    close_time = pd.DataFrame({"close_time": df.index + pd.Timedelta(minutes=TF_MINUTES[tf])})
    m = pd.merge_asof(close_time, st_avail, left_on="close_time", right_on="avail", direction="backward")
    df["structure"] = m["structure"].fillna(0).astype(int).to_numpy()

    po, pc, pv = df.open.shift(), df.close.shift(), df.tickvol.shift()
    low_vol = df.tickvol < pv
    if min_body_atr > 0:
        low_vol &= (df.close - df.open).abs() >= min_body_atr * atr(df, 14)
    bull = (pc < po) & (df.close > df.open) & (df.close >= po) & (df.open <= pc) & low_vol
    bear = (pc > po) & (df.close < df.open) & (df.close <= po) & (df.open >= pc) & low_vol

    df["signal"] = np.select([bull & (df.structure == 1), bear & (df.structure == -1)], [1, -1], 0)
    df["entry_price"] = np.where(df.signal != 0, df.open, np.nan)
    df["valid_bars"] = valid_bars
    df["sl_dist"] = sl_pips * pip
    df["tp_dist"] = sl_pips * pip * rr
    return df.loc[df.index >= h1.index[0]]   # no structure before the H1 data starts


REGISTRY = {
    "ema_cross": ema_cross,
    "engulfing": engulfing_retrace,
}
