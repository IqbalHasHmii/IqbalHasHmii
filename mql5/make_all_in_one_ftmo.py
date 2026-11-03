"""Writes the FTMO version of the all-in-one EA from the Exness version, so both trade the same
rules. Only these differ:
  - clock: FTMO's server time already is the strategy clock (UTC+2 winter / UTC+3 summer);
  - risk 0.10% per trade (the backtest drawdown at 0.25% was 11-17%, over FTMO's 10% limit);
  - magic numbers 903001-903009 (Exness version: 902001-902009);
  - FTMO protection: a daily and a total loss stop that close every trade of the EA.

    python mql5/make_all_in_one_ftmo.py
"""
import re
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "exness" / "XAUUSD_All_In_One_EA_Exness.mq5"
DST = HERE / "XAUUSD_All_In_One_EA_FTMO.mq5"

HEADER = r'''//+------------------------------------------------------------------+
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
'''

GUARD_INPUTS = '''input group "FTMO protection (0 = off)"
input double     InpDailyLossPct   = 4.0;  // Daily stop: equity this % of the initial balance below the day's start (FTMO: 5%)
input double     InpMaxLossPct     = 9.0;  // Final stop: equity this % below the initial balance (FTMO: 10%)
input double     InpInitialBalance = 0;    // Initial account balance (0 = the balance when the EA first ran here)

'''

GUARD_STATE = '''
datetime  guardDay = 0;               // FTMO protection: current server day,
double    dayStartBalance = 0;        // its starting balance (or equity, the higher)
bool      dayStopped = false;         // and whether the daily stop was hit today
'''

GUARD_FUNCS = '''//+------------------------------------------------------------------+
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

'''


def build() -> str:
    s = SRC.read_text()
    reps = [
        # header and description
        (s[:s.index('#property copyright')], HEADER),
        ('#property description "9 XAUUSD strategies in one EA, TP 1:3, Exness clock (UTC+0) converted automatically"',
         '#property description "9 XAUUSD strategies in one EA, TP 1:3, FTMO clock (UTC+2/+3) and FTMO loss protection"'),
        # clock, risk
        ('input ENUM_CLOCK InpClock        = CLOCK_FIXED_UTC; // Broker clock',
         'input ENUM_CLOCK InpClock        = CLOCK_BACKTEST;  // Broker clock (FTMO: same as the backtest data)'),
        ('input int        InpServerUTC    = 0;      // Fixed-offset broker: server time = UTC+N (Exness = 0)',
         'input int        InpServerUTC    = 0;      // Only for a "Fixed UTC offset" broker: server time = UTC+N'),
        ('input double     InpRiskPercent  = 0.25;   // Risk per trade, % of equity (0 = fixed lots)',
         'input double     InpRiskPercent  = 0.10;   // Risk per trade, % of equity (0 = fixed lots); FTMO: at most 0.15'),
        # FTMO protection inputs, state and functions
        ('input group "1) M15 Asian range breakout"', GUARD_INPUTS + 'input group "1) M15 Asian range breakout"'),
        ('int       skippedMinLot = 0;          // trades skipped because the risk lot was below the minimum lot\n',
         'int       skippedMinLot = 0;          // trades skipped because the risk lot was below the minimum lot\n' + GUARD_STATE),
        ('//+------------------------------------------------------------------+\n//| Helpers ',
         GUARD_FUNCS + '//+------------------------------------------------------------------+\n//| Helpers '),
        ('      return;                                          // history not ready yet\n',
         '      return;                                          // history not ready yet\n\n'
         '   if(GuardBlocks())                                   // FTMO protection: a loss limit was reached\n'
         '   {\n'
         '      static datetime shown = 0;\n'
         '      if(TimeCurrent() - shown >= 60) { shown = TimeCurrent(); ShowStatus(); }\n'
         '      return;\n'
         '   }\n'),
        ('   if(!AlgoTradingAllowed())\n      Print("Algo Trading is OFF - turn it on, otherwise no trade can open");\n'
         '   return(INIT_SUCCEEDED);',
         '   PrintFormat("FTMO protection: initial balance %.2f, daily stop %.1f%%, final stop %.1f%%",\n'
         '               InitialBalance(), InpDailyLossPct, InpMaxLossPct);\n'
         '   if(!AlgoTradingAllowed())\n      Print("Algo Trading is OFF - turn it on, otherwise no trade can open");\n'
         '   return(INIT_SUCCEEDED);'),
        # status
        ('   string s = "XAUUSD All-in-One EA (TP 1:"', '   string s = "XAUUSD All-in-One EA, FTMO (TP 1:"'),
        ('   if(skippedMinLot > 0)\n', '   s += "\\n" + GuardStatus();\n   if(skippedMinLot > 0)\n'),
    ]
    for old, new in reps:
        if s.count(old) != 1:
            raise SystemExit(f"template text not found exactly once: {old[:70]!r}")
        s = s.replace(old, new)
    s, n = re.subn(r"(InpS\d_Magic\s+=\s+)9020(\d\d)", r"\g<1>9030\2", s)
    if n != 9:
        raise SystemExit(f"expected 9 magic numbers, found {n}")
    return s


if __name__ == "__main__":
    DST.write_text(build())
    print(f"written {DST}")
