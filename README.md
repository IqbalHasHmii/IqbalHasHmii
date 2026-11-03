# XAUUSD Strategy Backtester

Backtester for XAUUSD (Gold) using MT5-exported data (H1, M15, M5, about 5 years).

## Chalane ka tareeqa

```bash
pip install pandas numpy matplotlib
python backtest.py --strategy ema_cross --tf H1 --balance 10000 --risk 1
```

Options:
- `--tf` : `H1`, `M15` ya `M5` (data `data/<TF>/` folder mein hai)
- `--risk` : har trade pe equity ka kitna % risk
- `--commission` : $ per lot (round turn)
- `--exit-on-opposite` : ulta signal aane pe trade band kar do

Har run ke baad `results/` folder mein ye files banti hain: report (`*_report.txt`), har trade ki list (`*_trades.csv`) aur equity curve ka chart (`*_equity.png`).

## Aap ki strategy: H1 structure + low-volume engulfing + retracement entry

```bash
python backtest.py --strategy engulfing --tf H1    # ya M15 / M5
python variants.py                                 # sab settings ek table mein
```

Rules jis tarah code mein likhe gaye hain (`strategies.py` -> `engulfing_retrace`):
1. **H1 structure:** swing high/low (dono taraf 3 candles) se. Jab H1 candle last swing high ke upar close ho to structure bullish, aur last swing low ke neeche close ho to bearish (BOS). `--structure hhhl` se HH/HL wala tareeqa bhi test ho sakta hai.
2. **Engulfing:** jis timeframe pe test ho raha hai us pe. Bullish structure mein sirf bullish engulfing aur bearish mein sirf bearish engulfing liya jata hai. Engulfing candle ki body pichli candle ki body ko poora cover kare.
3. **Volume filter:** engulfing candle ka tick volume pichli candle se **kam** ho.
4. **Entry:** engulfing candle ke **open** pe limit order lagta hai, jo sirf **agli candle** tak valid rehta hai (`--valid-bars` se badal sakte hain).
5. **SL / TP:** SL 50 pips (1 pip = $0.10, yaani $5) aur TP 1:3 ($15). `--sl-pips`, `--rr` aur `--pip` se badal sakte hain.

## Execution model
- Signal candle ke **close** pe banta hai aur trade **agli candle ke open** pe khulta hai (look-ahead bias nahi hota).
- Har candle ka asal spread CSV ke `<SPREAD>` column se liya jata hai. Buy ask pe aur sell bid pe fill hoti hai.
- Agar SL aur TP dono ek hi candle ke andar hit hon to **SL** maana jata hai (conservative assumption).
- Ek waqt mein sirf ek trade khulti hai. Lot size risk % aur SL distance se nikalta hai (1 lot = 100 oz).

## Nayi strategy add karna
`strategies.py` mein ek function likhein jo `signal` (1/-1/0), `sl_dist` aur `tp_dist` columns return kare, phir use `REGISTRY` mein add kar dein.

## SMC Extreme Order Block strategy (H1 signals + M15 monitoring)

```bash
python smc_ob.py                              # strict rules, 1% risk sized on the wick
python smc_ob.py --sizing max --tag _sizing_max   # 1% risk sized on the 50-pip max SL
python smc_ob.py --sizing fixed --tag _fixed_0.1lot
python smc_variants.py                        # comparison table
```

Strict rules (`smc_ob.py`):
1. H1 body engulfing, and the engulfing body must be bigger than its wicks (upper + lower combined).
2. Engulfing tick volume <= previous candle's tick volume.
3. Swing High/Low = 5 candles left, 2 right (strict). BOS: close above the last swing high -> buys only, close below the last swing low -> sells only.
4. Limit order at the engulfing open, SL at the engulfing wick (setup skipped if > 50 pips = $5), TP 1:3. The trade is closed in loss when an H1 candle closes beyond the wick. If a candle takes the wick's liquidity but closes back inside, the SL moves to that candle's wick (normal stop) after it closes. TP is checked on M15.

The rules leave a few things open, so these defaults are used: the limit order is valid for one H1 candle, only one trade at a time, and setups with a 0 wick distance are skipped. `--hard-sl` exists only for comparison and is not part of the rules.

## Engulfing sell strategy: SL 50-100 pips at 1:3 (`sl_sweep.py`)

```bash
python sl_sweep.py               # sells only, no volume filter
python sl_sweep.py --side both   # buys + sells
```

Rules: H1 structure must be bearish (swing 3, BOS on a close), a bearish engulfing candle closes, a sell limit goes at the engulfing **open** and stays valid only for the next candle, SL 50/60/.../100 pips, TP = 3 x SL. Results go to `results/engulf_<side>_sl_sweep.csv`, with each SL's trade list in `results/engulf_<side>_sl<N>_trades.csv`.

## SMC v2: 5/2 swings, limit valid 5-10 candles, H1-close stop (`smc_v2.py`)

```bash
python smc_v2.py      # prints the full comparison table -> results/smc_v2_summary.csv
```

Rules (H1 only, no volume or body filter):
1. Swing High = High above the 5 candles to its left and the 2 to its right (Swing Low mirrored), confirmed after the 2 right candles close. A close above the last Swing High = buys only, a close below the last Swing Low = sells only.
2. Bearish/bullish body engulfing in the trend direction. A limit order goes at the engulfing **open** and stays valid for the next 5 (or 10) H1 candles. It is cancelled if the structure flips, and replaced if a new setup forms first.
3. SL level = engulfing wick (High for sells, Low for buys). There is no hard stop: the trade closes in loss only when an H1 candle **closes** beyond that level. TP = 3 x SL distance.

The table also shows comparison variants that are not part of the rules: a minimum SL distance (`max(wick, N pips)`) and a normal hard stop at the SL level. P/L in $ uses a fixed 0.10 lot ($1 per pip).

## v3: 200 EMA trend + low-volume engulfing (`ema_v3.py`)

```bash
python ema_v3.py      # comparison table -> results/ema_v3_summary.csv
```

Same as v2, with two changes: the trend comes from EMA(200) (H1 close above it = buys only, below = sells only), and the engulfing candle's tick volume must be lower than the previous candle's. The limit order at the engulfing open stays valid for 5 H1 candles and is cancelled if the close crosses the EMA the other way. The script compares wick SL (H1-close exit or hard stop) with fixed 50/70/100-pip hard stops, at 1:3. It runs each one in two modes: `every` (each engulfing gets its own trade, so trades can overlap) and `one-at-time`.

## v4: engulfing only inside an Order Block / FVG (`zones_v4.py`)

```bash
python zones_v4.py    # comparison table -> results/zones_v4_summary.csv
```

v3 plus a zone filter. Zones are built on H1 from closed candles only:
- **Bullish FVG:** `low[i] > high[i-2]`. **Bearish FVG:** `high[i] < low[i-2]`.
- **OB:** the last opposite-colour candle within the 5 candles before that FVG displacement.
- A zone stays active until a candle closes through it, or for at most 100 candles.

A buy needs a bullish engulfing whose two-candle range touches an active bullish zone and closes above the zone bottom; sells are the mirror. The EMA(200) trend, limit at the engulfing open (valid 5 candles), every-setup trading and the SL versions are the same as v3. The table compares OB only, FVG only and OB-or-FVG, each with and without the volume filter.

## MT5 EA: XAUUSD M15 Extreme OB (`mql5/XAUUSD_M15_Extreme_OB_EA.mq5`)

v2.10 fixes the reasons v2.00 took (almost) no trades:
1. An armed setup never expired. If price did not come back to the engulfing open, the EA waited forever and never looked for a new setup. Now the entry stays valid for `InpSetupExpiryBars` candles (default 10), a newer setup replaces it, and it is cancelled when the trend turns.
2. `PositionsTotal()` counted every position on the account. Now only this EA's trades on the chart symbol count.
3. Order results were never checked, and rejected orders silently dropped the setup. Now the filling mode comes from the symbol, the SL is validated before sending, and every error is printed in the Experts tab. A status line on the chart shows what the EA is waiting for.
4. The hard SL on the wick made the M15-close exit useless, and after a restart any SELL was closed at the next M15 close. Now `InpCloseBasedSL` chooses between the M15-close exit (with a far `InpEmergencySLPips` broker SL) and a normal stop at the wick.
5. The pip size is an input (`InpPipSize`, 0.10 for gold) instead of `10 * _Point`, which was 10x off on 3-digit gold quotes.

```bash
python ea_m15_replay.py   # replays v2.00 as written and the v2.10 logic on the M15 history
```

## MT5 EA: XAUUSD H1 Extreme OB (`mql5/XAUUSD_Extreme_OB_EA.mq5`)

The H1 version had its own problems in v2.00, fixed in v2.10:
1. `tradeArmed` was never reset after an entry. After every TP or SL, the same setup was entered again whenever price came back to the engulfing open. When the wick SL was already on the wrong side of the price, the rejected order was re-sent on every tick.
2. A setup never expired (only a newer one replaced it), so entries could come days later.
3. The "H1 close" exit ran at minute 45 and looked at the previous H1 candle, and the hard SL on the wick fired before it anyway. Now the just-closed H1 candle is checked when the next one starts.
4. It had the same account-wide `PositionsTotal()`, unchecked orders, FOK filling and `10 * _Point` pip issues as the M15 EA.

```bash
python ea_h1_replay.py    # replays H1 v2.00 as written (on M15 candles) and the v2.10 logic (on H1)
```

## M15 strategy search: >= 40% win rate, 3-5 trades a week (`m15_search.py`)

```bash
python m15_search.py   # -> results/m15_search.csv
```

The script tests three families on M15 with small parameter grids: Asian-range breakout, previous-day high/low sweep, and EMA trend pullback. SL limits are scaled by the average M15 candle range, so they follow volatility. Parameters are judged on 2021-11..2024-10 (in-sample) and then checked on 2024-11..2026-10 (out-of-sample). Times are broker server time (UTC+2 winter / UTC+3 summer).

## MT5 EA: M15 Asian breakout + previous-day sweep, 1:3 (`mql5/XAUUSD_M15_Breakout_Sweep_EA.mq5`)

This EA runs the two `m15_search.py` setups with TP = 3 x SL, and its defaults match the backtest:
- **Asian breakout:** range from 01:00-09:45, breakout window 10:00-15:45, SL at the other side of the range.
- **Sweep:** window 09:00-20:45, SL beyond the sweep wick + 0.2x the average range, SL size between 1x and 5x the average range.
- Each setup has its own magic number and at most one open trade.
- Risk is 1% of equity per trade, or a fixed lot size.
- Hours are broker server time.

In the backtest at 1:3, the two setups together made about 3.5 trades a week at a 28.5% win rate, +125.6R over 5 years.

## MT5 EA: all three setups in one (`mql5/XAUUSD_Combo_3Strategy_EA.mq5`)

This EA runs three setups, each with TP = 3 x SL and its own magic number:
- **Asian breakout (M15):** magic 777101.
- **Previous-day sweep (M15):** magic 777102.
- **H1 EMA200 engulfing:** magic 777103. A limit order goes at the engulfing open with SL 100 pips. It stays valid for 5 H1 candles and is deleted if the H1 close crosses the EMA the other way.

`InpMultipleTrades = true` (default) lets every setup trade even when trades are already open. `false` limits each setup to one trade at a time. `InpMaxOpenTrades` caps the EA's total open trades (0 = no limit). The default risk is 0.5% per trade.

Backtest with multiple trades (5 years, 1:3):

| Setup | Trades / week | Win rate | Net | Max drawdown |
|---|---|---|---|---|
| Asian breakout | 4.1 | 27.4% | +100.3R | -44.1R |
| Previous-day sweep | 2.2 | 28.1% | +71.2R | -18.0R |
| H1 EMA200 engulfing | 5.4 | 27.5% | +146.1R | -56.0R |
| All three | 11.7 | 27.5% | +317.6R | -60.7R |

All three together had up to 16 trades open at once.

Backtest with one trade per setup (5 years, 1:3):

| Setup | Trades / week | Win rate | Net | Max drawdown |
|---|---|---|---|---|
| Asian breakout + sweep | 3.5 | 28.5% | +125.6R | -27R |
| H1 EMA200 engulfing (one at a time) | 3.0 | 28.0% | +101.9R | -30.7R |

## M1 strategy search (`m1_search.py`)

```bash
python m1_search.py      # ~5 minutes -> results/m1_search.csv
```

This runs the same three families as `m15_search.py` on 1-minute candles, with limits scaled by the average M1 candle range of the last day. `m15_search.run_every` replays a strategy with overlapping trades allowed.

M1 data is not committed (about 100 MB). Export it from MT5 into `data/M1/`.

Findings (5 years):
- The sweep and EMA pullback setups lose on M1. The median spread ($0.18) is about 30% of a median M1 candle ($0.63).
- Only the Asian breakout (SL at the other side of the range, 1:3) works, and it is no better than on M15. With multiple trades it made 4.6 trades a week, 27.2% win rate, +101.5R and -48R max drawdown, compared with 4.1 trades a week, +100.3R and -44R on M15.
- With one trade at a time, a single January 2026 trade had a $384 SL (the crash range) and stayed open until October, which blocked the rest of 2026.

## M5 strategy search, with new strategies (`m5_search.py`)

```bash
python m5_search.py      # ~1 minute -> results/m5_search.csv
```

This tests the three `m15_search.py` families on M5, plus three new ones: an RSI pullback with an EMA(2400) trend, Bollinger mean reversion in the Asian session, and a New York opening-range breakout. The data covers 2020-11..2026-10. Parameters are judged on the period up to 2024-10 and checked on 2024-11..2026-10.

Best three (1:3, each one trade at a time):

| Setup | Trades / week | Win rate | Net | Max drawdown | In-sample / out-of-sample |
|---|---|---|---|---|---|
| RSI pullback (level 25, SL 1x-10x the average range) | 2.4 | 29.3% | +130.9R | -30.0R | +72.1 / +58.9 |
| NY opening-range breakout (SL at the other side of the range) | 3.2 | 28.0% | +115.6R | -27.7R | +78.8 / +36.8 |
| Asian breakout (SL at the other side of the range) | 1.6 | 29.7% | +90.5R | -21.0R | +57.2 / +33.3 |
| All three together | 7.1 | 28.8% | +337.0R | -32.7R | +208.2 / +128.9 |

Every full year from 2021 to 2026 was positive. With overlapping trades allowed, the combined result is worse: +267.5R with a -72.3R drawdown. The sweep, EMA pullback and Bollinger reversion setups lose on M5.

## Mass search: 226,800 strategies, 1:3, M1-M60 (`mass_search.py`, `mass_analyze.py`)

```bash
pip install numba
python mass_search.py && python mass_analyze.py   # ~1 minute
```

A strategy combines one choice from each of these:
- timeframe (10)
- trigger (21)
- trend filter (5)
- session (6)
- volatility filter (3)
- SL size (4, in ATR)
- direction (3)

TP is always 3 x SL. The M1 data is resampled to each timeframe, and every signal is its own trade. Picks are ranked only on 2021-11..2024-10 and then checked on 2024-11..2026-10.

Outputs:
- `results/mass_search.csv.gz`: every strategy.
- `results/mass_search_by_tf.csv`: summary per timeframe.
- `results/mass_search_top.csv`: top 50 by in-sample t-stat.
- `results/mass_search_baseline.csv`: no-skill win rate per timeframe.

Findings:
- **Higher timeframes are more accurate at 1:3.** Taking a trade after every candle (SL 2 ATR) wins 21.9% on M1 and 26.1% on M60, against a break-even of 25%. Strategies profitable in both periods: 0.6% on M1, 7.5% on M5, 19.4% on M15, 30.7% on M30, 37.1% on M60.
- **The top in-sample strategies are almost all buy-only with an uptrend filter.** All of the top 50 stayed profitable out-of-sample (+0.22R/trade). But simply buying every M60 candle above the H1 EMA200 (SL 2 ATR, 1:3) already makes 31.7% / 32.9% wins and +0.25R / +0.29R per trade. Most of the "edge" is gold's 2021-2026 uptrend.
- **Sell-only strategies that looked best in-sample failed out-of-sample.** Only 40% of the top 10 stayed profitable, averaging -0.12R per trade.

### Buy vs sell (`mass_by_direction.py`)

```bash
python mass_by_direction.py   # -> results/mass_search_by_direction.csv, results/mass_search_best_by_direction.csv
```

This script combines both mass-search runs and splits the results by direction. "Both" means buys when the trend filter is up and sells when it is down.

| Timeframe | Profitable in both periods: buy only | sell only | both | Top-20 out-of-sample R/trade: buy | sell | both |
|---|---|---|---|---|---|---|
| M5 | 13.1% | 3.7% | 5.8% | +0.16 | +0.07 | +0.10 |
| M15 | 34.4% | 6.0% | 17.4% | +0.25 | +0.05 | +0.10 |
| M30 | 46.0% | 11.8% | 32.4% | +0.27 | +0.01 | +0.15 |
| M60 | 52.8% | 13.2% | 40.5% | +0.31 | +0.09 | +0.16 |

Sell-only strategies picked on 2021-24 mostly failed in 2024-26, because of gold's uptrend.

## MT5 EA: H1 EMA20 pullback, buys and sells (`mql5/XAUUSD_H1_EMA20_Pullback_EA.mq5`)

Rules (checked at every H1 close, any hour):
- **Buy:** close above EMA200, the low touches EMA20, and the candle closes bullish above EMA20.
- **Sell:** the mirror of the buy rule.
- **Exits:** SL 2 x ATR(14), TP 3 x SL, and a time stop after 115 candles.
- **Trades:** every signal is its own trade, up to `InpMaxOpenTrades` open at once (default 5).

`python m60_ema20_pullback.py` backtests the same rules on H1 built from the M1 data (2021-11..2026-10):

| Version | Trades / week | Win rate | R / trade | Net | Max drawdown |
|---|---|---|---|---|---|
| All signals | 13.4 | 30.4% | +0.198 | +678R | -69.3R (up to 18 trades open) |
| Max 5 open (EA default) | 9.9 | 30.6% | +0.200 | +508.5R | -54.6R |
| One at a time | 2.7 | 29.5% | +0.162 | +112.3R | -28.8R |

Split by side, buys made +0.33R per trade and sells only +0.03R.

## Exness versions (`mql5/exness/`)

Exness runs its server on UTC+0 all year. The backtest data (and FTMO) uses UTC+2 in winter and UTC+3 in summer, following European DST.

The three EAs that use session hours have Exness versions that convert every time automatically, with nothing to change between summer and winter:
- `XAUUSD_M15_Breakout_Sweep_EA_Exness`
- `XAUUSD_Combo_3Strategy_EA_Exness`
- `XAUUSD_M5_3Strategy_EA_Exness`

The new `InpServerUTC` input holds the broker's UTC offset (Exness = 0). The hour inputs stay on the backtest clock, so the defaults are unchanged. The previous-day high/low is built from M15 candles on that clock instead of the broker's D1 candle.

The other three EAs use no session hours. Their `_Exness` copies are identical apart from the description:
- `XAUUSD_H1_EMA20_Pullback_EA_Exness`
- `XAUUSD_Extreme_OB_EA_Exness`
- `XAUUSD_M15_Extreme_OB_EA_Exness`

## MT5 EA: all strategies in one (`mql5/XAUUSD_All_Strategies_EA.mq5`)

This EA runs nine strategies side by side. Each strategy has its own on/off switch, magic number, state, trades and max-open setting, so they never touch each other's trades. `InpMaxOpenTotal` is the only shared limit, and it is off by default.

| # | Strategy | Default |
|---|---|---|
| 1 | M15 Asian breakout | on, 1 trade at a time |
| 2 | M15 previous-day sweep | on, 1 at a time |
| 3 | H1 EMA200 engulfing (limit order) | on, 1 at a time |
| 4 | M5 RSI pullback | on, 1 at a time |
| 5 | M5 NY opening range | on, 1 at a time |
| 6 | M5 Asian breakout | on, 1 at a time |
| 7 | H1 EMA20 pullback, buys and sells | on, up to 5 open |
| 8 | M15 Extreme OB v2.10 | off (lost money in the backtest) |
| 9 | H1 Extreme OB v2.10 | off (lost money in the backtest) |

Set `InpClock` to match the broker:
- **Exness and other fixed-UTC brokers:** `Fixed UTC offset` with `InpServerUTC` (Exness = 0). The session hours are converted automatically.
- **FTMO and other brokers on the backtest clock (UTC+2/+3):** `Same as the backtest data`.

## 5-million-strategy search, 1:3 (`strategy_library.py`, `mass5m.py`, `mass5m_analyze.py`)

```bash
pip install numba
python mass5m.py && python mass5m_analyze.py                         # 1-5 minutes: 5,378,400 strategies
python mass5m.py 15,30,60 && python mass5m_analyze.py 15,30,60 _htf  # same rules on 15/30/60 minutes: 3,227,040
```

`strategy_library.py` holds 83 entry rules collected from common online strategies:
- candle patterns
- RSI, Stochastic, MACD, CCI, Williams %R, MFI, ROC, Aroon and ADX
- moving-average crosses and pullbacks
- Donchian, Bollinger and Keltner channels
- Supertrend, Parabolic SAR, Ichimoku and Heikin Ashi
- VWAP, pivots, previous-day levels, round numbers and the weekly open
- Asian, London and New York breakouts
- SMC: break of structure, change of character, liquidity sweep, FVG and order-block retests

Each rule is combined with 6 trend filters, 5 SL types, 3 directions, 8 sessions, 3 volatility filters, 3 ADX filters and 2 day filters. TP is always 3 x SL.

The data is split into three periods:
- **P1 (2021-11..2023-10):** choose.
- **P2 (2023-11..2024-10):** confirm.
- **P3 (2024-11..2026-10):** test. It is never used for selection.

A win means the take-profit was hit.

Findings:
- **No strategy keeps a 40%+ TP rate.** On 1-5 minutes, 268 strategies had >= 40% wins in P1, 2 of them also in P2, and none in P3. On 15-60 minutes it was 310, then 19, then 1: M30 three soldiers in an uptrend, about 1.5 trades a week. With >= 3 trades a week, none reached 40% in both P1 and P2.
- **Best 1-5 minute strategies (ranked on P1+P2):** buy-only momentum entries in an uptrend (above the H1 EMA200) when volatility is high, in the late (20:00-00:59) or New York session. Examples are Heikin Ashi two strong candles and three soldiers. The top 100 kept 29.8% TP and +0.20R/trade in P3, and 99% were profitable. By timeframe, M3 is best and M1 has no edge.
- **Best overall (15-60 minutes):** M30 EMA9 pullback (EMA9 > EMA21, the candle touches EMA9 and closes bullish above it), buy only, close above the H1 EMA200, ADX(14) < 20, SL 2 ATR. The TP rate was 34.3% / 40.1% / 35.2% (P1 / P2 / P3), with +0.40R/trade and about 7 trades a week in P3. It lost money in 2026 (-25R) while gold fell.

### M3 Heikin Ashi strategy on Exness data (`m3_ha_test.py`)

```bash
python m3_ha_test.py --ours --clock utc0 data/M3_exness/*.csv   # -> results/m3_ha_test.txt
```

This tests the 1-5 minute pick from the 5M search on the user's Exness M3 export (UTC+0 server, 3-digit prices, 2020-01..2026-11). Times are converted to the backtest clock and spreads use the 0.001 point.

The strategy:
- **Entry:** buy after two strong bullish Heikin Ashi candles.
- **Filters:** close above the H1 EMA200, a 20:00-00:59 candle, and ATR above its 20-day average.
- **Exits:** SL 2 x ATR and TP 1:3.

Results:
- **On our data** it reproduces the search exactly (P1 / P2 / P3 TP 25.8% / 39.8% / 32.5%).
- **On Exness:**
  - 2020-01..2021-10 (data never used before): 27.7% TP, +0.12R/trade.
  - P1 (2021-11..2023-10): 24.3% TP, +0.06R/trade.
  - P2 (2023-11..2024-10): 42.9% TP, +0.73R/trade.
  - P3 (2024-11..2026-10): 34.3% TP, +0.39R/trade.
- **By year:** every year was positive except 2022 (-3R).
- **Drawdowns:**

| Version | Trades / week | Max drawdown | When |
|---|---|---|---|
| Every signal | 8.6 | -111R | Mar-Jul 2020 |
| Max 3 open | 5.0 | -63R | |
| One at a time | 2.2 | -41R | |

The Exness M3 files are not committed (about 50 MB); put them in `data/M3_exness/`.

## MT5 EAs: M3 Heikin Ashi strategy, Exness and FTMO (`mql5/exness/XAUUSD_M3_HeikinAshi_EA_Exness.mq5`, `mql5/XAUUSD_M3_HeikinAshi_EA_FTMO.mq5`)

These two EAs trade only the best 3-minute strategy from the 5M search. Both are generated from one template by `mql5/make_m3_ha_eas.py`, so their trading logic is identical.

Rules:
- **Entry:** buy after two strong bullish Heikin Ashi candles.
- **Filters:** close above EMA(4000) on M3 (about the H1 EMA200), ATR(14) at or above its 9200-candle average, and a candle hour of 20:00-00:59 on the strategy clock.
- **Exits:** SL 2 x ATR(14), TP 3 x SL (1:3), time stop after 2300 candles.
- **Defaults:** up to 3 trades open at once, 0.25% risk per trade.

Only the clock handling differs:
- **Exness (UTC+0):** the EA converts the time itself (+2 h in winter, +3 h in European summer).
- **FTMO:** the server time already is the strategy clock.

The EA's windowed Heikin Ashi and ATR calculations match the backtest on 3,000 random candles.

On the Exness data, with max 3 open, the EMA4000 trend filter beat the Supertrend and EMA50 variants. It was the only one profitable on the never-used 2020-01..2021-10 data (+0.19R/trade), and it had the smallest max drawdown (-63R, against -106R and -127R).

## H1 higher highs + bearish engulfing, sell limit at the open (`h1_hh_engulf.py`)

```bash
python h1_hh_engulf.py   # -> results/h1_hh_engulf.txt (trend-filter check: results/h1_hh_engulf_trend.txt)
```

The user's rules for the sell:
- **Setup:** 3 (or 4) H1 candles in a row make higher highs, then a bearish body engulfing closes.
- **Entry:** a sell limit at the engulfing open.
- **Exits:** SL at the engulfing high + 50 pips, TP 1:3.
- **Cancel:** the order is removed only when an H1 candle closes below the engulfing low.

The mirror buy is tested too. Signals come from H1; fills and exits run on M1 (our data) or M3 (the Exness export).

Results:
- **The sell loses.** With N = 3:
  - Our data: 203 trades (0.8 a week), 20.7% TP, -0.17R/trade.
  - Exness 2020-2026: 218 trades, 19.7% TP, -0.20R/trade (-0.42R/trade on the never-used 2020-21 data).
  - N = 4: -0.08R and -0.12R per trade.
  - About half the orders fill and the rest are cancelled.
- **Only sells below the H1 EMA200:** still a loss.
- **The mirror buy:** about break-even overall. Only above the H1 EMA200 it is slightly positive (+0.19R / +0.06R per trade), but that is about 1 trade a month.

### What the unfilled setups did (`h1_hh_engulf_unfilled.py`)

```bash
python h1_hh_engulf_unfilled.py   # -> results/h1_hh_engulf_unfilled.txt
```

For the cancelled sell limits (price closed below the engulfing low before retracing to the open), the script checks which planned level price reached first after the engulfing closed.

With 3 higher highs, most unfilled setups reached the planned TP first:

| Data | Reached TP first | Reached SL first |
|---|---|---|
| Our data | 120 (65%) | 65 (35%) |
| Exness | 114 (61%) | 72 (39%) |

Of the filled orders, only about 20% reached TP. The limit entry fills mostly on the setups that go against the trade.

Selling at market at the engulfing close does not fix this. Across all setups (same SL at the engulfing high + 50 pips, TP 1:3) it still loses: -0.10R/trade on our data and -0.25R/trade on Exness. The setups that later retrace lose heavily (about 11-12% TP, -0.53R/trade), and there is no way to know in advance which setups will retrace.

### Retracement of the unfilled setups (`h1_hh_engulf_retrace.py`)

```bash
python h1_hh_engulf_retrace.py   # -> results/h1_hh_engulf_retrace.txt
```

This looks at the setups whose limit at the open never filled but whose planned TP was reached first (114 on Exness, 120 on our data). For each, it measures the highest retracement before the TP.

- **How far they retraced:** a median of 44% of the engulfing body, or 48% of the whole candle. About 22% barely retraced at all (under 10% of the body).
- **Other entry levels:** with the sell limit at 0-100% of the body, every level still loses. The least bad is 25-38%: -0.12R/trade on Exness and -0.02R to -0.05R on our data.

### Entry on the confirming close instead of a retracement (`h1_hh_engulf_confirm.py`)

```bash
python h1_hh_engulf_confirm.py   # -> results/h1_hh_engulf_confirm.txt
```

Rules:
- **Entry:** after the engulfing, sell at market once an H1 candle closes below the engulfing low.
- **SL:** at the engulfing high (or high + 50 pips). TP is 1:3.
- **Dropped:** a setup is dropped if price reaches the SL level before the confirming close. This happens to about 45% of setups.

Results with 3 higher highs and the SL at the high:

| Data | Trades | TP | R / trade |
|---|---|---|---|
| Exness 2020-26 | 222 | 18.9% | -0.24 |
| Our data | 216 | 24.5% | -0.03 |

- With the SL at high + 50 pips, both datasets do worse.
- The median SL is about 100 pips, so the median TP is about 300 pips.
- The mirror buy (close above the high of a bullish engulfing after lower lows, SL at the low) made +0.11R/trade on Exness and +0.26R/trade on our data. That is only about 0.5-0.7 trades a week, and it lost on the 2020-21 Exness data.

**Engulfing on 3-decimal brokers:** our data has 2-decimal prices, so 36% of bearish engulfings there have an open exactly equal to the previous close. On Exness (3 decimals) that is 2%, and 1,309 candles failed the "open >= previous close" rule by only 1-5 cents. Engulfing rules without a small tolerance therefore find fewer, and different, setups on Exness.

### Sell limit at 25% retracement, SL at the engulfing high (`h1_hh_engulf_25.py`)

```bash
python h1_hh_engulf_25.py   # -> results/h1_hh_engulf_25.txt (levels 0-62%: results/h1_hh_engulf_levels_slhigh.txt)
```

Rules:
- **Setup:** 3 higher highs, then a bearish engulfing.
- **Entry:** a sell limit at close + 25% of the body.
- **Exits:** SL at the engulfing high, TP 1:3.
- **Cancel:** when an H1 candle closes below the engulfing low.

This is the first version of the user's engulfing idea that is profitable on both datasets:

| Data | Fills | Trades / week | TP | R / trade | Net | Max drawdown | Median SL / TP |
|---|---|---|---|---|---|---|---|
| Exness 2020-26 | 335 of 404 | 0.94 | 29.0% | +0.18 | +59R | -13R | 40 / 120 pips |
| Our data 2021-26 | 323 of 388 | 1.24 | 28.2% | +0.15 | +48R | -16R | |

- **By period:** every period is positive, including the never-used 2020-21 Exness data (+0.10R/trade).
- **Entry level:** the result is a smooth hump, positive from about 15% to 38% of the body, with 25-30% best on both datasets.
- **Failing variants:** the same rules with SL at high + 50 pips lose, and the mirror buy loses.

### Engulfing types and non-consecutive higher highs (`h1_hh_engulf_types.py`)

```bash
python h1_hh_engulf_types.py   # -> results/h1_hh_engulf_types.txt / .csv, periods: results/h1_hh_engulf_types_periods.txt
```

All tests use the 25% limit, SL at the engulfing high and TP 1:3. The script tries 6 bearish-engulfing types (body, body with a 5-cent tolerance, perfect, outside bar, strong, two-candle) and 6 higher-high rules. A higher high here is a new high above all earlier highs of the run, with 0, 1 or 2 pauses allowed.

- **Allowing pauses:** this gives more trades, but the results are not consistent. On Exness it turns the body engulfing negative (3 HH with 1 pause: -0.10R/trade). Consecutive higher highs are the reliable choice.
- **Results with 3 consecutive higher highs:**

| Type | Rule | Exness 2020-26 | Our data 2021-26 |
|---|---|---|---|
| Perfect | body + takes the previous high and low | 90 trades, 37.8% TP, +0.51R/trade, DD -6R | 81 trades, 37.0% TP, +0.48R/trade |
| Strong | body + close below the previous low | 189 trades, +0.22R/trade | 194 trades, +0.29R/trade |
| Body (baseline) | | 335 trades, +0.18R/trade | 323 trades, +0.15R/trade |

- **Perfect engulfing:** positive in every Exness period, including 2020-21, but it gives only about one trade a month. On our data, 2024-11..2026-10 was weak (+0.06R/trade).
- **Outside bar (wick engulfing):** loses.

### Losing trades that were in profit first, and breakeven stops (`h1_hh_engulf_be.py`)

```bash
python h1_hh_engulf_be.py   # -> results/h1_hh_engulf_be.txt
```

How far the SL trades went into profit before the stop was hit (25% sell, 3 consecutive higher highs):

| Data | SL trades | Reached 1:1 first | Reached 1:2 first |
|---|---|---|---|
| Exness | 238 | 72 (30%) | 27 (11%) |
| Our data | 232 | 72 (31%) | 28 (12%) |

A breakeven stop does not help:

| Breakeven at | Exness R / trade | Our data R / trade | Effect |
|---|---|---|---|
| none | +0.18 | +0.15 | |
| 1:1 | +0.08 | +0.07 | Exness TPs drop from 97 to 62 |
| 1:2 | +0.18 | +0.10 | |

Many winners come back to the entry before going on to the 1:3 TP.
