//+------------------------------------------------------------------+
//|                                    XAUUSD_All_In_One_EA_FTMO.mq5 |
//|                                     Copyright 2026, Auto Trading |
//|                                             https://www.mql5.com |
//+------------------------------------------------------------------+
//| FTMO version of XAUUSD_All_In_One_EA_Exness.mq5: the same nine   |
//| strategies and rules (written from it by                         |
//| mql5/make_all_in_one_ftmo.py). Each strategy runs on its own     |
//| magic number, state, trades, on/off switch and max open trades.  |
//| TP = 3 x SL for all.                                             |
//|                                                                  |
//|  1  M15 Asian range breakout              on,  1 at a time       |
//|  2  M15 previous-day high/low sweep       on,  1 at a time       |
//|  3  H1 EMA200 engulfing, limit order      on,  1 at a time       |
//|  4  M5 RSI pullback                       on,  1 at a time       |
//|  5  M5 New York opening range             on,  1 at a time       |
//|  6  M5 Asian range breakout               on,  1 at a time       |
//|  7  H1 EMA20 pullback, buys and sells     OFF, max 5 when on     |
//|  8  M3 Heikin Ashi, buy only              on,  max 5             |
//|  9  H1 3 higher highs + perfect/strong    on,  no limit          |
//|     bearish engulfing, sell limit at 25% of the body             |
//|                                                                  |
//| FTMO CLOCK: the server runs on UTC+2 in winter and UTC+3 in      |
//| European summer, which is the strategy clock itself - nothing is |
//| converted (InpClock = "Same as the backtest data").              |
//|                                                                  |
//| FTMO RISK: 0.10% per trade by default. In the backtest the worst |
//| day was -14.5R and the biggest drawdown -45R to -66R, so 0.10%   |
//| means about -1.5% and -4.5% to -6.6% (FTMO limits: 5% a day, 10% |
//| in total). Do not go above 0.15%.                                |
//| FTMO PROTECTION: when equity drops InpDailyLossPct of the initial|
//| balance below the day's start (default 4%, FTMO 5%), every trade |
//| and order of this EA is closed and nothing new opens until the   |
//| next server day. At InpMaxLossPct below the initial balance      |
//| (default 9%, FTMO 10%) it stops for good; delete the global      |
//| variable AIO_<login>_STOP (F3) to let it trade again.            |
//| The EA's day starts at server midnight; check FTMO's current     |
//| rules for the exact limits of your account.                      |
//|                                                                  |
//| Attach to ONE XAUUSD chart, any timeframe. Keep enough history:  |
//| Tools > Options > Charts > Max bars in chart = 50000 or more     |
//| (strategy 8 needs about 13,500 M3 candles).                      |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026"
#property link      "https://www.mql5.com"
#property version   "1.10"
#property description "9 XAUUSD strategies in one EA, TP 1:3, FTMO clock (UTC+2/+3) and FTMO loss protection"

#include <Trade\Trade.mqh>
CTrade trade;

enum ENUM_CLOCK
{
   CLOCK_FIXED_UTC = 0,   // Fixed UTC offset, no DST (Exness: UTC+0)
   CLOCK_BACKTEST  = 1    // Same as the backtest data (FTMO: UTC+2 / UTC+3)
};

enum ENUM_S9_ENGULF
{
   S9_PERFECT_STRONG = 0, // Perfect or strong engulfing (best in the backtest)
   S9_PERFECT        = 1, // Perfect engulfing only
   S9_BODY           = 2  // Any body engulfing
};

input group "General"
input ENUM_CLOCK InpClock        = CLOCK_BACKTEST;  // Broker clock (FTMO: same as the backtest data)
input int        InpServerUTC    = 0;      // Only for a "Fixed UTC offset" broker: server time = UTC+N
input double     InpRiskPercent  = 0.10;   // Risk per trade, % of equity (0 = fixed lots); FTMO: at most 0.15
input double     InpMinLotMaxRisk = 0.0;   // Risk lot below the minimum: still trade the minimum lot if it risks at most this % (0 = skip)
input double     InpFixedLots    = 0.01;   // Fixed lots, used when risk % is 0
input double     InpRiskReward   = 3.0;    // TP = RR x SL distance
input double     InpPipSize      = 0.10;   // Price value of 1 pip (gold: 0.10)
input int        InpMaxOpenTotal = 0;      // Max open trades of ALL strategies together (0 = no limit)

input group "FTMO protection (0 = off)"
input double     InpDailyLossPct   = 4.0;  // Daily stop: equity this % of the initial balance below the day's start (FTMO: 5%)
input double     InpMaxLossPct     = 9.0;  // Final stop: equity this % below the initial balance (FTMO: 10%)
input double     InpInitialBalance = 0;    // Initial account balance (0 = the balance when the EA first ran here)

input group "1) M15 Asian range breakout"
input bool   InpS1_On      = true;    // On
input int    InpS1_MaxOpen = 1;       // Max open trades of this strategy (0 = no limit)
input ulong  InpS1_Magic   = 903001;  // Magic number

input group "2) M15 previous-day high/low sweep"
input bool   InpS2_On      = true;    // On
input int    InpS2_MaxOpen = 1;       // Max open trades of this strategy (0 = no limit)
input ulong  InpS2_Magic   = 903002;  // Magic number

input group "3) H1 EMA200 engulfing (limit at the engulfing open)"
input bool   InpS3_On      = true;    // On
input int    InpS3_MaxOpen = 1;       // 1 = one at a time (newer setup replaces the order), 0 = no limit
input ulong  InpS3_Magic   = 903003;  // Magic number

input group "4) M5 RSI pullback"
input bool   InpS4_On      = true;    // On
input int    InpS4_MaxOpen = 1;       // Max open trades of this strategy (0 = no limit)
input ulong  InpS4_Magic   = 903004;  // Magic number

input group "5) M5 New York opening-range breakout"
input bool   InpS5_On      = true;    // On
input int    InpS5_MaxOpen = 1;       // Max open trades of this strategy (0 = no limit)
input ulong  InpS5_Magic   = 903005;  // Magic number

input group "6) M5 Asian range breakout"
input bool   InpS6_On      = true;    // On
input int    InpS6_MaxOpen = 1;       // Max open trades of this strategy (0 = no limit)
input ulong  InpS6_Magic   = 903006;  // Magic number

input group "7) H1 EMA20 pullback, buys and sells (off: lost money on Exness 2020-21)"
input bool   InpS7_On      = false;   // On
input int    InpS7_MaxOpen = 5;       // Max open trades of this strategy (0 = no limit)
input ulong  InpS7_Magic   = 903007;  // Magic number

input group "8) M3 Heikin Ashi, buy only"
input bool   InpS8_On      = true;    // On
input int    InpS8_MaxOpen = 5;       // Max open trades of this strategy (0 = no limit)
input ulong  InpS8_Magic   = 903008;  // Magic number

input group "9) H1 higher highs + bearish engulfing, sell limit at 25% of the body"
input bool           InpS9_On      = true;               // On
input ENUM_S9_ENGULF InpS9_Engulf  = S9_PERFECT_STRONG;  // Engulfing type
input int            InpS9_MaxOpen = 0;                  // Max open trades + pending orders (0 = no limit)
input ulong          InpS9_Magic   = 903009;             // Magic number

//--- fixed strategy settings (the backtested values)
#define S8_EMA          4000   // M3 trend EMA (about the H1 EMA200)
#define S8_ATR_PERIOD   14     // Wilder ATR period
#define S8_ATR_AVG      9200   // ATR average over this many M3 candles (about 20 days)
#define S8_ATR_MIN      1.15   // "high volatility" = ATR >= 1.15 x that average
#define S8_START_HOUR   20     // session start on the strategy clock
#define S8_HOURS        5      // session length: 20:00-00:59
#define S8_SL_ATR       2.0    // SL = 2 x ATR
#define S8_MAX_HOLD     2300   // time stop in M3 candles (about 5 days)
#define S7_MAX_HOLD     115    // time stop in H1 candles
#define S9_LEVEL        0.25   // sell limit at close + 25% of the body

//+------------------------------------------------------------------+
//| State                                                            |
//+------------------------------------------------------------------+
struct DayFlags                       // "first signal per side per day" memory of one strategy
{
   datetime day;
   bool     up;
   bool     dn;
};

DayFlags  f1, f2hi, f5, f6;           // f2hi: up = low swept (buy), dn = high swept (sell)
datetime  lastM3 = 0, lastM5 = 0, lastM15 = 0, lastH1 = 0;
bool      started = false;
int       hEma200 = INVALID_HANDLE, hEma20 = INVALID_HANDLE, hRsi = INVALID_HANDLE;
int       hEma2400 = INVALID_HANDLE, hEma4000 = INVALID_HANDLE;
string    last7 = "none yet", last8 = "none yet", last9 = "none yet", check8 = "";
int       skippedMinLot = 0;          // trades skipped because the risk lot was below the minimum lot

datetime  guardDay = 0;               // FTMO protection: current server day,
double    dayStartBalance = 0;        // its starting balance (or equity, the higher)
bool      dayStopped = false;         // and whether the daily stop was hit today

//+------------------------------------------------------------------+
int OnInit()
{
   if(InpRiskReward <= 0 || InpPipSize <= 0 || (InpRiskPercent <= 0 && InpFixedLots <= 0))
      return(INIT_PARAMETERS_INCORRECT);

   hEma200  = iMA(_Symbol, PERIOD_H1, 200, 0, MODE_EMA, PRICE_CLOSE);
   hEma20   = iMA(_Symbol, PERIOD_H1, 20, 0, MODE_EMA, PRICE_CLOSE);
   hRsi     = iRSI(_Symbol, PERIOD_M5, 14, PRICE_CLOSE);
   hEma2400 = iMA(_Symbol, PERIOD_M5, 2400, 0, MODE_EMA, PRICE_CLOSE);
   hEma4000 = iMA(_Symbol, PERIOD_M3, S8_EMA, 0, MODE_EMA, PRICE_CLOSE);
   if(hEma200 == INVALID_HANDLE || hEma20 == INVALID_HANDLE || hRsi == INVALID_HANDLE ||
      hEma2400 == INVALID_HANDLE || hEma4000 == INVALID_HANDLE)
   {
      Print("Could not create the indicators");
      return(INIT_FAILED);
   }

   f1.day = f2hi.day = f5.day = f6.day = 0;
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetDeviationInPoints(30);
   PrintFormat("Started on %s: digits %d, stops level %d points, spread %d points, clock: %s, M3 bars %d",
               _Symbol, (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS),
               (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL),
               (int)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD),
               InpClock == CLOCK_BACKTEST ? "same as backtest" : "UTC+" + (string)InpServerUTC + " converted",
               Bars(_Symbol, PERIOD_M3));
   if(InpS8_On && Bars(_Symbol, PERIOD_M3) < S8_ATR_AVG + S8_EMA + 300)
      Print("Warning: not much M3 history yet - set Tools > Options > Charts > Max bars in chart to 50000 or more");
   PrintFormat("FTMO protection: initial balance %.2f, daily stop %.1f%%, final stop %.1f%%",
               InitialBalance(), InpDailyLossPct, InpMaxLossPct);
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
   IndicatorRelease(hEma4000);
   Comment("");
}

//+------------------------------------------------------------------+
void OnTick()
{
   datetime t3[], t5[], t15[], t60[];
   if(CopyTime(_Symbol, PERIOD_M3, 0, 1, t3) < 1 || CopyTime(_Symbol, PERIOD_M5, 0, 1, t5) < 1 ||
      CopyTime(_Symbol, PERIOD_M15, 0, 1, t15) < 1 || CopyTime(_Symbol, PERIOD_H1, 0, 1, t60) < 1)
      return;                                          // history not ready yet

   if(GuardBlocks())                                   // FTMO protection: a loss limit was reached
   {
      static datetime shown = 0;
      if(TimeCurrent() - shown >= 60) { shown = TimeCurrent(); ShowStatus(); }
      return;
   }

   if(!started)                                        // first tick: learn today's signals, trade nothing
   {
      started = true;
      lastM3 = t3[0]; lastM5 = t5[0]; lastM15 = t15[0]; lastH1 = t60[0];
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
      S3_ManageOrders();                               // order upkeep runs even when a strategy is off
      S7_TimeStop();
      S9_ManageOrders();
      if(InpS3_On) S3_NewSetup();
      if(InpS7_On) S7_OnNewH1();
      if(InpS9_On) S9_NewSetup();
      changed = true;
   }
   if(t15[0] != lastM15)
   {
      lastM15 = t15[0];
      EvaluateM15(1, true);
      changed = true;
   }
   if(t5[0] != lastM5)
   {
      lastM5 = t5[0];
      EvaluateM5(1, true);
      changed = true;
   }
   if(t3[0] != lastM3)
   {
      lastM3 = t3[0];
      S8_TimeStop();
      if(InpS8_On) S8_OnNewM3();
      changed = true;
   }

   static bool lastAllowed = true;
   bool allowed = AlgoTradingAllowed();
   if(allowed != lastAllowed) { lastAllowed = allowed; changed = true; }
   if(changed) ShowStatus();
}

//+------------------------------------------------------------------+
//| FTMO protection: daily and total loss stops. When one is hit,    |
//| every position and pending order of this EA is closed and no new |
//| trade opens: until the next server day (daily stop) or for good  |
//| (total stop; delete the AIO_<login>_STOP global variable to      |
//| reset). The day's start and the initial balance are kept in      |
//| terminal global variables, so a restart keeps them.              |
//+------------------------------------------------------------------+
string GvName(string what)
{
   return("AIO_" + (string)AccountInfoInteger(ACCOUNT_LOGIN) + "_" + what);
}

double InitialBalance()
{
   if(InpInitialBalance > 0) return(InpInitialBalance);
   string n = GvName("INIT");
   if(!GlobalVariableCheck(n)) GlobalVariableSet(n, AccountInfoDouble(ACCOUNT_BALANCE));
   return(GlobalVariableGet(n));
}

bool IsMine(ulong magic)
{
   return(magic == InpS1_Magic || magic == InpS2_Magic || magic == InpS3_Magic || magic == InpS4_Magic ||
          magic == InpS5_Magic || magic == InpS6_Magic || magic == InpS7_Magic || magic == InpS8_Magic ||
          magic == InpS9_Magic);
}

int CountMineWithOrders()                      // open positions + pending orders of this EA
{
   int n = CountAllMine();
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0) continue;
      if(OrderGetString(ORDER_SYMBOL) == _Symbol && IsMine((ulong)OrderGetInteger(ORDER_MAGIC))) n++;
   }
   return(n);
}

void CloseAllMine()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol && IsMine((ulong)PositionGetInteger(POSITION_MAGIC)))
         if(!trade.PositionClose(ticket))
            PrintFormat("FTMO protection: could not close %s yet (retcode %u)", (string)ticket, trade.ResultRetcode());
   }
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0) continue;
      if(OrderGetString(ORDER_SYMBOL) == _Symbol && IsMine((ulong)OrderGetInteger(ORDER_MAGIC)))
         trade.OrderDelete(ticket);
   }
}

bool FinalStopSet()
{
   return(GlobalVariableCheck(GvName("STOP")));
}

// true when a loss limit is reached: everything of this EA is closed and nothing new may open
bool GuardBlocks()
{
   datetime today = DayOf(TimeCurrent());
   if(today != guardDay)                                      // a new server day: note its start
   {
      guardDay   = today;
      dayStopped = false;
      string nd = GvName("DAY"), nb = GvName("DAYBAL");
      if(GlobalVariableCheck(nd) && GlobalVariableCheck(nb) && (datetime)GlobalVariableGet(nd) == today)
         dayStartBalance = GlobalVariableGet(nb);             // restarted during the day
      else
      {
         dayStartBalance = MathMax(AccountInfoDouble(ACCOUNT_BALANCE), AccountInfoDouble(ACCOUNT_EQUITY));
         GlobalVariableSet(nd, (double)today);
         GlobalVariableSet(nb, dayStartBalance);
      }
   }
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double init   = InitialBalance();
   if(!FinalStopSet() && InpMaxLossPct > 0 && equity <= init * (1.0 - InpMaxLossPct / 100.0))
   {
      GlobalVariableSet(GvName("STOP"), 1);
      PrintFormat("FTMO protection: equity %.2f is %.1f%% below the initial balance %.2f - trading stopped for good",
                  equity, InpMaxLossPct, init);
   }
   if(!dayStopped && InpDailyLossPct > 0 && equity <= dayStartBalance - init * InpDailyLossPct / 100.0)
   {
      dayStopped = true;
      PrintFormat("FTMO protection: equity %.2f is %.1f%% of the initial balance below today's start %.2f - "
                  "trading stopped until the next day", equity, InpDailyLossPct, dayStartBalance);
   }
   if(!FinalStopSet() && !dayStopped) return(false);
   if(CountMineWithOrders() > 0) CloseAllMine();
   return(true);
}

string GuardStatus()
{
   double init = InitialBalance();
   string d = InpDailyLossPct > 0 ? StringFormat("daily stop at equity %.2f", dayStartBalance - init * InpDailyLossPct / 100.0)
                                  : "daily stop off";
   string f = InpMaxLossPct > 0 ? StringFormat("final stop at %.2f", init * (1.0 - InpMaxLossPct / 100.0)) : "final stop off";
   string st = FinalStopSet() ? " | STOPPED for good (total loss limit)" : (dayStopped ? " | STOPPED until the next day" : " | OK");
   return(StringFormat("FTMO protection: initial %.2f, day start %.2f, %s, %s%s", init, dayStartBalance, d, f, st));
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
   double lossPerLot = 0;
   if(slDist <= 0 || step <= 0) return(0);
   if(InpRiskPercent > 0)
   {
      double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
      double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
      if(tickValue <= 0 || tickSize <= 0) return(0);
      double riskMoney = AccountInfoDouble(ACCOUNT_EQUITY) * InpRiskPercent / 100.0;
      lossPerLot = slDist / tickSize * tickValue;
      lots = riskMoney / lossPerLot;
   }
   lots = MathFloor(lots / step + 1e-9) * step;      // 1e-9: 0.03 / 0.01 must not round down to 2.999...
   if(lots < vmin - 1e-9)
   {
      double equity  = AccountInfoDouble(ACCOUNT_EQUITY);
      double minRisk = (lossPerLot > 0 && equity > 0) ? vmin * lossPerLot / equity * 100.0 : 0.0;
      if(InpRiskPercent > 0 && InpMinLotMaxRisk > 0 && minRisk > 0 && minRisk <= InpMinLotMaxRisk)
      {
         PrintFormat("Minimum lot %.2f used: with a %s SL it risks %.2f%% of equity (InpMinLotMaxRisk %.2f%%)",
                     vmin, DoubleToString(slDist, _Digits), minRisk, InpMinLotMaxRisk);
         return(NormalizeDouble(vmin, 2));
      }
      skippedMinLot++;
      PrintFormat("Trade skipped: %.2f%% risk with a %s SL is below the minimum lot %.2f (that lot would risk %.2f%%) - "
                  "raise the risk, set InpMinLotMaxRisk or use a fixed lot",
                  InpRiskPercent, DoubleToString(slDist, _Digits), vmin, minRisk);
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

// close this strategy's positions that are `maxBars` candles of `tf` old
void TimeStop(ulong magic, ENUM_TIMEFRAMES tf, int maxBars, string name)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol || (ulong)PositionGetInteger(POSITION_MAGIC) != magic) continue;
      int age = iBarShift(_Symbol, tf, (datetime)PositionGetInteger(POSITION_TIME), false);
      if(age >= maxBars && trade.PositionClose(ticket))
         PrintFormat("%s trade %s closed by the time stop (%d candles)", name, (string)ticket, age);
   }
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
int S3_Trend()
{
   MqlRates r[];
   double e[];
   if(CopyRates(_Symbol, PERIOD_H1, 1, 1, r) < 1 || CopyBuffer(hEma200, 0, 1, 1, e) < 1) return(0);
   return((r[0].close > e[0]) ? 1 : ((r[0].close < e[0]) ? -1 : 0));
}

void S3_ManageOrders()                                    // expiry and trend flip for the pending orders
{
   if(CountOrders(InpS3_Magic) == 0) return;
   int trend = S3_Trend();
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
}

void S3_NewSetup()
{
   MqlRates r[];
   ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, PERIOD_H1, 1, 2, r) < 2) return;
   int trend = S3_Trend();
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
   TimeStop(InpS7_Magic, PERIOD_H1, S7_MAX_HOLD, "S7");
}

//+------------------------------------------------------------------+
//| Strategy 8: M3 Heikin Ashi buy. Two strong bullish HA candles    |
//| (HA close > HA open, no lower wick), close above EMA(4000) on M3,|
//| ATR(14) at least 1.15x its 9200-candle average, candle hour      |
//| 20:00-00:59 on the strategy clock. SL 2 x ATR, time stop 2300.   |
//+------------------------------------------------------------------+
bool S8_InSession(datetime serverTime)
{
   MqlDateTime d;
   TimeToStruct(ToRef(serverTime), d);
   return(((d.hour - S8_START_HOUR + 24) % 24) < S8_HOURS);
}

// Wilder ATR of the closed candle at shift 1 and its average over the last S8_ATR_AVG candles
bool S8_AtrNowAndAverage(double &atrNow, double &atrAvg)
{
   int need = S8_ATR_AVG + 300;                    // 300 extra candles to settle the smoothing
   MqlRates r[];
   ArraySetAsSeries(r, false);                     // oldest first
   if(CopyRates(_Symbol, PERIOD_M3, 1, need, r) < need) return(false);
   double atr = 0, sum = 0;
   for(int i = 0; i < need; i++)
   {
      double tr = (i == 0) ? r[i].high - r[i].low
                           : MathMax(r[i].high, r[i - 1].close) - MathMin(r[i].low, r[i - 1].close);
      atr = (i == 0) ? tr : atr + (tr - atr) / S8_ATR_PERIOD;
      if(i >= need - S8_ATR_AVG) sum += atr;
   }
   atrNow = atr;
   atrAvg = sum / S8_ATR_AVG;
   return(true);
}

// "strong bullish" Heikin Ashi state of the closed candles at shift 1 (last) and shift 2
bool S8_HeikinAshiStrong(bool &strong1, bool &strong2)
{
   int need = 600;                                 // the HA open settles within a few dozen candles
   MqlRates r[];
   ArraySetAsSeries(r, false);
   if(CopyRates(_Symbol, PERIOD_M3, 1, need, r) < need) return(false);
   double prevOpen = 0, prevClose = 0;
   bool s1 = false, s2 = false;
   for(int i = 0; i < need; i++)
   {
      double hc = (r[i].open + r[i].high + r[i].low + r[i].close) / 4.0;
      double ho = (i == 0) ? r[0].open : (prevOpen + prevClose) / 2.0;
      bool strong = (hc > ho) && (r[i].low >= MathMin(ho, hc) - 1e-9);
      s2 = s1;
      s1 = strong;
      prevOpen = ho;
      prevClose = hc;
   }
   strong1 = s1;
   strong2 = s2;
   return(true);
}

void S8_OnNewM3()
{
   MqlRates r[];
   double e[];
   if(CopyRates(_Symbol, PERIOD_M3, 1, 1, r) < 1) return;
   if(CopyBuffer(hEma4000, 0, 1, 1, e) < 1) return;
   bool s1, s2;
   double atrNow, atrAvg;
   if(!S8_HeikinAshiStrong(s1, s2) || !S8_AtrNowAndAverage(atrNow, atrAvg))
   {
      check8 = "not enough M3 history";
      return;
   }
   bool trendUp = r[0].close > e[0];
   bool highVol = atrNow >= S8_ATR_MIN * atrAvg;
   bool session = S8_InSession(r[0].time);
   check8 = StringFormat("HA strong %s/%s, trend %s, volatility %.2fx avg (%s), session %s", s2 ? "yes" : "no",
                         s1 ? "yes" : "no", trendUp ? "UP" : "down", atrAvg > 0 ? atrNow / atrAvg : 0.0,
                         highVol ? "HIGH" : "low", session ? "OPEN" : "closed");
   if(!(s1 && s2 && trendUp && highVol && session)) return;
   last8 = "BUY " + TimeToString(TimeCurrent(), TIME_DATE | TIME_MINUTES);
   OpenMarket(1, S8_SL_ATR * atrNow, InpS8_Magic, InpS8_MaxOpen, "S8_M3_HA_Buy");
}

void S8_TimeStop()
{
   TimeStop(InpS8_Magic, PERIOD_M3, S8_MAX_HOLD, "S8");
}

//+------------------------------------------------------------------+
//| Strategy 9: 3 H1 candles in a row make higher highs, then a      |
//| bearish engulfing closes (perfect or strong by default).         |
//| Sell limit at close + 25% of the body, SL at the engulfing high, |
//| TP 1:3. Every setup is its own trade. The unfilled order is      |
//| deleted when an H1 candle closes below the engulfing low.        |
//+------------------------------------------------------------------+
void S9_ManageOrders()
{
   if(CountOrders(InpS9_Magic) == 0) return;
   MqlRates lc[];
   if(CopyRates(_Symbol, PERIOD_H1, 1, 1, lc) < 1) return;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0) continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol || (ulong)OrderGetInteger(ORDER_MAGIC) != InpS9_Magic) continue;
      // the order was placed in the candle right after the engulfing candle
      int s = iBarShift(_Symbol, PERIOD_H1, (datetime)OrderGetInteger(ORDER_TIME_SETUP), false);
      if(s < 1) continue;                                  // placed in the candle that is still open
      double engulfLow = iLow(_Symbol, PERIOD_H1, s + 1);
      if(engulfLow > 0 && lc[0].close < engulfLow && trade.OrderDelete(ticket))
         PrintFormat("S9 sell limit %s deleted: H1 closed at %s, below the engulfing low %s", (string)ticket,
                     DoubleToString(lc[0].close, _Digits), DoubleToString(engulfLow, _Digits));
   }
}

void S9_NewSetup()
{
   MqlRates r[];
   ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, PERIOD_H1, 1, 5, r) < 5) return;   // r[0] = engulfing candle, r[1..4] before it
   bool higherHighs = (r[3].high > r[4].high) && (r[2].high > r[3].high) && (r[1].high > r[2].high);
   if(!higherHighs) return;
   double o = r[0].open, h = r[0].high, l = r[0].low, c = r[0].close;
   double po = r[1].open, ph = r[1].high, pl = r[1].low, pc = r[1].close;
   bool body    = (pc > po) && (c < o) && (c <= po) && (o >= pc);
   bool perfect = body && (h > ph) && (l < pl);
   bool strong  = body && (c < pl);
   bool ok = (InpS9_Engulf == S9_PERFECT_STRONG) ? (perfect || strong)
           : (InpS9_Engulf == S9_PERFECT)        ? perfect
           : body;
   if(!ok) return;

   double entry = NormalizeDouble(c + S9_LEVEL * (o - c), _Digits);
   double sl    = NormalizeDouble(h, _Digits);
   double dist  = sl - entry;
   if(dist <= 0) return;
   double tp    = NormalizeDouble(entry - InpRiskReward * dist, _Digits);
   last9 = StringFormat("%s engulfing %s, sell limit %s, SL %s, TP %s", perfect ? "perfect" : (strong ? "strong" : "body"),
                        TimeToString(r[0].time, TIME_DATE | TIME_MINUTES), DoubleToString(entry, _Digits),
                        DoubleToString(sl, _Digits), DoubleToString(tp, _Digits));
   if(InpS9_MaxOpen > 0 && CountPositions(InpS9_Magic) + CountOrders(InpS9_Magic) >= InpS9_MaxOpen)
   {
      PrintFormat("S9 setup skipped: %d trades / orders already open", InpS9_MaxOpen);
      return;
   }
   if(TotalCapReached("S9")) return;

   MqlTick tk;
   if(!SymbolInfoTick(_Symbol, tk)) return;
   double minGap = (SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) + 2) * _Point;
   trade.SetExpertMagicNumber(InpS9_Magic);
   bool   sent;
   string what;
   double lots;
   if(tk.bid >= entry - minGap)                             // price is already at the entry: sell now
   {
      if(sl <= tk.ask + minGap) { Print("S9 setup skipped: price is already at the SL"); return; }
      lots = LotSize(sl - tk.bid);
      if(lots <= 0) return;
      what = "S9_HH_Engulf_Sell";
      sent = trade.Sell(lots, _Symbol, tk.bid, sl, tp, what);
   }
   else
   {
      if(dist < minGap) { Print("S9 setup skipped: SL too close to the entry"); return; }
      lots = LotSize(dist);
      if(lots <= 0) return;
      what = "S9_HH_Engulf_SellLimit";
      sent = trade.SellLimit(lots, entry, _Symbol, sl, tp, ORDER_TIME_GTC, 0, what);
   }
   uint rc = trade.ResultRetcode();
   if(sent && (rc == TRADE_RETCODE_DONE || rc == TRADE_RETCODE_PLACED))
      PrintFormat("%s: %.2f lots at %s | SL %s | TP %s | deleted if an H1 candle closes below %s", what, lots,
                  DoubleToString(entry, _Digits), DoubleToString(sl, _Digits), DoubleToString(tp, _Digits),
                  DoubleToString(l, _Digits));
   else
      PrintFormat("%s ORDER FAILED: retcode %u (%s)%s", what, rc, trade.ResultRetcodeDescription(),
                  AlgoTradingAllowed() ? "" : " - Algo Trading is OFF");
}

//+------------------------------------------------------------------+
//| Status lines on the chart                                        |
//+------------------------------------------------------------------+
string OnOff(bool on) { return(on ? "ON " : "off"); }

void ShowStatus()
{
   datetime ref = ToRef(TimeCurrent());
   string s = "XAUUSD All-in-One EA, FTMO (TP 1:" + DoubleToString(InpRiskReward, 1) + ", risk " +
              DoubleToString(InpRiskPercent, 2) + "% per trade)\n";
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
   s += StringFormat("8) M3 Heikin Ashi buy   %s | open %d | last signal %s\n", OnOff(InpS8_On),
                     CountPositions(InpS8_Magic), last8);
   if(InpS8_On && check8 != "") s += "   last M3 candle: " + check8 + "\n";
   s += StringFormat("9) H1 HH engulfing sell %s | open %d, sell limits %d\n", OnOff(InpS9_On),
                     CountPositions(InpS9_Magic), CountOrders(InpS9_Magic));
   s += "   last setup: " + last9 + "\n";
   s += StringFormat("All open: %d%s", CountAllMine(), InpMaxOpenTotal > 0 ? " / " + (string)InpMaxOpenTotal + " max" : "");
   s += "\n" + GuardStatus();
   if(skippedMinLot > 0)
      s += StringFormat("\nSkipped %d trade(s): lot below the minimum at %.2f%% risk (raise the risk or set InpMinLotMaxRisk)",
                        skippedMinLot, InpRiskPercent);
   if(!AlgoTradingAllowed())
      s += "\nAlgo Trading is OFF - turn it on, otherwise no trade can open";
   Comment(s);
}
//+------------------------------------------------------------------+
