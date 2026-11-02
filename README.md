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

## Execution model
- Signal candle ke **close** pe banta hai aur trade **agli candle ke open** pe khulta hai (look-ahead bias nahi hota).
- Har candle ka asal spread CSV ke `<SPREAD>` column se liya jata hai. Buy ask pe aur sell bid pe fill hoti hai.
- Agar SL aur TP dono ek hi candle ke andar hit hon to **SL** maana jata hai (conservative assumption).
- Ek waqt mein sirf ek trade khulti hai. Lot size risk % aur SL distance se nikalta hai (1 lot = 100 oz).

## Nayi strategy add karna
`strategies.py` mein ek function likhein jo `signal` (1/-1/0), `sl_dist` aur `tp_dist` columns return kare, phir use `REGISTRY` mein add kar dein.
