"""Writes the two M3 Heikin Ashi EAs (Exness and FTMO) from one template, so their trading logic
is identical and only the clock handling differs.

    python mql5/make_m3_ha_eas.py
"""
from pathlib import Path

TEMPLATE = r'''//+------------------------------------------------------------------+
//|                                   XAUUSD_M3_HeikinAshi_EA_@NAME@.mq5 |
//|                                     Copyright 2026, Auto Trading |
//|                                             https://www.mql5.com |
//+------------------------------------------------------------------+
//| M3 Heikin Ashi strategy from the 5-million-strategy search,      |
//| @NAME@ version. TP = 3 x SL (1:3). Same rules as m3_ha_test.py:   |
//|                                                                  |
//|  BUY when the M3 candle that just closed and the one before are  |
//|  both strong bullish Heikin Ashi candles (HA close > HA open and  |
//|  no lower wick), the close is above EMA(4000) on M3 (about the    |
//|  H1 EMA200), ATR(14) is at or above its average of the last 9200  |
//|  candles (about 20 days), and the candle's hour is 20:00-00:59   |
//|  on the strategy clock (UTC+2 winter / UTC+3 summer).            |
//|  Market buy right after that candle closes. SL = 2 x ATR(14),    |
//|  TP = 3 x SL. Time stop after 2300 M3 candles (~5 days).          |
//|  Up to InpMaxOpenTrades trades at once (default 3).              |
//|                                                                  |
@CLOCK_NOTE@
//| Attach to ONE XAUUSD chart (any timeframe). Keep enough M3       |
//| history: Tools > Options > Charts > Max bars in chart >= 50000.  |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026"
#property link      "https://www.mql5.com"
#property version   "1.00"
#property description "M3 Heikin Ashi buy strategy, 1:3, @NAME@ clock"

#include <Trade\Trade.mqh>
CTrade trade;

input group "Risk"
input double InpRiskPercent   = 0.25;   // Risk per trade, % of equity (0 = fixed lots)
input double InpFixedLots     = 0.01;   // Fixed lots, used when risk % is 0
input double InpRiskReward    = 3.0;    // TP = RR x SL distance
input int    InpMaxOpenTrades = 3;      // Max trades open at once (0 = no limit)

input group "Strategy"
input double InpSLATR         = 2.0;    // SL = this x ATR(14)
input int    InpTrendEma      = 4000;   // Trend EMA on M3 (4000 = about the H1 EMA200)
input int    InpAtrPeriod     = 14;     // ATR period (Wilder)
input int    InpAtrAvgBars    = 9200;   // "High volatility" = ATR >= its average over this many M3 candles
input int    InpStartHour     = 20;     // Session start hour on the strategy clock (UTC+2 / UTC+3)
input int    InpSessionHours  = 5;      // Session length in hours (20 + 5 -> 20:00-00:59)
input int    InpMaxHoldBars   = 2300;   // Time stop in M3 candles (0 = off)
input ulong  InpMagic         = @MAGIC@; // Magic number
@CLOCK_INPUT@
//--- State
datetime lastBar    = 0;
int      hEma       = INVALID_HANDLE;
string   lastSignal = "none yet";
string   lastCheck  = "";

//+------------------------------------------------------------------+
@CLOCK_FUNCS@
//+------------------------------------------------------------------+
int OnInit()
{
   if(InpRiskReward <= 0 || InpSLATR <= 0 || InpAtrPeriod < 1 || InpAtrAvgBars < InpAtrPeriod ||
      InpSessionHours < 1 || InpSessionHours > 24 || (InpRiskPercent <= 0 && InpFixedLots <= 0))
      return(INIT_PARAMETERS_INCORRECT);
   hEma = iMA(_Symbol, PERIOD_M3, InpTrendEma, 0, MODE_EMA, PRICE_CLOSE);
   if(hEma == INVALID_HANDLE)
   {
      Print("Could not create the EMA indicator");
      return(INIT_FAILED);
   }
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetDeviationInPoints(30);
   PrintFormat("Started on %s (@NAME@ clock): digits %d, stops level %d points, spread %d points, M3 bars available %d",
               _Symbol, (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS),
               (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL),
               (int)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD), Bars(_Symbol, PERIOD_M3));
   if(Bars(_Symbol, PERIOD_M3) < InpAtrAvgBars + InpTrendEma)
      Print("Warning: not much M3 history yet - raise 'Max bars in chart' (Tools > Options > Charts) to 50000 or more");
   if(!AlgoTradingAllowed())
      Print("Algo Trading is OFF - turn it on, otherwise no trade can open");
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(hEma != INVALID_HANDLE) IndicatorRelease(hEma);
   Comment("");
}

//+------------------------------------------------------------------+
void OnTick()
{
   datetime t[];
   if(CopyTime(_Symbol, PERIOD_M3, 0, 1, t) < 1) return;   // M3 history not ready yet

   if(lastBar == 0)              // first tick after attaching: do not trade a candle that closed earlier
   {
      lastBar = t[0];
      ShowStatus();
      return;
   }
   if(t[0] != lastBar)           // a new M3 candle started, so the previous one just closed
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
//| Is the candle that opened at server time `t` inside the session? |
//+------------------------------------------------------------------+
bool InSession(datetime t)
{
   MqlDateTime d;
   TimeToStruct(ToRef(t), d);
   return(((d.hour - InpStartHour + 24) % 24) < InpSessionHours);
}

//+------------------------------------------------------------------+
//| Wilder ATR of the closed candle at shift 1 and its average over  |
//| the last InpAtrAvgBars candles                                   |
//+------------------------------------------------------------------+
bool AtrNowAndAverage(double &atrNow, double &atrAvg)
{
   int need = InpAtrAvgBars + 300;               // 300 extra candles to settle the smoothing
   MqlRates r[];
   ArraySetAsSeries(r, false);                    // oldest first
   if(CopyRates(_Symbol, PERIOD_M3, 1, need, r) < need) return(false);
   double atr = 0, sum = 0;
   for(int i = 0; i < need; i++)
   {
      double tr = (i == 0) ? r[i].high - r[i].low
                           : MathMax(r[i].high, r[i - 1].close) - MathMin(r[i].low, r[i - 1].close);
      atr = (i == 0) ? tr : atr + (tr - atr) / InpAtrPeriod;
      if(i >= need - InpAtrAvgBars) sum += atr;
   }
   atrNow = atr;
   atrAvg = sum / InpAtrAvgBars;
   return(true);
}

//+------------------------------------------------------------------+
//| Heikin Ashi "strong bullish" state of the closed candles at      |
//| shift 1 (last) and shift 2 (before)                              |
//+------------------------------------------------------------------+
bool HeikinAshiStrong(bool &strong1, bool &strong2)
{
   int need = 600;                                // HA open settles within a few dozen candles
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

//+------------------------------------------------------------------+
//| Signal on the M3 candle that just closed                         |
//+------------------------------------------------------------------+
void CheckSignal()
{
   MqlRates r[];
   double e[];
   if(CopyRates(_Symbol, PERIOD_M3, 1, 1, r) < 1) return;
   if(CopyBuffer(hEma, 0, 1, 1, e) < 1) return;
   bool s1, s2;
   double atrNow, atrAvg;
   if(!HeikinAshiStrong(s1, s2) || !AtrNowAndAverage(atrNow, atrAvg))
   {
      lastCheck = "not enough M3 history";
      return;
   }
   bool trendUp  = r[0].close > e[0];
   bool highVol  = atrNow >= atrAvg;
   bool session  = InSession(r[0].time);
   lastCheck = StringFormat("HA strong %s/%s | trend %s | volatility %s | session %s",
                            s2 ? "yes" : "no", s1 ? "yes" : "no", trendUp ? "UP" : "down",
                            highVol ? "HIGH" : "low", session ? "OPEN" : "closed");
   if(!(s1 && s2 && trendUp && highVol && session)) return;
   lastSignal = "BUY at " + TimeToString(TimeCurrent(), TIME_DATE | TIME_MINUTES);
   OpenBuy(InpSLATR * atrNow);
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
//| Market buy, SL / TP measured from the fill price                 |
//+------------------------------------------------------------------+
void OpenBuy(double slDist)
{
   if(InpMaxOpenTrades > 0 && CountMine() >= InpMaxOpenTrades)
   {
      PrintFormat("Signal skipped: %d trades already open (InpMaxOpenTrades)", InpMaxOpenTrades);
      return;
   }
   MqlTick tk;
   if(!SymbolInfoTick(_Symbol, tk)) return;
   double sl     = NormalizeDouble(tk.ask - slDist, _Digits);
   double tp     = NormalizeDouble(tk.ask + slDist * InpRiskReward, _Digits);
   double minGap = (SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) + 2) * _Point;
   if(sl >= tk.bid - minGap)
   {
      PrintFormat("Signal skipped: SL %s is too close to the price", DoubleToString(sl, _Digits));
      return;
   }
   double lots = LotSize(slDist);
   if(lots <= 0) return;
   bool sent = trade.Buy(lots, _Symbol, tk.ask, sl, tp, "M3_HA_Buy");
   uint rc = trade.ResultRetcode();
   if(sent && (rc == TRADE_RETCODE_DONE || rc == TRADE_RETCODE_PLACED))
      PrintFormat("BUY opened: %.2f lots at %s | SL %s | TP %s (1:%.1f)", lots,
                  DoubleToString(trade.ResultPrice(), _Digits), DoubleToString(sl, _Digits),
                  DoubleToString(tp, _Digits), InpRiskReward);
   else
      PrintFormat("BUY ORDER FAILED: retcode %u (%s)%s", rc, trade.ResultRetcodeDescription(),
                  AlgoTradingAllowed() ? "" : " - Algo Trading is OFF");
}

//+------------------------------------------------------------------+
//| Close trades that have been open for InpMaxHoldBars M3 candles   |
//+------------------------------------------------------------------+
void TimeStop()
{
   if(InpMaxHoldBars <= 0) return;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol || (ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      int age = iBarShift(_Symbol, PERIOD_M3, (datetime)PositionGetInteger(POSITION_TIME), false);
      if(age >= InpMaxHoldBars && trade.PositionClose(ticket))
         PrintFormat("Trade %s closed by the time stop (%d M3 candles)", (string)ticket, age);
   }
}

//+------------------------------------------------------------------+
//| Status lines on the chart                                        |
//+------------------------------------------------------------------+
void ShowStatus()
{
   datetime ref = ToRef(TimeCurrent());
   string s = "XAUUSD M3 Heikin Ashi EA (@NAME@) - buy only, TP 1:" + DoubleToString(InpRiskReward, 1) + "\n";
   s += StringFormat("Strategy clock %s (server %s) | session %02d:00 for %d h: %s\n",
                     TimeToString(ref, TIME_MINUTES), TimeToString(TimeCurrent(), TIME_MINUTES),
                     InpStartHour, InpSessionHours, InSession(TimeCurrent()) ? "OPEN" : "closed");
   if(lastCheck != "") s += "Last candle: " + lastCheck + "\n";
   s += StringFormat("Open trades: %d%s | last signal: %s",
                     CountMine(), InpMaxOpenTrades > 0 ? " / " + (string)InpMaxOpenTrades + " max" : "", lastSignal);
   if(!AlgoTradingAllowed())
      s += "\nAlgo Trading is OFF - turn it on, otherwise no trade can open";
   Comment(s);
}
//+------------------------------------------------------------------+
'''

EXNESS_NOTE = r'''//| EXNESS: the server runs on UTC+0 all year. The EA converts its   |
//| time to the strategy clock itself (UTC+2 in winter, UTC+3 during  |
//| European summer time), so the session is 18:00-22:59 server time |
//| in winter and 17:00-21:59 in summer - nothing to change by hand. |'''

FTMO_NOTE = r'''//| FTMO: the server clock (UTC+2 winter / UTC+3 summer) IS the      |
//| strategy clock, so the session is 20:00-00:59 server time.       |'''

EXNESS_INPUT = r'''
input group "Broker clock"
input int    InpServerUTC     = 0;      // Server time zone, UTC+N without DST (Exness = 0)
'''

EXNESS_FUNCS = r'''//| Exness clock -> strategy clock (UTC+2 winter / UTC+3 EU summer)  |
//+------------------------------------------------------------------+
datetime LastSundayAt0100(int year, int mon)       // last Sunday of a 31-day month, 01:00 UTC
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

int RefOffsetHours(datetime utc)                    // strategy clock minus UTC: 3 in European summer, else 2
{
   MqlDateTime d;
   TimeToStruct(utc, d);
   return((utc >= LastSundayAt0100(d.year, 3) && utc < LastSundayAt0100(d.year, 10)) ? 3 : 2);
}

datetime ToRef(datetime server)                     // server time -> strategy clock
{
   datetime utc = server - InpServerUTC * 3600;
   return(utc + RefOffsetHours(utc) * 3600);
}'''

FTMO_FUNCS = r'''//| FTMO clock = strategy clock, nothing to convert                  |
//+------------------------------------------------------------------+
datetime ToRef(datetime server)
{
   return(server);
}'''


def build(name, note, inp, funcs, magic):
    s = TEMPLATE.replace("@NAME@", name).replace("@CLOCK_NOTE@", note).replace("@CLOCK_INPUT@", inp)
    return s.replace("@CLOCK_FUNCS@", funcs).replace("@MAGIC@", magic)


here = Path(__file__).resolve().parent
(here / "exness").mkdir(exist_ok=True)
(here / "exness" / "XAUUSD_M3_HeikinAshi_EA_Exness.mq5").write_text(build("Exness", EXNESS_NOTE, EXNESS_INPUT, EXNESS_FUNCS, "303001"))
(here / "XAUUSD_M3_HeikinAshi_EA_FTMO.mq5").write_text(build("FTMO", FTMO_NOTE, "", FTMO_FUNCS, "303002"))
print("written")
