//+------------------------------------------------------------------+
//|                                       XAUUSD_All_Strategies_EA.mq5 |
//|                                     Copyright 2026, Auto Trading |
//|                                             https://www.mql5.com |
//+------------------------------------------------------------------+
//| Every strategy built so far, in one EA. Each strategy runs on    |
//| its own: own magic number, own state, own trades, own on/off     |
//| switch and own "max open trades". One strategy never closes,     |
//| blocks or changes another strategy's trades (only the optional   |
//| InpMaxOpenTotal cap counts them together). TP = 3 x SL for all.  |
//|                                                                  |
//|  1  M15 Asian range breakout      (backtest +)                   |
//|  2  M15 previous-day sweep        (backtest +)                   |
//|  3  H1 EMA200 engulfing limit     (backtest +)                   |
//|  4  M5 RSI pullback               (backtest +)                   |
//|  5  M5 New York opening range     (backtest +)                   |
//|  6  M5 Asian range breakout       (backtest +)                   |
//|  7  H1 EMA20 pullback, buy + sell (backtest +)                   |
//|  8  M15 Extreme OB (v2.10)        (backtest LOSS - off)          |
//|  9  H1 Extreme OB (v2.10)         (backtest LOSS - off)          |
//|                                                                  |
//| Session hours are those of the backtest data (UTC+2 winter /     |
//| UTC+3 summer). InpClock tells the EA how your broker's clock     |
//| relates to that: Exness (UTC+0) is converted automatically,      |
//| summer and winter included; FTMO already matches.                |
//| Attach to ONE XAUUSD chart (any timeframe).                      |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026"
#property link      "https://www.mql5.com"
#property version   "1.00"

#include <Trade\Trade.mqh>
CTrade trade;

enum ENUM_CLOCK
{
   CLOCK_FIXED_UTC = 0,   // Fixed UTC offset, no DST (Exness: UTC+0)
   CLOCK_BACKTEST  = 1    // Same as the backtest data (FTMO: UTC+2 / UTC+3)
};

input group "General"
input ENUM_CLOCK InpClock        = CLOCK_FIXED_UTC; // Broker clock
input int        InpServerUTC    = 0;      // Fixed-offset broker: server time = UTC+N (Exness = 0)
input double     InpRiskPercent  = 0.5;    // Risk per trade, % of equity (0 = fixed lots)
input double     InpFixedLots    = 0.10;   // Fixed lots, used when risk % is 0
input double     InpRiskReward   = 3.0;    // TP = RR x SL distance
input double     InpPipSize      = 0.10;   // Price value of 1 pip (gold: 0.10)
input int        InpMaxOpenTotal = 0;      // Max open trades of ALL strategies together (0 = no limit)

input group "1) M15 Asian range breakout"
input bool   InpS1_On      = true;    // On
input int    InpS1_MaxOpen = 1;       // Max open trades of this strategy (0 = no limit)
input ulong  InpS1_Magic   = 901001;  // Magic number

input group "2) M15 previous-day high/low sweep"
input bool   InpS2_On      = true;    // On
input int    InpS2_MaxOpen = 1;       // Max open trades of this strategy (0 = no limit)
input ulong  InpS2_Magic   = 901002;  // Magic number

input group "3) H1 EMA200 engulfing (limit at the engulfing open)"
input bool   InpS3_On      = true;    // On
input int    InpS3_MaxOpen = 1;       // 1 = one at a time (newer setup replaces the order), 0 = no limit
input ulong  InpS3_Magic   = 901003;  // Magic number

input group "4) M5 RSI pullback"
input bool   InpS4_On      = true;    // On
input int    InpS4_MaxOpen = 1;       // Max open trades of this strategy (0 = no limit)
input ulong  InpS4_Magic   = 901004;  // Magic number

input group "5) M5 New York opening-range breakout"
input bool   InpS5_On      = true;    // On
input int    InpS5_MaxOpen = 1;       // Max open trades of this strategy (0 = no limit)
input ulong  InpS5_Magic   = 901005;  // Magic number

input group "6) M5 Asian range breakout"
input bool   InpS6_On      = true;    // On
input int    InpS6_MaxOpen = 1;       // Max open trades of this strategy (0 = no limit)
input ulong  InpS6_Magic   = 901006;  // Magic number

input group "7) H1 EMA20 pullback, buys and sells"
input bool   InpS7_On      = true;    // On
input int    InpS7_MaxOpen = 5;       // Max open trades of this strategy (0 = no limit)
input ulong  InpS7_Magic   = 901007;  // Magic number

input group "8) M15 Extreme OB v2.10 (lost money in the backtest)"
input bool   InpS8_On      = false;   // On
input ulong  InpS8_Magic   = 901008;  // Magic number

input group "9) H1 Extreme OB v2.10 (lost money in the backtest)"
input bool   InpS9_On      = false;   // On
input ulong  InpS9_Magic   = 901009;  // Magic number

//+------------------------------------------------------------------+
//| State                                                            |
//+------------------------------------------------------------------+
struct DayFlags                       // "first signal per side per day" memory of one strategy
{
   datetime day;
   bool     up;
   bool     dn;
};

struct ObState                        // one Extreme OB strategy (8 or 9)
{
   bool            on;
   ENUM_TIMEFRAMES tf;
   int             structN;           // trend: close vs close N candles ago
   double          minSL, maxSL;      // pips
   double          emergencyPips;     // broker SL distance from entry
   ulong           magic;
   string          name;
   string          gv;                // terminal global variable: wick level of the open trade
   bool            armed;
   int             dir;
   double          entry, wick;
   int             left;              // candles the limit entry stays valid
};

DayFlags  f1, f2hi, f5, f6;           // f2hi: up = low swept (buy), dn = high swept (sell)
ObState   ob8, ob9;
datetime  lastM5 = 0, lastM15 = 0, lastH1 = 0;
bool      started = false;
int       hEma200 = INVALID_HANDLE, hEma20 = INVALID_HANDLE, hRsi = INVALID_HANDLE, hEma2400 = INVALID_HANDLE;
string    last7 = "none yet";

//+------------------------------------------------------------------+
int OnInit()
{
   if(InpRiskReward <= 0 || InpPipSize <= 0 || (InpRiskPercent <= 0 && InpFixedLots <= 0))
      return(INIT_PARAMETERS_INCORRECT);

   hEma200  = iMA(_Symbol, PERIOD_H1, 200, 0, MODE_EMA, PRICE_CLOSE);
   hEma20   = iMA(_Symbol, PERIOD_H1, 20, 0, MODE_EMA, PRICE_CLOSE);
   hRsi     = iRSI(_Symbol, PERIOD_M5, 14, PRICE_CLOSE);
   hEma2400 = iMA(_Symbol, PERIOD_M5, 2400, 0, MODE_EMA, PRICE_CLOSE);
   if(hEma200 == INVALID_HANDLE || hEma20 == INVALID_HANDLE || hRsi == INVALID_HANDLE || hEma2400 == INVALID_HANDLE)
   {
      Print("Could not create the indicators");
      return(INIT_FAILED);
   }

   ob8.on = InpS8_On; ob8.tf = PERIOD_M15; ob8.structN = 20; ob8.minSL = 5; ob8.maxSL = 30;
   ob8.emergencyPips = 300; ob8.magic = InpS8_Magic; ob8.name = "8) M15 Extreme OB";
   ob8.gv = "ALL_" + (string)InpS8_Magic + "_" + _Symbol + "_SL"; ob8.armed = false;
   ob9.on = InpS9_On; ob9.tf = PERIOD_H1; ob9.structN = 5; ob9.minSL = 5; ob9.maxSL = 50;
   ob9.emergencyPips = 500; ob9.magic = InpS9_Magic; ob9.name = "9) H1 Extreme OB";
   ob9.gv = "ALL_" + (string)InpS9_Magic + "_" + _Symbol + "_SL"; ob9.armed = false;

   f1.day = f2hi.day = f5.day = f6.day = 0;
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetDeviationInPoints(30);
   PrintFormat("Started on %s: digits %d, stops level %d points, spread %d points, clock: %s",
               _Symbol, (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS),
               (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL),
               (int)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD),
               InpClock == CLOCK_BACKTEST ? "same as backtest" : "UTC+" + (string)InpServerUTC + " converted");
   if(!AlgoTradingAllowed())
      Print("Algo Trading is OFF - turn it on, otherwise no trade can open");
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   IndicatorRelease(hEma200);
   IndicatorRelease(hEma20);
   IndicatorRelease(hRsi);
   IndicatorRelease(hEma2400);
   Comment("");
}

//+------------------------------------------------------------------+
void OnTick()
{
   datetime t5[], t15[], t60[];
   if(CopyTime(_Symbol, PERIOD_M5, 0, 1, t5) < 1 || CopyTime(_Symbol, PERIOD_M15, 0, 1, t15) < 1 ||
      CopyTime(_Symbol, PERIOD_H1, 0, 1, t60) < 1)
      return;                                          // history not ready yet

   if(!started)                                        // first tick: learn today's signals, trade nothing
   {
      started = true;
      lastM5 = t5[0]; lastM15 = t15[0]; lastH1 = t60[0];
      int first15 = iBarShift(_Symbol, PERIOD_M15, ToServer(DayOf(ToRef(t15[0]))), false);
      for(int s = first15; s >= 1; s--) EvaluateM15(s, false);
      int first5 = iBarShift(_Symbol, PERIOD_M5, ToServer(DayOf(ToRef(t5[0]))), false);
      for(int s = first5; s >= 1; s--) EvaluateM5(s, false);
      ShowStatus();
      return;
   }

   bool changed = false;
   if(t60[0] != lastH1)
   {
      lastH1 = t60[0];
      if(InpS3_On) S3_OnNewH1();
      if(InpS7_On) { S7_TimeStop(); S7_OnNewH1(); }
      if(ob9.on)   ObOnNewBar(ob9);
      changed = true;
   }
   if(t15[0] != lastM15)
   {
      lastM15 = t15[0];
      EvaluateM15(1, true);
      if(ob8.on) ObOnNewBar(ob8);
      changed = true;
   }
   if(t5[0] != lastM5)
   {
      lastM5 = t5[0];
      EvaluateM5(1, true);
      changed = true;
   }

   if(ob8.on && ob8.armed && CountPositions(ob8.magic) == 0) ObMonitorEntry(ob8);
   if(ob9.on && ob9.armed && CountPositions(ob9.magic) == 0) ObMonitorEntry(ob9);

   static bool lastAllowed = true;
   bool allowed = AlgoTradingAllowed();
   if(allowed != lastAllowed) { lastAllowed = allowed; changed = true; }
   if(changed) ShowStatus();
}

//+------------------------------------------------------------------+
//| Helpers                                                          |
//+------------------------------------------------------------------+
bool AlgoTradingAllowed()
{
   return(TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) != 0 && MQLInfoInteger(MQL_TRADE_ALLOWED) != 0);
}

datetime DayOf(datetime t)
{
   return(StringToTime(TimeToString(t, TIME_DATE)));
}

datetime LastSundayAt0100(int year, int mon)           // last Sunday of a 31-day month, 01:00 UTC
{
   MqlDateTime d;
   ZeroMemory(d);
   d.year = year;
   d.mon  = mon;
   d.day  = 31;
   datetime t = StructToTime(d);
   TimeToStruct(t, d);
   return(t - d.day_of_week * 86400 + 3600);
}

int RefOffsetHours(datetime utc)                        // backtest clock minus UTC: 3 in European summer, else 2
{
   MqlDateTime d;
   TimeToStruct(utc, d);
   return((utc >= LastSundayAt0100(d.year, 3) && utc < LastSundayAt0100(d.year, 10)) ? 3 : 2);
}

datetime ToRef(datetime server)                         // broker time -> backtest clock
{
   if(InpClock == CLOCK_BACKTEST) return(server);
   datetime utc = server - InpServerUTC * 3600;
   return(utc + RefOffsetHours(utc) * 3600);
}

datetime ToServer(datetime ref)                         // backtest clock -> broker time
{
   if(InpClock == CLOCK_BACKTEST) return(ref);
   datetime utc = ref - RefOffsetHours(ref - 2 * 3600) * 3600;
   return(utc + InpServerUTC * 3600);
}

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

int CountOrders(ulong magic)
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

int CountAllMine()
{
   return(CountPositions(InpS1_Magic) + CountPositions(InpS2_Magic) + CountPositions(InpS3_Magic) +
          CountPositions(InpS4_Magic) + CountPositions(InpS5_Magic) + CountPositions(InpS6_Magic) +
          CountPositions(InpS7_Magic) + CountPositions(InpS8_Magic) + CountPositions(InpS9_Magic));
}

void ResetFlags(DayFlags &f, datetime day)
{
   if(f.day != day) { f.day = day; f.up = false; f.dn = false; }
}

// average true range of the `n` candles ending at `shift` (simple mean)
double AvgRange(ENUM_TIMEFRAMES tf, int shift, int n)
{
   MqlRates r[];
   ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, tf, shift, n + 1, r) < n + 1) return(0);
   double sum = 0;
   for(int i = 0; i < n; i++)
      sum += MathMax(r[i].high, r[i + 1].close) - MathMin(r[i].low, r[i + 1].close);
   return(sum / n);
}

// Wilder ATR(14) of the closed candle at `shift`
double WilderATR(ENUM_TIMEFRAMES tf, int shift)
{
   int need = 14 * 20 + 1;
   MqlRates r[];
   ArraySetAsSeries(r, false);
   if(CopyRates(_Symbol, tf, shift, need, r) < need) return(0);
   double atr = 0;
   for(int i = 1; i < need; i++)
   {
      double tr = MathMax(r[i].high, r[i - 1].close) - MathMin(r[i].low, r[i - 1].close);
      atr = (i == 1) ? tr : atr + (tr - atr) / 14.0;
   }
   return(atr);
}

// high / low of the candles between two BACKTEST-clock times (both included)
bool RangeHighLow(ENUM_TIMEFRAMES tf, datetime refFrom, datetime refTo, double &rh, double &rl)
{
   MqlRates a[];
   int n = CopyRates(_Symbol, tf, ToServer(refFrom), ToServer(refTo), a);
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

// previous trading day's high / low on the backtest clock (skips weekends)
bool PrevDayHighLow(datetime refDay, double &pdh, double &pdl)
{
   for(int k = 1; k <= 5; k++)
   {
      datetime from = refDay - k * 86400;
      if(RangeHighLow(PERIOD_M15, from, from + 86400 - 60, pdh, pdl)) return(true);
   }
   return(false);
}

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
      PrintFormat("Trade skipped: %.2f%% risk with a %s SL is below the minimum lot %.2f",
                  InpRiskPercent, DoubleToString(slDist, _Digits), vmin);
      return(0);
   }
   return(NormalizeDouble(MathMin(lots, vmax), 2));
}

bool TotalCapReached(string what)
{
   if(InpMaxOpenTotal <= 0 || CountAllMine() < InpMaxOpenTotal) return(false);
   PrintFormat("%s skipped: %d trades already open in total (InpMaxOpenTotal)", what, InpMaxOpenTotal);
   return(true);
}

// market order, SL / TP measured from the fill price
void OpenMarket(int dir, double slDist, ulong magic, int maxOpen, string comment)
{
   if(slDist <= 0) return;
   if(maxOpen > 0 && CountPositions(magic) >= maxOpen)
   {
      PrintFormat("%s skipped: this strategy already has %d open trade(s)", comment, maxOpen);
      return;
   }
   if(TotalCapReached(comment)) return;
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
//| Strategies 1 and 2 (M15) on the closed M15 candle at `shift`     |
//+------------------------------------------------------------------+
void EvaluateM15(int shift, bool doTrade)
{
   if(!InpS1_On && !InpS2_On) return;
   MqlRates r[];
   ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, PERIOD_M15, shift, 1, r) < 1) return;
   double atr = AvgRange(PERIOD_M15, shift, 96);
   if(atr <= 0) return;
   datetime ref = ToRef(r[0].time);
   datetime day = DayOf(ref);
   MqlDateTime dt;
   TimeToStruct(ref, dt);
   double c = r[0].close;

   //--- 1) Asian range 01:00-09:45, breakout 10:00-15:45, SL at the other side, range 2x-10x
   if(InpS1_On && dt.hour >= 10 && dt.hour <= 15)
   {
      ResetFlags(f1, day);
      double rh, rl;
      if(RangeHighLow(PERIOD_M15, day + 3600, day + 9 * 3600 + 45 * 60, rh, rl))
      {
         bool ok = (rh - rl >= 2.0 * atr) && (rh - rl <= 10.0 * atr);
         if(ok && !f1.up && c > rh) { f1.up = true; if(doTrade) OpenMarket(1, c - rl, InpS1_Magic, InpS1_MaxOpen, "S1_Asia15_Buy"); }
         if(ok && !f1.dn && c < rl) { f1.dn = true; if(doTrade) OpenMarket(-1, rh - c, InpS1_Magic, InpS1_MaxOpen, "S1_Asia15_Sell"); }
      }
   }

   //--- 2) previous-day high/low sweep 09:00-20:45, SL beyond the wick + 0.2x, SL 1x-5x
   if(InpS2_On && dt.hour >= 9 && dt.hour <= 20)
   {
      ResetFlags(f2hi, day);
      double pdh, pdl;
      if(PrevDayHighLow(day, pdh, pdl))
      {
         if(!f2hi.up && r[0].low < pdl && c > pdl)
         {
            f2hi.up = true;
            double dist = c - r[0].low + 0.2 * atr;
            if(doTrade && dist >= atr && dist <= 5 * atr) OpenMarket(1, dist, InpS2_Magic, InpS2_MaxOpen, "S2_Sweep_Buy");
         }
         if(!f2hi.dn && r[0].high > pdh && c < pdh)
         {
            f2hi.dn = true;
            double dist = r[0].high - c + 0.2 * atr;
            if(doTrade && dist >= atr && dist <= 5 * atr) OpenMarket(-1, dist, InpS2_Magic, InpS2_MaxOpen, "S2_Sweep_Sell");
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Strategies 4, 5 and 6 (M5) on the closed M5 candle at `shift`    |
//+------------------------------------------------------------------+
void EvaluateM5(int shift, bool doTrade)
{
   if(!InpS4_On && !InpS5_On && !InpS6_On) return;
   MqlRates r[];
   ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, PERIOD_M5, shift, 12, r) < 12) return;
   double atr = AvgRange(PERIOD_M5, shift, 288);
   if(atr <= 0) return;
   datetime ref = ToRef(r[0].time);
   datetime day = DayOf(ref);
   MqlDateTime dt;
   TimeToStruct(ref, dt);
   int    mins = dt.hour * 60 + dt.min;
   double c = r[0].close;

   //--- 5) NY range 16:30-16:55, breakout 17:00-19:55, SL at the other side, range 2x-15x
   if(InpS5_On && mins >= 17 * 60 && mins <= 19 * 60 + 55)
   {
      ResetFlags(f5, day);
      double rh, rl;
      if(RangeHighLow(PERIOD_M5, day + 16 * 3600 + 30 * 60, day + 16 * 3600 + 55 * 60, rh, rl))
      {
         bool ok = (rh - rl >= 2.0 * atr) && (rh - rl <= 15.0 * atr);
         if(ok && !f5.up && c > rh) { f5.up = true; if(doTrade) OpenMarket(1, c - rl, InpS5_Magic, InpS5_MaxOpen, "S5_NY_ORB_Buy"); }
         if(ok && !f5.dn && c < rl) { f5.dn = true; if(doTrade) OpenMarket(-1, rh - c, InpS5_Magic, InpS5_MaxOpen, "S5_NY_ORB_Sell"); }
      }
   }

   //--- 6) Asian range 01:00-09:55, breakout 10:00-15:55, SL at the other side, range 3.5x-25x
   if(InpS6_On && dt.hour >= 10 && dt.hour <= 15)
   {
      ResetFlags(f6, day);
      double rh, rl;
      if(RangeHighLow(PERIOD_M5, day + 3600, day + 9 * 3600 + 55 * 60, rh, rl))
      {
         bool ok = (rh - rl >= 3.5 * atr) && (rh - rl <= 25.0 * atr);
         if(ok && !f6.up && c > rh) { f6.up = true; if(doTrade) OpenMarket(1, c - rl, InpS6_Magic, InpS6_MaxOpen, "S6_Asia5_Buy"); }
         if(ok && !f6.dn && c < rl) { f6.dn = true; if(doTrade) OpenMarket(-1, rh - c, InpS6_Magic, InpS6_MaxOpen, "S6_Asia5_Sell"); }
      }
   }

   //--- 4) RSI(14) back from 25/75 with the EMA2400 trend, 09:00-20:55, SL 1x-10x
   if(doTrade && InpS4_On && dt.hour >= 9 && dt.hour <= 20)
   {
      double rs[], em[];
      ArraySetAsSeries(rs, true);
      if(CopyBuffer(hRsi, 0, shift, 2, rs) < 2 || CopyBuffer(hEma2400, 0, shift, 1, em) < 1) return;
      double lo = r[0].low, hi = r[0].high;
      for(int i = 1; i < 12; i++) { lo = MathMin(lo, r[i].low); hi = MathMax(hi, r[i].high); }
      if(c > em[0] && rs[1] < 25 && rs[0] >= 25)
      {
         double dist = c - lo + 0.3 * atr;
         if(dist >= atr && dist <= 10 * atr) OpenMarket(1, dist, InpS4_Magic, InpS4_MaxOpen, "S4_RSI_Buy");
      }
      else if(c < em[0] && rs[1] > 75 && rs[0] <= 75)
      {
         double dist = hi - c + 0.3 * atr;
         if(dist >= atr && dist <= 10 * atr) OpenMarket(-1, dist, InpS4_Magic, InpS4_MaxOpen, "S4_RSI_Sell");
      }
   }
}

//+------------------------------------------------------------------+
//| Strategy 3: H1 EMA200 engulfing, limit order at the engulfing    |
//| open, valid 5 H1 candles, SL 100 pips, TP 3 x SL                 |
//+------------------------------------------------------------------+
void S3_OnNewH1()
{
   MqlRates r[];
   double e[];
   ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, PERIOD_H1, 1, 2, r) < 2 || CopyBuffer(hEma200, 0, 1, 1, e) < 1) return;
   int trend = (r[0].close > e[0]) ? 1 : ((r[0].close < e[0]) ? -1 : 0);

   // expiry and trend flip for our pending orders
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0) continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol || (ulong)OrderGetInteger(ORDER_MAGIC) != InpS3_Magic) continue;
      int dir = (OrderGetInteger(ORDER_TYPE) == ORDER_TYPE_BUY_LIMIT) ? 1 : -1;
      int age = iBarShift(_Symbol, PERIOD_H1, (datetime)OrderGetInteger(ORDER_TIME_SETUP), false);
      if(trend == -dir || age >= 5)
         if(trade.OrderDelete(ticket))
            PrintFormat("S3 limit order %s deleted (%s)", (string)ticket, trend == -dir ? "trend turned" : "expired");
   }

   double o = r[0].open, c = r[0].close, po = r[1].open, pc = r[1].close;
   int dir = 0;
   if((po > pc) && (c > o) && (c >= po) && (o <= pc) && trend == 1)       dir = 1;
   else if((pc > po) && (o > c) && (c <= po) && (o >= pc) && trend == -1) dir = -1;
   if(dir == 0) return;

   if(InpS3_MaxOpen == 1)
   {
      if(CountPositions(InpS3_Magic) > 0) return;                         // one at a time
      for(int i = OrdersTotal() - 1; i >= 0; i--)                         // newer setup replaces the order
      {
         ulong ticket = OrderGetTicket(i);
         if(ticket == 0) continue;
         if(OrderGetString(ORDER_SYMBOL) == _Symbol && (ulong)OrderGetInteger(ORDER_MAGIC) == InpS3_Magic)
            trade.OrderDelete(ticket);
      }
   }
   else if(InpS3_MaxOpen > 1 && CountPositions(InpS3_Magic) + CountOrders(InpS3_Magic) >= InpS3_MaxOpen)
      return;
   if(TotalCapReached("S3")) return;

   MqlTick tk;
   if(!SymbolInfoTick(_Symbol, tk)) return;
   double dist   = 100 * InpPipSize;
   double p      = NormalizeDouble(o, _Digits);
   double sl     = NormalizeDouble(p - dir * dist, _Digits);
   double tp     = NormalizeDouble(p + dir * dist * InpRiskReward, _Digits);
   double minGap = (SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) + 2) * _Point;
   double lots   = LotSize(dist);
   if(lots <= 0) return;
   trade.SetExpertMagicNumber(InpS3_Magic);

   bool   there = (dir == 1) ? (tk.ask <= p + minGap) : (tk.bid >= p - minGap);
   bool   sent;
   string what;
   if(there)
   {
      bool slOK = (dir == 1) ? (sl < tk.bid - minGap) : (sl > tk.ask + minGap);
      if(!slOK) { Print("S3 setup skipped: price is already beyond the SL"); return; }
      what = (dir == 1) ? "S3_EMA200_Buy" : "S3_EMA200_Sell";
      sent = (dir == 1) ? trade.Buy(lots, _Symbol, tk.ask, sl, tp, what) : trade.Sell(lots, _Symbol, tk.bid, sl, tp, what);
   }
   else
   {
      what = (dir == 1) ? "S3_EMA200_BuyLimit" : "S3_EMA200_SellLimit";
      sent = (dir == 1) ? trade.BuyLimit(lots, p, _Symbol, sl, tp, ORDER_TIME_GTC, 0, what)
                        : trade.SellLimit(lots, p, _Symbol, sl, tp, ORDER_TIME_GTC, 0, what);
   }
   uint rc = trade.ResultRetcode();
   if(sent && (rc == TRADE_RETCODE_DONE || rc == TRADE_RETCODE_PLACED))
      PrintFormat("%s: %.2f lots at %s | SL %s | TP %s", what, lots, DoubleToString(p, _Digits),
                  DoubleToString(sl, _Digits), DoubleToString(tp, _Digits));
   else
      PrintFormat("%s ORDER FAILED: retcode %u (%s)", what, rc, trade.ResultRetcodeDescription());
}

//+------------------------------------------------------------------+
//| Strategy 7: H1 EMA20 pullback, buys and sells, SL 2x ATR,        |
//| time stop after 115 H1 candles                                   |
//+------------------------------------------------------------------+
void S7_OnNewH1()
{
   MqlRates r[];
   double f[], s[];
   if(CopyRates(_Symbol, PERIOD_H1, 1, 1, r) < 1) return;
   if(CopyBuffer(hEma20, 0, 1, 1, f) < 1 || CopyBuffer(hEma200, 0, 1, 1, s) < 1) return;
   double o = r[0].open, h = r[0].high, l = r[0].low, c = r[0].close;
   int dir = 0;
   if(c > s[0] && l <= f[0] && c > f[0] && c > o)      dir = 1;
   else if(c < s[0] && h >= f[0] && c < f[0] && c < o) dir = -1;
   if(dir == 0) return;
   double atr = WilderATR(PERIOD_H1, 1);
   if(atr <= 0) return;
   last7 = StringFormat("%s %s", dir == 1 ? "BUY" : "SELL", TimeToString(r[0].time + 3600));
   OpenMarket(dir, 2.0 * atr, InpS7_Magic, InpS7_MaxOpen, dir == 1 ? "S7_EMA20_Buy" : "S7_EMA20_Sell");
}

void S7_TimeStop()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol || (ulong)PositionGetInteger(POSITION_MAGIC) != InpS7_Magic) continue;
      int age = iBarShift(_Symbol, PERIOD_H1, (datetime)PositionGetInteger(POSITION_TIME), false);
      if(age >= 115 && trade.PositionClose(ticket))
         PrintFormat("S7 trade %s closed by the time stop", (string)ticket);
   }
}

//+------------------------------------------------------------------+
//| Strategies 8 and 9: Extreme OB v2.10 (engulfing + volume <= prev |
//| + trend, limit at the open valid 10 candles, wick SL with exit   |
//| on a candle CLOSE beyond it, emergency broker SL)                |
//+------------------------------------------------------------------+
void ObOnNewBar(ObState &s)
{
   // exit rule: candle closed beyond the wick
   if(GlobalVariableCheck(s.gv))
   {
      if(CountPositions(s.magic) == 0)
         GlobalVariableDel(s.gv);
      else
      {
         double wick = GlobalVariableGet(s.gv);
         MqlRates lc[];
         if(CopyRates(_Symbol, s.tf, 1, 1, lc) == 1)
         {
            for(int i = PositionsTotal() - 1; i >= 0; i--)
            {
               ulong ticket = PositionGetTicket(i);
               if(ticket == 0) continue;
               if(PositionGetString(POSITION_SYMBOL) != _Symbol || (ulong)PositionGetInteger(POSITION_MAGIC) != s.magic) continue;
               long type = PositionGetInteger(POSITION_TYPE);
               bool beyond = (type == POSITION_TYPE_BUY && lc[0].close < wick) || (type == POSITION_TYPE_SELL && lc[0].close > wick);
               if(beyond && trade.PositionClose(ticket))
               {
                  PrintFormat("%s: closed, candle closed beyond the wick %s", s.name, DoubleToString(wick, _Digits));
                  GlobalVariableDel(s.gv);
               }
            }
         }
      }
   }

   // setup check
   if(CountPositions(s.magic) > 0) { s.armed = false; return; }
   int need = s.structN + 2;
   MqlRates r[];
   ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, s.tf, 1, need, r) < need) return;
   double o = r[0].open, c = r[0].close, po = r[1].open, pc = r[1].close;
   bool bullEngulf = (po > pc) && (c > o) && (c >= po) && (o <= pc);
   bool bearEngulf = (pc > po) && (o > c) && (c <= po) && (o >= pc);
   bool volumeOK   = (r[0].tick_volume <= r[1].tick_volume);
   bool bullTrend  = (c > r[s.structN].close);
   bool bearTrend  = (c < r[s.structN].close);
   int    dir  = 0;
   double wick = 0;
   if(volumeOK && bullEngulf && bullTrend)      { dir = 1;  wick = r[0].low;  }
   else if(volumeOK && bearEngulf && bearTrend) { dir = -1; wick = r[0].high; }
   if(dir != 0)
   {
      double slPips = MathAbs(o - wick) / InpPipSize;
      if(slPips >= s.minSL && slPips <= s.maxSL)
      {
         s.armed = true; s.dir = dir; s.entry = o; s.wick = wick; s.left = 10;
         PrintFormat("%s: %s setup, limit %s, wick SL %s", s.name, dir == 1 ? "BUY" : "SELL",
                     DoubleToString(o, _Digits), DoubleToString(wick, _Digits));
         return;
      }
   }
   if(!s.armed) return;
   if((s.dir == 1 && bearTrend) || (s.dir == -1 && bullTrend)) { s.armed = false; return; }
   s.left--;
   if(s.left <= 0) s.armed = false;
}

void ObMonitorEntry(ObState &s)
{
   MqlTick tk;
   if(!SymbolInfoTick(_Symbol, tk)) return;
   bool touched = (s.dir == 1) ? (tk.ask <= s.entry) : (tk.bid >= s.entry);
   if(!touched) return;
   double minGap = (SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) + 2) * _Point;
   bool slOK = (s.dir == 1) ? (s.wick < tk.bid - minGap) : (s.wick > tk.ask + minGap);
   if(!slOK) { s.armed = false; return; }
   if(TotalCapReached(s.name)) { s.armed = false; return; }
   double risk = MathAbs(s.entry - s.wick);
   double tp   = NormalizeDouble(s.entry + s.dir * risk * InpRiskReward, _Digits);
   double sl   = NormalizeDouble(s.entry - s.dir * s.emergencyPips * InpPipSize, _Digits);
   double lots = LotSize(risk);
   if(lots <= 0) { s.armed = false; return; }
   trade.SetExpertMagicNumber(s.magic);
   bool sent = (s.dir == 1) ? trade.Buy(lots, _Symbol, tk.ask, sl, tp, s.name)
                            : trade.Sell(lots, _Symbol, tk.bid, sl, tp, s.name);
   uint rc = trade.ResultRetcode();
   if(sent && (rc == TRADE_RETCODE_DONE || rc == TRADE_RETCODE_PLACED))
   {
      GlobalVariableSet(s.gv, s.wick);
      PrintFormat("%s opened at %s, wick SL %s, TP %s", s.name, DoubleToString(trade.ResultPrice(), _Digits),
                  DoubleToString(s.wick, _Digits), DoubleToString(tp, _Digits));
      s.armed = false;
      return;
   }
   PrintFormat("%s ORDER FAILED: retcode %u (%s)", s.name, rc, trade.ResultRetcodeDescription());
   if(rc != TRADE_RETCODE_REQUOTE && rc != TRADE_RETCODE_PRICE_CHANGED && rc != TRADE_RETCODE_PRICE_OFF)
      s.armed = false;
}

//+------------------------------------------------------------------+
//| Status lines on the chart                                        |
//+------------------------------------------------------------------+
string OnOff(bool on) { return(on ? "ON " : "off"); }

void ShowStatus()
{
   datetime ref = ToRef(TimeCurrent());
   string s = "XAUUSD All Strategies EA (TP 1:" + DoubleToString(InpRiskReward, 1) + ")\n";
   s += StringFormat("Clock: %s | strategy time now %s\n",
                     InpClock == CLOCK_BACKTEST ? "same as backtest" : "server UTC+" + (string)InpServerUTC + " converted",
                     TimeToString(ref, TIME_MINUTES));
   s += StringFormat("1) M15 Asian breakout   %s | open %d\n", OnOff(InpS1_On), CountPositions(InpS1_Magic));
   s += StringFormat("2) M15 prev-day sweep   %s | open %d\n", OnOff(InpS2_On), CountPositions(InpS2_Magic));
   s += StringFormat("3) H1 EMA200 engulfing  %s | open %d, limit orders %d\n", OnOff(InpS3_On),
                     CountPositions(InpS3_Magic), CountOrders(InpS3_Magic));
   s += StringFormat("4) M5 RSI pullback      %s | open %d\n", OnOff(InpS4_On), CountPositions(InpS4_Magic));
   s += StringFormat("5) M5 NY opening range  %s | open %d\n", OnOff(InpS5_On), CountPositions(InpS5_Magic));
   s += StringFormat("6) M5 Asian breakout    %s | open %d\n", OnOff(InpS6_On), CountPositions(InpS6_Magic));
   s += StringFormat("7) H1 EMA20 pullback    %s | open %d | last signal %s\n", OnOff(InpS7_On),
                     CountPositions(InpS7_Magic), last7);
   s += StringFormat("8) M15 Extreme OB       %s | open %d%s\n", OnOff(ob8.on), CountPositions(ob8.magic),
                     ob8.armed ? " | waiting for retrace" : "");
   s += StringFormat("9) H1 Extreme OB        %s | open %d%s\n", OnOff(ob9.on), CountPositions(ob9.magic),
                     ob9.armed ? " | waiting for retrace" : "");
   s += StringFormat("All open: %d%s", CountAllMine(), InpMaxOpenTotal > 0 ? " / " + (string)InpMaxOpenTotal + " max" : "");
   if(!AlgoTradingAllowed())
      s += "\nAlgo Trading is OFF - turn it on, otherwise no trade can open";
   Comment(s);
}
//+------------------------------------------------------------------+
