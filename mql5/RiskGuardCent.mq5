//+------------------------------------------------------------------+
//|                                                RiskGuardCent.mq5 |
//|   Risk guard + one-click lot calculator for MANUAL trading on    |
//|   small (cent) accounts. It does not trade on its own.           |
//|                                                                  |
//|   Panel: drag the red SL line, press BUY/SELL -> the lot is      |
//|   sized so that hitting the stop loses exactly the chosen risk.  |
//|                                                                  |
//|   Guard (works for trades opened anywhere: PC, phone, panel):    |
//|   - every position must have a stop loss (emergency stop / close)|
//|   - risk per position capped (volume reduced, stop tightened)    |
//|   - total open risk, max open positions, max trades per day      |
//|   - daily loss limit and loss streak -> locked until tomorrow    |
//|   - cooldown after a loss (anti revenge trading)                 |
//|   - equity hard stop -> everything closed and locked             |
//|   While locked, any new position is closed immediately.          |
//|   The guard only works while this terminal is running.           |
//+------------------------------------------------------------------+
#property copyright "edwardt88/trade"
#property version   "1.00"
#property description "Risk guard + lot calculator for manual trading on cent accounts (no automatic entries)."

#include <Trade/Trade.mqh>

enum ENUM_NO_SL_ACTION
  {
   NOSL_SET   = 0, // Set an emergency stop at the max risk
   NOSL_CLOSE = 1  // Close the position
  };

//=================================================================== inputs
input group "=== Risk per trade ==="
input double InpRiskPct             = 1.0;   // Risk per trade for the BUY/SELL buttons (%)
input double InpMaxRiskPerTradePct  = 2.0;   // Max risk of any position (%); bigger ones are cut down
input double InpMaxOpenRiskPct      = 4.0;   // Max total risk of all open positions (%)
input int    InpMaxPositions        = 2;     // Max open positions at the same time
input ENUM_NO_SL_ACTION InpNoSLAction = NOSL_SET; // What to do with a position without stop loss
input int    InpNoSLGraceSec        = 30;    // Seconds you have to add a stop loss yourself
input double InpDefaultRR           = 2.0;   // TP line = this x the SL distance (0 = no TP line)
input double InpSLDefaultATR        = 1.5;   // New SL line = this x ATR(14) of the chart timeframe

input group "=== Daily limits ==="
input double InpDailyLossPct        = 5.0;   // Lock for the day after losing this % (closed + floating)
input int    InpMaxTradesPerDay     = 6;     // Max new positions per day
input int    InpMaxConsecLosses     = 3;     // Lock for the day after this many losses in a row
input int    InpCooldownMin         = 15;    // Minutes without new trades after a losing trade (0 = off)
input int    InpDayStartHourServer  = 0;     // Server hour when a new trading day starts

input group "=== Hard stop ==="
input double InpHardStopPct         = 30.0;  // Close all and HALT if equity falls this % below the start balance
input double InpStartBalance        = 0.0;   // Start balance in ACCOUNT currency (cent: USC, $50 = 5000). 0 = balance at first run
input bool   InpResetHalt           = false; // Set true once to clear a HALT (start = current balance), then back to false

input group "=== Scope ==="
input bool   InpGuardAllSymbols     = true;  // Guard positions on all symbols (false = this chart's symbol only)
input bool   InpManualOnly          = true;  // Per-position rules touch only manual positions (magic 0); limits count all
input bool   InpCloseAllOnLock      = true;  // Close open positions when the daily loss limit locks the account
input bool   InpFridayCloseAll      = false; // Close all guarded positions on Friday ...
input int    InpFridayCloseHourSrv  = 22;    // ... at this server hour

input group "=== Panel ==="
input int    InpPanelX              = 10;    // Panel X (pixels)
input int    InpPanelY              = 25;    // Panel Y (pixels)
input bool   InpWriteLog            = true;  // Log every action to Common/Files/RiskGuard_<login>.log

//=================================================================== constants / globals
#define PFX       "RG_"
#define SL_LINE   "RG_SL_LINE"
#define TP_LINE   "RG_TP_LINE"
#define BTN_SL    "RG_BTN_SL"
#define BTN_BUY   "RG_BTN_BUY"
#define BTN_SELL  "RG_BTN_SELL"
#define BTN_CLOSE "RG_BTN_CLOSE"
#define EDT_RISK  "RG_EDT_RISK"
#define LBL       "RG_LBL_"
#define N_LINES   12

struct PosInfo
  {
   ulong             ticket;
   long              posId;
   string            sym;
   long              magic;
   bool              buy;
   double            vol;
   double            open;
   double            sl;
   double            tp;
   datetime          time;
   double            risk;     // money lost at the stop from the open price; -1 = no stop
  };

struct PosState
  {
   long              posId;
   datetime          noSLSince;
   bool              entryChecked;
   datetime          lastAction;
  };

struct DayStats
  {
   double            realized;
   int               entries;        // new positions today (counted per rules scope)
   int               consecLosses;
   datetime          lastLossTime;
  };

CTrade   g_trade;
string   g_gv;
int      g_hAtr = INVALID_HANDLE;
PosState g_state[];
double   g_riskPct = 1.0;
bool     g_tpMoved = false;
datetime g_closeArm = 0;
string   g_lastMsg = "";

//+------------------------------------------------------------------+
//| Small helpers                                                    |
//+------------------------------------------------------------------+
double GvGet(const string key, const double def)
  {
   string name = g_gv + key;
   return GlobalVariableCheck(name) ? GlobalVariableGet(name) : def;
  }

void GvSet(const string key, const double v)
  {
   if(GlobalVariableSet(g_gv + key, v) == 0)
      PrintFormat("GlobalVariableSet(%s) failed: %d", g_gv + key, GetLastError());
  }

void GvSetFlush(const string key, const double v)
  {
   GvSet(key, v);
   GlobalVariablesFlush();
  }

string Ccy() { return AccountInfoString(ACCOUNT_CURRENCY); }

void Log(const string msg)
  {
   g_lastMsg = msg;
   Print("RiskGuard: ", msg);
   if(!InpWriteLog || (bool)MQLInfoInteger(MQL_TESTER))
      return;
   string file = StringFormat("RiskGuard_%I64d.log", AccountInfoInteger(ACCOUNT_LOGIN));
   int h = FileOpen(file, FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON | FILE_SHARE_READ);
   if(h == INVALID_HANDLE)
      return;
   FileSeek(h, 0, SEEK_END);
   FileWriteString(h, TimeToString(TimeTradeServer(), TIME_DATE | TIME_SECONDS) + "  " + msg + "\r\n");
   FileClose(h);
  }

double StartBalance()
  {
   double v = GvGet("start", 0.0);
   return (v > 0.0) ? v : AccountInfoDouble(ACCOUNT_BALANCE);
  }

bool InScope(const string sym) { return InpGuardAllSymbols || sym == _Symbol; }
bool Controlled(const long magic) { return !InpManualOnly || magic == 0; }

// trading day (server time, starting at InpDayStartHourServer)
long DayKey(const datetime t)              { return ((long)t - InpDayStartHourServer * 3600) / 86400; }
datetime DayStartTime(const datetime t)    { return (datetime)(DayKey(t) * 86400 + InpDayStartHourServer * 3600); }
datetime NextDayStart()                    { return DayStartTime(TimeTradeServer()) + 86400; }

//+------------------------------------------------------------------+
//| Lock / halt state                                                |
//+------------------------------------------------------------------+
bool IsHalted()    { return GvGet("halted", 0.0) > 0.5; }
bool IsDayLocked() { return (long)GvGet("lock_day", -1.0) == DayKey(TimeTradeServer()); }

string LockReason()
  {
   int code = (int)GvGet("lock_reason", 0.0);
   if(code == 1)
      return "daily loss limit";
   if(code == 2)
      return "loss streak limit";
   return "locked";
  }

void LockDay(const int reasonCode, const string why)
  {
   if(IsDayLocked())
      return;
   GvSet("lock_day", (double)DayKey(TimeTradeServer()));
   GvSet("lock_time", (double)TimeTradeServer());
   GvSetFlush("lock_reason", (double)reasonCode);
   Log("LOCKED for today: " + why);
   Alert("RiskGuard: trading LOCKED until the next day (" + why + ").");
  }

// time after which new positions are refused (0 = not locked)
datetime LockedSince()
  {
   if(IsHalted())
      return (datetime)GvGet("halt_time", 1.0);
   if(IsDayLocked())
      return (datetime)GvGet("lock_time", 1.0);
   return 0;
  }

//+------------------------------------------------------------------+
//| Positions                                                        |
//+------------------------------------------------------------------+
double LossMoney(const string sym, const bool buy, const double vol, const double from, const double to)
  {
   double profit = 0.0;
   if(!OrderCalcProfit(buy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, sym, vol, from, to, profit))
      return -1.0;
   return (profit < 0.0) ? -profit : 0.0;
  }

int Snapshot(PosInfo &out[])
  {
   ArrayResize(out, 0);
   int total = PositionsTotal();
   for(int i = total - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      string sym = PositionGetString(POSITION_SYMBOL);
      if(!InScope(sym))
         continue;
      PosInfo p;
      p.ticket = ticket;
      p.posId  = PositionGetInteger(POSITION_IDENTIFIER);
      p.sym    = sym;
      p.magic  = PositionGetInteger(POSITION_MAGIC);
      p.buy    = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
      p.vol    = PositionGetDouble(POSITION_VOLUME);
      p.open   = PositionGetDouble(POSITION_PRICE_OPEN);
      p.sl     = PositionGetDouble(POSITION_SL);
      p.tp     = PositionGetDouble(POSITION_TP);
      p.time   = (datetime)PositionGetInteger(POSITION_TIME);
      p.risk   = -1.0;
      int n = ArraySize(out);
      ArrayResize(out, n + 1);
      out[n] = p;
     }
   for(int k = 0; k < ArraySize(out); k++)
      if(out[k].sl > 0.0)
         out[k].risk = LossMoney(out[k].sym, out[k].buy, out[k].vol, out[k].open, out[k].sl);
   return ArraySize(out);
  }

int StateIndex(const long posId, const bool create)
  {
   for(int i = 0; i < ArraySize(g_state); i++)
      if(g_state[i].posId == posId)
         return i;
   if(!create)
      return -1;
   int n = ArraySize(g_state);
   ArrayResize(g_state, n + 1);
   g_state[n].posId = posId;
   g_state[n].noSLSince = 0;
   g_state[n].entryChecked = false;
   g_state[n].lastAction = 0;
   return n;
  }

void PruneStates(const PosInfo &pos[])
  {
   for(int i = ArraySize(g_state) - 1; i >= 0; i--)
     {
      bool alive = false;
      for(int k = 0; k < ArraySize(pos); k++)
         if(pos[k].posId == g_state[i].posId)
           {
            alive = true;
            break;
           }
      if(!alive)
        {
         int last = ArraySize(g_state) - 1;
         g_state[i] = g_state[last];
         ArrayResize(g_state, last);
        }
     }
  }

bool ClosePos(const PosInfo &p, const string why)
  {
   g_trade.SetTypeFillingBySymbol(p.sym);
   if(g_trade.PositionClose(p.ticket))
     {
      Log(StringFormat("CLOSED %s %s %.2f lots (#%I64u): %s", p.sym, p.buy ? "BUY" : "SELL", p.vol, p.ticket, why));
      return true;
     }
   Log(StringFormat("Close #%I64u failed (%s): %u %s", p.ticket, why, g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription()));
   return false;
  }

void CloseAllGuarded(const string why)
  {
   PosInfo pos[];
   Snapshot(pos);
   for(int k = 0; k < ArraySize(pos); k++)
      ClosePos(pos[k], why);
  }

// throttle: at most one corrective action per position every 3 seconds
bool MayAct(const long posId)
  {
   int i = StateIndex(posId, true);
   if(TimeLocal() - g_state[i].lastAction < 3)
      return false;
   g_state[i].lastAction = TimeLocal();
   return true;
  }

//+------------------------------------------------------------------+
//| Today's statistics from the deal history                         |
//+------------------------------------------------------------------+
DayStats TodayStats()
  {
   DayStats s;
   s.realized = 0.0;
   s.entries = 0;
   s.consecLosses = 0;
   s.lastLossTime = 0;
   if(!HistorySelect(DayStartTime(TimeTradeServer()), TimeTradeServer() + 60))
      return s;
   int total = HistoryDealsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong d = HistoryDealGetTicket(i);
      if(d == 0)
         continue;
      long type = HistoryDealGetInteger(d, DEAL_TYPE);
      if(type != DEAL_TYPE_BUY && type != DEAL_TYPE_SELL)
         continue;
      if(!InScope(HistoryDealGetString(d, DEAL_SYMBOL)))
         continue;
      long entry = HistoryDealGetInteger(d, DEAL_ENTRY);
      double money = HistoryDealGetDouble(d, DEAL_PROFIT) + HistoryDealGetDouble(d, DEAL_SWAP)
                     + HistoryDealGetDouble(d, DEAL_COMMISSION);
      if(entry == DEAL_ENTRY_IN)
        {
         s.realized += HistoryDealGetDouble(d, DEAL_COMMISSION);
         if(Controlled(HistoryDealGetInteger(d, DEAL_MAGIC)))
            s.entries++;
         continue;
        }
      s.realized += money;
      if(money < 0.0)
        {
         s.consecLosses++;
         s.lastLossTime = (datetime)HistoryDealGetInteger(d, DEAL_TIME);
        }
      else
         s.consecLosses = 0;
     }
   return s;
  }

double FloatingPnL(const PosInfo &pos[])
  {
   double sum = 0.0;
   for(int k = 0; k < ArraySize(pos); k++)
      if(PositionSelectByTicket(pos[k].ticket))
         sum += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
   return sum;
  }

datetime CooldownUntil(const DayStats &ds)
  {
   if(InpCooldownMin <= 0 || ds.lastLossTime == 0)
      return 0;
   datetime until = ds.lastLossTime + InpCooldownMin * 60;
   return (until > TimeTradeServer()) ? until : 0;
  }

//+------------------------------------------------------------------+
//| Corrective actions on one position                               |
//+------------------------------------------------------------------+
double MaxRiskMoney() { return AccountInfoDouble(ACCOUNT_EQUITY) * InpMaxRiskPerTradePct / 100.0; }

// stop price at which `p` loses exactly `money`; 0 if it cannot be computed
double StopForMoney(const PosInfo &p, const double money)
  {
   double point = SymbolInfoDouble(p.sym, SYMBOL_POINT);
   if(point <= 0.0)
      return 0.0;
   double probe = 1000.0 * point;
   double lossProbe = LossMoney(p.sym, p.buy, p.vol, p.open, p.buy ? p.open - probe : p.open + probe);
   if(lossProbe <= 0.0)
      return 0.0;
   double dist = money / (lossProbe / probe);
   int digits = (int)SymbolInfoInteger(p.sym, SYMBOL_DIGITS);
   return NormalizeDouble(p.buy ? p.open - dist : p.open + dist, digits);
  }

// true if `sl` can be placed now for `p` (on the correct side of price, outside the stops/freeze levels)
bool StopPlaceable(const PosInfo &p, const double sl)
  {
   double point = SymbolInfoDouble(p.sym, SYMBOL_POINT);
   long stops  = SymbolInfoInteger(p.sym, SYMBOL_TRADE_STOPS_LEVEL);
   long freeze = SymbolInfoInteger(p.sym, SYMBOL_TRADE_FREEZE_LEVEL);
   double gap = (double)(stops > freeze ? stops : freeze) * point;
   if(p.buy)
      return sl > 0.0 && sl < SymbolInfoDouble(p.sym, SYMBOL_BID) - gap;
   return sl > SymbolInfoDouble(p.sym, SYMBOL_ASK) + gap;
  }

void SetEmergencyStop(const PosInfo &p)
  {
   double sl = StopForMoney(p, MaxRiskMoney());
   if(InpNoSLAction == NOSL_CLOSE || sl <= 0.0 || !StopPlaceable(p, sl))
     {
      ClosePos(p, "no stop loss");
      return;
     }
   g_trade.SetTypeFillingBySymbol(p.sym);
   if(g_trade.PositionModify(p.ticket, sl, p.tp))
      Log(StringFormat("Emergency STOP set on %s #%I64u at %s (risk %.1f%%)", p.sym, p.ticket,
                       DoubleToString(sl, (int)SymbolInfoInteger(p.sym, SYMBOL_DIGITS)), InpMaxRiskPerTradePct));
   else
      Log(StringFormat("Emergency stop on #%I64u failed: %u %s", p.ticket, g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription()));
  }

// position risks more than allowed: reduce volume, else tighten the stop, else close
void CutRisk(const PosInfo &p)
  {
   double allowed = MaxRiskMoney();
   double vmin  = SymbolInfoDouble(p.sym, SYMBOL_VOLUME_MIN);
   double vstep = SymbolInfoDouble(p.sym, SYMBOL_VOLUME_STEP);
   if(vstep <= 0.0)
      vstep = vmin;
   if(p.risk > 0.0 && vstep > 0.0 && p.vol > 0.0)
     {
      double perLot = p.risk / p.vol;
      double keep = MathFloor(allowed / perLot / vstep + 1e-9) * vstep;
      if(keep >= vmin && keep < p.vol)
        {
         double cut = NormalizeDouble(p.vol - keep, 8);
         g_trade.SetTypeFillingBySymbol(p.sym);
         if(g_trade.PositionClosePartial(p.ticket, cut))
           {
            Log(StringFormat("Volume CUT on %s #%I64u: %.2f -> %.2f lots (risk was %.2f %s, max %.2f)", p.sym, p.ticket,
                             p.vol, keep, p.risk, Ccy(), allowed));
            return;
           }
         Log(StringFormat("Partial close #%I64u failed: %u %s", p.ticket, g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription()));
        }
     }
   double sl = StopForMoney(p, allowed);
   if(sl > 0.0 && StopPlaceable(p, sl))
     {
      g_trade.SetTypeFillingBySymbol(p.sym);
      if(g_trade.PositionModify(p.ticket, sl, p.tp))
        {
         Log(StringFormat("Stop TIGHTENED on %s #%I64u to %s (risk was %.2f %s, max %.2f)", p.sym, p.ticket,
                          DoubleToString(sl, (int)SymbolInfoInteger(p.sym, SYMBOL_DIGITS)), p.risk, Ccy(), allowed));
         return;
        }
     }
   ClosePos(p, StringFormat("risk %.2f %s above the max %.2f and could not be reduced", p.risk, Ccy(), allowed));
  }

//+------------------------------------------------------------------+
//| The guard: runs every second and after every trade event         |
//+------------------------------------------------------------------+
void Guard()
  {
   PosInfo pos[];
   Snapshot(pos);
   PruneStates(pos);
   DayStats ds = TodayStats();
   double equity  = AccountInfoDouble(ACCOUNT_EQUITY);
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   datetime now   = TimeTradeServer();

   // 1) hard stop
   if(!IsHalted() && GvGet("start", 0.0) > 0.0 && equity <= StartBalance() * (1.0 - InpHardStopPct / 100.0))
     {
      GvSet("halt_time", (double)now);
      GvSetFlush("halted", 1.0);
      Log(StringFormat("HARD STOP: equity %.2f is %.0f%% below the start balance %.2f. Everything closed, trading halted.",
                       equity, InpHardStopPct, StartBalance()));
      Alert("RiskGuard HALTED: equity hit the hard stop. Review before trading again.");
     }
   if(IsHalted())
     {
      for(int k = 0; k < ArraySize(pos); k++)
         if(MayAct(pos[k].posId))
            ClosePos(pos[k], "account HALTED (hard stop)");
      return;
     }

   // 2) daily loss limit and loss streak
   double dayStart = balance - ds.realized;
   if(dayStart > 0.0 && ds.realized + FloatingPnL(pos) <= -InpDailyLossPct / 100.0 * dayStart)
     {
      if(!IsDayLocked())
        {
         LockDay(1, StringFormat("daily loss %.2f %s reached the %.1f%% limit", ds.realized + FloatingPnL(pos), Ccy(), InpDailyLossPct));
         if(InpCloseAllOnLock)
            for(int k = 0; k < ArraySize(pos); k++)
               ClosePos(pos[k], "daily loss limit");
         return;
        }
     }
   if(ds.consecLosses >= InpMaxConsecLosses)
      LockDay(2, StringFormat("%d losses in a row", ds.consecLosses));

   // 3) Friday close
   if(InpFridayCloseAll)
     {
      MqlDateTime t;
      TimeToStruct(now, t);
      if(t.day_of_week == 5 && t.hour >= InpFridayCloseHourSrv)
         for(int k = 0; k < ArraySize(pos); k++)
            if(MayAct(pos[k].posId))
               ClosePos(pos[k], "Friday close");
     }

   datetime lockedSince = LockedSince();
   datetime cooldown = CooldownUntil(ds);
   double maxOpen = equity * InpMaxOpenRiskPct / 100.0;

   // 4) rules for newly opened positions (oldest first, so the newest ones are the ones refused)
   int order[];
   ArrayResize(order, ArraySize(pos));
   for(int k = 0; k < ArraySize(pos); k++)
      order[k] = k;
   for(int a = 0; a < ArraySize(order); a++)
      for(int b = a + 1; b < ArraySize(order); b++)
         if(pos[order[b]].time < pos[order[a]].time)
           {
            int tmp = order[a];
            order[a] = order[b];
            order[b] = tmp;
           }
   // entries today that are already settled (closed, or open and already accepted)
   int newToday = 0;
   datetime dayStartT = DayStartTime(now);
   for(int k = 0; k < ArraySize(pos); k++)
     {
      int si0 = StateIndex(pos[k].posId, false);
      if(Controlled(pos[k].magic) && pos[k].time >= dayStartT && (si0 < 0 || !g_state[si0].entryChecked))
         newToday++;
     }
   int entriesSoFar = ds.entries - newToday;
   int kept = 0;
   double keptRisk = 0.0;
   for(int o = 0; o < ArraySize(order); o++)
     {
      PosInfo p = pos[order[o]];
      int si = StateIndex(p.posId, true);
      double r = (p.risk >= 0.0) ? p.risk : MaxRiskMoney();   // a position without a stop counts at the max
      if(g_state[si].entryChecked || !Controlled(p.magic))
        {
         kept++;
         keptRisk += r;
         g_state[si].entryChecked = true;
         continue;
        }
      bool today = (p.time >= dayStartT);
      if(today)
         entriesSoFar++;
      string refuse = "";
      if(lockedSince > 0 && p.time >= lockedSince)
         refuse = IsHalted() ? "account halted" : "trading locked for today (" + LockReason() + ")";
      else if(cooldown > 0 && p.time < cooldown && p.time >= ds.lastLossTime)
         refuse = StringFormat("cooldown after a loss until %s", TimeToString(cooldown, TIME_MINUTES));
      else if(today && entriesSoFar > InpMaxTradesPerDay)
         refuse = StringFormat("max %d trades per day", InpMaxTradesPerDay);
      else if(kept + 1 > InpMaxPositions)
         refuse = StringFormat("max %d open positions", InpMaxPositions);
      else if(keptRisk + MathMin(r, MaxRiskMoney()) > maxOpen + 1e-9)
         refuse = StringFormat("total open risk would exceed %.1f%%", InpMaxOpenRiskPct);
      if(refuse != "")
        {
         if(MayAct(p.posId) && ClosePos(p, "REFUSED: " + refuse))
           {
            if(today)
               entriesSoFar--;
            continue;
           }
         kept++;
         keptRisk += r;
         continue;
        }
      g_state[si].entryChecked = true;
      kept++;
      keptRisk += MathMin(r, MaxRiskMoney());
     }

   // 5) continuous rules: stop loss present, risk per position
   for(int k = 0; k < ArraySize(pos); k++)
     {
      PosInfo p = pos[k];
      if(!Controlled(p.magic))
         continue;
      int si = StateIndex(p.posId, true);
      if(p.sl <= 0.0)
        {
         if(g_state[si].noSLSince == 0)
            g_state[si].noSLSince = TimeLocal();
         if(TimeLocal() - g_state[si].noSLSince >= InpNoSLGraceSec && MayAct(p.posId))
            SetEmergencyStop(p);
         continue;
        }
      g_state[si].noSLSince = 0;
      if(p.risk > MaxRiskMoney() * 1.02 && MayAct(p.posId))
         CutRisk(p);
     }
  }

//+------------------------------------------------------------------+
//| Lot calculator / order panel                                     |
//+------------------------------------------------------------------+
double SymbolLossPerLot(const bool buy, const double entry, const double sl)
  {
   return LossMoney(_Symbol, buy, 1.0, entry, sl);
  }

// lots for the chart symbol so that the stop loses g_riskPct of equity; 0 + reason when not allowed
double PanelLots(const bool buy, const double sl, string &why, double &riskMoney)
  {
   riskMoney = 0.0;
   double entry = buy ? SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(entry <= 0.0 || sl <= 0.0)
     {
      why = "no price / no SL line";
      return 0.0;
     }
   if((buy && sl >= SymbolInfoDouble(_Symbol, SYMBOL_BID)) || (!buy && sl <= SymbolInfoDouble(_Symbol, SYMBOL_ASK)))
     {
      why = "SL line is on the wrong side";
      return 0.0;
     }
   double perLot = SymbolLossPerLot(buy, entry, sl);
   if(perLot <= 0.0)
     {
      why = "cannot price the risk";
      return 0.0;
     }
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double pct = MathMin(g_riskPct, InpMaxRiskPerTradePct);
   double vmin  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double vstep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(vstep <= 0.0)
      vstep = vmin;
   if(vstep <= 0.0)
     {
      why = "volume limits unknown";
      return 0.0;
     }
   double lots = MathFloor(equity * pct / 100.0 / perLot / vstep + 1e-9) * vstep;
   if(lots < vmin)
     {
      double minPct = vmin * perLot / equity * 100.0;
      if(minPct > InpMaxRiskPerTradePct)
        {
         why = StringFormat("min lot risks %.1f%% (> %.1f%%): move the SL closer", minPct, InpMaxRiskPerTradePct);
         return 0.0;
        }
      lots = vmin;
     }
   lots = MathMin(lots, vmax);
   riskMoney = lots * perLot;
   int digits = 0;
   double s = vstep;
   while(digits < 8 && MathAbs(s - MathRound(s)) > 1e-9)
     {
      s *= 10.0;
      digits++;
     }
   return NormalizeDouble(lots, digits);
  }

// why the panel must not open a new trade right now ("" = allowed)
string PanelBlock()
  {
   if(IsHalted())
      return "HALTED (hard stop)";
   if(IsDayLocked())
      return "locked today: " + LockReason();
   DayStats ds = TodayStats();
   datetime cd = CooldownUntil(ds);
   if(cd > 0)
      return "cooldown until " + TimeToString(cd, TIME_MINUTES);
   if(ds.entries >= InpMaxTradesPerDay)
      return StringFormat("max %d trades today", InpMaxTradesPerDay);
   PosInfo pos[];
   int n = Snapshot(pos);
   if(n >= InpMaxPositions)
      return StringFormat("max %d open positions", InpMaxPositions);
   double open = 0.0;
   for(int k = 0; k < n; k++)
      open += (pos[k].risk >= 0.0) ? pos[k].risk : MaxRiskMoney();
   if(open + AccountInfoDouble(ACCOUNT_EQUITY) * MathMin(g_riskPct, InpMaxRiskPerTradePct) / 100.0
      > AccountInfoDouble(ACCOUNT_EQUITY) * InpMaxOpenRiskPct / 100.0 + 1e-9)
      return StringFormat("total open risk would exceed %.1f%%", InpMaxOpenRiskPct);
   return "";
  }

double LinePrice(const string name)
  {
   if(ObjectFind(0, name) < 0)
      return 0.0;
   return ObjectGetDouble(0, name, OBJPROP_PRICE, 0);
  }

void PlaceTPLine()
  {
   double sl = LinePrice(SL_LINE);
   if(sl <= 0.0 || InpDefaultRR <= 0.0)
      return;
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   bool buy = sl < bid;
   double entry = buy ? ask : bid;
   double tp = buy ? entry + InpDefaultRR * (entry - sl) : entry - InpDefaultRR * (sl - entry);
   if(ObjectFind(0, TP_LINE) < 0)
     {
      ObjectCreate(0, TP_LINE, OBJ_HLINE, 0, 0, tp);
      ObjectSetInteger(0, TP_LINE, OBJPROP_COLOR, clrLimeGreen);
      ObjectSetInteger(0, TP_LINE, OBJPROP_STYLE, STYLE_DASH);
      ObjectSetInteger(0, TP_LINE, OBJPROP_SELECTABLE, true);
      ObjectSetString(0, TP_LINE, OBJPROP_TOOLTIP, "RiskGuard TP (drag to change)");
     }
   else
      ObjectSetDouble(0, TP_LINE, OBJPROP_PRICE, 0, tp);
  }

void CreateSLLine()
  {
   double atr[];
   double dist = 0.0;
   if(g_hAtr != INVALID_HANDLE && CopyBuffer(g_hAtr, 0, 1, 1, atr) == 1)
      dist = InpSLDefaultATR * atr[0];
   if(dist <= 0.0)
      dist = 200 * _Point;
   double sl = NormalizeDouble(SymbolInfoDouble(_Symbol, SYMBOL_BID) - dist, _Digits);
   ObjectDelete(0, SL_LINE);
   ObjectCreate(0, SL_LINE, OBJ_HLINE, 0, 0, sl);
   ObjectSetInteger(0, SL_LINE, OBJPROP_COLOR, clrRed);
   ObjectSetInteger(0, SL_LINE, OBJPROP_WIDTH, 2);
   ObjectSetInteger(0, SL_LINE, OBJPROP_SELECTABLE, true);
   ObjectSetInteger(0, SL_LINE, OBJPROP_SELECTED, true);
   ObjectSetString(0, SL_LINE, OBJPROP_TOOLTIP, "RiskGuard SL: drag below price for BUY, above for SELL");
   g_tpMoved = false;
   PlaceTPLine();
   ChartRedraw();
  }

void PanelTrade(const bool buy)
  {
   string block = PanelBlock();
   if(block != "")
     {
      Log("Panel order refused: " + block);
      return;
     }
   double sl = LinePrice(SL_LINE);
   string why = "";
   double riskMoney = 0.0;
   double lots = PanelLots(buy, sl, why, riskMoney);
   if(lots <= 0.0)
     {
      Log("Panel order refused: " + why);
      return;
     }
   double tp = LinePrice(TP_LINE);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(tp > 0.0 && ((buy && tp <= ask) || (!buy && tp >= bid)))
      tp = 0.0;
   sl = NormalizeDouble(sl, _Digits);
   tp = (tp > 0.0) ? NormalizeDouble(tp, _Digits) : 0.0;
   g_trade.SetTypeFillingBySymbol(_Symbol);
   bool ok = buy ? g_trade.Buy(lots, _Symbol, 0.0, sl, tp, "RiskGuard panel")
                 : g_trade.Sell(lots, _Symbol, 0.0, sl, tp, "RiskGuard panel");
   uint rc = g_trade.ResultRetcode();
   if(ok && (rc == TRADE_RETCODE_DONE || rc == TRADE_RETCODE_DONE_PARTIAL || rc == TRADE_RETCODE_PLACED))
     {
      Log(StringFormat("Panel %s %.2f lots %s, SL %s, TP %s, risk %.2f %s (%.2f%%)", buy ? "BUY" : "SELL", lots, _Symbol,
                       DoubleToString(sl, _Digits), tp > 0.0 ? DoubleToString(tp, _Digits) : "-", riskMoney, Ccy(),
                       riskMoney / AccountInfoDouble(ACCOUNT_EQUITY) * 100.0));
      ObjectDelete(0, SL_LINE);
      ObjectDelete(0, TP_LINE);
     }
   else
      Log(StringFormat("Panel %s failed: %u %s", buy ? "BUY" : "SELL", rc, g_trade.ResultRetcodeDescription()));
  }

//+------------------------------------------------------------------+
//| Panel drawing                                                    |
//+------------------------------------------------------------------+
void MakeButton(const string name, const string text, const int x, const int y, const int w, const color bg)
  {
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_BUTTON, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_XSIZE, w);
   ObjectSetInteger(0, name, OBJPROP_YSIZE, 22);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR, bg);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clrWhite);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 9);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_STATE, false);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
  }

void MakeLabel(const string name, const int x, const int y)
  {
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 9);
   ObjectSetString(0, name, OBJPROP_FONT, "Consolas");
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clrSilver);
  }

// chart label text is limited to 63 characters
void SetLine(const int i, const string text, const color c)
  {
   string name = LBL + IntegerToString(i);
   ObjectSetString(0, name, OBJPROP_TEXT, text == "" ? " " : StringSubstr(text, 0, 63));
   ObjectSetInteger(0, name, OBJPROP_COLOR, c);
  }

void BuildPanel()
  {
   int x = InpPanelX;
   int y = InpPanelY;
   MakeButton(BTN_SL, "SL LINE", x, y, 70, clrDimGray);
   MakeButton(BTN_BUY, "BUY", x + 75, y, 60, clrSeaGreen);
   MakeButton(BTN_SELL, "SELL", x + 140, y, 60, clrFireBrick);
   MakeButton(BTN_CLOSE, "CLOSE ALL", x + 205, y, 80, clrDarkSlateGray);
   if(ObjectFind(0, EDT_RISK) < 0)
      ObjectCreate(0, EDT_RISK, OBJ_EDIT, 0, 0, 0);
   ObjectSetInteger(0, EDT_RISK, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, EDT_RISK, OBJPROP_XDISTANCE, x + 290);
   ObjectSetInteger(0, EDT_RISK, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, EDT_RISK, OBJPROP_XSIZE, 50);
   ObjectSetInteger(0, EDT_RISK, OBJPROP_YSIZE, 22);
   ObjectSetInteger(0, EDT_RISK, OBJPROP_ALIGN, ALIGN_CENTER);
   ObjectSetString(0, EDT_RISK, OBJPROP_TEXT, DoubleToString(g_riskPct, 1));
   ObjectSetString(0, EDT_RISK, OBJPROP_TOOLTIP, "Risk per trade % (max " + DoubleToString(InpMaxRiskPerTradePct, 1) + ")");
   for(int i = 0; i < N_LINES; i++)
      MakeLabel(LBL + IntegerToString(i), x, y + 28 + i * 15);
  }

void UpdatePanel()
  {
   if((bool)MQLInfoInteger(MQL_TESTER) && !(bool)MQLInfoInteger(MQL_VISUAL_MODE))
      return;
   PosInfo pos[];
   int n = Snapshot(pos);
   DayStats ds = TodayStats();
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   double dayStart = bal - ds.realized;
   double dayPnl = ds.realized + FloatingPnL(pos);
   double openRisk = 0.0;
   int noSL = 0;
   for(int k = 0; k < n; k++)
     {
      if(pos[k].risk < 0.0)
         noSL++;
      openRisk += (pos[k].risk >= 0.0) ? pos[k].risk : 0.0;
     }
   string status;
   string reason = "";
   color sc = clrLimeGreen;
   if(IsHalted())
     {
      status = "HALTED (hard stop)";
      reason = "Review first, then set InpResetHalt=true";
      sc = clrRed;
     }
   else if(IsDayLocked())
     {
      status = "LOCKED until " + TimeToString(NextDayStart(), TIME_DATE | TIME_MINUTES);
      reason = "Reason: " + LockReason();
      sc = clrOrangeRed;
     }
   else
     {
      datetime cd = CooldownUntil(ds);
      if(cd > 0)
        {
         status = "COOLDOWN until " + TimeToString(cd, TIME_MINUTES);
         reason = "No new trades after a loss (anti revenge)";
         sc = clrGold;
        }
      else
         status = "OK - trading allowed";
     }
   SetLine(0, "RiskGuard: " + status, sc);
   SetLine(1, reason, sc);
   SetLine(2, StringFormat("Equity %.2f %s  start %.2f", eq, Ccy(), StartBalance()), clrSilver);
   SetLine(3, StringFormat("Hard stop at %.2f %s", StartBalance() * (1.0 - InpHardStopPct / 100.0), Ccy()), clrSilver);
   SetLine(4, StringFormat("Today %+.2f (%+.1f%%)  limit -%.1f%%", dayPnl, dayStart > 0 ? dayPnl / dayStart * 100.0 : 0.0,
                           InpDailyLossPct), dayPnl < 0 ? clrOrange : clrSilver);
   SetLine(5, StringFormat("Trades %d/%d  loss streak %d/%d", ds.entries, InpMaxTradesPerDay, ds.consecLosses,
                           InpMaxConsecLosses), clrSilver);
   SetLine(6, StringFormat("Open risk %.2f (%.1f%%) max %.1f%%  pos %d/%d", openRisk, eq > 0 ? openRisk / eq * 100.0 : 0.0,
                           InpMaxOpenRiskPct, n, InpMaxPositions), clrSilver);
   SetLine(7, noSL > 0 ? StringFormat("WARNING: %d position(s) WITHOUT stop loss", noSL) : "", clrOrangeRed);
   double sl = LinePrice(SL_LINE);
   if(sl > 0.0)
     {
      bool buy = sl < SymbolInfoDouble(_Symbol, SYMBOL_BID);
      string why = "";
      double riskMoney = 0.0;
      double lots = PanelLots(buy, sl, why, riskMoney);
      double entry = buy ? SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double tp = LinePrice(TP_LINE);
      if(lots > 0.0)
        {
         SetLine(8, StringFormat("%s %s %.2f lot  risk %.2f (%.2f%%)", buy ? "BUY" : "SELL", _Symbol, lots, riskMoney,
                                 eq > 0 ? riskMoney / eq * 100.0 : 0.0), buy ? clrMediumSeaGreen : clrTomato);
         SetLine(9, StringFormat("SL %s (%s away)  TP %s", DoubleToString(sl, _Digits), DoubleToString(MathAbs(entry - sl), _Digits),
                                 tp > 0.0 ? DoubleToString(tp, _Digits) : "-"), clrSilver);
        }
      else
        {
         SetLine(8, "Setup: " + why, clrOrange);
         SetLine(9, "", clrSilver);
        }
     }
   else
     {
      SetLine(8, "Press SL LINE, drag the red line to your stop,", clrGray);
      SetLine(9, "then press BUY or SELL", clrGray);
     }
   string block = PanelBlock();
   SetLine(10, block == "" ? "" : "Blocked: " + block, clrOrange);
   SetLine(11, g_lastMsg == "" ? "" : "Last: " + g_lastMsg, clrGray);
   ChartRedraw();
  }

//+------------------------------------------------------------------+
//| Events                                                           |
//+------------------------------------------------------------------+
void OnChartEvent(const int id, const long &lparam, const double &dparam, const string &sparam)
  {
   if(id == CHARTEVENT_OBJECT_CLICK)
     {
      if(sparam == BTN_SL)
         CreateSLLine();
      else if(sparam == BTN_BUY)
         PanelTrade(true);
      else if(sparam == BTN_SELL)
         PanelTrade(false);
      else if(sparam == BTN_CLOSE)
        {
         if(g_closeArm > 0 && TimeLocal() - g_closeArm <= 5)
           {
            g_closeArm = 0;
            CloseAllGuarded("CLOSE ALL button");
            ObjectSetString(0, BTN_CLOSE, OBJPROP_TEXT, "CLOSE ALL");
           }
         else
           {
            g_closeArm = TimeLocal();
            ObjectSetString(0, BTN_CLOSE, OBJPROP_TEXT, "CONFIRM?");
           }
        }
      if(StringFind(sparam, PFX + "BTN_") == 0)
         ObjectSetInteger(0, sparam, OBJPROP_STATE, false);
      UpdatePanel();
     }
   else if(id == CHARTEVENT_OBJECT_DRAG)
     {
      if(sparam == SL_LINE && !g_tpMoved)
         PlaceTPLine();
      else if(sparam == TP_LINE)
         g_tpMoved = true;
      UpdatePanel();
     }
   else if(id == CHARTEVENT_OBJECT_ENDEDIT && sparam == EDT_RISK)
     {
      double v = StringToDouble(ObjectGetString(0, EDT_RISK, OBJPROP_TEXT));
      if(v > 0.0)
         g_riskPct = MathMin(v, InpMaxRiskPerTradePct);
      ObjectSetString(0, EDT_RISK, OBJPROP_TEXT, DoubleToString(g_riskPct, 1));
      UpdatePanel();
     }
  }

void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &request, const MqlTradeResult &result)
  {
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD || trans.deal == 0)
      return;
   if(HistoryDealSelect(trans.deal) && HistoryDealGetInteger(trans.deal, DEAL_TYPE) == DEAL_TYPE_BALANCE)
     {
      double flow = HistoryDealGetDouble(trans.deal, DEAL_PROFIT);
      GvSetFlush("start", StartBalance() + flow);
      Log(StringFormat("Balance operation %+.2f: hard-stop start balance is now %.2f", flow, StartBalance()));
      return;
     }
   Guard();
  }

void OnTimer()
  {
   if(GvGet("start", 0.0) <= 0.0 && AccountInfoDouble(ACCOUNT_BALANCE) > 0.0)
      GvSetFlush("start", AccountInfoDouble(ACCOUNT_BALANCE));
   Guard();
   if(g_closeArm > 0 && TimeLocal() - g_closeArm > 5)
     {
      g_closeArm = 0;
      ObjectSetString(0, BTN_CLOSE, OBJPROP_TEXT, "CLOSE ALL");
     }
   UpdatePanel();
  }

void OnTick()
  {
   // the guard runs on the 1-second timer; ticks only refresh the setup line quickly
  }

//+------------------------------------------------------------------+
//| Lifecycle                                                        |
//+------------------------------------------------------------------+
bool AnotherInstance()
  {
   for(long id = ChartFirst(); id >= 0; id = ChartNext(id))
      if(id != ChartID() && ChartGetString(id, CHART_EXPERT_NAME) == MQLInfoString(MQL_PROGRAM_NAME))
         return true;
   return false;
  }

int OnInit()
  {
   if(!(bool)MQLInfoInteger(MQL_TESTER) && AnotherInstance())
     {
      Alert("RiskGuard already runs on another chart. Use only one instance per account.");
      return INIT_FAILED;
     }
   if(InpRiskPct <= 0.0 || InpMaxRiskPerTradePct <= 0.0 || InpMaxRiskPerTradePct > 10.0 || InpMaxOpenRiskPct < InpMaxRiskPerTradePct
      || InpHardStopPct <= 0.0 || InpHardStopPct >= 100.0 || InpMaxPositions < 1 || InpDayStartHourServer < 0 || InpDayStartHourServer > 23)
     {
      Print("RiskGuard: inputs out of range (0 < risk; max risk per trade <= 10%; max open risk >= max per trade; 0 < hard stop < 100%; positions >= 1).");
      return INIT_PARAMETERS_INCORRECT;
     }
   g_gv = StringFormat("RG_%I64d_", AccountInfoInteger(ACCOUNT_LOGIN));
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   bool newStartInput = (InpStartBalance > 0.0 && MathAbs(GvGet("start_input", 0.0) - InpStartBalance) > 0.001);
   if(newStartInput && bal > 0.0 && (InpStartBalance < 0.2 * bal || InpStartBalance > 5.0 * bal))
     {
      Alert(StringFormat("InpStartBalance %.2f looks wrong for balance %.2f %s (cent account: enter USC, e.g. 5000 for $50)",
                         InpStartBalance, bal, Ccy()));
      return INIT_PARAMETERS_INCORRECT;
     }
   if(newStartInput)
     {
      GvSetFlush("start", InpStartBalance);
      GvSetFlush("start_input", InpStartBalance);
     }
   else if(GvGet("start", 0.0) <= 0.0 && bal > 0.0)
      GvSetFlush("start", bal);
   if(InpResetHalt && GvGet("reset_armed", 1.0) > 0.5 && bal > 0.0)
     {
      if(!newStartInput)
         GvSetFlush("start", bal);
      GvSetFlush("halted", 0.0);
      GvSetFlush("reset_armed", 0.0);
      Log(StringFormat("Halt cleared. New hard-stop start balance %.2f.", StartBalance()));
     }
   else if(!InpResetHalt)
      GvSet("reset_armed", 1.0);

   g_riskPct = MathMin(InpRiskPct, InpMaxRiskPerTradePct);
   g_trade.SetExpertMagicNumber(0);        // panel orders count as manual trades
   g_trade.SetDeviationInPoints(50);
   g_trade.SetAsyncMode(false);
   g_hAtr = iATR(_Symbol, _Period, 14);
   BuildPanel();
   EventSetTimer(1);
   Log(StringFormat("started. Risk %.1f%% (max %.1f%% per trade, %.1f%% open), daily loss %.1f%%, hard stop at %.2f %s",
                    g_riskPct, InpMaxRiskPerTradePct, InpMaxOpenRiskPct, InpDailyLossPct,
                    StartBalance() * (1.0 - InpHardStopPct / 100.0), Ccy()));
   Guard();
   UpdatePanel();
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   if(g_hAtr != INVALID_HANDLE)
      IndicatorRelease(g_hAtr);
   ObjectsDeleteAll(0, PFX + "BTN_");
   ObjectsDeleteAll(0, PFX + "EDT_");
   ObjectsDeleteAll(0, LBL);
   if(reason == REASON_REMOVE)
     {
      ObjectDelete(0, SL_LINE);
      ObjectDelete(0, TP_LINE);
     }
  }
//+------------------------------------------------------------------+
