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
