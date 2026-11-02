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
