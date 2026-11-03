//+------------------------------------------------------------------+
//|                                       XAUUSD_M5_3Strategy_EA.mq5 |
//|                                     Copyright 2026, Auto Trading |
//|                                             https://www.mql5.com |
//+------------------------------------------------------------------+
//| Three M5 XAUUSD setups (same rules as m5_search.py), TP = 3 x SL.|
//| Signals are checked when an M5 candle closes; the trade opens at |
//| market right after. Each setup has its own magic number and, by  |
//| default, one open trade at a time (better than overlapping trades|
//| in the backtest). Hours are broker server time (data: UTC+2      |
//| winter / UTC+3 summer) - change the hour inputs if yours differs.|
//| "Average range" = average M5 true range of the last 288 candles. |
//|                                                                  |
//| 1. RSI pullback                                                  |
//|    Trend: close above EMA(2400) -> buys only, below -> sells.    |
//|    Buy when RSI(14) was below 25 and closes back above 25 (sell: |
//|    above 75 and back below). SL beyond the lowest low / highest  |
//|    high of the last 12 candles + 0.3x average range; the SL must |
//|    be 1x-10x the average range. Hours 09:00-20:55.               |
//| 2. New York opening-range breakout                               |
//|    Range = 16:30-16:55 candles. 17:00-19:55: first close above   |
//|    the range -> buy, below -> sell (first per side per day). SL  |
//|    at the other side of the range. Range must be 2x-15x the      |
//|    average range.                                                |
//| 3. Asian range breakout                                          |
//|    Range = 01:00-09:55 candles. 10:00-15:55: first close above / |
//|    below -> buy / sell (first per side per day). SL at the other |
//|    side. Range must be 3.5x-25x the average range.               |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026"
#property link      "https://www.mql5.com"
#property version   "1.00"

#include <Trade\Trade.mqh>
CTrade trade;

input group "Risk"
input double InpRiskPercent    = 0.5;    // Risk per trade, % of equity (0 = fixed lots)
input double InpFixedLots      = 0.10;   // Fixed lots, used when risk % is 0
input double InpRiskReward     = 3.0;    // TP = RR x SL distance
input bool   InpMultipleTrades = false;  // Let a setup open a new trade while its last one is open
input int    InpMaxOpenTrades  = 0;      // Safety cap: max open trades of this EA (0 = no limit)

input group "Setup 1: RSI pullback"
input bool   InpUseRsi         = true;   // Trade the RSI pullback
input int    InpRsiPeriod      = 14;     // RSI period
input double InpRsiLevel       = 25.0;   // Buy level (sell level = 100 - this)
input int    InpTrendEma       = 2400;   // Trend EMA period on M5 (~H1 EMA200)
input int    InpRsiLookback    = 12;     // SL beyond the low/high of the last N candles
input double InpRsiBufferATR   = 0.3;    // SL buffer, x average range
input double InpRsiMinSLATR    = 1.0;    // Min SL, x average range
input double InpRsiMaxSLATR    = 10.0;   // Max SL, x average range
input int    InpRsiStartHour   = 9;      // Signals from hour (server time)
input int    InpRsiEndHour     = 20;     // Signals to hour (20:55 candle included)
input ulong  InpMagicRsi       = 555501; // Magic number, setup 1

input group "Setup 2: New York opening-range breakout"
input bool   InpUseNy          = true;   // Trade the NY opening-range breakout
input int    InpNyStartHour    = 16;     // Range start hour (server time, NY 09:30)
input int    InpNyStartMinute  = 30;     // Range start minute
input int    InpNyRangeMinutes = 30;     // Range length in minutes
input int    InpNyEndHour      = 19;     // Breakout window to hour (19:55 candle included)
input double InpNyMinRangeATR  = 2.0;    // Min range width, x average range
input double InpNyMaxRangeATR  = 15.0;   // Max range width, x average range
input ulong  InpMagicNy        = 555502; // Magic number, setup 2

input group "Setup 3: Asian range breakout"
input bool   InpUseAsia        = true;   // Trade the Asian range breakout
input int    InpAsiaStartHour  = 1;      // Range: first candle hour (server time)
input int    InpAsiaEndHour    = 9;      // Range: last candle hour (09:55 candle included)
input int    InpBreakStartHour = 10;     // Breakout window from hour
input int    InpBreakEndHour   = 15;     // Breakout window to hour (15:55 candle included)
input double InpAsiaMinRangeATR = 3.5;   // Min range width, x average range
input double InpAsiaMaxRangeATR = 25.0;  // Max range width, x average range
input ulong  InpMagicAsia      = 555503; // Magic number, setup 3

#define ATR_BARS 288

//--- State
datetime lastBar    = 0;
datetime flagDay    = 0;
bool     nyUpDone   = false, nyDnDone   = false;   // today's first breakout per side already seen
bool     asiaUpDone = false, asiaDnDone = false;
int      rsiHandle  = INVALID_HANDLE;
int      emaHandle  = INVALID_HANDLE;

//+------------------------------------------------------------------+
int OnInit()
{
   if(InpRiskReward <= 0 || (InpRiskPercent <= 0 && InpFixedLots <= 0) || InpRsiLookback < 1 ||
      InpNyRangeMinutes < 5 || InpAsiaEndHour < InpAsiaStartHour || InpBreakEndHour < InpBreakStartHour ||
      InpRsiEndHour < InpRsiStartHour)
      return(INIT_PARAMETERS_INCORRECT);

   rsiHandle = iRSI(_Symbol, PERIOD_M5, InpRsiPeriod, PRICE_CLOSE);
   emaHandle = iMA(_Symbol, PERIOD_M5, InpTrendEma, 0, MODE_EMA, PRICE_CLOSE);
   if(rsiHandle == INVALID_HANDLE || emaHandle == INVALID_HANDLE)
   {
      Print("Could not create the RSI / EMA indicators");
      return(INIT_FAILED);
   }
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
   if(rsiHandle != INVALID_HANDLE) IndicatorRelease(rsiHandle);
   if(emaHandle != INVALID_HANDLE) IndicatorRelease(emaHandle);
   Comment("");
}

//+------------------------------------------------------------------+
void OnTick()
{
   datetime t[];
   if(CopyTime(_Symbol, PERIOD_M5, 0, 1, t) < 1) return;   // M5 history not ready yet

   if(lastBar == 0)              // first tick after attaching: learn today's signals, trade nothing
   {
      lastBar = t[0];
      int first = iBarShift(_Symbol, PERIOD_M5, DayOf(t[0]), false);
      for(int s = first; s >= 1; s--)
         Evaluate(s, false);
      ShowStatus();
      return;
   }
   if(t[0] != lastBar)           // a new M5 candle started, so the previous one just closed
   {
      lastBar = t[0];
      Evaluate(1, true);
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
datetime DayOf(datetime t)
{
   return(StringToTime(TimeToString(t, TIME_DATE)));
}

//+------------------------------------------------------------------+
int CountPositions(ulong magic)
{
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol && (ulong)PositionGetInteger(POSITION_MAGIC) == magic)
         n++;
   }
   return(n);
}

//+------------------------------------------------------------------+
int CountAllMine()
{
   return(CountPositions(InpMagicRsi) + CountPositions(InpMagicNy) + CountPositions(InpMagicAsia));
}

//+------------------------------------------------------------------+
//| High / low of the M5 candles between two times (both included)   |
//+------------------------------------------------------------------+
bool RangeHighLow(datetime from, datetime to, double &rh, double &rl)
{
   MqlRates a[];
   int n = CopyRates(_Symbol, PERIOD_M5, from, to, a);
   if(n < 1) return(false);
   rh = a[0].high;
   rl = a[0].low;
   for(int i = 1; i < n; i++)
   {
      rh = MathMax(rh, a[i].high);
      rl = MathMin(rl, a[i].low);
   }
   return(true);
}

//+------------------------------------------------------------------+
datetime NyRangeStart(datetime day) { return(day + InpNyStartHour * 3600 + InpNyStartMinute * 60); }
datetime NyRangeLast(datetime day)  { return(NyRangeStart(day) + (InpNyRangeMinutes - 5) * 60); }

//+------------------------------------------------------------------+
//| Check the closed M5 candle at `shift` for all three setups       |
//+------------------------------------------------------------------+
void Evaluate(int shift, bool doTrade)
{
   MqlRates r[];
   ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, PERIOD_M5, shift, ATR_BARS + 1, r) < ATR_BARS + 1) return;   // r[0] = closed candle

   double sum = 0;
   for(int i = 0; i < ATR_BARS; i++)
      sum += MathMax(r[i].high, r[i + 1].close) - MathMin(r[i].low, r[i + 1].close);
   double atr = sum / ATR_BARS;

   datetime day = DayOf(r[0].time);
   if(day != flagDay)
   {
      flagDay = day;
      nyUpDone = nyDnDone = asiaUpDone = asiaDnDone = false;
   }
   MqlDateTime dt;
   TimeToStruct(r[0].time, dt);
   int mins = dt.hour * 60 + dt.min;
   double c = r[0].close;

   //--- Setup 2: New York opening-range breakout
   int nyFrom = InpNyStartHour * 60 + InpNyStartMinute + InpNyRangeMinutes;
   if(InpUseNy && mins >= nyFrom && mins <= InpNyEndHour * 60 + 55)
   {
      double rh, rl;
      if(RangeHighLow(NyRangeStart(day), NyRangeLast(day), rh, rl))
      {
         double width = rh - rl;
         bool ok = (width >= InpNyMinRangeATR * atr) && (width <= InpNyMaxRangeATR * atr);
         if(ok && !nyUpDone && c > rh)
         {
            nyUpDone = true;
            if(doTrade) OpenMarket(1, c - rl, InpMagicNy, "NY_ORB_Buy");
         }
         if(ok && !nyDnDone && c < rl)
         {
            nyDnDone = true;
            if(doTrade) OpenMarket(-1, rh - c, InpMagicNy, "NY_ORB_Sell");
         }
      }
   }

   //--- Setup 3: Asian range breakout
   if(InpUseAsia && dt.hour >= InpBreakStartHour && dt.hour <= InpBreakEndHour)
   {
      double rh, rl;
      if(RangeHighLow(day + InpAsiaStartHour * 3600, day + InpAsiaEndHour * 3600 + 55 * 60, rh, rl))
      {
         double width = rh - rl;
         bool ok = (width >= InpAsiaMinRangeATR * atr) && (width <= InpAsiaMaxRangeATR * atr);
         if(ok && !asiaUpDone && c > rh)
         {
            asiaUpDone = true;
            if(doTrade) OpenMarket(1, c - rl, InpMagicAsia, "Asia_BO_Buy");
         }
         if(ok && !asiaDnDone && c < rl)
         {
            asiaDnDone = true;
            if(doTrade) OpenMarket(-1, rh - c, InpMagicAsia, "Asia_BO_Sell");
         }
      }
   }

   //--- Setup 1: RSI pullback (no daily flags, so nothing to learn when only replaying)
   if(doTrade && InpUseRsi && dt.hour >= InpRsiStartHour && dt.hour <= InpRsiEndHour)
   {
      double rs[], em[];
      ArraySetAsSeries(rs, true);
      if(CopyBuffer(rsiHandle, 0, shift, 2, rs) < 2) return;   // rs[0] = closed candle, rs[1] = before
      if(CopyBuffer(emaHandle, 0, shift, 1, em) < 1) return;
      double lo = r[0].low, hi = r[0].high;
      for(int i = 1; i < InpRsiLookback; i++)
      {
         lo = MathMin(lo, r[i].low);
         hi = MathMax(hi, r[i].high);
      }
      int dir = 0;
      double dist = 0;
      if(c > em[0] && rs[1] < InpRsiLevel && rs[0] >= InpRsiLevel)
      {
         dir = 1;  dist = c - lo + InpRsiBufferATR * atr;
      }
      else if(c < em[0] && rs[1] > 100 - InpRsiLevel && rs[0] <= 100 - InpRsiLevel)
      {
         dir = -1; dist = hi - c + InpRsiBufferATR * atr;
      }
      if(dir != 0)
      {
         if(dist >= InpRsiMinSLATR * atr && dist <= InpRsiMaxSLATR * atr)
            OpenMarket(dir, dist, InpMagicRsi, dir == 1 ? "RSI_PB_Buy" : "RSI_PB_Sell");
         else
            PrintFormat("RSI signal skipped: SL %s outside %.1f-%.1f x average range",
                        DoubleToString(dist, _Digits), InpRsiMinSLATR, InpRsiMaxSLATR);
      }
   }
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
      PrintFormat("Trade skipped: %.1f%% risk with a %s SL is below the minimum lot %.2f - "
                  "raise the risk or set a fixed lot", InpRiskPercent, DoubleToString(slDist, _Digits), vmin);
      return(0);
   }
   return(NormalizeDouble(MathMin(lots, vmax), 2));
}

//+------------------------------------------------------------------+
//| Market order with SL / TP measured from the fill price           |
//+------------------------------------------------------------------+
void OpenMarket(int dir, double slDist, ulong magic, string comment)
{
   if(slDist <= 0) return;
   if(!InpMultipleTrades && CountPositions(magic) > 0)
   {
      PrintFormat("%s skipped: this setup already has an open trade", comment);
      return;
   }
   if(InpMaxOpenTrades > 0 && CountAllMine() >= InpMaxOpenTrades)
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

   trade.SetExpertMagicNumber(magic);
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
//| Status lines on the chart                                        |
//+------------------------------------------------------------------+
void ShowStatus()
{
   string s = "XAUUSD M5 3-strategy EA (TP 1:" + DoubleToString(InpRiskReward, 1) + ", " +
              (InpMultipleTrades ? "multiple trades" : "one trade per setup") + ")\n";
   datetime day = DayOf(TimeCurrent());
   if(InpUseRsi)
   {
      double rs[], em[];
      MqlRates r[];
      string trend = "-", rsiTxt = "-";
      if(CopyBuffer(emaHandle, 0, 1, 1, em) == 1 && CopyRates(_Symbol, PERIOD_M5, 1, 1, r) == 1)
         trend = (r[0].close > em[0]) ? "UP (buys)" : "DOWN (sells)";
      if(CopyBuffer(rsiHandle, 0, 1, 1, rs) == 1) rsiTxt = DoubleToString(rs[0], 1);
      s += StringFormat("1) RSI pullback: trend %s, RSI %s | open %d\n", trend, rsiTxt, CountPositions(InpMagicRsi));
   }
   if(InpUseNy)
   {
      double rh, rl;
      if(TimeCurrent() > NyRangeLast(day) + 5 * 60 && RangeHighLow(NyRangeStart(day), NyRangeLast(day), rh, rl))
         s += StringFormat("2) NY range %s - %s | buy %s, sell %s | open %d\n",
                           DoubleToString(rl, _Digits), DoubleToString(rh, _Digits),
                           nyUpDone ? "taken" : "waiting", nyDnDone ? "taken" : "waiting", CountPositions(InpMagicNy));
      else
         s += StringFormat("2) NY range: not formed yet | open %d\n", CountPositions(InpMagicNy));
   }
   if(InpUseAsia)
   {
      double rh, rl;
      if(RangeHighLow(day + InpAsiaStartHour * 3600, day + InpAsiaEndHour * 3600 + 55 * 60, rh, rl))
         s += StringFormat("3) Asian range %s - %s | buy %s, sell %s | open %d\n",
                           DoubleToString(rl, _Digits), DoubleToString(rh, _Digits),
                           asiaUpDone ? "taken" : "waiting", asiaDnDone ? "taken" : "waiting", CountPositions(InpMagicAsia));
      else
         s += StringFormat("3) Asian range: not formed yet | open %d\n", CountPositions(InpMagicAsia));
   }
   if(!AlgoTradingAllowed())
      s += "Algo Trading is OFF - turn it on, otherwise no trade can open";
   Comment(s);
}
//+------------------------------------------------------------------+
