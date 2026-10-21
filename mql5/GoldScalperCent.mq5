//+------------------------------------------------------------------+
//|                                              GoldScalperCent.mq5 |
//|   XAUUSD intraday scalper for small (cent) accounts, MT5.         |
//|   Risk first: fixed % risk per trade, min-lot risk cap, daily     |
//|   loss stop, loss-streak stop, drawdown risk reduction and an     |
//|   equity hard stop that halts the EA until a human reviews it.    |
//|   No martingale, no grid, no averaging, every trade has a stop.   |
//+------------------------------------------------------------------+
#property copyright "edwardt88/trade"
#property version   "1.00"
#property description "XAUUSD scalper for cent accounts with strict anti-margin-call risk rules."

#include <Trade/Trade.mqh>

//--- server time zone handling (sessions are defined in UTC / London / New York time)
enum ENUM_SERVER_TZ
  {
   TZ_AUTO   = 0,   // Auto (live: server-GMT; tester: uses fixed offset below)
   TZ_FIXED  = 1,   // Fixed offset (hours)
   TZ_NY     = 2    // GMT+2 / GMT+3 with US DST (most MT5 brokers)
  };

//=================================================================== inputs
input group "=== Risk (anti margin call) ==="
input double InpRiskPct            = 2.0;    // Risk per trade (% of equity)
input double InpReducedRiskPct     = 1.0;    // Risk while in drawdown (%)
input double InpDDReducePct        = 10.0;   // Drawdown from peak that switches to reduced risk (%)
input double InpMaxRiskAtMinLotPct = 3.0;    // Skip trade if the minimum lot would risk more than this (%)
input double InpDailyLossPct       = 5.0;    // Stop trading for the day after losing this % of day-start balance
input int    InpMaxTradesPerDay    = 8;      // Max trades per day
input int    InpMaxConsecLosses    = 3;      // Stop for the day after this many losses in a row
input double InpHardStopPct        = 30.0;   // HALT the EA if equity falls this % below the start balance
input double InpStartBalance       = 0.0;    // Start balance for the hard stop (0 = balance when EA first runs)
input bool   InpResetHalt          = false;  // Set true once to clear a HALT after reviewing

input group "=== Execution ==="
input long   InpMagic              = 20261021; // Magic number
input int    InpDeviationPoints    = 30;     // Max slippage (points)
input double InpMaxSpreadPctOfSL   = 15.0;   // Skip entry if spread > this % of stop distance
input int    InpMaxSpreadPoints    = 80;     // Skip entry if spread > this many points (0 = off)

input group "=== Time (all hours are UTC) ==="
input ENUM_SERVER_TZ InpServerTZ   = TZ_AUTO; // Broker server time zone
input int    InpFixedOffsetHours   = 0;      // Server GMT offset for Fixed mode / tester (Exness = 0)
input int    InpFlatHourUTC        = 21;     // Close everything at this UTC hour (rollover)
input int    InpFlatMinuteUTC      = 0;      // ... and minute
input int    InpFridayStopHourUTC  = 19;     // No new trades on Friday from this UTC hour

input group "=== News filter (live only, MT5 economic calendar) ==="
input bool   InpUseNewsFilter      = true;   // Block entries around high-impact USD news
input int    InpNewsMinutesBefore  = 30;     // Minutes before the event
input int    InpNewsMinutesAfter   = 30;     // Minutes after the event
input bool   InpNewsCloseOpen      = false;  // Also close open trades right before high-impact news

input group "=== Logging ==="
input bool   InpWriteCsv           = true;   // Write closed trades to Common/Files/GoldScalperCent_<login>.csv
input bool   InpShowPanel          = true;   // Show status on the chart

//STRATEGY_INPUTS

//=================================================================== globals
CTrade   g_trade;
string   g_gvPrefix;
datetime g_lastSignalBar = 0;
datetime g_lastM1Bar     = 0;
datetime g_newsCacheTime = 0;
datetime g_newsTimes[];
string   g_lastSkip      = "";

//+------------------------------------------------------------------+
//| Time helpers                                                     |
//+------------------------------------------------------------------+
// Nth Sunday (n>=1) of a month, or last Sunday when n==0, as a UTC date (00:00)
datetime NthSunday(const int year, const int month, const int n)
  {
   MqlDateTime d;
   ZeroMemory(d);
   d.year = year;
   d.mon  = month;
   d.day  = 1;
   if(n == 0)
     {
      // last Sunday: start from the first day of the next month and step back
      if(month == 12) { d.year = year + 1; d.mon = 1; }
      else            d.mon = month + 1;
      datetime t = StructToTime(d) - 86400;
      MqlDateTime x;
      TimeToStruct(t, x);
      return t - x.day_of_week * 86400;
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

// UK summer time: last Sunday of March 01:00 UTC .. last Sunday of October 01:00 UTC
bool IsUKDst(const datetime utc)
  {
   MqlDateTime d;
   TimeToStruct(utc, d);
   datetime start = NthSunday(d.year, 3, 0) + 3600;
   datetime end   = NthSunday(d.year, 10, 0) + 3600;
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
      // server = UTC+2 (UTC+3 during US DST); evaluate DST on an approximate UTC time
      datetime approxUtc = TimeTradeServer() - 2 * 3600;
      return (IsUSDst(approxUtc) ? 3 : 2) * 3600;
     }
   long diff = (long)TimeTradeServer() - (long)TimeGMT();
   // round to the nearest 15 minutes
   return (int)(MathRound(diff / 900.0) * 900);
  }

datetime ServerToUtc(const datetime server) { return server - ServerOffsetSeconds(); }
datetime UtcToServer(const datetime utc)    { return utc + ServerOffsetSeconds(); }
datetime NowUtc()                           { return ServerToUtc(TimeTradeServer()); }

int MinuteOfDay(const datetime t)
  {
   MqlDateTime d;
   TimeToStruct(t, d);
   return d.hour * 60 + d.min;
  }

datetime DayStart(const datetime t) { return t - (t % 86400); }

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

double StartBalance()  { return GvGet("start", AccountInfoDouble(ACCOUNT_BALANCE)); }
bool   IsHalted()      { return GvGet("halted", 0.0) > 0.5; }

void UpdatePeak()
  {
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   if(eq > GvGet("peak", 0.0))
      GvSet("peak", eq);
  }

//+------------------------------------------------------------------+
//| Today's realized results for this EA (UTC day)                   |
//+------------------------------------------------------------------+
struct DayStats
  {
   double realized;      // closed P/L today incl. swap and commission
   int    trades;        // trades opened today
   int    consecLosses;  // losses in a row at the end of today's closed trades
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
      if(!g_trade.PositionClose(ticket))
         PrintFormat("Close %I64u (%s) failed: %u %s", ticket, why, g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
      else
         PrintFormat("Closed %I64u: %s", ticket, why);
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

// Money lost (account currency, positive) per 1.0 lot if price moves `dist` against a position
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

// Lots for the given stop distance; 0 when the trade must be skipped
double LotsForRisk(const bool isBuy, const double slDist, double &riskPctUsed)
  {
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double peak   = MathMax(GvGet("peak", equity), equity);
   riskPctUsed   = (equity < peak * (1.0 - InpDDReducePct / 100.0)) ? InpReducedRiskPct : InpRiskPct;
   double riskMoney = equity * riskPctUsed / 100.0;
   double perLot    = LossPerLot(isBuy, slDist + InpDeviationPoints * _Point);
   if(perLot <= 0.0)
     {
      g_lastSkip = "cannot price risk";
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
         g_lastSkip = StringFormat("min lot would risk %.1f%%", minRiskPct);
         return 0.0;
        }
      lots = vmin;
     }
   lots = MathMin(lots, vmax);
   // margin check: never use more than half of free margin
   double price = isBuy ? SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double margin = 0.0;
   if(OrderCalcMargin(isBuy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, _Symbol, lots, price, margin))
     {
      if(margin > AccountInfoDouble(ACCOUNT_MARGIN_FREE) * 0.5)
        {
         g_lastSkip = "not enough free margin";
         return 0.0;
        }
     }
   int digits = (int)MathMax(0, MathCeil(-MathLog10(vstep)));
   return NormalizeDouble(lots, digits);
  }

//+------------------------------------------------------------------+
//| News filter (MT5 economic calendar, live only)                   |
//+------------------------------------------------------------------+
void RefreshNews()
  {
   if(TimeTradeServer() - g_newsCacheTime < 3600 && g_newsCacheTime > 0)
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
      g_newsTimes[n] = values[i].time;  // calendar times are trade-server times
     }
  }

// true if a high-impact USD event is within [-before, +after] minutes of now
bool NewsBlackout(const int before, const int after)
  {
   if(!InpUseNewsFilter || (bool)MQLInfoInteger(MQL_TESTER))
      return false;
   RefreshNews();
   datetime now = TimeTradeServer();
   for(int i = 0; i < ArraySize(g_newsTimes); i++)
     {
      if(now >= g_newsTimes[i] - before * 60 && now <= g_newsTimes[i] + after * 60)
         return true;
     }
   return false;
  }

//STRATEGY_CODE

//+------------------------------------------------------------------+
//| Entry gate: every risk rule in one place                         |
//+------------------------------------------------------------------+
bool CanOpenNewTrade(string &why)
  {
   if(IsHalted())
     {
      why = "HALTED (hard stop) - review, then set InpResetHalt=true";
      return false;
     }
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || !MQLInfoInteger(MQL_TRADE_ALLOWED))
     {
      why = "algo trading disabled";
      return false;
     }
   if(SelectMyPosition())
     {
      why = "position open";
      return false;
     }
   DayStats ds = TodayStats();
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double dayStartBalance = balance - ds.realized;
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
   datetime utc = NowUtc();
   MqlDateTime u;
   TimeToStruct(utc, u);
   int mod = u.hour * 60 + u.min;
   if(mod >= InpFlatHourUTC * 60 + InpFlatMinuteUTC - 5)
     {
      why = "after daily cutoff";
      return false;
     }
   if(u.day_of_week == 5 && u.hour >= InpFridayStopHourUTC)
     {
      why = "Friday cutoff";
      return false;
     }
   if(u.day_of_week == 0 || u.day_of_week == 6)
     {
      why = "weekend";
      return false;
     }
   if(NewsBlackout(InpNewsMinutesBefore, InpNewsMinutesAfter))
     {
      why = "news blackout";
      return false;
     }
   why = "";
   return true;
  }

//+------------------------------------------------------------------+
//| Open a trade with stop/target at exact distances from the fill   |
//+------------------------------------------------------------------+
bool OpenTrade(const bool isBuy, const double slDist, const double tpDist, const string tag)
  {
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double spread = ask - bid;
   if(slDist <= 0.0)
      return false;
   if(spread > slDist * InpMaxSpreadPctOfSL / 100.0 || (InpMaxSpreadPoints > 0 && spread > InpMaxSpreadPoints * _Point))
     {
      g_lastSkip = StringFormat("spread %.2f too wide", spread);
      return false;
     }
   double stopsLevel = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
   if(slDist <= stopsLevel || (tpDist > 0.0 && tpDist <= stopsLevel))
     {
      g_lastSkip = "stop inside broker stops level";
      return false;
     }
   double riskPct = 0.0;
   double lots = LotsForRisk(isBuy, slDist, riskPct);
   if(lots <= 0.0)
      return false;
   double entry = isBuy ? ask : bid;
   double sl = NormPrice(isBuy ? entry - slDist : entry + slDist);
   double tp = (tpDist > 0.0) ? NormPrice(isBuy ? entry + tpDist : entry - tpDist) : 0.0;
   string comment = StringFormat("GSC %s r%.1f", tag, riskPct);
   bool ok = isBuy ? g_trade.Buy(lots, _Symbol, 0.0, sl, tp, comment)
                   : g_trade.Sell(lots, _Symbol, 0.0, sl, tp, comment);
   uint rc = g_trade.ResultRetcode();
   if(!ok || (rc != TRADE_RETCODE_DONE && rc != TRADE_RETCODE_PLACED && rc != TRADE_RETCODE_DONE_PARTIAL))
     {
      PrintFormat("Open %s failed: %u %s", isBuy ? "BUY" : "SELL", rc, g_trade.ResultRetcodeDescription());
      return false;
     }
   // re-anchor stop/target to the actual fill price so distances match the plan exactly
   if(SelectMyPosition())
     {
      double fill = PositionGetDouble(POSITION_PRICE_OPEN);
      double nsl = NormPrice(isBuy ? fill - slDist : fill + slDist);
      double ntp = (tpDist > 0.0) ? NormPrice(isBuy ? fill + tpDist : fill - tpDist) : 0.0;
      if(MathAbs(nsl - PositionGetDouble(POSITION_SL)) >= _Point || MathAbs(ntp - PositionGetDouble(POSITION_TP)) >= _Point)
         g_trade.PositionModify((ulong)PositionGetInteger(POSITION_TICKET), nsl, ntp);
     }
   PrintFormat("%s %.2f lots @ %.2f SL %.2f TP %.2f risk %.1f%% (%s)", isBuy ? "BUY" : "SELL", lots,
               entry, sl, tp, riskPct, tag);
   return true;
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
      PrintFormat("HARD STOP: equity %.2f <= %.0f%% below start balance %.2f. EA halted.", eq, InpHardStopPct, start);
      Alert("GoldScalperCent HALTED: equity hit the hard stop. Review before restarting.");
     }
  }

//+------------------------------------------------------------------+
//| Trade log                                                        |
//+------------------------------------------------------------------+
void LogDeal(const ulong deal)
  {
   if(!InpWriteCsv)
      return;
   if(!HistoryDealSelect(deal))
      return;
   if(HistoryDealGetInteger(deal, DEAL_MAGIC) != InpMagic || HistoryDealGetString(deal, DEAL_SYMBOL) != _Symbol)
      return;
   long entry = HistoryDealGetInteger(deal, DEAL_ENTRY);
   if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_OUT_BY)
      return;
   string file = StringFormat("GoldScalperCent_%I64d.csv", AccountInfoInteger(ACCOUNT_LOGIN));
   int h = FileOpen(file, FILE_READ | FILE_WRITE | FILE_CSV | FILE_COMMON | FILE_SHARE_READ, ',');
   if(h == INVALID_HANDLE)
      return;
   if(FileSize(h) == 0)
      FileWrite(h, "close_time_server", "position", "type", "volume", "price", "profit", "swap", "commission", "reason", "balance_after", "comment");
   FileSeek(h, 0, SEEK_END);
   long reason = HistoryDealGetInteger(deal, DEAL_REASON);
   string r = (reason == DEAL_REASON_SL) ? "SL" : (reason == DEAL_REASON_TP) ? "TP" : (reason == DEAL_REASON_EXPERT) ? "EA" : "OTHER";
   FileWrite(h, TimeToString((datetime)HistoryDealGetInteger(deal, DEAL_TIME), TIME_DATE | TIME_SECONDS),
             HistoryDealGetInteger(deal, DEAL_POSITION_ID),
             (HistoryDealGetInteger(deal, DEAL_TYPE) == DEAL_TYPE_SELL) ? "close_buy" : "close_sell",
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
      LogDeal(trans.deal);
  }

//+------------------------------------------------------------------+
//| Panel                                                            |
//+------------------------------------------------------------------+
void DrawPanel(const string status)
  {
   if(!InpShowPanel)
      return;
   DayStats ds = TodayStats();
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   double peak = MathMax(GvGet("peak", eq), eq);
   double start = StartBalance();
   string s = StringFormat("GoldScalperCent v1.00  |  %s\n", status);
   s += StringFormat("Equity %.2f  Start %.2f  Peak %.2f  DD %.1f%%\n", eq, start, peak, peak > 0 ? (1 - eq / peak) * 100 : 0);
   s += StringFormat("Hard stop at %.2f  %s\n", start * (1 - InpHardStopPct / 100.0), IsHalted() ? "[HALTED]" : "");
   s += StringFormat("Today: P/L %.2f  trades %d/%d  loss streak %d/%d\n", ds.realized + FloatingPnL(), ds.trades, InpMaxTradesPerDay, ds.consecLosses, InpMaxConsecLosses);
   s += StringFormat("Spread %.2f  UTC %s  server offset %+.1fh\n", SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID),
                     TimeToString(NowUtc(), TIME_MINUTES), ServerOffsetSeconds() / 3600.0);
   if(g_lastSkip != "")
      s += "Last skip: " + g_lastSkip + "\n";
   Comment(s);
  }

//+------------------------------------------------------------------+
//| Lifecycle                                                        |
//+------------------------------------------------------------------+
int OnInit()
  {
   g_gvPrefix = StringFormat("GSC_%I64d_%I64d_%s_", AccountInfoInteger(ACCOUNT_LOGIN), InpMagic, _Symbol);
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
   g_trade.SetDeviationInPoints((ulong)InpDeviationPoints);
   g_trade.SetTypeFillingBySymbol(_Symbol);
   g_trade.SetAsyncMode(false);
   if(!StrategyInit())
      return INIT_FAILED;
   PrintFormat("GoldScalperCent started on %s. Start balance %.2f, hard stop %.2f, server offset %+.1fh",
               _Symbol, StartBalance(), StartBalance() * (1 - InpHardStopPct / 100.0), ServerOffsetSeconds() / 3600.0);
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

   // daily / Friday flat time and news protection for open trades
   if(SelectMyPosition())
     {
      MqlDateTime u;
      TimeToStruct(NowUtc(), u);
      int mod = u.hour * 60 + u.min;
      if(mod >= InpFlatHourUTC * 60 + InpFlatMinuteUTC - 5 || (u.day_of_week == 5 && mod >= InpFlatHourUTC * 60 - 65))
         CloseAll("daily flat time");
      else if(InpNewsCloseOpen && NewsBlackout(2, 0))
         CloseAll("high-impact news");
      else
         ManagePosition();
     }

   string why = "";
   bool can = CanOpenNewTrade(why);
   StrategyOnTick(can);
   DrawPanel(can ? "ready" : why);
  }

double OnTester()
  {
   // custom optimisation score: net profit / max equity drawdown, 0 when too few trades
   double trades = TesterStatistics(STAT_TRADES);
   double dd = TesterStatistics(STAT_EQUITY_DD);
   if(trades < 30 || dd <= 0.0)
      return 0.0;
   return TesterStatistics(STAT_PROFIT) / dd;
  }
//+------------------------------------------------------------------+
