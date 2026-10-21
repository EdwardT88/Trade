"""M1 execution engine + small-account risk manager for XAUUSD.

Price data is BID. Longs enter at ASK (bid + spread) and exit at BID; shorts enter at BID and
exit at ASK. Stops/targets are checked against every M1 bar's high/low; if both are touched
inside the same bar the stop is assumed to fill first (pessimistic). Breakeven and trailing
updates computed from a bar only take effect from the next bar (no intrabar look-ahead).

Position size is expressed in ounces of gold:
    standard account: 0.01 lot = 1 oz      -> min_size = 1.0
    cent account:     0.01 lot = 0.01 oz   -> min_size = 0.01  ($1 move = 1 US cent)
Equity is always tracked in USD.

Strategies produce `Signals`: one row per intended entry. `entry_idx` is the M1 bar at whose
OPEN the order is filled, so a signal computed from bar t's close must use entry_idx = t + 1.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from numba import njit

# skip / status codes per signal
TAKEN, SKIP_BUSY, SKIP_HARD_STOP, SKIP_DAILY_LOSS, SKIP_CONSEC, SKIP_MAX_TRADES, SKIP_MIN_LOT, SKIP_MARGIN, SKIP_OOR = range(9)
STATUS_NAMES = ["taken", "busy", "hard_stop", "daily_loss", "consec_losses", "max_trades", "min_lot_risk", "margin", "out_of_range"]
# exit reasons
EXIT_SL, EXIT_TP, EXIT_TIME, EXIT_BE, EXIT_TRAIL, EXIT_EOD = 1, 2, 3, 4, 5, 6
EXIT_NAMES = {1: "sl", 2: "tp", 3: "time", 4: "breakeven", 5: "trail", 6: "end_of_data"}


@dataclass
class CostModel:
    spread_fixed: float = 0.25        # minimum spread in $ (price units)
    spread_bps: float = 0.80          # spread as basis points of price; spread = max(fixed, bps * price)
    rollover_mult: float = 3.0        # spread multiplier during the daily rollover window
    rollover_hours_utc: tuple = (21, 22)  # inclusive UTC hours treated as rollover
    slippage_stop: float = 0.05       # extra adverse $ on stop / time exits
    commission_per_oz: float = 0.0    # round-trip commission per oz (cent accounts are usually 0)

    def spread_array(self, close: np.ndarray, hours: np.ndarray) -> np.ndarray:
        sp = np.maximum(self.spread_fixed, self.spread_bps * 1e-4 * close)
        lo, hi = self.rollover_hours_utc
        sp = np.where((hours >= lo) & (hours <= hi), sp * self.rollover_mult, sp)
        return sp


@dataclass
class RiskConfig:
    initial_equity: float = 50.0          # USD ($50 = 5000 USC on a cent account)
    risk_pct: float = 2.0                 # % of equity risked per trade
    reduced_risk_pct: float = 1.0         # used while in drawdown
    dd_reduce_pct: float = 10.0           # drawdown from peak that triggers reduced risk
    max_risk_pct_at_min_lot: float = 3.0  # if min lot risks more than this, skip the trade
    min_size: float = 0.01                # oz (cent account 0.01 lot)
    size_step: float = 0.01               # oz
    daily_loss_pct: float = 5.0           # stop for the day after losing this % of day-start equity
    max_trades_per_day: int = 8
    max_consec_losses_per_day: int = 3
    hard_stop_equity: float = 35.0        # stop trading entirely (needs human review)
    leverage: float = 500.0


@dataclass
class Signals:
    entry_idx: np.ndarray                 # int64, M1 bar index filled at its open
    direction: np.ndarray                 # +1 long / -1 short
    sl_dist: np.ndarray                   # $ distance from fill to stop (> 0)
    tp_dist: np.ndarray                   # $ distance from fill to target (0 = none)
    exit_idx: np.ndarray | None = None    # close at open of this M1 bar (-1 = none)
    be_trigger_r: np.ndarray | None = None  # move stop to breakeven at +x R (0 = off)
    be_offset: np.ndarray | None = None   # $ locked in when moved to breakeven
    trail_dist: np.ndarray | None = None  # $ trailing distance, active after breakeven (0 = off)
    tag: np.ndarray | None = None         # optional int label (e.g. setup type)

    def finalize(self) -> "Signals":
        n = len(self.entry_idx)
        z = lambda v, dt=float: np.zeros(n, dtype=dt) if v is None else np.asarray(v, dtype=dt)  # noqa: E731
        order = np.argsort(np.asarray(self.entry_idx), kind="stable")
        out = Signals(
            entry_idx=np.asarray(self.entry_idx, dtype=np.int64)[order],
            direction=np.asarray(self.direction, dtype=np.int64)[order],
            sl_dist=np.asarray(self.sl_dist, dtype=float)[order],
            tp_dist=np.asarray(self.tp_dist, dtype=float)[order],
            exit_idx=(np.full(n, -1, np.int64) if self.exit_idx is None else np.asarray(self.exit_idx, np.int64))[order],
            be_trigger_r=z(self.be_trigger_r)[order],
            be_offset=z(self.be_offset)[order],
            trail_dist=z(self.trail_dist)[order],
            tag=z(self.tag, np.int64)[order],
        )
        bad = ~(np.isfinite(out.sl_dist) & (out.sl_dist > 0) & np.isin(out.direction, (-1, 1)))
        if bad.any():
            keep = ~bad
            for f in ("entry_idx", "direction", "sl_dist", "tp_dist", "exit_idx", "be_trigger_r", "be_offset", "trail_dist", "tag"):
                setattr(out, f, getattr(out, f)[keep])
        return out

    @staticmethod
    def empty() -> "Signals":
        e = np.zeros(0)
        return Signals(e.astype(np.int64), e.astype(np.int64), e, e)


@njit(cache=True)
def _simulate(open_, high, low, close, spread, day,
              sig_idx, sig_dir, sig_sl, sig_tp, sig_exit, sig_be_r, sig_be_off, sig_trail,
              init_eq, risk_pct, reduced_risk_pct, dd_reduce_pct, max_risk_min_pct,
              min_size, size_step, daily_loss_pct, max_trades_day, max_consec_day,
              hard_stop_eq, leverage, slip, comm):
    n = open_.shape[0]
    ns = sig_idx.shape[0]
    status = np.zeros(ns, np.int64)
    exit_i = np.full(ns, -1, np.int64)
    entry_px = np.full(ns, np.nan)
    exit_px = np.full(ns, np.nan)
    size = np.zeros(ns)
    pnl = np.zeros(ns)
    risk_amt = np.zeros(ns)
    reason = np.zeros(ns, np.int64)
    eq_after = np.full(ns, np.nan)
    mae = np.zeros(ns)  # max adverse excursion in $ per oz
    mfe = np.zeros(ns)

    equity = init_eq
    peak = init_eq
    cur_day = -1
    day_start = init_eq
    day_pnl = 0.0
    day_trades = 0
    day_consec = 0
    busy_until = -1
    stopped = False

    for k in range(ns):
        i = sig_idx[k]
        if i < 0 or i >= n:
            status[k] = 8
            continue
        if i <= busy_until:
            status[k] = 1
            continue
        d = day[i]
        if d != cur_day:
            cur_day = d
            day_start = equity
            day_pnl = 0.0
            day_trades = 0
            day_consec = 0
        if stopped or equity <= hard_stop_eq:
            stopped = True
            status[k] = 2
            continue
        if day_pnl <= -daily_loss_pct / 100.0 * day_start:
            status[k] = 3
            continue
        if day_consec >= max_consec_day:
            status[k] = 4
            continue
        if day_trades >= max_trades_day:
            status[k] = 5
            continue

        rp = risk_pct
        if equity < peak * (1.0 - dd_reduce_pct / 100.0):
            rp = reduced_risk_pct
        dirn = sig_dir[k]
        sl = sig_sl[k]
        tp = sig_tp[k]
        sp = spread[i]
        ent = open_[i] + sp if dirn > 0 else open_[i]
        per_oz = sl + slip + comm
        sz = np.floor((equity * rp / 100.0) / per_oz / size_step + 1e-9) * size_step
        if sz < min_size - 1e-12:
            if min_size * per_oz / equity * 100.0 <= max_risk_min_pct:
                sz = min_size
            else:
                status[k] = 6
                continue
        if sz * ent / leverage > equity * 0.5:
            status[k] = 7
            continue

        sl_px = ent - dirn * sl
        tp_px = ent + dirn * tp
        has_tp = tp > 0
        be_r = sig_be_r[k]
        be_px = ent + dirn * be_r * sl
        moved = False
        trail = sig_trail[k]
        best = ent
        worst = ent
        end = sig_exit[k] if sig_exit[k] > i else n
        if end > n:
            end = n
        j = i
        xp = np.nan
        rsn = 0
        while j < end:
            o = open_[j]
            h = high[j]
            lo = low[j]
            if dirn > 0:
                if j > i and o <= sl_px:
                    xp = o - slip
                    rsn = 1
                    break
                if j > i and has_tp and o >= tp_px:
                    xp = o
                    rsn = 2
                    break
                if lo < worst:
                    worst = lo
                if lo <= sl_px:
                    xp = sl_px - slip
                    rsn = 1
                    break
                if has_tp and h >= tp_px:
                    xp = tp_px
                    rsn = 2
                    break
                if h > best:
                    best = h
                if be_r > 0 and not moved and best >= be_px:
                    nb = ent + sig_be_off[k]
                    if nb > sl_px:
                        sl_px = nb
                    moved = True
                if trail > 0 and moved and best - trail > sl_px:
                    sl_px = best - trail
            else:
                spj = spread[j]
                ao = o + spj
                ah = h + spj
                al = lo + spj
                if j > i and ao >= sl_px:
                    xp = ao + slip
                    rsn = 1
                    break
                if j > i and has_tp and ao <= tp_px:
                    xp = ao
                    rsn = 2
                    break
                if ah > worst:
                    worst = ah
                if ah >= sl_px:
                    xp = sl_px + slip
                    rsn = 1
                    break
                if has_tp and al <= tp_px:
                    xp = tp_px
                    rsn = 2
                    break
                if al < best:
                    best = al
                if be_r > 0 and not moved and best <= be_px:
                    nb = ent - sig_be_off[k]
                    if nb < sl_px:
                        sl_px = nb
                    moved = True
                if trail > 0 and moved and best + trail < sl_px:
                    sl_px = best + trail
            j += 1
        if rsn == 0:
            if end < n:
                j = end
                xp = open_[end] - slip if dirn > 0 else open_[end] + spread[end] + slip
                rsn = 3
            else:
                j = n - 1
                xp = close[n - 1] if dirn > 0 else close[n - 1] + spread[n - 1]
                rsn = 6
        elif rsn == 1 and moved:
            # stop that was moved to breakeven or trailed
            if (dirn > 0 and sl_px > ent - 1e-9) or (dirn < 0 and sl_px < ent + 1e-9):
                rsn = 5 if trail > 0 else 4

        p = (xp - ent) * dirn * sz - comm * sz
        status[k] = 0
        exit_i[k] = j
        entry_px[k] = ent
        exit_px[k] = xp
        size[k] = sz
        pnl[k] = p
        risk_amt[k] = sz * per_oz
        reason[k] = rsn
        mae[k] = (ent - worst) if dirn > 0 else (worst - ent)
        mfe[k] = (best - ent) if dirn > 0 else (ent - best)
        equity += p
        if equity > peak:
            peak = equity
        eq_after[k] = equity
        day_pnl += p
        day_trades += 1
        if p < 0:
            day_consec += 1
        else:
            day_consec = 0
        busy_until = j
        if equity <= hard_stop_eq:
            stopped = True

    return status, exit_i, entry_px, exit_px, size, pnl, risk_amt, reason, eq_after, mae, mfe


@dataclass
class Result:
    trades: pd.DataFrame
    skipped: dict
    final_equity: float
    initial_equity: float
    stopped_out: bool
    cost: CostModel
    risk: RiskConfig
    extra: dict = field(default_factory=dict)


def run_backtest(m1: pd.DataFrame, sig: Signals, cost: CostModel | None = None, risk: RiskConfig | None = None) -> Result:
    cost = cost or CostModel()
    risk = risk or RiskConfig()
    sig = sig.finalize()
    idx = m1.index
    open_ = m1["open"].to_numpy(float)
    high = m1["high"].to_numpy(float)
    low = m1["low"].to_numpy(float)
    close = m1["close"].to_numpy(float)
    hours = idx.hour.to_numpy()
    spread = cost.spread_array(close, hours)
    day = (ns(idx) // (86_400 * 10**9)).astype(np.int64)

    out = _simulate(
        open_, high, low, close, spread, day,
        sig.entry_idx, sig.direction, sig.sl_dist, sig.tp_dist, sig.exit_idx,
        sig.be_trigger_r, sig.be_offset, sig.trail_dist,
        float(risk.initial_equity), float(risk.risk_pct), float(risk.reduced_risk_pct), float(risk.dd_reduce_pct),
        float(risk.max_risk_pct_at_min_lot), float(risk.min_size), float(risk.size_step), float(risk.daily_loss_pct),
        int(risk.max_trades_per_day), int(risk.max_consec_losses_per_day), float(risk.hard_stop_equity),
        float(risk.leverage), float(cost.slippage_stop), float(cost.commission_per_oz),
    )
    status, exit_i, entry_px, exit_px, size, pnl, risk_amt, reason, eq_after, mae, mfe = out
    taken = status == TAKEN
    t = pd.DataFrame({
        "entry_time": idx[sig.entry_idx[taken]],
        "exit_time": idx[exit_i[taken]],
        "direction": sig.direction[taken],
        "entry": entry_px[taken],
        "exit": exit_px[taken],
        "sl_dist": sig.sl_dist[taken],
        "tp_dist": sig.tp_dist[taken],
        "size_oz": size[taken],
        "pnl": pnl[taken],
        "risk": risk_amt[taken],
        "r": pnl[taken] / risk_amt[taken],
        "exit_reason": pd.Series(reason[taken]).map(EXIT_NAMES).to_numpy(),
        "equity": eq_after[taken],
        "mae": mae[taken],
        "mfe": mfe[taken],
        "tag": sig.tag[taken],
        "entry_idx": sig.entry_idx[taken],
        "exit_idx": exit_i[taken],
    })
    skipped = {STATUS_NAMES[c]: int((status == c).sum()) for c in range(1, len(STATUS_NAMES)) if (status == c).any()}
    final = float(t["equity"].iloc[-1]) if len(t) else float(risk.initial_equity)
    stopped = bool(skipped.get("hard_stop", 0) > 0 or final <= risk.hard_stop_equity)
    return Result(t, skipped, final, float(risk.initial_equity), stopped, cost, risk)


# ---------------------------------------------------------------- helpers for strategies

def ns(index) -> np.ndarray:
    """int64 nanoseconds since epoch for any DatetimeIndex (pandas >= 3 may default to us resolution)."""
    return pd.DatetimeIndex(index).as_unit("ns").asi8


def htf_close_to_m1_entry(m1_index: pd.DatetimeIndex, htf_index: pd.DatetimeIndex, rule: str) -> np.ndarray:
    """For each higher-timeframe bar (labelled by open time), return the M1 index of the first
    M1 bar at or after that HTF bar's close. That is where a signal computed on the HTF close fills.
    Returns len(m1_index) when no such bar exists."""
    close_times = ns(htf_index + pd.Timedelta(rule))
    return np.searchsorted(ns(m1_index), close_times, side="left")


def align_htf_to_m1(m1_index: pd.DatetimeIndex, htf_index: pd.DatetimeIndex, rule: str, values: np.ndarray) -> np.ndarray:
    """Value of the most recent *completed* HTF bar for each M1 bar (no look-ahead).
    An HTF bar opened at T with period P is completed for M1 bars with time >= T + P."""
    close_times = ns(htf_index + pd.Timedelta(rule))
    pos = np.searchsorted(close_times, ns(m1_index), side="right") - 1
    out = np.full(len(m1_index), np.nan)
    ok = pos >= 0
    out[ok] = np.asarray(values, dtype=float)[pos[ok]]
    return out
