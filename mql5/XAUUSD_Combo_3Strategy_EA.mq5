//+------------------------------------------------------------------+
//|                                    XAUUSD_Combo_3Strategy_EA.mq5 |
//|                                     Copyright 2026, Auto Trading |
//|                                             https://www.mql5.com |
//+------------------------------------------------------------------+
//| Three XAUUSD setups in one EA, TP = 3 x SL. Attach to any XAUUSD |
//| chart (the EA reads M15 and H1 itself). Each setup has its own   |
//| magic number. Hours are broker server time (data: UTC+2 winter / |
//| UTC+3 summer) - change the hour inputs if your broker differs.   |
//|                                                                  |
//| 1. Asian range breakout (M15)                                    |
//|    Range = high/low of the 01:00-09:45 candles. 10:00-15:45: the |
//|    first M15 candle that CLOSES above the range -> buy at the    |
//|    next open (first close below -> sell). SL at the other side   |
//|    of the range. Range must be 2x-10x the average M15 candle     |
//|    range of the last day. One trade at a time.                   |
//| 2. Previous-day high/low sweep (M15)                             |
//|    09:00-20:45: a candle trades above yesterday's high but       |
//|    CLOSES back below it -> sell at the next open (mirror for the |
//|    low). SL beyond the wick + 0.2x the average candle range, SL  |
//|    must be 1x-5x the average range. First sweep per side per day.|
//| 3. H1 EMA200 engulfing                                           |
//|    H1 close above EMA200 -> buys only, below -> sells only. Body |
//|    engulfing in that direction -> limit order at the engulfing   |
//|    OPEN, valid for 5 H1 candles, deleted if the close crosses    |
//|    the EMA the other way. SL 100 pips, TP 300 pips from the open.|
//|    Mode "one trade at a time": a newer setup replaces an unfilled |
//|    order, no new setups while a trade is open. Mode "every       |
//|    engulfing": every setup gets its own order (bigger drawdown). |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026"
#property link      "https://www.mql5.com"
#property version   "1.00"

#include <Trade\Trade.mqh>
CTrade trade;

enum ENUM_H1_MODE
{
   H1_ONE_AT_A_TIME = 0,   // One trade at a time
   H1_EVERY_SETUP   = 1    // Every engulfing (trades can overlap)
};

input group "Risk"
input double InpRiskPercent    = 1.0;    // Risk per trade, % of equity (0 = fixed lots)
input double InpFixedLots      = 0.10;   // Fixed lots, used when risk % is 0
input double InpRiskReward     = 3.0;    // TP = RR x SL distance
input double InpPipSize        = 0.10;   // Price value of 1 pip (gold: 0.10)

input group "Setup 1: Asian range breakout (M15)"
input bool   InpUseAsia        = true;   // Trade the Asian range breakout
input int    InpAsiaStartHour  = 1;      // Asian range: first candle hour (server time)
input int    InpAsiaEndHour    = 9;      // Asian range: last candle hour (09:45 candle included)
input int    InpBreakStartHour = 10;     // Breakout window: from hour
input int    InpBreakEndHour   = 15;     // Breakout window: to hour (15:45 candle included)
input double InpMinRangeATR    = 2.0;    // Min range width, x average M15 candle range
input double InpMaxRangeATR    = 10.0;   // Max range width, x average M15 candle range
input ulong  InpMagicAsia      = 777101; // Magic number, setup 1

input group "Setup 2: Previous-day high/low sweep (M15)"
input bool   InpUseSweep       = true;   // Trade the previous-day high/low sweep
input int    InpSweepStartHour = 9;      // Window: from hour (server time)
input int    InpSweepEndHour   = 20;     // Window: to hour (20:45 candle included)
input double InpSweepBufferATR = 0.2;    // SL buffer beyond the wick, x average candle range
input double InpSweepMinSLATR  = 1.0;    // Min SL distance, x average candle range
input double InpSweepMaxSLATR  = 5.0;    // Max SL distance, x average candle range
input ulong  InpMagicSweep     = 777102; // Magic number, setup 2

input group "Setup 3: H1 EMA200 engulfing"
input bool         InpUseEma      = true;              // Trade the H1 EMA200 engulfing
input ENUM_H1_MODE InpEmaMode     = H1_ONE_AT_A_TIME;  // Mode
input int          InpEmaPeriod   = 200;               // EMA period (H1)
input double       InpEmaSLPips   = 100.0;             // SL distance from the engulfing open (pips)
input int          InpEmaValidBars = 5;                // Limit order valid for N H1 candles
input ulong        InpMagicEma    = 777103;            // Magic number, setup 3

//--- State
datetime lastM15     = 0;
datetime lastH1      = 0;
datetime flagDay     = 0;
bool     asiaUpDone  = false, asiaDnDone  = false;   // today's first breakout already seen
bool     sweepHiDone = false, sweepLoDone = false;   // today's first sweep already seen
int      emaHandle   = INVALID_HANDLE;

//+------------------------------------------------------------------+
int OnInit()
{
   if(InpRiskReward <= 0 || InpPipSize <= 0 || InpEmaValidBars < 1 || InpEmaSLPips <= 0 ||
      InpAsiaEndHour < InpAsiaStartHour || InpBreakEndHour < InpBreakStartHour ||
      InpSweepEndHour < InpSweepStartHour || (InpRiskPercent <= 0 && InpFixedLots <= 0))
      return(INIT_PARAMETERS_INCORRECT);

   emaHandle = iMA(_Symbol, PERIOD_H1, InpEmaPeriod, 0, MODE_EMA, PRICE_CLOSE);
   if(emaHandle == INVALID_HANDLE)
   {
      Print("Could not create the H1 EMA indicator");
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
   if(emaHandle != INVALID_HANDLE) IndicatorRelease(emaHandle);
   Comment("");
}

//+------------------------------------------------------------------+
void OnTick()
{
   datetime m[], h[];
   if(CopyTime(_Symbol, PERIOD_M15, 0, 1, m) < 1) return;   // history not ready yet
   if(CopyTime(_Symbol, PERIOD_H1, 0, 1, h) < 1) return;

   if(lastM15 == 0)              // first tick after attaching: learn today's signals, trade nothing
   {
      lastM15 = m[0];
      lastH1  = h[0];
      InitTodayFlags(m[0]);
      ShowStatus();
      return;
   }
   bool changed = false;
   if(m[0] != lastM15)           // a new M15 candle started, so the previous one just closed
   {
      lastM15 = m[0];
      EvaluateM15(1, true);
      changed = true;
   }
   if(h[0] != lastH1)            // a new H1 candle started
   {
      lastH1 = h[0];
      if(InpUseEma) EvaluateH1();
      changed = true;
   }
   if(changed) ShowStatus();

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
int CountPendingOrders(ulong magic)
{
   int n = 0;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0) continue;
      if(OrderGetString(ORDER_SYMBOL) == _Symbol && (ulong)OrderGetInteger(ORDER_MAGIC) == magic)
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
//| After attaching: replay today's closed M15 candles to know which |
//| first-of-the-day signals already happened (no orders are sent)   |
//+------------------------------------------------------------------+
void InitTodayFlags(datetime now)
{
   int first = iBarShift(_Symbol, PERIOD_M15, DayOf(now), false);
   for(int s = first; s >= 1; s--)
      EvaluateM15(s, false);
}

//+------------------------------------------------------------------+
//| Setups 1 and 2 on the closed M15 candle at `shift`               |
//+------------------------------------------------------------------+
void EvaluateM15(int shift, bool doTrade)
{
   if(!InpUseAsia && !InpUseSweep) return;
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
            if(doTrade) OpenMarket(1, r[0].close - rl, InpMagicAsia, "Asia_BO_Buy");
         }
         if(ok && !asiaDnDone && r[0].close < rl)
         {
            asiaDnDone = true;
            if(doTrade) OpenMarket(-1, rh - r[0].close, InpMagicAsia, "Asia_BO_Sell");
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
               if(doTrade) OpenMarket(1, dist, InpMagicSweep, "Sweep_Buy");
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
               if(doTrade) OpenMarket(-1, dist, InpMagicSweep, "Sweep_Sell");
            }
            else if(doTrade)
               PrintFormat("Sweep sell skipped: SL %s outside %.1f-%.1f x average range",
                           DoubleToString(dist, _Digits), InpSweepMinSLATR, InpSweepMaxSLATR);
         }
      }
   }
}

//+------------------------------------------------------------------+
//| H1 trend of the closed candle: 1 above EMA, -1 below, 0 unknown  |
//+------------------------------------------------------------------+
int EmaTrend(double close1)
{
   double e[];
   if(CopyBuffer(emaHandle, 0, 1, 1, e) < 1) return(0);
   if(close1 > e[0]) return(1);
   if(close1 < e[0]) return(-1);
   return(0);
}

//+------------------------------------------------------------------+
//| Setup 3 on the H1 candle that just closed                        |
//+------------------------------------------------------------------+
void EvaluateH1()
{
   MqlRates r[];
   ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, PERIOD_H1, 1, 2, r) < 2) return;   // r[0] = closed candle, r[1] = the one before
   int trend = EmaTrend(r[0].close);

   //--- manage our pending limit orders: expiry and trend flip
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0) continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol || (ulong)OrderGetInteger(ORDER_MAGIC) != InpMagicEma) continue;
      long type = OrderGetInteger(ORDER_TYPE);
      int  dir  = (type == ORDER_TYPE_BUY_LIMIT) ? 1 : -1;
      int  age  = iBarShift(_Symbol, PERIOD_H1, (datetime)OrderGetInteger(ORDER_TIME_SETUP), false);
      string why = "";
      if(trend == -dir)            why = "trend turned";
      else if(age >= InpEmaValidBars) why = "expired";
      if(why != "")
      {
         if(trade.OrderDelete(ticket)) PrintFormat("EMA limit order %s deleted: %s", (string)ticket, why);
         else PrintFormat("EMA limit order %s delete FAILED: %u (%s)", (string)ticket, trade.ResultRetcode(),
                          trade.ResultRetcodeDescription());
      }
   }

   //--- new setup on the closed candle
   double o = r[0].open, c = r[0].close, po = r[1].open, pc = r[1].close;
   bool bullEngulf = (po > pc) && (c > o) && (c >= po) && (o <= pc);
   bool bearEngulf = (pc > po) && (o > c) && (c <= po) && (o >= pc);
   int dir = 0;
   if(bullEngulf && trend == 1)       dir = 1;
   else if(bearEngulf && trend == -1) dir = -1;
   if(dir == 0) return;

   if(InpEmaMode == H1_ONE_AT_A_TIME)
   {
      if(CountPositions(InpMagicEma) > 0) return;          // no new setups while a trade is open
      for(int i = OrdersTotal() - 1; i >= 0; i--)          // a newer setup replaces the unfilled order
      {
         ulong ticket = OrderGetTicket(i);
         if(ticket == 0) continue;
         if(OrderGetString(ORDER_SYMBOL) == _Symbol && (ulong)OrderGetInteger(ORDER_MAGIC) == InpMagicEma)
            if(trade.OrderDelete(ticket)) PrintFormat("EMA limit order %s replaced by a newer setup", (string)ticket);
      }
   }
   PlaceEmaOrder(dir, o);
}

//+------------------------------------------------------------------+
//| Limit order at the engulfing open (market order if price is      |
//| already past it), SL / TP measured from the engulfing open       |
//+------------------------------------------------------------------+
void PlaceEmaOrder(int dir, double openPrice)
{
   MqlTick tk;
   if(!SymbolInfoTick(_Symbol, tk)) return;
   double dist   = InpEmaSLPips * InpPipSize;
   double p      = NormalizeDouble(openPrice, _Digits);
   double sl     = NormalizeDouble(p - dir * dist, _Digits);
   double tp     = NormalizeDouble(p + dir * dist * InpRiskReward, _Digits);
   double minGap = (SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) + 2) * _Point;
   double lots   = LotSize(dist);
   if(lots <= 0) return;
   trade.SetExpertMagicNumber(InpMagicEma);

   bool   priceAlreadyThere = (dir == 1) ? (tk.ask <= p + minGap) : (tk.bid >= p - minGap);
   bool   sent;
   string what;
   if(priceAlreadyThere)
   {
      bool slOK = (dir == 1) ? (sl < tk.bid - minGap) : (sl > tk.ask + minGap);
      if(!slOK) { Print("EMA setup skipped: price is already beyond the SL"); return; }
      what = (dir == 1) ? "EMA_Buy (market)" : "EMA_Sell (market)";
      sent = (dir == 1) ? trade.Buy(lots, _Symbol, tk.ask, sl, tp, what)
                        : trade.Sell(lots, _Symbol, tk.bid, sl, tp, what);
   }
   else
   {
      what = (dir == 1) ? "EMA_BuyLimit" : "EMA_SellLimit";
      sent = (dir == 1) ? trade.BuyLimit(lots, p, _Symbol, sl, tp, ORDER_TIME_GTC, 0, what)
                        : trade.SellLimit(lots, p, _Symbol, sl, tp, ORDER_TIME_GTC, 0, what);
   }
   uint rc = trade.ResultRetcode();
   if(sent && (rc == TRADE_RETCODE_DONE || rc == TRADE_RETCODE_PLACED))
      PrintFormat("%s: %.2f lots at %s | SL %s | TP %s", what, lots, DoubleToString(p, _Digits),
                  DoubleToString(sl, _Digits), DoubleToString(tp, _Digits));
   else
      PrintFormat("%s ORDER FAILED: retcode %u (%s)%s", what, rc, trade.ResultRetcodeDescription(),
                  AlgoTradingAllowed() ? "" : " - Algo Trading is OFF");
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
//| Market order with SL / TP from the fill price (setups 1 and 2)   |
//+------------------------------------------------------------------+
void OpenMarket(int dir, double slDist, ulong magic, string comment)
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
   string s = "XAUUSD 3-strategy EA (TP 1:" + DoubleToString(InpRiskReward, 1) + ")\n";
   datetime now = TimeCurrent();
   if(InpUseAsia)
   {
      double rh, rl;
      if(AsianRange(DayOf(now), rh, rl))
         s += StringFormat("1) Asian range %s - %s | buy %s, sell %s | open %d\n",
                           DoubleToString(rl, _Digits), DoubleToString(rh, _Digits),
                           asiaUpDone ? "taken" : "waiting", asiaDnDone ? "taken" : "waiting",
                           CountPositions(InpMagicAsia));
      else
         s += "1) Asian range: not formed yet\n";
   }
   if(InpUseSweep)
   {
      double pdh, pdl;
      if(PrevDayHighLow(now, pdh, pdl))
         s += StringFormat("2) Yesterday high %s / low %s | sweep high %s, low %s | open %d\n",
                           DoubleToString(pdh, _Digits), DoubleToString(pdl, _Digits),
                           sweepHiDone ? "taken" : "waiting", sweepLoDone ? "taken" : "waiting",
                           CountPositions(InpMagicSweep));
   }
   if(InpUseEma)
   {
      MqlRates r[];
      int trend = 0;
      if(CopyRates(_Symbol, PERIOD_H1, 1, 1, r) == 1) trend = EmaTrend(r[0].close);
      s += StringFormat("3) H1 EMA%d trend %s | limit orders %d | open %d\n", InpEmaPeriod,
                        trend == 1 ? "UP (buys)" : (trend == -1 ? "DOWN (sells)" : "-"),
                        CountPendingOrders(InpMagicEma), CountPositions(InpMagicEma));
   }
   if(!AlgoTradingAllowed())
      s += "Algo Trading is OFF - turn it on, otherwise no trade can open";
   Comment(s);
}
//+------------------------------------------------------------------+
