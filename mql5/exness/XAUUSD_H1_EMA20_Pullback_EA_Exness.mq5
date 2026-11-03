//+------------------------------------------------------------------+
//|                                  XAUUSD_H1_EMA20_Pullback_EA.mq5 |
//|                                     Copyright 2026, Auto Trading |
//|                                             https://www.mql5.com |
//+------------------------------------------------------------------+
//| H1 EMA20 pullback, buys and sells, TP = 3 x SL                   |
//| (same rules as m60_ema20_pullback.py)                            |
//|                                                                  |
//| Checked when every H1 candle closes, at any hour:                |
//|  BUY : close above EMA200, the candle's low touched EMA20, it     |
//|        closed above EMA20 and is bullish (close > open).         |
//|  SELL: close below EMA200, the high touched EMA20, it closed      |
//|        below EMA20 and is bearish.                               |
//| Market order right after the candle closes. SL = 2 x ATR(14),    |
//| TP = 3 x SL. A trade still open after InpMaxHoldBars H1 candles  |
//| is closed at market (time stop, as in the backtest).             |
//| Every signal is its own trade, up to InpMaxOpenTrades at once.   |
//| Attach to any XAUUSD chart; the EA reads H1 itself.              |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026"
#property link      "https://www.mql5.com"
#property description "Exness version: same as XAUUSD_H1_EMA20_Pullback_EA - it uses no session hours, so the broker time zone does not matter."
#property version   "1.00"

#include <Trade\Trade.mqh>
CTrade trade;

input group "Risk"
input double InpRiskPercent   = 0.5;    // Risk per trade, % of equity (0 = fixed lots)
input double InpFixedLots     = 0.10;   // Fixed lots, used when risk % is 0
input double InpRiskReward    = 3.0;    // TP = RR x SL distance
input int    InpMaxOpenTrades = 5;      // Max trades open at once (0 = no limit)

input group "Strategy"
input bool   InpAllowBuys     = true;   // Take buy signals
input bool   InpAllowSells    = true;   // Take sell signals
input int    InpFastEma       = 20;     // Pullback EMA
input int    InpTrendEma      = 200;    // Trend EMA
input int    InpAtrPeriod     = 14;     // ATR period (Wilder)
input double InpSLATR         = 2.0;    // SL = this x ATR
input int    InpMaxHoldBars   = 115;    // Time stop: close after N H1 candles (0 = off)
input ulong  InpMagic         = 606020; // Magic number

//--- State
datetime lastBar    = 0;
int      fastHandle = INVALID_HANDLE;
int      trendHandle = INVALID_HANDLE;
string   lastSignal = "none yet";

//+------------------------------------------------------------------+
int OnInit()
{
   if(InpRiskReward <= 0 || InpSLATR <= 0 || InpAtrPeriod < 1 || (InpRiskPercent <= 0 && InpFixedLots <= 0))
      return(INIT_PARAMETERS_INCORRECT);
   fastHandle  = iMA(_Symbol, PERIOD_H1, InpFastEma, 0, MODE_EMA, PRICE_CLOSE);
   trendHandle = iMA(_Symbol, PERIOD_H1, InpTrendEma, 0, MODE_EMA, PRICE_CLOSE);
   if(fastHandle == INVALID_HANDLE || trendHandle == INVALID_HANDLE)
   {
      Print("Could not create the EMA indicators");
      return(INIT_FAILED);
   }
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetDeviationInPoints(30);
   PrintFormat("Started on %s: digits %d, stops level %d points, spread %d points",
               _Symbol, (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS),
               (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL),
               (int)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD));
   if(!AlgoTradingAllowed())
      Print("Algo Trading is OFF - turn it on, otherwise no trade can open");
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(fastHandle != INVALID_HANDLE)  IndicatorRelease(fastHandle);
   if(trendHandle != INVALID_HANDLE) IndicatorRelease(trendHandle);
   Comment("");
}

//+------------------------------------------------------------------+
void OnTick()
{
   datetime t[];
   if(CopyTime(_Symbol, PERIOD_H1, 0, 1, t) < 1) return;   // H1 history not ready yet

   if(lastBar == 0)              // first tick after attaching: do not trade a candle that closed earlier
   {
      lastBar = t[0];
      ShowStatus();
      return;
   }
   if(t[0] != lastBar)           // a new H1 candle started, so the previous one just closed
   {
      lastBar = t[0];
      TimeStop();
      CheckSignal();
      ShowStatus();
   }

   // refresh the chart status right away when Algo Trading is switched on or off
   static bool lastAllowed = true;
   bool allowed = AlgoTradingAllowed();
   if(allowed != lastAllowed) { lastAllowed = allowed; ShowStatus(); }
}

//+------------------------------------------------------------------+
bool AlgoTradingAllowed()
{
   return(TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) != 0 && MQLInfoInteger(MQL_TRADE_ALLOWED) != 0);
}

//+------------------------------------------------------------------+
int CountMine()
{
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol && (ulong)PositionGetInteger(POSITION_MAGIC) == InpMagic)
         n++;
   }
   return(n);
}

//+------------------------------------------------------------------+
//| Wilder ATR of the closed H1 candle at `shift`                    |
//+------------------------------------------------------------------+
double WilderATR(int shift)
{
   int need = InpAtrPeriod * 20 + 1;                 // long enough for the smoothing to settle
   MqlRates r[];
   ArraySetAsSeries(r, false);                       // oldest first
   if(CopyRates(_Symbol, PERIOD_H1, shift, need, r) < need) return(0);
   double atr = 0;
   for(int i = 1; i < need; i++)
   {
      double tr = MathMax(r[i].high, r[i - 1].close) - MathMin(r[i].low, r[i - 1].close);
      atr = (i == 1) ? tr : atr + (tr - atr) / InpAtrPeriod;
   }
   return(atr);
}

//+------------------------------------------------------------------+
//| Signal on the H1 candle that just closed                         |
//+------------------------------------------------------------------+
void CheckSignal()
{
   MqlRates r[];
   double f[], s[];
   if(CopyRates(_Symbol, PERIOD_H1, 1, 1, r) < 1) return;
   if(CopyBuffer(fastHandle, 0, 1, 1, f) < 1 || CopyBuffer(trendHandle, 0, 1, 1, s) < 1) return;

   double o = r[0].open, h = r[0].high, l = r[0].low, c = r[0].close;
   int dir = 0;
   if(InpAllowBuys && c > s[0] && l <= f[0] && c > f[0] && c > o)       dir = 1;
   else if(InpAllowSells && c < s[0] && h >= f[0] && c < f[0] && c < o) dir = -1;
   if(dir == 0) return;

   double atr = WilderATR(1);
   if(atr <= 0) { Print("ATR not ready - signal skipped"); return; }
   lastSignal = StringFormat("%s at %s", dir == 1 ? "BUY" : "SELL", TimeToString(r[0].time + PeriodSeconds(PERIOD_H1)));
   OpenMarket(dir, InpSLATR * atr);
}

//+------------------------------------------------------------------+
//| Lots for the chosen risk (rounded down to the volume step)       |
//+------------------------------------------------------------------+
double LotSize(double slDist)
{
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double lots = InpFixedLots;
   if(InpRiskPercent > 0)
   {
      double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
      double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
      if(tickValue <= 0 || tickSize <= 0 || step <= 0) return(0);
      double riskMoney  = AccountInfoDouble(ACCOUNT_EQUITY) * InpRiskPercent / 100.0;
      double lossPerLot = slDist / tickSize * tickValue;
      lots = riskMoney / lossPerLot;
   }
   lots = MathFloor(lots / step) * step;
   if(lots < vmin)
   {
      PrintFormat("Trade skipped: %.2f%% risk with a %s SL is below the minimum lot %.2f - "
                  "raise the risk or set a fixed lot", InpRiskPercent, DoubleToString(slDist, _Digits), vmin);
      return(0);
   }
   return(NormalizeDouble(MathMin(lots, vmax), 2));
}

//+------------------------------------------------------------------+
//| Market order with SL / TP measured from the fill price           |
//+------------------------------------------------------------------+
void OpenMarket(int dir, double slDist)
{
   string comment = (dir == 1) ? "EMA20_PB_Buy" : "EMA20_PB_Sell";
   if(InpMaxOpenTrades > 0 && CountMine() >= InpMaxOpenTrades)
   {
      PrintFormat("%s skipped: %d trades already open (InpMaxOpenTrades)", comment, InpMaxOpenTrades);
      return;
   }
   MqlTick tk;
   if(!SymbolInfoTick(_Symbol, tk)) return;

   double price  = (dir == 1) ? tk.ask : tk.bid;
   double sl     = NormalizeDouble(price - dir * slDist, _Digits);
   double tp     = NormalizeDouble(price + dir * slDist * InpRiskReward, _Digits);
   double minGap = (SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) + 2) * _Point;
   bool slOK = (dir == 1) ? (sl < tk.bid - minGap) : (sl > tk.ask + minGap);
   if(!slOK)
   {
      PrintFormat("%s skipped: SL %s is too close to the price", comment, DoubleToString(sl, _Digits));
      return;
   }
   double lots = LotSize(slDist);
   if(lots <= 0) return;

   bool sent = (dir == 1) ? trade.Buy(lots, _Symbol, price, sl, tp, comment)
                          : trade.Sell(lots, _Symbol, price, sl, tp, comment);
   uint rc = trade.ResultRetcode();
   if(sent && (rc == TRADE_RETCODE_DONE || rc == TRADE_RETCODE_PLACED))
      PrintFormat("%s opened: %.2f lots at %s | SL %s | TP %s", comment, lots,
                  DoubleToString(trade.ResultPrice(), _Digits), DoubleToString(sl, _Digits), DoubleToString(tp, _Digits));
   else
      PrintFormat("%s ORDER FAILED: retcode %u (%s)%s", comment, rc, trade.ResultRetcodeDescription(),
                  AlgoTradingAllowed() ? "" : " - Algo Trading is OFF");
}

//+------------------------------------------------------------------+
//| Close trades that have been open for InpMaxHoldBars H1 candles   |
//+------------------------------------------------------------------+
void TimeStop()
{
   if(InpMaxHoldBars <= 0) return;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol || (ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      int age = iBarShift(_Symbol, PERIOD_H1, (datetime)PositionGetInteger(POSITION_TIME), false);
      if(age < InpMaxHoldBars) continue;
      if(trade.PositionClose(ticket))
         PrintFormat("Trade %s closed by the time stop (%d H1 candles)", (string)ticket, age);
      else
         PrintFormat("Time-stop close FAILED: retcode %u (%s)", trade.ResultRetcode(), trade.ResultRetcodeDescription());
   }
}

//+------------------------------------------------------------------+
//| Status lines on the chart                                        |
//+------------------------------------------------------------------+
void ShowStatus()
{
   string s = "XAUUSD H1 EMA20 pullback EA (buys + sells, TP 1:" + DoubleToString(InpRiskReward, 1) + ")\n";
   MqlRates r[];
   double f[], e[];
   if(CopyRates(_Symbol, PERIOD_H1, 1, 1, r) == 1 && CopyBuffer(fastHandle, 0, 1, 1, f) == 1 &&
      CopyBuffer(trendHandle, 0, 1, 1, e) == 1)
      s += StringFormat("Trend: %s | EMA20 %s | EMA200 %s | ATR %s\n",
                        r[0].close > e[0] ? "UP (buys)" : "DOWN (sells)", DoubleToString(f[0], _Digits),
                        DoubleToString(e[0], _Digits), DoubleToString(WilderATR(1), _Digits));
   s += StringFormat("Open trades: %d%s | last signal: %s\n", CountMine(),
                     InpMaxOpenTrades > 0 ? " / " + (string)InpMaxOpenTrades + " max" : "", lastSignal);
   if(!AlgoTradingAllowed())
      s += "Algo Trading is OFF - turn it on, otherwise no trade can open";
   Comment(s);
}
//+------------------------------------------------------------------+
