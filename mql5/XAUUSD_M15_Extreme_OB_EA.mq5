//+------------------------------------------------------------------+
//|                                     XAUUSD_M15_Extreme_OB_EA.mq5 |
//|                                     Copyright 2026, Auto Trading |
//|                                             https://www.mql5.com |
//+------------------------------------------------------------------+
//| v2.10 - why v2.00 took no trades, and what changed               |
//|  1. An armed setup never expired. If price did not come back to  |
//|     the engulfing open, the EA waited forever and never looked   |
//|     for a new setup. Now the entry is valid for                  |
//|     InpSetupExpiryBars candles, a newer setup replaces it, and   |
//|     it is cancelled when the trend turns the other way.          |
//|  2. PositionsTotal() counted EVERY position on the account (other|
//|     symbols, manual trades, other EAs), which blocked the EA.    |
//|     Now only this EA's trades on this symbol are counted.        |
//|  3. Order results were never checked, and the setup was dropped  |
//|     even when the broker rejected the order (invalid stops,      |
//|     unsupported filling mode). Now the filling mode comes from   |
//|     the symbol, the SL is validated before sending, and every    |
//|     error is printed in the Experts tab.                         |
//|  4. The hard SL sat on the wick, so the M15-close "stop hunt     |
//|     protection" could never trigger, and after a restart         |
//|     currentSLPrice = 0 closed any SELL at the next M15 close.    |
//|     The exit is now selectable (InpCloseBasedSL) and the wick    |
//|     level is kept in a terminal global variable.                 |
//|  5. The pip size no longer depends on the broker's digits.       |
//|  6. CopyTime/CopyRates results are checked (no array errors).    |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026"
#property link      "https://www.mql5.com"
#property version   "2.10"

#include <Trade\Trade.mqh>
CTrade trade;

//--- Inputs
input double InpLotSize         = 0.1;    // Lot size
input double InpRiskReward      = 3.0;    // Risk:Reward (TP = 3 x SL distance)
input int    InpStructPeriod    = 20;     // Trend: close vs close N M15 candles ago
input double InpMaxSLPips       = 30.0;   // Max SL distance (pips)
input double InpMinSLPips       = 5.0;    // Min SL distance (pips) - smaller wicks sit inside the spread
input double InpPipSize         = 0.10;   // Price value of 1 pip (gold: 0.10)
input int    InpSetupExpiryBars = 10;     // Limit entry stays valid for N M15 candles
input bool   InpCloseBasedSL    = true;   // true: close only when an M15 candle CLOSES beyond the wick
input double InpEmergencySLPips = 300.0;  // With close-based SL: broker SL this far from entry (0 = none)
input ulong  InpMagicNumber     = 555015; // Magic number

//--- State
datetime lastBarTime   = 0;
bool     tradeArmed    = false;
int      armedDir      = 0;      // 1 = buy, -1 = sell
double   armedEntry    = 0;      // engulfing open (limit price)
double   armedWick     = 0;      // engulfing wick (SL level)
int      armedBarsLeft = 0;
string   gvKey         = "";     // terminal global variable: wick level of the open trade

//+------------------------------------------------------------------+
int OnInit()
{
   if(InpStructPeriod < 1 || InpPipSize <= 0 || InpSetupExpiryBars < 1)
      return(INIT_PARAMETERS_INCORRECT);

   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetTypeFillingBySymbol(_Symbol);   // FOK is not accepted by every broker
   trade.SetDeviationInPoints(30);
   gvKey = "EOB_" + (string)InpMagicNumber + "_" + _Symbol + "_SL";

   PrintFormat("Started on %s: digits %d, 1 pip = %s, stops level %d points, spread %d points",
               _Symbol, (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS), DoubleToString(InpPipSize, _Digits),
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

   if(t[0] != lastBarTime)      // a new M15 candle started, so the previous one just closed
   {
      lastBarTime = t[0];
      CheckM15ExitRule();       // exits first, so a closed trade frees the EA for this candle
      CheckM15Setup();
      ShowStatus();
   }

   // refresh the chart status right away when Algo Trading is switched on or off
   static bool lastAllowed = true;
   bool allowed = AlgoTradingAllowed();
   if(allowed != lastAllowed) { lastAllowed = allowed; ShowStatus(); }

   if(tradeArmed && CountMyPositions() == 0)
      MonitorLimitEntry();
}

//+------------------------------------------------------------------+
bool AlgoTradingAllowed()
{
   return(TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) != 0 && MQLInfoInteger(MQL_TRADE_ALLOWED) != 0);
}

//+------------------------------------------------------------------+
//| Positions opened by THIS EA on THIS symbol only                  |
//+------------------------------------------------------------------+
int CountMyPositions()
{
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol &&
         (ulong)PositionGetInteger(POSITION_MAGIC) == InpMagicNumber)
         n++;
   }
   return(n);
}

//+------------------------------------------------------------------+
//| Body engulfing + volume <= previous + trend, entry at the open   |
//+------------------------------------------------------------------+
void CheckM15Setup()
{
   if(CountMyPositions() > 0) { tradeArmed = false; return; }   // one trade at a time

   int need = InpStructPeriod + 2;
   MqlRates r[];
   ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, PERIOD_M15, 1, need, r) < need) return;   // r[0] = candle that just closed

   double o  = r[0].open,  c  = r[0].close;
   double po = r[1].open,  pc = r[1].close;

   bool bullEngulf = (po > pc) && (c > o) && (c >= po) && (o <= pc);
   bool bearEngulf = (pc > po) && (o > c) && (c <= po) && (o >= pc);
   bool volumeOK   = (r[0].tick_volume <= r[1].tick_volume);
   bool bullTrend  = (c > r[InpStructPeriod].close);
   bool bearTrend  = (c < r[InpStructPeriod].close);

   int    dir  = 0;
   double wick = 0;
   if(volumeOK && bullEngulf && bullTrend)      { dir =  1; wick = r[0].low;  }
   else if(volumeOK && bearEngulf && bearTrend) { dir = -1; wick = r[0].high; }

   if(dir != 0)
   {
      double slPips = MathAbs(o - wick) / InpPipSize;
      if(slPips >= InpMinSLPips && slPips <= InpMaxSLPips)
      {
         if(tradeArmed) Print("Older setup replaced by a new one");
         tradeArmed    = true;
         armedDir      = dir;
         armedEntry    = o;
         armedWick     = wick;
         armedBarsLeft = InpSetupExpiryBars;
         PrintFormat("%s setup: limit at engulfing open %s, SL (wick) %s = %.1f pips, valid %d candles",
                     dir == 1 ? "BUY" : "SELL", DoubleToString(o, _Digits), DoubleToString(wick, _Digits),
                     slPips, InpSetupExpiryBars);
         return;
      }
      PrintFormat("Engulfing skipped: SL %.1f pips is outside %.1f-%.1f pips", slPips, InpMinSLPips, InpMaxSLPips);
   }

   if(!tradeArmed) return;
   if((armedDir == 1 && bearTrend) || (armedDir == -1 && bullTrend))
   {
      tradeArmed = false;
      Print("Setup cancelled: the trend turned before the entry was touched");
      return;
   }
   armedBarsLeft--;
   if(armedBarsLeft <= 0)
   {
      tradeArmed = false;
      Print("Setup expired: price did not come back to the engulfing open");
   }
}

//+------------------------------------------------------------------+
//| Tick by tick: enter when price comes back to the engulfing open  |
//+------------------------------------------------------------------+
void MonitorLimitEntry()
{
   MqlTick tk;
   if(!SymbolInfoTick(_Symbol, tk)) return;

   bool touched = (armedDir == 1) ? (tk.ask <= armedEntry) : (tk.bid >= armedEntry);
   if(!touched) return;

   // the wick SL must still be on the correct side of the price (plus the broker's stops level)
   double minGap = (SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) + 2) * _Point;
   bool slOK = (armedDir == 1) ? (armedWick < tk.bid - minGap) : (armedWick > tk.ask + minGap);
   if(!slOK)
   {
      PrintFormat("Entry skipped: price %s is already at or beyond the wick SL %s",
                  DoubleToString(armedDir == 1 ? tk.bid : tk.ask, _Digits), DoubleToString(armedWick, _Digits));
      tradeArmed = false;
      return;
   }

   double risk = MathAbs(armedEntry - armedWick);
   double tp   = NormalizeDouble(armedEntry + armedDir * risk * InpRiskReward, _Digits);
   double sl   = 0.0;                                                   // 0 = no broker SL
   if(!InpCloseBasedSL)
      sl = NormalizeDouble(armedWick, _Digits);                         // normal stop at the wick
   else if(InpEmergencySLPips > 0)
      sl = NormalizeDouble(armedEntry - armedDir * InpEmergencySLPips * InpPipSize, _Digits);

   bool sent = (armedDir == 1)
               ? trade.Buy(InpLotSize, _Symbol, tk.ask, sl, tp, "M15_Extreme_Buy")
               : trade.Sell(InpLotSize, _Symbol, tk.bid, sl, tp, "M15_Extreme_Sell");
   uint rc = trade.ResultRetcode();

   if(sent && (rc == TRADE_RETCODE_DONE || rc == TRADE_RETCODE_PLACED))
   {
      GlobalVariableSet(gvKey, armedWick);
      PrintFormat("%s opened at %s | wick SL %s | broker SL %s | TP %s", armedDir == 1 ? "BUY" : "SELL",
                  DoubleToString(trade.ResultPrice(), _Digits), DoubleToString(armedWick, _Digits),
                  DoubleToString(sl, _Digits), DoubleToString(tp, _Digits));
      tradeArmed = false;
      return;
   }

   PrintFormat("ORDER FAILED: retcode %u (%s)%s", rc, trade.ResultRetcodeDescription(),
               AlgoTradingAllowed() ? "" : " - Algo Trading is OFF");
   // retry on the next tick only when the rejection was about the price itself
   if(rc != TRADE_RETCODE_REQUOTE && rc != TRADE_RETCODE_PRICE_CHANGED && rc != TRADE_RETCODE_PRICE_OFF)
      tradeArmed = false;
}

//+------------------------------------------------------------------+
//| Stop-hunt protection: close only when an M15 candle CLOSES       |
//| beyond the engulfing wick                                        |
//+------------------------------------------------------------------+
void CheckM15ExitRule()
{
   if(!GlobalVariableCheck(gvKey)) return;
   if(CountMyPositions() == 0) { GlobalVariableDel(gvKey); return; }   // already closed by TP / broker SL
   if(!InpCloseBasedSL) return;                                         // the broker SL at the wick does the job

   double wick = GlobalVariableGet(gvKey);
   MqlRates r[];
   if(CopyRates(_Symbol, PERIOD_M15, 1, 1, r) < 1) return;
   double lastClose = r[0].close;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC) != InpMagicNumber) continue;

      long type = PositionGetInteger(POSITION_TYPE);
      bool beyond = (type == POSITION_TYPE_BUY  && lastClose < wick) ||
                    (type == POSITION_TYPE_SELL && lastClose > wick);
      if(!beyond) continue;

      if(trade.PositionClose(ticket))
      {
         PrintFormat("Closed: M15 candle closed at %s, beyond the wick SL %s",
                     DoubleToString(lastClose, _Digits), DoubleToString(wick, _Digits));
         GlobalVariableDel(gvKey);
      }
      else
         PrintFormat("CLOSE FAILED: retcode %u (%s)", trade.ResultRetcode(), trade.ResultRetcodeDescription());
   }
}

//+------------------------------------------------------------------+
//| Status line on the chart, so you can see what the EA is waiting  |
//+------------------------------------------------------------------+
void ShowStatus()
{
   string s = "XAUUSD M15 Extreme OB EA v2.10\n";
   if(CountMyPositions() > 0)
      s += "Trade open";
   else if(tradeArmed)
      s += StringFormat("Waiting for the retrace: %s at %s, wick SL %s, %d candle(s) left",
                        armedDir == 1 ? "BUY" : "SELL", DoubleToString(armedEntry, _Digits),
                        DoubleToString(armedWick, _Digits), armedBarsLeft);
   else
      s += "No setup - waiting for an engulfing candle";
   if(!AlgoTradingAllowed())
      s += "\nAlgo Trading is OFF - turn it on, otherwise no trade can open";
   Comment(s);
}
//+------------------------------------------------------------------+
