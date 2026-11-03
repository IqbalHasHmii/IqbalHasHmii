"""Library of 83 entry rules for the 5-million-strategy search (mass5m.py).

The rules are the common strategies traders share online, from scalping to swing trading:
candle patterns, RSI / Stochastic / MACD / CCI / Williams %R / MFI / ROC / Aroon / ADX, moving
average crosses and pullbacks, Donchian / Bollinger / Keltner channels, Supertrend, Parabolic
SAR, Ichimoku, Heikin Ashi, VWAP, daily pivots and previous-day levels, round numbers, the
weekly open, Asian / London / New York session breakouts and Smart Money Concepts (break of
structure, change of character, liquidity sweeps, fair value gaps, order blocks).

library(d) gets an OHLC DataFrame (bid prices; index = candle open time on the backtest clock,
UTC+2 winter / UTC+3 summer) and returns {name: (long, short)} boolean arrays. Every rule is
decided on the candle's close and only uses candles that have closed (no look-ahead).
"""
from __future__ import annotations

import numba
import numpy as np
import pandas as pd


# ----------------------------------------------------------------------------- indicators
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rma(s, n):
    return s.ewm(alpha=1 / n, adjust=False).mean()


def true_range(d):
    pc = d.close.shift()
    return pd.concat([d.high - d.low, (d.high - pc).abs(), (d.low - pc).abs()], axis=1).max(axis=1)


def atr(d, n=14):
    return rma(true_range(d), n)


def rsi(c, n):
    diff = c.diff()
    up, dn = rma(diff.clip(lower=0), n), rma(-diff.clip(upper=0), n)
    return 100 - 100 / (1 + up / dn)


def adx_di(d, n=14):
    up, dn = d.high.diff(), -d.low.diff()
    pdm = up.where((up > dn) & (up > 0), 0.0)
    ndm = dn.where((dn > up) & (dn > 0), 0.0)
    a = rma(true_range(d), n)
    pdi, ndi = 100 * rma(pdm, n) / a, 100 * rma(ndm, n) / a
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi)
    return rma(dx, n), pdi, ndi


def cross(a, b):
    """a crosses above b on this candle."""
    return (a > b) & (a.shift() <= b.shift())


@numba.njit(cache=True)
def supertrend_dir(h, l, c, a, m):
    n = len(c)
    d = np.zeros(n, np.int8)
    fu, fd = np.nan, np.nan
    for i in range(n):
        if not a[i] > 0:
            continue
        hl2 = (h[i] + l[i]) / 2
        up, dn = hl2 - m * a[i], hl2 + m * a[i]
        if np.isnan(fu):
            fu, fd, d[i] = up, dn, 1
            continue
        pfu, pfd = fu, fd
        fu = max(up, pfu) if c[i - 1] > pfu else up
        fd = min(dn, pfd) if c[i - 1] < pfd else dn
        if c[i] > pfd:
            d[i] = 1
        elif c[i] < pfu:
            d[i] = -1
        else:
            d[i] = d[i - 1]
    return d


@numba.njit(cache=True)
def psar_dir(h, l, af0, afmax):
    n = len(h)
    d = np.zeros(n, np.int8)
    up, sar, ep, af = True, l[0], h[0], af0
    d[0] = 1
    for i in range(1, n):
        sar = sar + af * (ep - sar)
        lo2 = l[i - 2] if i >= 2 else l[i - 1]
        hi2 = h[i - 2] if i >= 2 else h[i - 1]
        if up:
            sar = min(sar, l[i - 1], lo2)
            if l[i] < sar:
                up, sar, ep, af = False, ep, l[i], af0
            elif h[i] > ep:
                ep, af = h[i], min(af + af0, afmax)
        else:
            sar = max(sar, h[i - 1], hi2)
            if h[i] > sar:
                up, sar, ep, af = True, ep, h[i], af0
            elif l[i] < ep:
                ep, af = l[i], min(af + af0, afmax)
        d[i] = 1 if up else -1
    return d


@numba.njit(cache=True)
def ha_open(o, hac):
    r = np.empty(len(o))
    r[0] = o[0]
    for i in range(1, len(o)):
        r[i] = (r[i - 1] + hac[i - 1]) / 2
    return r


@numba.njit(cache=True)
def bars_since_extreme(x, n, is_max):
    m = len(x)
    out = np.full(m, np.nan)
    for i in range(n, m):
        best = i - n
        for k in range(i - n, i + 1):
            if (is_max and x[k] >= x[best]) or ((not is_max) and x[k] <= x[best]):
                best = k
        out[i] = i - best
    return out


@numba.njit(cache=True)
def structure(h, l, c, left, right):
    """Swing high = high above `left` candles before and `right` after (mirror for lows),
    known once the `right` candles have closed. Returns trend and events."""
    n = len(c)
    trend = np.zeros(n, np.int8)
    bos_up = np.zeros(n, np.bool_)
    bos_dn = np.zeros(n, np.bool_)
    choch_up = np.zeros(n, np.bool_)
    choch_dn = np.zeros(n, np.bool_)
    sweep_lo = np.zeros(n, np.bool_)
    sweep_hi = np.zeros(n, np.bool_)
    sh, slw = np.nan, np.nan
    sh_done, sl_done, sh_swept, sl_swept = True, True, True, True
    t = 0
    for i in range(n):
        j = i - right
        if j - left >= 0:
            ok = True
            for k in range(j - left, i + 1):
                if k != j and h[k] >= h[j]:
                    ok = False
                    break
            if ok:
                sh, sh_done, sh_swept = h[j], False, False
            ok = True
            for k in range(j - left, i + 1):
                if k != j and l[k] <= l[j]:
                    ok = False
                    break
            if ok:
                slw, sl_done, sl_swept = l[j], False, False
        if (not sh_done) and c[i] > sh:
            bos_up[i] = True
            sh_done = True
            if t == -1:
                choch_up[i] = True
            t = 1
        elif (not sl_done) and c[i] < slw:
            bos_dn[i] = True
            sl_done = True
            if t == 1:
                choch_dn[i] = True
            t = -1
        if (not sh_swept) and (not sh_done) and h[i] > sh and c[i] < sh:
            sweep_hi[i] = True
            sh_swept = True
        if (not sl_swept) and (not sl_done) and l[i] < slw and c[i] > slw:
            sweep_lo[i] = True
            sl_swept = True
        trend[i] = t
    return trend, bos_up, bos_dn, choch_up, choch_dn, sweep_lo, sweep_hi


@numba.njit(cache=True)
def zone_retest(o, h, l, c, max_age, order_block):
    """Fair value gap (order_block=False) or order block (True) retest.
    Bullish FVG: low[i] > high[i-2] -> zone [high[i-2], low[i]]; the bullish order block is the last
    bearish candle within 5 candles before that displacement. Long when a later candle trades into
    the zone and closes bullish above its bottom (the zone is then used up); the zone dies when a
    candle closes below it or after max_age candles. Mirror for shorts."""
    n = len(c)
    lg = np.zeros(n, np.bool_)
    sh = np.zeros(n, np.bool_)
    bt, bb, bborn = np.nan, np.nan, 0
    st, sb, sborn = np.nan, np.nan, 0
    for i in range(2, n):
        if not np.isnan(bt):
            if c[i] < bb or i - bborn > max_age:
                bt = np.nan
            elif l[i] <= bt and c[i] > bb and c[i] > o[i]:
                lg[i] = True
                bt = np.nan
        if not np.isnan(st):
            if c[i] > st or i - sborn > max_age:
                st = np.nan
            elif h[i] >= sb and c[i] < st and c[i] < o[i]:
                sh[i] = True
                st = np.nan
        if l[i] > h[i - 2]:
            if order_block:
                for j in range(i - 1, max(i - 6, -1), -1):
                    if c[j] < o[j]:
                        bt, bb, bborn = h[j], l[j], i
                        break
            else:
                bt, bb, bborn = l[i], h[i - 2], i
        if h[i] < l[i - 2]:
            if order_block:
                for j in range(i - 1, max(i - 6, -1), -1):
                    if c[j] > o[j]:
                        st, sb, sborn = h[j], l[j], i
                        break
            else:
                st, sb, sborn = l[i - 2], h[i], i
    return lg, sh


# ----------------------------------------------------------------------------- the rules
def library(d: pd.DataFrame) -> dict:
    idx = d.index
    o, h, l, c, v = d.open, d.high, d.low, d.close, d.tickvol.astype(float)
    on, hn, ln, cn = (x.to_numpy(np.float64) for x in (o, h, l, c))
    a = atr(d)
    po, pc, ph, pl = o.shift(), c.shift(), h.shift(), l.shift()
    bull, bear = c > o, c < o
    rng = h - l
    body = (c - o).abs()
    lower = np.minimum(o, c) - l
    upper = h - np.maximum(o, c)
    day = idx.normalize()
    hr, mn = idx.hour, idx.minute
    tmin = np.asarray(hr * 60 + mn)
    T = {}

    def fpd(mask):                                        # first True of each day
        m = pd.Series(np.asarray(mask, bool), index=idx)
        return (m & (m.astype(np.int32).groupby(day).cumsum() == 1)).to_numpy()

    def day_range(mask):                                  # high / low of the masked candles of each day
        mask = np.asarray(mask, bool)
        g = d[mask].groupby(day[mask]).agg(rh=("high", "max"), rl=("low", "min")).reindex(day)
        return g.rh.to_numpy(), g.rl.to_numpy()

    # --- candle patterns
    eng_b = (pc < po) & bull & (c >= po) & (o <= pc)
    eng_s = (pc > po) & bear & (c <= po) & (o >= pc)
    T["engulfing"] = (eng_b, eng_s)
    lowv = v < v.shift()
    T["engulfing_lowvol"] = (eng_b & lowv, eng_s & lowv)
    T["pinbar"] = ((rng > 0) & (lower >= 2 * body) & (lower >= 0.6 * rng),
                   (rng > 0) & (upper >= 2 * body) & (upper >= 0.6 * rng))
    inside = (ph <= h.shift(2)) & (pl >= l.shift(2))
    T["inside_bar_breakout"] = (inside & (c > ph), inside & (c < pl))
    outside = (h > ph) & (l < pl)
    T["outside_bar"] = (outside & bull & (c >= h - 0.25 * rng), outside & bear & (c <= l + 0.25 * rng))
    up3 = bull & bull.shift(1, fill_value=False) & bull.shift(2, fill_value=False) & (c > pc) & (pc > c.shift(2))
    dn3 = bear & bear.shift(1, fill_value=False) & bear.shift(2, fill_value=False) & (c < pc) & (pc < c.shift(2))
    T["three_soldiers_crows"] = (up3, dn3)
    T["three_candles_reversal"] = (dn3, up3)
    b2 = body.shift(2)
    small_mid = (body.shift() <= 0.3 * b2) & (b2 >= 0.6 * a.shift(2))
    mid2 = (o.shift(2) + c.shift(2)) / 2
    T["morning_evening_star"] = (bear.shift(2, fill_value=False) & small_mid & bull & (c > mid2),
                                 bull.shift(2, fill_value=False) & small_mid & bear & (c < mid2))
    T["tweezer"] = (((l - pl).abs() <= 0.1 * a) & bear.shift(fill_value=False) & bull,
                    ((h - ph).abs() <= 0.1 * a) & bull.shift(fill_value=False) & bear)
    maru = (body >= 0.9 * rng) & (rng >= a)
    T["marubozu_momentum"] = (maru & bull, maru & bear)
    doji = (body.shift() <= 0.1 * rng.shift()) & (rng.shift() > 0)
    T["doji_breakout"] = (doji & (c > ph), doji & (c < pl))

    # --- oscillators
    r14 = rsi(c, 14)
    for lv in (20, 25, 30):
        T[f"rsi14_back_from_{lv}"] = ((r14.shift() < lv) & (r14 >= lv), (r14.shift() > 100 - lv) & (r14 <= 100 - lv))
    T["rsi14_cross_50"] = ((r14.shift() < 50) & (r14 >= 50), (r14.shift() > 50) & (r14 <= 50))
    r2 = rsi(c, 2)
    for lv in (5, 10):
        T[f"rsi2_connors_{lv}"] = ((r2.shift() >= lv) & (r2 < lv), (r2.shift() <= 100 - lv) & (r2 > 100 - lv))
    r7 = rsi(c, 7)
    T["rsi7_back_from_20"] = ((r7.shift() < 20) & (r7 >= 20), (r7.shift() > 80) & (r7 <= 80))

    def stoch(k, sm, dp):
        ll, hh = l.rolling(k).min(), h.rolling(k).max()
        K = (100 * (c - ll) / (hh - ll)).rolling(sm).mean()
        return K, K.rolling(dp).mean()
    K, D = stoch(14, 3, 3)
    T["stoch14_cross_in_zone"] = (cross(K, D) & (K < 20), cross(D, K) & (K > 80))
    K5, D5 = stoch(5, 3, 3)
    T["stoch5_cross_in_zone"] = (cross(K5, D5) & (K5 < 20), cross(D5, K5) & (K5 > 80))
    T["stoch14_back_from_20"] = ((K.shift() < 20) & (K >= 20), (K.shift() > 80) & (K <= 80))

    m = ema(c, 12) - ema(c, 26)
    sg = ema(m, 9)
    T["macd_signal_cross"] = (cross(m, sg), cross(sg, m))
    T["macd_zero_cross"] = ((m > 0) & (m.shift() <= 0), (m < 0) & (m.shift() >= 0))
    mf = ema(c, 5) - ema(c, 35)
    sf = ema(mf, 5)
    T["macd_5_35_5_cross"] = (cross(mf, sf), cross(sf, mf))

    tp = (h + l + c) / 3
    cci = (tp - tp.rolling(20).mean()) / (0.015 * 0.7979 * tp.rolling(20).std())
    T["cci20_back_from_100"] = ((cci.shift() < -100) & (cci >= -100), (cci.shift() > 100) & (cci <= 100))
    T["cci20_cross_0"] = ((cci.shift() < 0) & (cci >= 0), (cci.shift() > 0) & (cci <= 0))
    hh14, ll14 = h.rolling(14).max(), l.rolling(14).min()
    wr = -100 * (hh14 - c) / (hh14 - ll14)
    T["williams_r_back_from_80"] = ((wr.shift() < -80) & (wr >= -80), (wr.shift() > -20) & (wr <= -20))
    mfv = tp * v
    pos = mfv.where(tp > tp.shift(), 0.0).rolling(14).sum()
    neg = mfv.where(tp < tp.shift(), 0.0).rolling(14).sum()
    mfi = 100 - 100 / (1 + pos / neg)
    T["mfi14_back_from_20"] = ((mfi.shift() < 20) & (mfi >= 20), (mfi.shift() > 80) & (mfi <= 80))
    roc = c / c.shift(10) - 1
    T["roc10_cross_0"] = ((roc.shift() <= 0) & (roc > 0), (roc.shift() >= 0) & (roc < 0))
    au = pd.Series(100 * (25 - bars_since_extreme(hn, 25, True)) / 25, index=idx)
    ad = pd.Series(100 * (25 - bars_since_extreme(ln, 25, False)) / 25, index=idx)
    T["aroon25_cross"] = (cross(au, ad), cross(ad, au))
    adx, pdi, ndi = adx_di(d)
    T["adx_di_cross"] = (cross(pdi, ndi) & (adx > 20), cross(ndi, pdi) & (adx > 20))

    # --- moving averages
    e8, e9, e20, e21, e50, e55, e200 = (ema(c, n) for n in (8, 9, 20, 21, 50, 55, 200))
    T["ema9_21_cross"] = (cross(e9, e21), cross(e21, e9))
    T["ema20_50_cross"] = (cross(e20, e50), cross(e50, e20))
    T["ema50_200_cross"] = (cross(e50, e200), cross(e200, e50))
    s10, s30 = c.rolling(10).mean(), c.rolling(30).mean()
    T["sma10_30_cross"] = (cross(s10, s30), cross(s30, s10))
    T["ema20_pullback"] = ((l <= e20) & (c > e20) & bull, (h >= e20) & (c < e20) & bear)
    T["ema50_pullback"] = ((l <= e50) & (c > e50) & bull, (h >= e50) & (c < e50) & bear)
    T["ema9_pullback_9over21"] = ((e9 > e21) & (l <= e9) & (c > e9) & bull, (e9 < e21) & (h >= e9) & (c < e9) & bear)
    T["triple_ema_8_21_55_pullback"] = ((e8 > e21) & (e21 > e55) & (l <= e21) & (c > e21) & bull,
                                        (e8 < e21) & (e21 < e55) & (h >= e21) & (c < e21) & bear)
    T["ema200_bounce"] = ((l <= e200) & (c > e200) & bull, (h >= e200) & (c < e200) & bear)
    T["ema200_cross"] = (cross(c, e200), cross(e200, c))

    # --- channels
    for n in (10, 20, 55):
        hh, ll = h.rolling(n).max().shift(), l.rolling(n).min().shift()
        T[f"donchian_breakout_{n}"] = (c > hh, c < ll)
    for n in (10, 20, 50):
        hh, ll = h.rolling(n).max().shift(), l.rolling(n).min().shift()
        T[f"donchian_fade_{n}"] = ((l < ll) & (c > ll), (h > hh) & (c < hh))
    mid, sd = c.rolling(20).mean(), c.rolling(20).std()
    for k in (2.0, 2.5):
        up, lo = mid + k * sd, mid - k * sd
        T[f"bollinger_reentry_{k}"] = ((pc < lo.shift()) & (c > lo), (pc > up.shift()) & (c < up))
    up, lo = mid + 2 * sd, mid - 2 * sd
    T["bollinger_breakout"] = ((c > up) & (pc <= up.shift()), (c < lo) & (pc >= lo.shift()))
    bw = (up - lo) / mid
    sq = (bw.rolling(5).min() <= bw.rolling(120).min() * 1.0001).shift(fill_value=False)
    T["bollinger_squeeze_breakout"] = (sq & (c > up), sq & (c < lo))
    ku, kl = e20 + 2 * a, e20 - 2 * a
    T["keltner_breakout"] = ((c > ku) & (pc <= ku.shift()), (c < kl) & (pc >= kl.shift()))
    T["keltner_reentry"] = ((pc < kl.shift()) & (c > kl), (pc > ku.shift()) & (c < ku))

    # --- trend systems
    an = a.to_numpy(np.float64)
    for p, mlt in ((10, 3.0), (7, 3.0)):
        st = supertrend_dir(hn, ln, cn, atr(d, p).to_numpy(np.float64), mlt)
        prev = np.r_[0, st[:-1]]
        T[f"supertrend_{p}_{int(mlt)}_flip"] = ((st == 1) & (prev == -1), (st == -1) & (prev == 1))
    ps = psar_dir(hn, ln, 0.02, 0.2)
    prev = np.r_[0, ps[:-1]]
    T["parabolic_sar_flip"] = ((ps == 1) & (prev == -1), (ps == -1) & (prev == 1))
    tenkan = (h.rolling(9).max() + l.rolling(9).min()) / 2
    kijun = (h.rolling(26).max() + l.rolling(26).min()) / 2
    span_a = ((tenkan + kijun) / 2).shift(26)
    span_b = ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)
    ctop, cbot = np.maximum(span_a, span_b), np.minimum(span_a, span_b)
    T["ichimoku_tk_cross"] = (cross(tenkan, kijun) & (c > ctop), cross(kijun, tenkan) & (c < cbot))
    T["ichimoku_cloud_breakout"] = ((c > ctop) & (pc <= ctop.shift()), (c < cbot) & (pc >= cbot.shift()))
    hac = ((o + h + l + c) / 4).to_numpy(np.float64)
    hao = ha_open(on, hac)
    hah, hal = np.maximum(hn, np.maximum(hao, hac)), np.minimum(ln, np.minimum(hao, hac))
    hab, has = hac > hao, hac < hao
    nolow = hal >= np.minimum(hao, hac) - 1e-9
    nohigh = hah <= np.maximum(hao, hac) + 1e-9
    sb, ss = hab & nolow, has & nohigh
    pb, pbe = np.r_[False, hab[:-1]], np.r_[False, has[:-1]]
    T["heikin_ashi_flip"] = (sb & pbe, ss & pb)
    T["heikin_ashi_two_strong"] = (sb & np.r_[False, sb[:-1]], ss & np.r_[False, ss[:-1]])

    # --- VWAP (resets every day)
    vwap = (tp * v).groupby(day).cumsum() / v.groupby(day).cumsum()
    T["vwap_cross"] = (cross(c, vwap), cross(vwap, c))
    T["vwap_pullback"] = ((c > vwap) & (l <= vwap) & bull, (c < vwap) & (h >= vwap) & bear)

    # --- daily levels
    daily = d.groupby(day).agg(H=("high", "max"), L=("low", "min"), C=("close", "last"))
    prev_d = daily.shift(1).reindex(day)
    pdh = pd.Series(prev_d.H.to_numpy(), index=idx)
    pdl = pd.Series(prev_d.L.to_numpy(), index=idx)
    pdc = pd.Series(prev_d.C.to_numpy(), index=idx)
    T["prev_day_breakout"] = (fpd(c > pdh), fpd(c < pdl))
    T["prev_day_sweep"] = (fpd((l < pdl) & (c > pdl)), fpd((h > pdh) & (c < pdh)))
    pp = (pdh + pdl + pdc) / 3
    r1, s1 = 2 * pp - pdl, 2 * pp - pdh
    T["pivot_s1_r1_bounce"] = ((l <= s1) & (c > s1) & bull, (h >= r1) & (c < r1) & bear)
    T["pivot_r1_s1_breakout"] = ((c > r1) & (pc <= r1), (c < s1) & (pc >= s1))
    T["pivot_pp_cross"] = ((c > pp) & (pc <= pp), (c < pp) & (pc >= pp))
    lvl_dn, lvl_up = np.floor(c / 10) * 10, np.ceil(c / 10) * 10
    T["round_number_bounce"] = ((l <= lvl_dn) & (o > lvl_dn) & (c > lvl_dn + 0.1 * a),
                                (h >= lvl_up) & (o < lvl_up) & (c < lvl_up - 0.1 * a))
    wk = (idx - pd.to_timedelta(idx.weekday, unit="D")).normalize()
    wo = o.groupby(wk).transform("first")
    T["weekly_open_cross"] = ((c > wo) & (pc <= wo), (c < wo) & (pc >= wo))

    # --- sessions (backtest clock: Asia 01-09, London 10, New York 16:30)
    arh, arl = day_range((hr >= 1) & (hr <= 9))
    win = (hr >= 10) & (hr <= 15)
    T["asian_range_breakout"] = (fpd(win & (c > arh)), fpd(win & (c < arl)))
    lrh, lrl = day_range((tmin >= 600) & (tmin < 630))
    win = (tmin >= 630) & (tmin < 840)
    T["london_opening_range_breakout"] = (fpd(win & (c > lrh)), fpd(win & (c < lrl)))
    nrh, nrl = day_range((tmin >= 990) & (tmin < 1020))
    win = (tmin >= 1020) & (tmin < 1200)
    T["ny_opening_range_breakout"] = (fpd(win & (c > nrh)), fpd(win & (c < nrl)))
    first_ldn = (hr == 10) & (mn == 0)
    T["london_first_candle"] = (first_ldn & bull, first_ldn & bear)

    # --- Smart Money Concepts
    trend_s, bos_up, bos_dn, ch_up, ch_dn, sw_lo, sw_hi = structure(hn, ln, cn, 5, 2)
    T["smc_break_of_structure"] = (bos_up, bos_dn)
    T["smc_change_of_character"] = (ch_up, ch_dn)
    T["smc_liquidity_sweep"] = (sw_lo, sw_hi)
    T["smc_trend_ema20_pullback"] = ((trend_s == 1) & T["ema20_pullback"][0], (trend_s == -1) & T["ema20_pullback"][1])
    T["smc_fair_value_gap_retest"] = zone_retest(on, hn, ln, cn, 100, False)
    T["smc_order_block_retest"] = zone_retest(on, hn, ln, cn, 100, True)

    # --- other popular setups
    dn5 = (c < pc) & (pc < c.shift(2)) & (c.shift(2) < c.shift(3)) & (c.shift(3) < c.shift(4)) & (c.shift(4) < c.shift(5))
    up5 = (c > pc) & (pc > c.shift(2)) & (c.shift(2) > c.shift(3)) & (c.shift(3) > c.shift(4)) & (c.shift(4) > c.shift(5))
    T["five_closes_reversal"] = (dn5, up5)
    nr7 = (rng <= rng.rolling(7).min()).shift(fill_value=False)
    T["nr7_breakout"] = (nr7 & (c > ph), nr7 & (c < pl))
    spike = rng >= 2.5 * a
    T["capitulation_wick_reversal"] = (spike & (lower >= 0.5 * rng), spike & (upper >= 0.5 * rng))
    T["momentum_burst"] = (c - c.shift(3) > 1.5 * a, c - c.shift(3) < -1.5 * a)

    out = {}
    for k, (x, y) in T.items():
        out[k] = (np.nan_to_num(np.asarray(x, dtype=float)).astype(bool),
                  np.nan_to_num(np.asarray(y, dtype=float)).astype(bool))
    return out
