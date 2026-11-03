//+------------------------------------------------------------------+
//|                                  XAUUSD_M15_Breakout_Sweep_EA.mq5 |
//|                                     Copyright 2026, Auto Trading |
//|                                             https://www.mql5.com |
//+------------------------------------------------------------------+
//| Two M15 setups, TP = 3 x SL (same rules as m15_search.py):       |
//|                                                                  |
//| Setup 1 - Asian range breakout                                   |
//|   Range = high/low of the 01:00-09:45 candles (server time).     |
//|   10:00-15:45: the first M15 candle that CLOSES above the range  |
//|   -> buy at the next candle's open (first close below -> sell).  |
//|   SL at the other side of the range. One buy and one sell signal |
//|   per day at most. Skipped when the range is narrower than 2x or |
//|   wider than 10x the average M15 candle range of the last day.   |
//|                                                                  |
//| Setup 2 - previous-day high/low sweep                            |
//|   09:00-20:45: an M15 candle trades above yesterday's high but   |
//|   CLOSES back below it -> sell at the next open (mirror: below   |
//|   yesterday's low, close back above -> buy). SL beyond the sweep |
//|   wick + 0.2x the average candle range; the SL must be 1x-5x the |
//|   average candle range. Only the first sweep per side per day.   |
//|                                                                  |
//| Each setup has its own magic number and at most one open trade.  |
//| Hours are broker server time (data was UTC+2 winter / UTC+3      |
//| summer) - change the hour inputs if your broker differs.         |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026"
#property link      "https://www.mql5.com"
#property version   "1.00"

#include <Trade\Trade.mqh>
CTrade trade;

input group "Risk"
input double InpRiskPercent    = 1.0;    // Risk per trade, % of equity (0 = fixed lots)
input double InpFixedLots      = 0.10;   // Fixed lots, used when risk % is 0
input double InpRiskReward     = 3.0;    // TP = RR x SL distance

input group "Setup 1: Asian range breakout"
input bool   InpUseAsia        = true;   // Trade the Asian range breakout
input int    InpAsiaStartHour  = 1;      // Asian range: first candle hour (server time)
input int    InpAsiaEndHour    = 9;      // Asian range: last candle hour (09:45 candle included)
input int    InpBreakStartHour = 10;     // Breakout window: from hour
input int    InpBreakEndHour   = 15;     // Breakout window: to hour (15:45 candle included)
input double InpMinRangeATR    = 2.0;    // Min range width, x average M15 candle range
input double InpMaxRangeATR    = 10.0;   // Max range width, x average M15 candle range
input ulong  InpMagicAsia      = 777101; // Magic number, setup 1

input group "Setup 2: Previous-day high/low sweep"
input bool   InpUseSweep       = true;   // Trade the previous-day high/low sweep
input int    InpSweepStartHour = 9;      // Window: from hour (server time)
input int    InpSweepEndHour   = 20;     // Window: to hour (20:45 candle included)
input double InpSweepBufferATR = 0.2;    // SL buffer beyond the wick, x average candle range
input double InpSweepMinSLATR  = 1.0;    // Min SL distance, x average candle range
input double InpSweepMaxSLATR  = 5.0;    // Max SL distance, x average candle range
input ulong  InpMagicSweep     = 777102; // Magic number, setup 2

//--- State
datetime lastBar     = 0;
datetime flagDay     = 0;
bool     asiaUpDone  = false, asiaDnDone  = false;   // today's first breakout already seen
bool     sweepHiDone = false, sweepLoDone = false;   // today's first sweep already seen

//+------------------------------------------------------------------+
int OnInit()
{
   if(InpRiskReward <= 0 || InpAsiaEndHour < InpAsiaStartHour || InpBreakEndHour < InpBreakStartHour ||
      InpSweepEndHour < InpSweepStartHour || (InpRiskPercent <= 0 && InpFixedLots <= 0))
      return(INIT_PARAMETERS_INCORRECT);
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
   Comment("");
}

//+------------------------------------------------------------------+
void OnTick()
{
   datetime t[];
   if(CopyTime(_Symbol, PERIOD_M15, 0, 1, t) < 1) return;   // M15 history not ready yet

   if(lastBar == 0)              // first tick after attaching: learn today's signals, trade nothing
   {
      lastBar = t[0];
      InitTodayFlags(t[0]);
      ShowStatus();
      return;
   }
   if(t[0] != lastBar)           // a new M15 candle started, so the previous one just closed
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
//| High / low of the Asian-session candles of one day               |
//+------------------------------------------------------------------+
bool AsianRange(datetime day, double &rh, double &rl)
{
   MqlRates a[];
   datetime from = day + InpAsiaStartHour * 3600;
   datetime to   = day + InpAsiaEndHour * 3600 + 45 * 60;
   int n = CopyRates(_Symbol, PERIOD_M15, from, to, a);
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
//| Yesterday's high / low for the day that contains time t          |
//+------------------------------------------------------------------+
bool PrevDayHighLow(datetime t, double &pdh, double &pdl)
{
   int d1 = iBarShift(_Symbol, PERIOD_D1, t, false);
   if(d1 < 0) return(false);
   pdh = iHigh(_Symbol, PERIOD_D1, d1 + 1);
   pdl = iLow(_Symbol, PERIOD_D1, d1 + 1);
   return(pdh > 0 && pdl > 0);
}

//+------------------------------------------------------------------+
//| After attaching: replay today's closed candles to know which     |
//| first-of-the-day signals already happened (no orders are sent)   |
//+------------------------------------------------------------------+
void InitTodayFlags(datetime now)
{
   int first = iBarShift(_Symbol, PERIOD_M15, DayOf(now), false);   // first M15 candle of today
   for(int s = first; s >= 1; s--)
      Evaluate(s, false);
}

//+------------------------------------------------------------------+
//| Check the closed M15 candle at `shift` for both setups           |
//+------------------------------------------------------------------+
void Evaluate(int shift, bool doTrade)
{
   MqlRates r[];
   ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, PERIOD_M15, shift, 97, r) < 97) return;   // r[0] = candle being checked

   // average M15 candle range (true range) of the last 96 candles, r[0] included
   double sum = 0;
   for(int i = 0; i < 96; i++)
      sum += MathMax(r[i].high, r[i + 1].close) - MathMin(r[i].low, r[i + 1].close);
   double atr = sum / 96.0;

   datetime day = DayOf(r[0].time);
   if(day != flagDay)
   {
      flagDay = day;
      asiaUpDone = asiaDnDone = sweepHiDone = sweepLoDone = false;
   }
   MqlDateTime dt;
   TimeToStruct(r[0].time, dt);

   //--- Setup 1: Asian range breakout
   if(InpUseAsia && dt.hour >= InpBreakStartHour && dt.hour <= InpBreakEndHour)
   {
      double rh, rl;
      if(AsianRange(day, rh, rl))
      {
         double width = rh - rl;
         bool ok = (width >= InpMinRangeATR * atr) && (width <= InpMaxRangeATR * atr);
         if(ok && !asiaUpDone && r[0].close > rh)
         {
            asiaUpDone = true;
            if(doTrade) Open(1, r[0].close - rl, InpMagicAsia, "Asia_BO_Buy");
         }
         if(ok && !asiaDnDone && r[0].close < rl)
         {
            asiaDnDone = true;
            if(doTrade) Open(-1, rh - r[0].close, InpMagicAsia, "Asia_BO_Sell");
         }
      }
   }

   //--- Setup 2: previous-day high/low sweep
   if(InpUseSweep && dt.hour >= InpSweepStartHour && dt.hour <= InpSweepEndHour)
   {
      double pdh, pdl;
      if(PrevDayHighLow(r[0].time, pdh, pdl))
      {
         if(!sweepLoDone && r[0].low < pdl && r[0].close > pdl)
         {
            sweepLoDone = true;
            double dist = r[0].close - r[0].low + InpSweepBufferATR * atr;
            if(dist >= InpSweepMinSLATR * atr && dist <= InpSweepMaxSLATR * atr)
            {
               if(doTrade) Open(1, dist, InpMagicSweep, "Sweep_Buy");
            }
            else if(doTrade)
               PrintFormat("Sweep buy skipped: SL %s outside %.1f-%.1f x average range",
                           DoubleToString(dist, _Digits), InpSweepMinSLATR, InpSweepMaxSLATR);
         }
         if(!sweepHiDone && r[0].high > pdh && r[0].close < pdh)
         {
            sweepHiDone = true;
            double dist = r[0].high - r[0].close + InpSweepBufferATR * atr;
            if(dist >= InpSweepMinSLATR * atr && dist <= InpSweepMaxSLATR * atr)
            {
               if(doTrade) Open(-1, dist, InpMagicSweep, "Sweep_Sell");
            }
            else if(doTrade)
               PrintFormat("Sweep sell skipped: SL %s outside %.1f-%.1f x average range",
                           DoubleToString(dist, _Digits), InpSweepMinSLATR, InpSweepMaxSLATR);
         }
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
//| Market order with SL / TP from the fill price                    |
//+------------------------------------------------------------------+
void Open(int dir, double slDist, ulong magic, string comment)
{
   if(slDist <= 0) return;
   if(CountPositions(magic) > 0)
   {
      PrintFormat("%s skipped: this setup already has an open trade", comment);
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
   string s = "XAUUSD M15 Breakout + Sweep EA (TP 1:" + DoubleToString(InpRiskReward, 1) + ")\n";
   datetime now = TimeCurrent();
   if(InpUseAsia)
   {
      double rh, rl;
      if(AsianRange(DayOf(now), rh, rl))
         s += StringFormat("Asian range %s - %s | buy %s, sell %s | open trades %d\n",
                           DoubleToString(rl, _Digits), DoubleToString(rh, _Digits),
                           asiaUpDone ? "taken" : "waiting", asiaDnDone ? "taken" : "waiting",
                           CountPositions(InpMagicAsia));
      else
         s += "Asian range: not formed yet\n";
   }
   if(InpUseSweep)
   {
      double pdh, pdl;
      if(PrevDayHighLow(now, pdh, pdl))
         s += StringFormat("Yesterday high %s / low %s | sweep high %s, sweep low %s | open trades %d\n",
                           DoubleToString(pdh, _Digits), DoubleToString(pdl, _Digits),
                           sweepHiDone ? "taken" : "waiting", sweepLoDone ? "taken" : "waiting",
                           CountPositions(InpMagicSweep));
   }
   if(!AlgoTradingAllowed())
      s += "Algo Trading is OFF - turn it on, otherwise no trade can open";
   Comment(s);
}
//+------------------------------------------------------------------+
