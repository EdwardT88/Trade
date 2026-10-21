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
//|   Risk first: fixed % risk per trade, min-lot risk cap, daily    |
//|   loss stop, loss-streak stop, drawdown risk reduction and an    |
//|   equity hard stop that halts the EA until a human reviews it.   |
//|   No martingale, no grid, no averaging, every trade has a stop.  |
//+------------------------------------------------------------------+
#property copyright "edwardt88/trade"
#property version   "1.00"
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
input int        InpMaxHoldDays        = 10;         // Close a position after this many days
input bool       InpFridayClose        = true;       // Close everything on Friday (no weekend gaps)
input int        InpFridayCloseHourUTC = 20;         // ... at this UTC hour
input int        InpFridayLastEntryUTC = 12;         // No new entries on Friday from this UTC hour
input int        InpNoEntryFromUTC     = 21;         // No new entries from this UTC hour (rollover/reopen spreads) ...
input int        InpNoEntryToUTC       = 24;         // ... until this UTC hour (24 = midnight)
input int        InpMaxEntryDelayMin   = 5;          // Skip a signal if the first tick arrives this late after the H1 close

input group "=== Risk (anti margin call) ==="
input double InpRiskPct            = 2.0;    // Risk per trade (% of equity)
input double InpReducedRiskPct     = 1.0;    // Risk while in drawdown (%)
input double InpDDReducePct        = 10.0;   // Drawdown from peak equity that switches to reduced risk (%)
input double InpMaxRiskAtMinLotPct = 3.0;    // Skip the trade if the minimum lot would risk more than this (%)
input double InpDailyLossPct       = 5.0;    // No new trades for the day after losing this % (closed + floating)
input int    InpMaxTradesPerDay    = 4;      // Max new trades per UTC day
input int    InpMaxConsecLosses    = 3;      // No new trades for the day after this many losses in a row
input double InpHardStopPct        = 30.0;   // HALT the EA if equity falls this % below the start balance
input double InpStartBalance       = 0.0;    // Start balance for the hard stop (0 = balance when the EA first runs)
input bool   InpResetHalt          = false;  // Set true once to clear a HALT after reviewing, then back to false

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
input bool   InpUseNewsFilter      = true;   // Block new entries around high-impact USD news
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
datetime NowUtc()                           { return ServerToUtc(TimeTradeServer()); }
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

void GvSet(const string key, const double value) { GlobalVariableSet(g_gvPrefix + key, value); }
void GvDel(const string key)                     { GlobalVariableDel(g_gvPrefix + key); }

double StartBalance() { return GvGet("start", AccountInfoDouble(ACCOUNT_BALANCE)); }
bool   IsHalted()     { return GvGet("halted", 0.0) > 0.5; }

void UpdatePeak()
  {
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   if(eq > GvGet("peak", 0.0))
      GvSet("peak", eq);
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
         PrintFormat("Closed #%I64u: %s", ticket, why);
      else
         PrintFormat("Close #%I64u (%s) failed: %u %s", ticket, why, g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
     }
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

// Lots for the given stop distance; 0 when the trade must be skipped
double LotsForRisk(const bool isBuy, const double slDist, double &riskPctUsed)
  {
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double peak   = MathMax(GvGet("peak", equity), equity);
   riskPctUsed   = (equity < peak * (1.0 - InpDDReducePct / 100.0)) ? InpReducedRiskPct : InpRiskPct;
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
   if(OrderCalcMargin(isBuy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, _Symbol, lots, price, margin)
      && margin > AccountInfoDouble(ACCOUNT_MARGIN_FREE) * 0.5)
     {
      g_lastSkip = "not enough free margin";
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
   g_newsCacheTime = TimeTradeServer();
   ArrayResize(g_newsTimes, 0);
   MqlCalendarValue values[];
   datetime from = TimeTradeServer() - 2 * 3600;
   datetime to   = TimeTradeServer() + 36 * 3600;
   if(CalendarValueHistory(values, from, to, NULL, "USD") <= 0)
      return;
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
   MqlDateTime u;
   TimeToStruct(NowUtc(), u);
   if(u.day_of_week == 0 || u.day_of_week == 6)
     {
      why = "weekend";
      return false;
     }
   if(u.hour >= InpNoEntryFromUTC && u.hour < InpNoEntryToUTC)
     {
      why = "rollover hours";
      return false;
     }
   if(InpFridayClose && u.day_of_week == 5 && u.hour >= InpFridayLastEntryUTC)
     {
      why = "Friday cutoff";
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
bool OpenTrade(const bool isBuy, const double slDist, const double trailDist, const string tag)
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
   double lots = LotsForRisk(isBuy, slDist, riskPct);
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
   if(SelectMyPosition())
     {
      long posId = PositionGetInteger(POSITION_IDENTIFIER);
      ulong ticket = (ulong)PositionGetInteger(POSITION_TICKET);
      double fill = PositionGetDouble(POSITION_PRICE_OPEN);
      // re-anchor the stop to the actual fill so the distance matches the plan exactly
      double nsl = NormPrice(isBuy ? fill - slDist : fill + slDist);
      if(MathAbs(nsl - PositionGetDouble(POSITION_SL)) >= _Point)
         if(!g_trade.PositionModify(ticket, nsl, 0.0))
            PrintFormat("Stop re-anchor failed (kept %.2f): %u %s", PositionGetDouble(POSITION_SL),
                        g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
      if(trailDist > 0.0)
         GvSet(StringFormat("trail_%I64d", posId), trailDist);
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

// +1 uptrend, -1 downtrend, 0 none, using the last completed H4 bar
int H4Trend()
  {
   double ema[];
   ArraySetAsSeries(ema, true);
   int need = InpTrendSlopeBars + 1;
   if(CopyBuffer(g_hEma, 0, 1, need, ema) != need)
      return 0;
   double c1 = iClose(_Symbol, PERIOD_H4, 1);
   if(c1 <= 0.0)
      return 0;
   if(c1 > ema[0] && ema[0] > ema[InpTrendSlopeBars])
      return 1;
   if(c1 < ema[0] && ema[0] < ema[InpTrendSlopeBars])
      return -1;
   return 0;
  }

// Called on every tick; acts only on the first tick of a new H1 bar
void CheckEntrySignal()
  {
   datetime h1 = iTime(_Symbol, PERIOD_H1, 0);
   if(h1 == 0 || h1 == g_lastH1Bar)
      return;
   g_lastH1Bar = h1;

   double rsi[];
   ArraySetAsSeries(rsi, true);
   if(CopyBuffer(g_hRsi, 0, 1, 2, rsi) != 2)
      return;
   int trend = H4Trend();
   double lo = InpRsiLevel;
   double hi = 100.0 - InpRsiLevel;
   bool longSig  = (trend > 0) && (rsi[1] < lo) && (rsi[0] >= lo) && InpSides != SIDES_SHORT;
   bool shortSig = (trend < 0) && (rsi[1] > hi) && (rsi[0] <= hi) && InpSides != SIDES_LONG;
   if(!longSig && !shortSig)
      return;
   g_lastSignal = StringFormat("%s %s RSI %.1f->%.1f", TimeToString(h1, TIME_DATE | TIME_MINUTES),
                               longSig ? "LONG" : "SHORT", rsi[1], rsi[0]);

   // the backtest fills right after the H1 close; skip stale signals (weekend, daily break, data holes)
   if(TimeCurrent() - h1 > InpMaxEntryDelayMin * 60)
     {
      g_lastSkip = "signal too late after the H1 close";
      return;
     }
   string why = "";
   if(!CanOpenNewTrade(why))
     {
      g_lastSkip = "signal skipped: " + why;
      return;
     }
   double atr[];
   if(CopyBuffer(g_hAtr, 0, 1, 1, atr) != 1 || atr[0] <= 0.0)
      return;
   double slDist    = InpStopATR * atr[0];
   double trailDist = InpTrailATR * atr[0];
   OpenTrade(longSig, slDist, trailDist, longSig ? "pb-long" : "pb-short");
  }

// Time exits and the chandelier trailing stop (stop updates once per closed M1 bar, like the backtest)
void ManagePosition()
  {
   if(!SelectMyPosition())
      return;
   ulong    ticket = (ulong)PositionGetInteger(POSITION_TICKET);
   long     posId  = PositionGetInteger(POSITION_IDENTIFIER);
   datetime opened = (datetime)PositionGetInteger(POSITION_TIME);
   bool     isBuy  = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
   double   curSL  = PositionGetDouble(POSITION_SL);

   MqlDateTime u;
   TimeToStruct(NowUtc(), u);
   if(InpFridayClose && u.day_of_week == 5 && u.hour >= InpFridayCloseHourUTC)
     {
      CloseAll("Friday close");
      return;
     }
   if(InpMaxHoldDays > 0 && TimeCurrent() - opened >= InpMaxHoldDays * 86400)
     {
      CloseAll("max hold time");
      return;
     }

   datetime m1 = iTime(_Symbol, PERIOD_M1, 0);
   if(m1 == 0 || m1 == g_lastM1Bar)
      return;
   g_lastM1Bar = m1;

   double trail = GvGet(StringFormat("trail_%I64d", posId), 0.0);
   if(trail <= 0.0)
      return;
   int shiftOpen = iBarShift(_Symbol, PERIOD_M1, opened, false);
   if(shiftOpen < 1)
      return;   // no closed M1 bar since the entry yet
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   long stopsLevel  = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   long freezeLevel = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL);
   double minGap = (double)(stopsLevel > freezeLevel ? stopsLevel : freezeLevel) * _Point;
   double tick = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick <= 0.0)
      tick = _Point;
   double newSL;
   if(isBuy)
     {
      int idx = iHighest(_Symbol, PERIOD_M1, MODE_HIGH, shiftOpen, 1);
      if(idx < 0)
         return;
      newSL = NormPrice(iHigh(_Symbol, PERIOD_M1, idx) - trail);
      if(newSL <= curSL + tick)
         return;
      if(newSL >= bid)
        {
         CloseAll("trailing stop crossed");
         return;
        }
      if(bid - newSL <= minGap)
         return;   // too close to price for the broker; try again on the next bar
     }
   else
     {
      int idx = iLowest(_Symbol, PERIOD_M1, MODE_LOW, shiftOpen, 1);
      if(idx < 0)
         return;
      newSL = NormPrice(iLow(_Symbol, PERIOD_M1, idx) + (ask - bid) + trail);
      if(curSL > 0.0 && newSL >= curSL - tick)
         return;
      if(newSL <= ask)
        {
         CloseAll("trailing stop crossed");
         return;
        }
      if(newSL - ask <= minGap)
         return;
     }
   if(!g_trade.PositionModify(ticket, newSL, PositionGetDouble(POSITION_TP)))
      PrintFormat("Trail modify failed: %u %s", g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
  }

//+------------------------------------------------------------------+
//| Hard stop                                                        |
//+------------------------------------------------------------------+
void CheckHardStop()
  {
   double start = StartBalance();
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   if(!IsHalted() && eq <= start * (1.0 - InpHardStopPct / 100.0))
     {
      GvSet("halted", 1.0);
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
   long posId = HistoryDealGetInteger(deal, DEAL_POSITION_ID);
   if(!SelectMyPosition())
      GvDel(StringFormat("trail_%I64d", posId));
   if(!InpWriteCsv)
      return;
   string file = StringFormat("GoldSwingCent_%I64d.csv", AccountInfoInteger(ACCOUNT_LOGIN));
   int h = FileOpen(file, FILE_READ | FILE_WRITE | FILE_CSV | FILE_COMMON | FILE_SHARE_READ, ',');
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

void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &request, const MqlTradeResult &result)
  {
   if(trans.type == TRADE_TRANSACTION_DEAL_ADD && trans.deal > 0)
      OnClosedDeal(trans.deal);
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
   string s = StringFormat("GoldSwingCent v1.00  |  %s\n", can ? "waiting for a signal" : why);
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
int OnInit()
  {
   g_gvPrefix = StringFormat("GSW_%I64d_%I64d_%s_", AccountInfoInteger(ACCOUNT_LOGIN), InpMagic, _Symbol);
   if((bool)MQLInfoInteger(MQL_TESTER))
     {
      // fresh state for every tester pass
      GlobalVariablesDeleteAll(g_gvPrefix);
     }
   if(!GlobalVariableCheck(g_gvPrefix + "start") || InpStartBalance > 0.0)
      GvSet("start", InpStartBalance > 0.0 ? InpStartBalance : AccountInfoDouble(ACCOUNT_BALANCE));
   if(InpResetHalt)
     {
      GvSet("halted", 0.0);
      GvSet("peak", AccountInfoDouble(ACCOUNT_EQUITY));
      Print("Halt flag cleared and peak equity reset.");
     }
   UpdatePeak();
   g_trade.SetExpertMagicNumber((ulong)InpMagic);
   g_trade.SetDeviationInPoints((ulong)MathMax(1.0, MathRound(InpMaxSlippageUSD / _Point)));
   g_trade.SetTypeFillingBySymbol(_Symbol);
   g_trade.SetAsyncMode(false);
   if(!StrategyInit())
      return INIT_FAILED;
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
   UpdatePeak();
   CheckHardStop();
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
