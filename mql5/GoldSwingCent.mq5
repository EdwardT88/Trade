//+------------------------------------------------------------------+
//|                                                GoldSwingCent.mq5 |
//|   XAUUSD trend-pullback swing EA for small (cent) accounts, MT5. |
//|                                                                  |
//|   Strategy (ported 1:1 from strategies/swing_pullback.py):       |
//|   - trend: last completed H4 bar close above EMA(40) and EMA(40) |
//|     higher than 6 H4 bars earlier (mirror for downtrend)         |
//|   - entry: on the close of an H1 bar, RSI(14) crosses back up    |
//|     through 40 in an uptrend (down through 60 in a downtrend)    |
//|   - stop 2 x ATR(14, H4); chandelier trail 3 x ATR updated on    |
//|     every closed M1 bar; flat every Friday 20:00 UTC             |
//|                                                                  |
//|   v1.10 sizing: rolling half-Kelly on the last 60 closed R       |
//|   (1-6%), x1.5 / x1 / x0.5 by the RSI pullback depth; winning    |
//|   longs may be held over the weekend with the stop locked at     |
//|   +0.5R (needs a swap-free account). Optional: cap extension and |
//|   re-entry after a stop-out (research package C7, minus the add).|
//|                                                                  |
//|   Risk first: min-lot risk cap, daily loss stop, loss-streak     |
//|   stop, optional drawdown risk reduction and an equity hard      |
//|   stop that halts the EA until a human reviews it.               |
//|   No martingale, no grid, no averaging, every trade has a stop.  |
//+------------------------------------------------------------------+
#property copyright "edwardt88/trade"
#property version   "1.10"
#property description "XAUUSD H4-trend / H1-pullback swing EA for cent accounts with strict anti-margin-call rules."

#include <Trade/Trade.mqh>

enum ENUM_SERVER_TZ
  {
   TZ_AUTO  = 0,   // Auto (live: server minus GMT; tester: fixed offset below)
   TZ_FIXED = 1,   // Fixed offset (hours)
   TZ_NY    = 2    // GMT+2 / GMT+3 with US DST (most MT5 brokers)
  };

enum ENUM_SIDES
  {
   SIDES_BOTH  = 0, // Long and short
   SIDES_LONG  = 1, // Long only
   SIDES_SHORT = 2  // Short only
  };

//=================================================================== inputs
input group "=== Strategy: H4 trend + H1 RSI pullback ==="
input int        InpTrendEMA           = 40;         // H4 trend EMA period
input int        InpTrendSlopeBars     = 6;          // EMA must be above/below its value this many H4 bars earlier
input int        InpRsiPeriod          = 14;         // H1 RSI period
input double     InpRsiLevel           = 40.0;       // Long: RSI crosses up through this. Short: through 100 - this
input int        InpAtrPeriod          = 14;         // H4 ATR period
input double     InpStopATR            = 2.0;        // Initial stop = this x ATR(H4)
input double     InpTrailATR           = 3.0;        // Chandelier trail = this x ATR(H4) at entry (0 = off)
input ENUM_SIDES InpSides              = SIDES_BOTH; // Directions to trade
input int        InpMaxHoldDays        = 3;          // Close a position after this many days (3 = ~same profit as 10, shorter trades)
input bool       InpFridayClose        = true;       // Close everything on Friday (no weekend gaps)
input int        InpFridayCloseHourUTC = 20;         // ... at this UTC hour
input int        InpFridayLastEntryUTC = 12;         // No new entries on Friday from this UTC hour
input int        InpNoEntryFromUTC     = 21;         // No new entries from this UTC hour (rollover/reopen spreads) ...
input int        InpNoEntryToUTC       = 24;         // ... until this UTC hour (24 = midnight)
input int        InpMaxEntryDelayMin   = 5;          // Skip a signal if it cannot be filled within this many minutes of the H1 close
input string     InpExtraFlatUTC       = "2026.11.27 17:00;2026.12.24 17:00;2026.12.31 17:00;2027.03.25 20:00;2027.11.26 17:00"; // Extra flat times (UTC, ';'-separated): holiday early closes / day before a closed Friday

input group "=== Risk (anti margin call) ==="
input double InpRiskPct            = 2.0;    // Risk per trade (% of equity)
input double InpReducedRiskPct     = 1.0;    // Risk while in drawdown (%)
input bool   InpRiskLadder         = false;  // Risk ladder: InpRiskPct until the balance doubles, then step down
input double InpRiskAt2x           = 3.0;    // ... risk once the balance is >= 2x the start balance (%)
input double InpRiskAt4x           = 2.0;    // ... risk once the balance is >= 4x the start balance (%)
input double InpDDReducePct        = 100.0;  // Drawdown from peak that switches to reduced risk (%; 100 = off: the brake cost > half the return)
input double InpMaxRiskAtMinLotPct = 3.0;    // Skip the trade if the minimum lot would risk more than this (%)
input double InpDailyLossPct       = 5.0;    // No new trades for the day after losing this % (closed + floating)
input int    InpMaxTradesPerDay    = 4;      // Max new trades per UTC day
input int    InpMaxConsecLosses    = 3;      // No new trades for the day after this many losses in a row
input double InpHardStopPct        = 30.0;   // HALT the EA if equity falls this % below the start balance
input double InpStartBalance       = 0.0;    // Hard-stop start balance in ACCOUNT currency (cent: USC, $50 = 5000). 0 = balance at first run
input bool   InpResetHalt          = false;  // Set true once to clear a HALT (start balance = current balance), then back to false

input group "=== Sizing: rolling half-Kelly x signal depth (research core 'KT') ==="
input bool   InpKellySizing        = true;   // Risk from the last closed trades (replaces InpRiskPct / ladder)
input int    InpKellyWindow        = 60;     // ... number of closed trades used (max 200)
input double InpKellyFrac          = 0.5;    // ... fraction of full Kelly (0.5 = half-Kelly)
input double InpKellyVarFloor      = 0.5;    // ... floor on the R variance (keeps a lucky streak from blowing up risk)
input double InpKellyMinPct        = 1.0;    // ... minimum base risk (%)
input double InpKellyMaxPct        = 6.0;    // ... maximum base risk (%)
input double InpKellyWarmPct       = 2.0;    // ... base risk until enough trades have closed (%)
input int    InpKellyMinTrades     = 15;     // ... closed trades needed before Kelly is used
input bool   InpDepthTiers         = true;   // Scale risk by how deep the RSI pullback was (shallow = bigger)
input int    InpDepthBars          = 10;     // ... H1 bars (incl. the signal bar) for the RSI extreme
input double InpDepthCutLo         = 1.826;  // ... depth <= this (shallow pullback): x InpDepthMultHi
input double InpDepthCutHi         = 4.905;  // ... depth >  this (deep pullback): x InpDepthMultLo
input double InpDepthMultHi        = 1.5;    // ... multiplier for shallow pullbacks
input double InpDepthMultLo        = 0.5;    // ... multiplier for deep pullbacks

input group "=== Trade management ==="
input bool   InpWeekendHold        = true;   // Friday close: keep a winning position over the weekend (swap-free account!)
input double InpWkMinR             = 1.0;    // ... only if open profit >= this x initial risk (R)
input double InpWkLockR            = 0.5;    // ... and move the stop to entry + this x R
input int    InpWkHours            = 96;     // ... close it this many hours after the Friday close (96 = Tuesday)
input bool   InpWkLongOnly         = true;   // ... longs only (shorts did not pass the research)
input bool   InpCapExtend          = false;  // AGGRESSIVE: at the max hold time keep a non-losing trend trade until Friday
input double InpExtMinR            = 0.0;    // ... only if open profit >= this x R
input double InpExtLockR           = 0.0;    // ... and move the stop to entry + this x R (0 = breakeven)
input bool   InpReentry            = false;  // AGGRESSIVE: after a losing stop-out, re-enter on an RSI cross of InpReRsi
input double InpReRsi              = 45.0;   // ... RSI level (long: up through it, short: down through 100 - it)
input int    InpReWindowHours      = 48;     // ... within this many hours of the stop-out, same direction and trend

input group "=== Execution ==="
input long   InpMagic              = 20261021; // Magic number
input double InpMaxSpreadUSD       = 1.00;   // Skip entry if the spread is wider than this (price units, $)
input double InpMaxSpreadPctOfSL   = 10.0;   // Skip entry if the spread is more than this % of the stop distance
input double InpMaxSlippageUSD     = 0.50;   // Max slippage accepted for market orders ($)
input double InpRiskBufferUSD      = 0.10;   // Added to the stop distance when sizing (slippage allowance, $)

input group "=== Time zone (all strategy hours are UTC) ==="
input ENUM_SERVER_TZ InpServerTZ   = TZ_AUTO; // Broker server time zone
input int    InpFixedOffsetHours   = 0;       // Server GMT offset for Fixed mode and the tester (Exness = 0)

input group "=== News filter (live only, MT5 economic calendar) ==="
input bool   InpUseNewsFilter      = false;  // Block new entries around high-impact USD news (OFF = same rules as the backtest)
input int    InpNewsMinutesBefore  = 15;     // Minutes before the event
input int    InpNewsMinutesAfter   = 15;     // Minutes after the event

input group "=== Logging ==="
input bool   InpWriteCsv           = true;   // Write closed trades to Common/Files/GoldSwingCent_<login>.csv
input bool   InpShowPanel          = true;   // Show status on the chart

//=================================================================== globals
CTrade   g_trade;
string   g_gvPrefix;
int      g_hEma = INVALID_HANDLE;
int      g_hAtr = INVALID_HANDLE;
int      g_hRsi = INVALID_HANDLE;
datetime g_lastH1Bar     = 0;
datetime g_lastM1Bar     = 0;
datetime g_newsCacheTime = 0;
datetime g_newsTimes[];
string   g_lastSkip      = "";
string   g_lastSignal    = "";
datetime g_lastCloseTry  = 0;
datetime g_lastOrderTry  = 0;
datetime g_lastExitM1    = 0;   // M1 bar of this EA's last exit (backtest: no new fill in the exit bar)
datetime g_lastRScan     = 0;
#define RH_CAP 200              // capacity of the closed-trade R ring buffer (global variables rh_0 .. rh_199)

//+------------------------------------------------------------------+
//| Time helpers                                                     |
//+------------------------------------------------------------------+
// Nth Sunday (n >= 1) of a month, or the last Sunday when n == 0, at 00:00
datetime NthSunday(const int year, const int month, const int n)
  {
   MqlDateTime d;
   ZeroMemory(d);
   d.year = year;
   d.mon  = month;
   d.day  = 1;
   if(n == 0)
     {
      if(month == 12)
        {
         d.year = year + 1;
         d.mon  = 1;
        }
      else
         d.mon = month + 1;
      datetime lastDay = StructToTime(d) - 86400;
      MqlDateTime x;
      TimeToStruct(lastDay, x);
      return lastDay - x.day_of_week * 86400;
     }
   datetime first = StructToTime(d);
   MqlDateTime f;
   TimeToStruct(first, f);
   int add = (7 - f.day_of_week) % 7;
   return first + (add + 7 * (n - 1)) * 86400;
  }

// US daylight saving: 2nd Sunday of March 07:00 UTC .. 1st Sunday of November 06:00 UTC
bool IsUSDst(const datetime utc)
  {
   MqlDateTime d;
   TimeToStruct(utc, d);
   datetime start = NthSunday(d.year, 3, 2) + 7 * 3600;
   datetime end   = NthSunday(d.year, 11, 1) + 6 * 3600;
   return (utc >= start && utc < end);
  }

// Server GMT offset in seconds
int ServerOffsetSeconds()
  {
   bool tester = (bool)MQLInfoInteger(MQL_TESTER);
   if(InpServerTZ == TZ_FIXED || (InpServerTZ == TZ_AUTO && tester))
      return InpFixedOffsetHours * 3600;
   if(InpServerTZ == TZ_NY)
     {
      datetime approxUtc = TimeTradeServer() - 2 * 3600;
      return (IsUSDst(approxUtc) ? 3 : 2) * 3600;
     }
   long diff = (long)TimeTradeServer() - (long)TimeGMT();
   return (int)(MathRound(diff / 900.0) * 900);   // nearest 15 minutes
  }

datetime ServerToUtc(const datetime server) { return server - ServerOffsetSeconds(); }
datetime UtcToServer(const datetime utc)    { return utc + ServerOffsetSeconds(); }
// TimeCurrent() is the server time of the tick being handled (the same clock as the bars); TimeTradeServer()
// follows the PC clock and can read hh-1:59:59 on the first tick of a new hour
datetime NowUtc()                           { return ServerToUtc(TimeCurrent()); }
datetime DayStart(const datetime t)         { return t - (t % 86400); }

//+------------------------------------------------------------------+
//| Persistent state (terminal global variables)                     |
//+------------------------------------------------------------------+
double GvGet(const string key, const double def)
  {
   string name = g_gvPrefix + key;
   if(GlobalVariableCheck(name))
      return GlobalVariableGet(name);
   return def;
  }

void GvSet(const string key, const double value)
  {
   if(GlobalVariableSet(g_gvPrefix + key, value) == 0)
      PrintFormat("GlobalVariableSet(%s) failed: %d", g_gvPrefix + key, GetLastError());
  }

// for state that must survive a crash (start balance, halt flag, trailing distance)
void GvSetFlush(const string key, const double value)
  {
   GvSet(key, value);
   GlobalVariablesFlush();
  }
void GvDel(const string key)                     { GlobalVariableDel(g_gvPrefix + key); }

double StartBalance()
  {
   double v = GvGet("start", 0.0);
   return (v > 0.0) ? v : AccountInfoDouble(ACCOUNT_BALANCE);
  }
bool   IsHalted()     { return GvGet("halted", 0.0) > 0.5; }

// peak of CLOSED-trade equity (the backtest sizes against the peak of realized equity)
void UpdatePeak()
  {
   if(SelectMyPosition())
      return;
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   if(bal > GvGet("peak", 0.0))
      GvSet("peak", bal);
  }

//+------------------------------------------------------------------+
//| Today's results for this EA (UTC day)                            |
//+------------------------------------------------------------------+
struct DayStats
  {
   double            realized;      // closed P/L today incl. swap and commission
   int               trades;        // trades opened today
   int               consecLosses;  // losing exits in a row at the end of today's history
  };

DayStats TodayStats()
  {
   DayStats s;
   s.realized = 0.0;
   s.trades = 0;
   s.consecLosses = 0;
   datetime fromServer = UtcToServer(DayStart(NowUtc()));
   if(!HistorySelect(fromServer, TimeTradeServer() + 60))
      return s;
   int total = HistoryDealsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0)
         continue;
      if(HistoryDealGetInteger(ticket, DEAL_MAGIC) != InpMagic)
         continue;
      if(HistoryDealGetString(ticket, DEAL_SYMBOL) != _Symbol)
         continue;
      long entry = HistoryDealGetInteger(ticket, DEAL_ENTRY);
      if(entry == DEAL_ENTRY_IN)
        {
         s.trades++;
         s.realized += HistoryDealGetDouble(ticket, DEAL_COMMISSION);
         continue;
        }
      if(entry == DEAL_ENTRY_OUT || entry == DEAL_ENTRY_OUT_BY || entry == DEAL_ENTRY_INOUT)
        {
         double p = HistoryDealGetDouble(ticket, DEAL_PROFIT)
                    + HistoryDealGetDouble(ticket, DEAL_SWAP)
                    + HistoryDealGetDouble(ticket, DEAL_COMMISSION);
         s.realized += p;
         if(p < 0.0)
            s.consecLosses++;
         else
            s.consecLosses = 0;
        }
     }
   return s;
  }

//+------------------------------------------------------------------+
//| Position helpers                                                 |
//+------------------------------------------------------------------+
bool SelectMyPosition()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol && PositionGetInteger(POSITION_MAGIC) == InpMagic)
         return true;
     }
   return false;
  }

double FloatingPnL()
  {
   double sum = 0.0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol && PositionGetInteger(POSITION_MAGIC) == InpMagic)
         sum += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
     }
   return sum;
  }

void CloseAll(const string why)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol || PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;
      if(g_trade.PositionClose(ticket))
        {
         g_lastExitM1 = iTime(_Symbol, PERIOD_M1, 0);
         PrintFormat("Closed #%I64u: %s", ticket, why);
        }
      else
         PrintFormat("Close #%I64u (%s) failed: %u %s", ticket, why, g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
     }
  }

// close at most once every 5 s so a failing close does not spam requests on every tick
void CloseAllThrottled(const string why)
  {
   if(TimeCurrent() - g_lastCloseTry < 5)
      return;
   g_lastCloseTry = TimeCurrent();
   CloseAll(why);
  }

//+------------------------------------------------------------------+
//| Extra flat times (holiday early closes)                          |
//+------------------------------------------------------------------+
// seconds until the next extra flat time within `horizon` (or that passed less than 12 h ago: returns <= 0);
// returns a large value when none applies
long SecondsToExtraFlat(const datetime nowUtc, const long horizon)
  {
   long best = LONG_MAX;
   string parts[];
   int n = StringSplit(InpExtraFlatUTC, ';', parts);
   for(int i = 0; i < n; i++)
     {
      StringTrimLeft(parts[i]);
      StringTrimRight(parts[i]);
      if(StringLen(parts[i]) < 10)
         continue;
      datetime t = StringToTime(parts[i]);
      if(t <= 0)
         continue;
      long d = (long)t - (long)nowUtc;
      if(d > -12 * 3600 && d <= horizon && d < best)
         best = d;
     }
   return best;
  }

//+------------------------------------------------------------------+
//| Price / volume helpers                                           |
//+------------------------------------------------------------------+
double NormPrice(const double price)
  {
   double tick = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick <= 0.0)
      tick = _Point;
   return NormalizeDouble(MathRound(price / tick) * tick, _Digits);
  }

// Money lost (account currency, positive) per 1.0 lot if price moves `dist` against the position
double LossPerLot(const bool isBuy, const double dist)
  {
   double price = isBuy ? SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double profit = 0.0;
   ENUM_ORDER_TYPE type = isBuy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double exitPrice = isBuy ? price - dist : price + dist;
   if(OrderCalcProfit(type, _Symbol, 1.0, price, exitPrice, profit) && profit < 0.0)
      return -profit;
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE_LOSS);
   if(tickValue <= 0.0)
      tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   if(tickSize <= 0.0 || tickValue <= 0.0)
      return 0.0;
   return dist / tickSize * tickValue;
  }

int VolumeDigits(const double step)
  {
   int digits = 0;
   double s = step;
   while(digits < 8 && MathAbs(s - MathRound(s)) > 1e-9)
     {
      s *= 10.0;
      digits++;
     }
   return digits;
  }

//+------------------------------------------------------------------+
//| Rolling Kelly: R multiples of this EA's closed trades            |
//+------------------------------------------------------------------+
int RHistCount() { return (int)GvGet("rh_n", 0.0); }

void RHistPush(const double r)
  {
   int n = RHistCount();
   GvSet(StringFormat("rh_%d", n % RH_CAP), r);
   GvSetFlush("rh_n", n + 1);
  }

// base risk % from the last InpKellyWindow closed R: clip(frac x mean / max(var, floor), min, max)
double KellyBasePct(int &used, double &kelly)
  {
   int n = RHistCount();
   used = (int)MathMin(n, MathMin(InpKellyWindow, RH_CAP));
   kelly = 0.0;
   if(n < InpKellyMinTrades || used < 2)
      return InpKellyWarmPct;
   double x[];
   ArrayResize(x, used);
   double mean = 0.0;
   for(int i = 0; i < used; i++)
     {
      x[i] = GvGet(StringFormat("rh_%d", (n - 1 - i) % RH_CAP), 0.0);
      mean += x[i];
     }
   mean /= used;
   double var = 0.0;
   for(int i = 0; i < used; i++)
      var += (x[i] - mean) * (x[i] - mean);
   var /= (used - 1);
   kelly = mean / MathMax(var, InpKellyVarFloor);
   return MathMax(InpKellyMinPct, MathMin(InpKellyMaxPct, InpKellyFrac * kelly * 100.0));
  }

// risk multiplier from the pullback depth at the signal bar (long: 40 - lowest RSI, short: highest RSI - 60)
double DepthMult(const bool isBuy, double &depth)
  {
   depth = 0.0;
   if(!InpDepthTiers)
      return 1.0;
   double r[];
   if(CopyBuffer(g_hRsi, 0, 1, InpDepthBars, r) != InpDepthBars)
      return -1.0;   // data not ready: caller retries
   double lo = r[0], hi = r[0];
   for(int i = 1; i < InpDepthBars; i++)
     {
      lo = MathMin(lo, r[i]);
      hi = MathMax(hi, r[i]);
     }
   depth = isBuy ? 40.0 - lo : hi - 60.0;
   if(depth <= InpDepthCutLo)
      return InpDepthMultHi;
   if(depth > InpDepthCutHi)
      return InpDepthMultLo;
   return 1.0;
  }

// risk % before the drawdown brake (base x depth multiplier)
double PlannedRiskPct(const double riskMult)
  {
   double baseRisk = InpRiskPct;
   if(InpKellySizing)
     {
      int used = 0;
      double k = 0.0;
      baseRisk = KellyBasePct(used, k);
     }
   else if(InpRiskLadder && StartBalance() > 0.0)
     {
      double growth = AccountInfoDouble(ACCOUNT_BALANCE) / StartBalance();
      baseRisk = (growth >= 4.0) ? InpRiskAt4x : (growth >= 2.0) ? InpRiskAt2x : InpRiskPct;
     }
   return baseRisk * riskMult;
  }

// Lots for the given stop distance; 0 when the trade must be skipped
double LotsForRisk(const bool isBuy, const double slDist, const double riskMult, double &riskPctUsed)
  {
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double peak   = MathMax(GvGet("peak", equity), equity);
   double baseRisk = PlannedRiskPct(riskMult);
   riskPctUsed   = (equity < peak * (1.0 - InpDDReducePct / 100.0)) ? MathMin(InpReducedRiskPct, baseRisk) : baseRisk;
   double riskMoney = equity * riskPctUsed / 100.0;
   double perLot    = LossPerLot(isBuy, slDist + InpRiskBufferUSD);
   if(perLot <= 0.0 || equity <= 0.0)
     {
      g_lastSkip = "cannot price the risk";
      return 0.0;
     }
   double vmin  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double vstep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(vstep <= 0.0)
      vstep = vmin;
   if(vstep <= 0.0 || vmax < vmin)
     {
      g_lastSkip = "symbol volume limits not available";
      return 0.0;
     }
   double lots = MathFloor(riskMoney / perLot / vstep + 1e-9) * vstep;
   if(lots < vmin)
     {
      double minRiskPct = vmin * perLot / equity * 100.0;
      if(minRiskPct > InpMaxRiskAtMinLotPct)
        {
         g_lastSkip = StringFormat("min lot would risk %.1f%% (> %.1f%%)", minRiskPct, InpMaxRiskAtMinLotPct);
         return 0.0;
        }
      lots = vmin;
     }
   lots = MathMin(lots, vmax);
   double price = isBuy ? SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double margin = 0.0;
   if(!OrderCalcMargin(isBuy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, _Symbol, lots, price, margin)
      || margin > AccountInfoDouble(ACCOUNT_MARGIN_FREE) * 0.5)
     {
      g_lastSkip = "margin check failed or not enough free margin";
      return 0.0;
     }
   return NormalizeDouble(lots, VolumeDigits(vstep));
  }

//+------------------------------------------------------------------+
//| News filter (MT5 economic calendar, live only)                   |
//+------------------------------------------------------------------+
void RefreshNews()
  {
   if(g_newsCacheTime > 0 && TimeTradeServer() - g_newsCacheTime < 3600)
      return;
   MqlCalendarValue values[];
   datetime from = TimeTradeServer() - 2 * 3600;
   datetime to   = TimeTradeServer() + 36 * 3600;
   if(!CalendarValueHistory(values, from, to, NULL, "USD"))
      return;   // retry on the next call
   g_newsCacheTime = TimeTradeServer();
   ArrayResize(g_newsTimes, 0);
   for(int i = 0; i < ArraySize(values); i++)
     {
      MqlCalendarEvent ev;
      if(!CalendarEventById(values[i].event_id, ev))
         continue;
      if(ev.importance != CALENDAR_IMPORTANCE_HIGH)
         continue;
      int n = ArraySize(g_newsTimes);
      ArrayResize(g_newsTimes, n + 1);
      g_newsTimes[n] = values[i].time;   // calendar times are trade-server times
     }
  }

bool NewsBlackout()
  {
   if(!InpUseNewsFilter || (bool)MQLInfoInteger(MQL_TESTER))
      return false;
   RefreshNews();
   datetime now = TimeTradeServer();
   for(int i = 0; i < ArraySize(g_newsTimes); i++)
      if(now >= g_newsTimes[i] - InpNewsMinutesBefore * 60 && now <= g_newsTimes[i] + InpNewsMinutesAfter * 60)
         return true;
   return false;
  }

//+------------------------------------------------------------------+
//| Entry gate: every risk / time rule in one place                  |
//+------------------------------------------------------------------+
bool CanOpenNewTrade(string &why)
  {
   if(IsHalted())
     {
      why = "HALTED (hard stop) - review, then InpResetHalt=true";
      return false;
     }
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || !MQLInfoInteger(MQL_TRADE_ALLOWED))
     {
      why = "algo trading is disabled";
      return false;
     }
   if(SelectMyPosition())
     {
      why = "position open";
      return false;
     }
   // netting account: one position per symbol, so an order would merge into a manual / other-EA position
   if((ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE) != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING
      && PositionSelect(_Symbol))
     {
      why = "netting account: symbol already has another position";
      return false;
     }
   MqlDateTime u;
   TimeToStruct(NowUtc(), u);
   if(u.day_of_week == 0 || u.day_of_week == 6)
     {
      why = "weekend";
      return false;
     }
   bool inNoEntry = (InpNoEntryFromUTC <= InpNoEntryToUTC)
                    ? (u.hour >= InpNoEntryFromUTC && u.hour < InpNoEntryToUTC)
                    : (u.hour >= InpNoEntryFromUTC || u.hour < InpNoEntryToUTC);   // window across midnight
   if(inNoEntry)
     {
      why = "rollover hours";
      return false;
     }
   if(InpFridayClose && u.day_of_week == 5 && u.hour >= InpFridayLastEntryUTC)
     {
      why = "Friday cutoff";
      return false;
     }
   if(SecondsToExtraFlat(NowUtc(), 8 * 3600) <= 8 * 3600)
     {
      why = "holiday early close ahead";
      return false;
     }
   DayStats ds = TodayStats();
   double dayStartBalance = AccountInfoDouble(ACCOUNT_BALANCE) - ds.realized;
   if(ds.realized + FloatingPnL() <= -InpDailyLossPct / 100.0 * dayStartBalance)
     {
      why = "daily loss limit";
      return false;
     }
   if(ds.consecLosses >= InpMaxConsecLosses)
     {
      why = "loss streak limit";
      return false;
     }
   if(ds.trades >= InpMaxTradesPerDay)
     {
      why = "max trades today";
      return false;
     }
   if(NewsBlackout())
     {
      why = "news blackout";
      return false;
     }
   why = "";
   return true;
  }

//+------------------------------------------------------------------+
//| Open a trade with the stop at an exact distance from the fill    |
//+------------------------------------------------------------------+
// returns true when a position was opened
bool OpenTrade(const bool isBuy, const double slDist, const double trailDist, const double riskMult, const bool reentry,
               const string tag)
  {
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double spread = ask - bid;
   if(slDist <= 0.0 || ask <= 0.0 || bid <= 0.0)
      return false;
   if(spread > InpMaxSpreadUSD || spread > slDist * InpMaxSpreadPctOfSL / 100.0)
     {
      g_lastSkip = StringFormat("spread %.2f too wide", spread);
      return false;
     }
   double stopsLevel = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
   if(slDist <= stopsLevel + spread)
     {
      g_lastSkip = "stop inside the broker stops level";
      return false;
     }
   double riskPct = 0.0;
   double lots = LotsForRisk(isBuy, slDist, riskMult, riskPct);
   if(lots <= 0.0)
      return false;
   double entry = isBuy ? ask : bid;
   double sl = NormPrice(isBuy ? entry - slDist : entry + slDist);
   string comment = StringFormat("GSW %s r%.1f", tag, riskPct);
   bool ok = isBuy ? g_trade.Buy(lots, _Symbol, 0.0, sl, 0.0, comment)
                   : g_trade.Sell(lots, _Symbol, 0.0, sl, 0.0, comment);
   uint rc = g_trade.ResultRetcode();
   if(!ok || (rc != TRADE_RETCODE_DONE && rc != TRADE_RETCODE_DONE_PARTIAL && rc != TRADE_RETCODE_PLACED))
     {
      PrintFormat("Open %s failed: %u %s", isBuy ? "BUY" : "SELL", rc, g_trade.ResultRetcodeDescription());
      return false;
     }
   // the position identifier equals the ticket of the order that opened it; store the trail even if the
   // position list has not refreshed yet
   ulong openOrder = g_trade.ResultOrder();
   if(trailDist > 0.0 && openOrder > 0)
      GvSetFlush(StringFormat("trail_%I64d", (long)openOrder), trailDist);
   if(openOrder > 0)
     {
      // initial stop distance, money at risk and kind, for R (Kelly), the weekend hold and the re-entry rule
      GvSet(StringFormat("s0_%I64d", (long)openOrder), slDist);
      GvSet(StringFormat("tg_%I64d", (long)openOrder), reentry ? 1.0 : 0.0);
      GvSet(StringFormat("ot_%I64d", (long)openOrder), (double)TimeCurrent());
      double filled = (g_trade.ResultVolume() > 0.0) ? g_trade.ResultVolume() : lots;
      GvSetFlush(StringFormat("r0_%I64d", (long)openOrder), filled * LossPerLot(isBuy, slDist + InpRiskBufferUSD));
     }
   GvSet("re_dir", 0.0);   // one re-entry per stop-out; a new trade replaces the last stop-out
   GvSetFlush("re_until", 0.0);
   if(SelectMyPosition())
     {
      ulong ticket = (ulong)PositionGetInteger(POSITION_TICKET);
      double fill = PositionGetDouble(POSITION_PRICE_OPEN);
      // re-anchor the stop to the actual fill so the distance matches the plan exactly
      double nsl = NormPrice(isBuy ? fill - slDist : fill + slDist);
      if(MathAbs(nsl - PositionGetDouble(POSITION_SL)) >= _Point)
         if(!g_trade.PositionModify(ticket, nsl, 0.0))
            PrintFormat("Stop re-anchor failed (kept %.2f): %u %s", PositionGetDouble(POSITION_SL),
                        g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
     }
   PrintFormat("%s %.2f lots @ %.2f  SL %.2f  trail %.2f  risk %.1f%%  (%s)", isBuy ? "BUY" : "SELL", lots,
               entry, sl, trailDist, riskPct, tag);
   return true;
  }

//+------------------------------------------------------------------+
//| Strategy                                                         |
//+------------------------------------------------------------------+
bool StrategyInit()
  {
   if(StringFind(_Symbol, "XAU") < 0 && StringFind(_Symbol, "GOLD") < 0)
      PrintFormat("Warning: %s does not look like gold. The strategy was researched on XAUUSD only.", _Symbol);
   g_hEma = iMA(_Symbol, PERIOD_H4, InpTrendEMA, 0, MODE_EMA, PRICE_CLOSE);
   g_hAtr = iATR(_Symbol, PERIOD_H4, InpAtrPeriod);
   g_hRsi = iRSI(_Symbol, PERIOD_H1, InpRsiPeriod, PRICE_CLOSE);
   if(g_hEma == INVALID_HANDLE || g_hAtr == INVALID_HANDLE || g_hRsi == INVALID_HANDLE)
     {
      Print("Failed to create indicator handles");
      return false;
     }
   return true;
  }

void StrategyDeinit()
  {
   if(g_hEma != INVALID_HANDLE)
      IndicatorRelease(g_hEma);
   if(g_hAtr != INVALID_HANDLE)
      IndicatorRelease(g_hAtr);
   if(g_hRsi != INVALID_HANDLE)
      IndicatorRelease(g_hRsi);
  }

// trend: +1 up, -1 down, 0 none, from the last completed H4 bar; false when the data is not ready yet
bool H4TrendEx(int &trend)
  {
   trend = 0;
   double ema[];
   ArraySetAsSeries(ema, true);
   int need = InpTrendSlopeBars + 1;
   if(CopyBuffer(g_hEma, 0, 1, need, ema) != need)
      return false;
   double c1 = iClose(_Symbol, PERIOD_H4, 1);
   if(c1 <= 0.0)
      return false;
   if(c1 > ema[0] && ema[0] > ema[InpTrendSlopeBars])
      trend = 1;
   else if(c1 < ema[0] && ema[0] < ema[InpTrendSlopeBars])
      trend = -1;
   return true;
  }

int H4Trend()
  {
   int t = 0;
   H4TrendEx(t);
   return t;
  }

// Evaluated on every tick until the current H1 bar's signal is resolved: no signal, filled, blocked by a
// risk/time rule, or older than InpMaxEntryDelayMin (the backtest fills at the first M1 bar after the close).
void CheckEntrySignal()
  {
   datetime h1 = iTime(_Symbol, PERIOD_H1, 0);
   if(h1 == 0 || h1 == g_lastH1Bar)
      return;
   // measured from the SIGNAL bar's close like the backtest; after a gap the current bar is the reopen hour
   datetime sigOpen = iTime(_Symbol, PERIOD_H1, 1);
   if(sigOpen == 0)
      return;   // series not ready: retry on the next tick
   if(TimeCurrent() - (sigOpen + PeriodSeconds(PERIOD_H1)) > InpMaxEntryDelayMin * 60)
     {
      g_lastH1Bar = h1;   // too late after the signal bar's close (weekend, daily break, data hole)
      return;
     }
   double rsi[];
   ArraySetAsSeries(rsi, true);
   int trend = 0;
   if(CopyBuffer(g_hRsi, 0, 1, 2, rsi) != 2 || !H4TrendEx(trend))
      return;   // indicator data not ready yet: retry on the next tick
   double lo = InpRsiLevel;
   double hi = 100.0 - InpRsiLevel;
   bool longSig  = (trend > 0) && (rsi[1] < lo) && (rsi[0] >= lo) && InpSides != SIDES_SHORT;
   bool shortSig = (trend < 0) && (rsi[1] > hi) && (rsi[0] <= hi) && InpSides != SIDES_LONG;
   bool reentry  = false;
   if(!longSig && !shortSig && InpReentry)
     {
      // within InpReWindowHours of a losing stop-out: an RSI cross of InpReRsi in the same direction
      double reDir = GvGet("re_dir", 0.0);
      if(reDir != 0.0 && TimeCurrent() <= (datetime)GvGet("re_until", 0.0))
        {
         longSig  = (reDir > 0) && (trend > 0) && (rsi[1] < InpReRsi) && (rsi[0] >= InpReRsi) && InpSides != SIDES_SHORT;
         shortSig = (reDir < 0) && (trend < 0) && (rsi[1] > 100.0 - InpReRsi) && (rsi[0] <= 100.0 - InpReRsi)
                    && InpSides != SIDES_LONG;
         reentry  = longSig || shortSig;
        }
     }
   if(!longSig && !shortSig)
     {
      g_lastH1Bar = h1;
      return;
     }
   g_lastSignal = StringFormat("%s %s%s RSI %.1f->%.1f", TimeToString(h1, TIME_DATE | TIME_MINUTES),
                               longSig ? "LONG" : "SHORT", reentry ? " (re-entry)" : "", rsi[1], rsi[0]);
   if(iTime(_Symbol, PERIOD_M1, 0) <= g_lastExitM1)
     {
      g_lastSkip  = "signal skipped: previous trade exited in this minute (backtest: busy)";
      g_lastH1Bar = h1;
      return;
     }
   string why = "";
   if(!CanOpenNewTrade(why))
     {
      g_lastSkip = "signal skipped: " + why;
      g_lastH1Bar = h1;
      return;
     }
   double atr[];
   if(CopyBuffer(g_hAtr, 0, 1, 1, atr) != 1 || atr[0] <= 0.0)
      return;
   double depth = 0.0;
   double mult = DepthMult(longSig, depth);
   if(mult <= 0.0)
      return;   // RSI history not ready yet
   if(TimeCurrent() - g_lastOrderTry < 10)
      return;   // spread / order retry at most every 10 s within the entry window
   g_lastOrderTry = TimeCurrent();
   string tag = StringFormat("%s%s d%.1f", reentry ? "re-" : "pb-", longSig ? "long" : "short", depth);
   if(OpenTrade(longSig, InpStopATR * atr[0], InpTrailATR * atr[0], mult, reentry, tag))
      g_lastH1Bar = h1;
  }

// ATR(H4) of the last H4 bar completed before `opened` (the value the entry used)
double EntryAtr(const datetime opened)
  {
   int sh = iBarShift(_Symbol, PERIOD_H4, opened, false);
   double a[];
   if(sh < 0 || CopyBuffer(g_hAtr, 0, sh + 1, 1, a) != 1 || a[0] <= 0.0)
      return 0.0;
   return a[0];
  }

// trailing distance for a position; rebuilt from the entry ATR if the stored value is missing
double TrailDistance(const long posId, const datetime opened)
  {
   if(InpTrailATR <= 0.0)
      return 0.0;
   string key = StringFormat("trail_%I64d", posId);
   double v = GvGet(key, -1.0);
   if(v > 0.0)
      return v;
   double a = EntryAtr(opened);
   if(a <= 0.0)
      return 0.0;
   v = InpTrailATR * a;
   GvSetFlush(key, v);
   PrintFormat("Trailing distance for position %I64d rebuilt from entry ATR: %.2f", posId, v);
   return v;
  }

// initial stop distance of a position (R); rebuilt from the entry ATR if the stored value is missing
double InitialStop(const long posId, const datetime opened)
  {
   string key = StringFormat("s0_%I64d", posId);
   double v = GvGet(key, -1.0);
   if(v > 0.0)
      return v;
   double a = EntryAtr(opened);
   if(a <= 0.0)
      return 0.0;
   v = InpStopATR * a;
   GvSet(key, v);
   return v;
  }

// Time exits (Friday close / weekend hold, max hold / cap extension), the profit lock of a held position and the
// chandelier trailing stop (stop updates once per closed M1 bar, like the backtest)
void ManagePosition()
  {
   if(!SelectMyPosition())
      return;
   ulong    ticket = (ulong)PositionGetInteger(POSITION_TICKET);
   long     posId  = PositionGetInteger(POSITION_IDENTIFIER);
   datetime opened = (datetime)PositionGetInteger(POSITION_TIME);
   bool     isBuy  = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
   double   curSL  = PositionGetDouble(POSITION_SL);
   double   entry  = PositionGetDouble(POSITION_PRICE_OPEN);
   double   bid    = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double   ask    = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double   sl0    = InitialStop(posId, opened);
   double   openR  = (sl0 > 0.0) ? (isBuy ? bid - entry : entry - ask) / sl0 : 0.0;   // open profit in R
   string   wkKey  = StringFormat("wk_%I64d", posId);
   string   exKey  = StringFormat("ex_%I64d", posId);

   datetime nowU = NowUtc();
   MqlDateTime u;
   TimeToStruct(nowU, u);
   double wkEnd = GvGet(wkKey, 0.0);   // > 0: held over the weekend until this UTC time
   if(wkEnd > 0.0)
     {
      if((double)nowU >= wkEnd)
        {
         CloseAllThrottled("weekend hold ended");
         return;
        }
     }
   else if(InpFridayClose && ((u.day_of_week == 5 && u.hour >= InpFridayCloseHourUTC) || u.day_of_week == 6 || u.day_of_week == 0))
     {
      bool hold = InpWeekendHold && u.day_of_week == 5 && sl0 > 0.0 && (isBuy || !InpWkLongOnly) && openR >= InpWkMinR;
      if(hold)
        {
         // the lock must be in place before the weekend: if the broker refuses it, close as usual
         double lock = NormPrice(isBuy ? entry + InpWkLockR * sl0 : entry - InpWkLockR * sl0);
         bool tighter = isBuy ? (lock > curSL) : (curSL <= 0.0 || lock < curSL);
         if(tighter && !g_trade.PositionModify(ticket, lock, PositionGetDouble(POSITION_TP)))
           {
            PrintFormat("Weekend hold: stop lock at %.2f refused (%u %s)", lock, g_trade.ResultRetcode(),
                        g_trade.ResultRetcodeDescription());
            hold = false;
           }
        }
      if(hold)
        {
         wkEnd = (double)(DayStart(nowU) + InpFridayCloseHourUTC * 3600 + InpWkHours * 3600);
         GvSetFlush(wkKey, wkEnd);
         PrintFormat("Weekend hold: open profit %.2fR >= %.2fR, stop locked at +%.2fR, close at %s UTC", openR, InpWkMinR,
                     InpWkLockR, TimeToString((datetime)wkEnd, TIME_DATE | TIME_MINUTES));
        }
      else
        {
         CloseAllThrottled("Friday close");
         return;
        }
     }
   if(SecondsToExtraFlat(nowU, 0) <= 0)
     {
      CloseAllThrottled("holiday early close");
      return;
     }
   double exEnd = GvGet(exKey, 0.0);   // > 0: extended until this UTC time (Friday close); < 0: declined
   bool extended = exEnd > 0.0;
   if(wkEnd <= 0.0 && extended && (double)nowU >= exEnd)
     {
      CloseAllThrottled("extension ended");   // the Friday close was missed (EA off, no ticks)
      return;
     }
   if(wkEnd <= 0.0 && !extended && InpMaxHoldDays > 0 && TimeCurrent() - opened >= InpMaxHoldDays * 86400)
     {
      // decided once at the cap, like the research; a failed close then retries instead of re-deciding
      if(exEnd == 0.0 && InpCapExtend && sl0 > 0.0 && openR >= InpExtMinR && H4Trend() == (isBuy ? 1 : -1))
        {
         exEnd = (double)(DayStart(nowU) + ((5 - u.day_of_week + 7) % 7) * 86400 + InpFridayCloseHourUTC * 3600);
         GvSetFlush(exKey, exEnd);
         extended = true;
         PrintFormat("Max hold reached with %.2fR in a live trend: kept until the Friday close, stop locked at +%.2fR",
                     openR, InpExtLockR);
        }
      else
        {
         if(exEnd == 0.0)
            GvSet(exKey, -1.0);
         CloseAllThrottled("max hold time");
         return;
        }
     }

   datetime m1 = iTime(_Symbol, PERIOD_M1, 0);
   if(m1 == 0 || m1 == g_lastM1Bar)
      return;
   g_lastM1Bar = m1;

   long stopsLevel  = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   long freezeLevel = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL);
   double minGap = (double)(stopsLevel > freezeLevel ? stopsLevel : freezeLevel) * _Point;
   double tick = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick <= 0.0)
      tick = _Point;

   // candidate stops: the chandelier trail and the lock of a held / extended position; the tightest wins
   bool   have = false;
   double newSL = 0.0;
   double trail = TrailDistance(posId, opened);
   int shiftOpen = iBarShift(_Symbol, PERIOD_M1, opened, false);
   if(trail > 0.0 && shiftOpen >= 1)   // needs a closed M1 bar since the entry
     {
      int idx = isBuy ? iHighest(_Symbol, PERIOD_M1, MODE_HIGH, shiftOpen, 1)
                      : iLowest(_Symbol, PERIOD_M1, MODE_LOW, shiftOpen, 1);
      if(idx >= 0)
        {
         newSL = isBuy ? NormPrice(iHigh(_Symbol, PERIOD_M1, idx) - trail)
                       : NormPrice(iLow(_Symbol, PERIOD_M1, idx) + (ask - bid) + trail);
         have = true;
        }
     }
   if(sl0 > 0.0 && (wkEnd > 0.0 || extended))
     {
      double lockR = MathMax(wkEnd > 0.0 ? InpWkLockR : -1e9, extended ? InpExtLockR : -1e9);
      double lock = NormPrice(isBuy ? entry + lockR * sl0 : entry - lockR * sl0);
      if(!have || (isBuy ? lock > newSL : lock < newSL))
         newSL = lock;
      have = true;
     }
   if(!have)
      return;
   if(isBuy)
     {
      if(newSL <= curSL + tick)
         return;
      if(newSL >= bid)
        {
         GvSet(StringFormat("xs_%I64d", posId), 1.0);   // a stop exit for the re-entry rule
         CloseAll("stop level crossed");
         return;
        }
      if(bid - newSL <= minGap)
         return;   // too close to price for the broker; try again on the next bar
     }
   else
     {
      if(curSL > 0.0 && newSL >= curSL - tick)
         return;
      if(newSL <= ask)
        {
         GvSet(StringFormat("xs_%I64d", posId), 1.0);
         CloseAll("stop level crossed");
         return;
        }
      if(newSL - ask <= minGap)
         return;
     }
   if(!g_trade.PositionModify(ticket, newSL, PositionGetDouble(POSITION_TP)))
      PrintFormat("Stop modify failed: %u %s", g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
  }

//+------------------------------------------------------------------+
//| Hard stop                                                        |
//+------------------------------------------------------------------+
void CheckHardStop()
  {
   double start = StartBalance();
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   if(IsHalted())
     {
      if(SelectMyPosition())
         CloseAllThrottled("hard stop (retry)");
      return;
     }
   if(eq <= start * (1.0 - InpHardStopPct / 100.0))
     {
      GvSetFlush("halted", 1.0);
      CloseAll("hard stop");
      PrintFormat("HARD STOP: equity %.2f is %.0f%% below the start balance %.2f. EA halted.", eq, InpHardStopPct, start);
      Alert("GoldSwingCent HALTED: equity hit the hard stop. Review before restarting.");
     }
  }

//+------------------------------------------------------------------+
//| Trade log + trailing-state cleanup                               |
//+------------------------------------------------------------------+
void OnClosedDeal(const ulong deal)
  {
   if(!HistoryDealSelect(deal))
      return;
   if(HistoryDealGetInteger(deal, DEAL_MAGIC) != InpMagic || HistoryDealGetString(deal, DEAL_SYMBOL) != _Symbol)
      return;
   long entry = HistoryDealGetInteger(deal, DEAL_ENTRY);
   if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_OUT_BY)
      return;
   datetime exitT  = (datetime)HistoryDealGetInteger(deal, DEAL_TIME);
   datetime exitM1 = (datetime)((long)exitT - (long)exitT % 60);
   if(exitM1 > g_lastExitM1)
      g_lastExitM1 = exitM1;
   long posId = HistoryDealGetInteger(deal, DEAL_POSITION_ID);
   if(!SelectMyPosition())
      GvDel(StringFormat("trail_%I64d", posId));
   if(!InpWriteCsv)
      return;
   string file = StringFormat("GoldSwingCent_%I64d.csv", AccountInfoInteger(ACCOUNT_LOGIN));
   int h = FileOpen(file, FILE_READ | FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON | FILE_SHARE_READ, ',');
   if(h == INVALID_HANDLE)
      return;
   if(FileSize(h) == 0)
      FileWrite(h, "close_time_server", "position", "closed", "volume", "price", "profit", "swap", "commission",
                "reason", "balance_after", "comment");
   FileSeek(h, 0, SEEK_END);
   long reason = HistoryDealGetInteger(deal, DEAL_REASON);
   string r = (reason == DEAL_REASON_SL) ? "SL" : (reason == DEAL_REASON_TP) ? "TP" : (reason == DEAL_REASON_EXPERT) ? "EA" : "OTHER";
   FileWrite(h, TimeToString((datetime)HistoryDealGetInteger(deal, DEAL_TIME), TIME_DATE | TIME_SECONDS),
             posId,
             (HistoryDealGetInteger(deal, DEAL_TYPE) == DEAL_TYPE_SELL) ? "buy" : "sell",
             DoubleToString(HistoryDealGetDouble(deal, DEAL_VOLUME), 2),
             DoubleToString(HistoryDealGetDouble(deal, DEAL_PRICE), _Digits),
             DoubleToString(HistoryDealGetDouble(deal, DEAL_PROFIT), 2),
             DoubleToString(HistoryDealGetDouble(deal, DEAL_SWAP), 2),
             DoubleToString(HistoryDealGetDouble(deal, DEAL_COMMISSION), 2),
             r,
             DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2),
             HistoryDealGetString(deal, DEAL_COMMENT));
   FileClose(h);
  }

bool PositionIsOpen(const long posId)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(PositionGetTicket(i) > 0 && PositionGetInteger(POSITION_IDENTIFIER) == posId)
         return true;
   return false;
  }

// Every closed position that still has its entry record (r0_<id>): add its R to the Kelly history, arm the
// re-entry after a losing stop-out of a normal entry, and drop the position's state. Runs after each deal and once a
// minute, so a stop hit while the terminal was off is booked at the next start.
void ProcessClosedPositions()
  {
   string pre = g_gvPrefix + "r0_";
   long ids[];
   for(int i = GlobalVariablesTotal() - 1; i >= 0; i--)
     {
      string name = GlobalVariableName(i);
      if(StringFind(name, pre) != 0)
         continue;
      int n = ArraySize(ids);
      ArrayResize(ids, n + 1);
      ids[n] = StringToInteger(StringSubstr(name, StringLen(pre)));
     }
   for(int k = 0; k < ArraySize(ids); k++)
     {
      long id = ids[k];
      if(id <= 0 || PositionIsOpen(id))
         continue;
      double net = 0.0, inVol = 0.0, outVol = 0.0, inPx = 0.0, outPx = 0.0;
      long reason = -1;
      datetime exitT = 0;
      bool isBuy = true;
      int deals = HistorySelectByPosition(id) ? HistoryDealsTotal() : 0;
      for(int i = 0; i < deals; i++)
        {
         ulong d = HistoryDealGetTicket(i);
         if(d == 0)
            continue;
         long e = HistoryDealGetInteger(d, DEAL_ENTRY);
         net += HistoryDealGetDouble(d, DEAL_PROFIT) + HistoryDealGetDouble(d, DEAL_SWAP)
                + HistoryDealGetDouble(d, DEAL_COMMISSION);
         if(e == DEAL_ENTRY_IN)
           {
            inVol += HistoryDealGetDouble(d, DEAL_VOLUME);
            inPx = HistoryDealGetDouble(d, DEAL_PRICE);
            isBuy = (HistoryDealGetInteger(d, DEAL_TYPE) == DEAL_TYPE_BUY);
           }
         else if(e == DEAL_ENTRY_OUT || e == DEAL_ENTRY_OUT_BY)
           {
            outVol += HistoryDealGetDouble(d, DEAL_VOLUME);
            datetime t = (datetime)HistoryDealGetInteger(d, DEAL_TIME);
            if(t >= exitT)
              {
               exitT = t;
               reason = HistoryDealGetInteger(d, DEAL_REASON);
               outPx = HistoryDealGetDouble(d, DEAL_PRICE);
              }
           }
        }
      bool never = (inVol <= 0.0 && TimeCurrent() - (datetime)GvGet(StringFormat("ot_%I64d", id), 0.0) > 86400);
      if(!never && (inVol <= 0.0 || outVol < inVol - 1e-8))
         continue;   // history not complete yet: retry later
      double risk0 = GvGet(StringFormat("r0_%I64d", id), 0.0);
      GvDel(StringFormat("r0_%I64d", id));   // removed before the push: a crash must not book the trade twice
      GlobalVariablesFlush();
      if(risk0 > 0.0 && !never)
        {
         double r = net / risk0;
         RHistPush(r);
         int used = 0;
         double kelly = 0.0;
         double nextBase = KellyBasePct(used, kelly);
         PrintFormat("Position %I64d closed: %.2f = %.2fR. Kelly history %d trades, next base risk %.2f%%", id, net, r,
                     RHistCount(), nextBase);
        }
      bool normal = GvGet(StringFormat("tg_%I64d", id), 0.0) < 0.5;
      // research: a stop hit at a level below the entry (not a breakeven stop, not a time exit)
      bool stopExit = (reason == DEAL_REASON_SL || GvGet(StringFormat("xs_%I64d", id), 0.0) > 0.5);
      bool belowEntry = isBuy ? (outPx < inPx - _Point) : (outPx > inPx + _Point);
      if(InpReentry && !never && normal && stopExit && belowEntry && !SelectMyPosition())
        {
         GvSet("re_dir", isBuy ? 1.0 : -1.0);
         GvSetFlush("re_until", (double)(exitT + InpReWindowHours * 3600));
        }
      GvDel(StringFormat("trail_%I64d", id));
      GvDel(StringFormat("s0_%I64d", id));
      GvDel(StringFormat("tg_%I64d", id));
      GvDel(StringFormat("wk_%I64d", id));
      GvDel(StringFormat("ex_%I64d", id));
      GvDel(StringFormat("ot_%I64d", id));
      GvDel(StringFormat("xs_%I64d", id));
      GlobalVariablesFlush();
     }
  }

void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &request, const MqlTradeResult &result)
  {
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD || trans.deal == 0)
      return;
   if(HistoryDealSelect(trans.deal) && HistoryDealGetInteger(trans.deal, DEAL_TYPE) == DEAL_TYPE_BALANCE)
     {
      // deposit (+) or withdrawal (-): shift the hard-stop baseline and the peak by the same amount
      double flow = HistoryDealGetDouble(trans.deal, DEAL_PROFIT);
      GvSetFlush("start", StartBalance() + flow);
      GvSet("peak", MathMax(0.0, GvGet("peak", 0.0) + flow));
      PrintFormat("Balance operation %.2f: hard-stop start balance is now %.2f", flow, StartBalance());
      return;
     }
   OnClosedDeal(trans.deal);
   ProcessClosedPositions();
  }

//+------------------------------------------------------------------+
//| Panel                                                            |
//+------------------------------------------------------------------+
void DrawPanel()
  {
   if(!InpShowPanel || (bool)MQLInfoInteger(MQL_OPTIMIZATION))
      return;
   string why = "";
   bool can = CanOpenNewTrade(why);
   DayStats ds = TodayStats();
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   double peak = MathMax(GvGet("peak", eq), eq);
   double start = StartBalance();
   string s = StringFormat("GoldSwingCent v1.10  |  %s\n", can ? "waiting for a signal" : why);
   if(InpKellySizing)
     {
      int used = 0;
      double k = 0.0;
      double base = KellyBasePct(used, k);
      s += StringFormat("Risk: Kelly base %.2f%% (%d closed trades%s) x depth %s\n", base, RHistCount(),
                        RHistCount() < InpKellyMinTrades ? ", warm-up" : "", InpDepthTiers ? "0.5/1/1.5" : "off");
     }
   else
      s += StringFormat("Risk: fixed %.2f%%\n", PlannedRiskPct(1.0));
   s += StringFormat("Equity %.2f  start %.2f  peak %.2f  DD %.1f%%\n", eq, start, peak, peak > 0 ? (1.0 - eq / peak) * 100.0 : 0.0);
   s += StringFormat("Hard stop at %.2f %s\n", start * (1.0 - InpHardStopPct / 100.0), IsHalted() ? "[HALTED]" : "");
   s += StringFormat("Today: P/L %.2f  trades %d/%d  loss streak %d/%d\n", ds.realized + FloatingPnL(), ds.trades,
                     InpMaxTradesPerDay, ds.consecLosses, InpMaxConsecLosses);
   s += StringFormat("H4 trend %s  spread %.2f  UTC %s  server %+.1fh\n", H4Trend() > 0 ? "UP" : H4Trend() < 0 ? "DOWN" : "none",
                     SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID),
                     TimeToString(NowUtc(), TIME_MINUTES), ServerOffsetSeconds() / 3600.0);
   if(g_lastSignal != "")
      s += "Last signal: " + g_lastSignal + "\n";
   if(g_lastSkip != "")
      s += "Last skip: " + g_lastSkip + "\n";
   Comment(s);
  }

//+------------------------------------------------------------------+
//| Lifecycle                                                        |
//+------------------------------------------------------------------+
// another chart already runs this EA on the same symbol (two instances would double the risk)
bool AnotherInstanceOnSymbol()
  {
   for(long id = ChartFirst(); id >= 0; id = ChartNext(id))
      if(id != ChartID() && ChartSymbol(id) == _Symbol
         && ChartGetString(id, CHART_EXPERT_NAME) == MQLInfoString(MQL_PROGRAM_NAME))
         return true;
   return false;
  }

int OnInit()
  {
   bool tester = (bool)MQLInfoInteger(MQL_TESTER);
   if(!tester && AnotherInstanceOnSymbol())
     {
      Alert("GoldSwingCent already runs on another ", _Symbol, " chart. Remove one instance.");
      return INIT_FAILED;
     }
   if(tester && InpServerTZ == TZ_AUTO)
     {
      Print("In the Strategy Tester the server offset cannot be measured. Set InpServerTZ to 'Fixed offset' ",
            "(InpFixedOffsetHours = 0 for Exness) or to 'GMT+2 / GMT+3 with US DST' (HFM and most brokers).");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(InpRiskPct <= 0.0 || InpRiskPct > 5.0 || InpReducedRiskPct <= 0.0 || InpReducedRiskPct > InpRiskPct
      || InpRiskAt2x <= 0.0 || InpRiskAt2x > 5.0 || InpRiskAt4x <= 0.0 || InpRiskAt4x > 5.0
      || InpDDReducePct <= 0.0 || InpDDReducePct > 100.0
      || InpStopATR <= 0.0 || InpHardStopPct <= 0.0 || InpHardStopPct >= 100.0)
     {
      Print("Risk inputs out of range: 0 < reduced risk <= risk <= 5%, 0 < DD reduce <= 100%, stop ATR > 0, ",
            "0 < hard stop < 100%.");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(InpKellySizing && (InpKellyWindow < 2 || InpKellyWindow > RH_CAP || InpKellyFrac <= 0.0 || InpKellyFrac > 1.0
      || InpKellyVarFloor <= 0.0 || InpKellyMinPct <= 0.0 || InpKellyMinPct > InpKellyMaxPct || InpKellyMaxPct > 8.0
      || InpKellyWarmPct < InpKellyMinPct || InpKellyWarmPct > InpKellyMaxPct || InpKellyMinTrades < 2))
     {
      Print("Kelly inputs out of range: window 2..200, 0 < fraction <= 1, variance floor > 0, ",
            "0 < min <= warm-up <= max <= 8%, min trades >= 2.");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(InpDepthTiers && (InpDepthBars < 1 || InpDepthBars > 100 || InpDepthCutLo > InpDepthCutHi
      || InpDepthMultLo <= 0.0 || InpDepthMultHi <= 0.0 || InpDepthMultHi > 2.0 || InpDepthMultLo > 2.0))
     {
      Print("Depth tier inputs out of range: 1..100 bars, low cut <= high cut, 0 < multipliers <= 2.");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(InpWkHours < 1 || InpWkHours > 120 || InpWkLockR < -1.0 || InpWkLockR >= InpWkMinR
      || InpExtLockR < -1.0 || InpExtLockR > InpExtMinR || InpReRsi <= 0.0 || InpReRsi >= 100.0 || InpReWindowHours < 1)
     {
      Print("Trade management inputs out of range: weekend hold 1..120 h, lock below the min profit, ",
            "extension lock <= its min profit, 0 < re-entry RSI < 100, re-entry window >= 1 h.");
      return INIT_PARAMETERS_INCORRECT;
     }
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   g_gvPrefix = StringFormat("GSW_%I64d_%I64d_%s_", AccountInfoInteger(ACCOUNT_LOGIN), InpMagic, _Symbol);
   if(tester)
      GlobalVariablesDeleteAll(g_gvPrefix);   // fresh state for every tester pass
   // InpStartBalance is applied (and unit-checked) only when it is entered or changed: re-applying it on every
   // init would undo deposit/withdrawal shifts, and the check would refuse a restart after the account grew
   bool newStartInput = (InpStartBalance > 0.0 && MathAbs(GvGet("start_input", 0.0) - InpStartBalance) > 0.001);
   if(newStartInput && bal > 0.0 && (InpStartBalance < 0.2 * bal || InpStartBalance > 5.0 * bal))
     {
      Alert(StringFormat("InpStartBalance %.2f looks wrong for balance %.2f %s (cent account: enter USC, e.g. 5000 for $50)",
                         InpStartBalance, bal, AccountInfoString(ACCOUNT_CURRENCY)));
      return INIT_PARAMETERS_INCORRECT;
     }
   if(newStartInput)
     {
      GvSetFlush("start", InpStartBalance);
      GvSetFlush("start_input", InpStartBalance);
     }
   else if(!GlobalVariableCheck(g_gvPrefix + "start") && bal > 0.0)
      GvSetFlush("start", bal);   // if the account is not synchronised yet, OnTick sets it
   // one-shot: leaving InpResetHalt = true must not silently clear a later HALT on a restart;
   // re-armed by any init with InpResetHalt = false
   if(InpResetHalt && GvGet("reset_armed", 1.0) > 0.5 && bal > 0.0)
     {
      if(!newStartInput)
         GvSetFlush("start", bal);   // new baseline, otherwise the EA would halt again on the next tick
      GvSetFlush("halted", 0.0);
      GvSet("peak", bal);
      GvSetFlush("reset_armed", 0.0);
      PrintFormat("Halt cleared. New hard-stop start balance %.2f.", StartBalance());
     }
   else if(!InpResetHalt)
      GvSet("reset_armed", 1.0);
   UpdatePeak();
   g_trade.SetExpertMagicNumber((ulong)InpMagic);
   g_trade.SetDeviationInPoints((ulong)MathMax(1.0, MathRound(InpMaxSlippageUSD / _Point)));
   g_trade.SetTypeFillingBySymbol(_Symbol);
   g_trade.SetAsyncMode(false);
   if(!StrategyInit())
      return INIT_FAILED;
   ProcessClosedPositions();   // book trades that closed while the EA was off
   PrintFormat("GoldSwingCent started on %s. Start balance %.2f, hard stop at %.2f, server offset %+.1fh",
               _Symbol, StartBalance(), StartBalance() * (1.0 - InpHardStopPct / 100.0), ServerOffsetSeconds() / 3600.0);
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   StrategyDeinit();
   Comment("");
  }

void OnTick()
  {
   if(GvGet("start", 0.0) <= 0.0 && AccountInfoDouble(ACCOUNT_BALANCE) > 0.0)
      GvSetFlush("start", AccountInfoDouble(ACCOUNT_BALANCE));
   UpdatePeak();
   CheckHardStop();
   if(TimeCurrent() - g_lastRScan >= 60)
     {
      g_lastRScan = TimeCurrent();
      ProcessClosedPositions();
     }
   if(SelectMyPosition())
      ManagePosition();
   if(!IsHalted())
      CheckEntrySignal();
   static datetime lastPanel = 0;
   datetime m1 = iTime(_Symbol, PERIOD_M1, 0);
   if(m1 != lastPanel)
     {
      lastPanel = m1;
      DrawPanel();
     }
  }

double OnTester()
  {
   // optimisation score: net profit / max equity drawdown (0 when there are too few trades)
   double trades = TesterStatistics(STAT_TRADES);
   double dd = TesterStatistics(STAT_EQUITY_DD);
   if(trades < 20 || dd <= 0.0)
      return 0.0;
   return TesterStatistics(STAT_PROFIT) / dd;
  }
//+------------------------------------------------------------------+
