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
def ema_cross(df: pd.DataFrame) -> pd.DataFrame:
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


REGISTRY = {
    "ema_cross": ema_cross,
}
