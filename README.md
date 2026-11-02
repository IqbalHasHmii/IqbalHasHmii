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
