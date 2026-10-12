"""Lógica pura de la estrategia: ruptura del máximo/mínimo del día (5m, cripto 24/7).

Réplica de la versión Pine "BRK_Dia_Cripto_BingX_5m". Sin red ni estado: dado un
DataFrame de velas de 5m CERRADAS, decide si la última vela es una señal.
Todo se mide en ADR / ATR / % del precio, así que vale para cualquier par.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

BAR_MS = 5 * 60 * 1000
DAY_MS = 24 * 60 * 60 * 1000


@dataclass(frozen=True)
class Params:
    level_mode: str = "day"          # "day" (máx/mín del día UTC) o "rolling" (ventana móvil)
    roll_len: int = 288              # velas de la ventana móvil (288 = 24 h en 5m)
    warmup_bars: int = 36            # modo day: velas mínimas desde 00:00 UTC antes de operar
    persist_bars: int = 2            # cierres seguidos más allá del nivel
    allow_long: bool = True
    allow_short: bool = True
    adr_len: int = 20
    use_dm: bool = True
    dm_min: float = 0.15             # sesgo mínimo |cierre - apertura UTC| en ADR
    use_room: bool = True
    room_thr: float = 1.0            # recorrido consumido máximo desde el extremo opuesto (ADR)
    use_quiet: bool = True
    quiet_span: float = 0.6          # ayer con rango < X·ADR = día tranquilo (se excluye)
    atr_len: int = 14
    stop_atr: float = 2.0
    use_cost_filter: bool = True
    rt_cost_pct: float = 0.12        # comisión + slippage ida y vuelta (% del precio)
    max_cost_r: float = 0.20         # coste máximo en R
    use_hours: bool = False
    hours_from: int = 7
    hours_to: int = 21
    eod_block: bool = True           # no emitir señales a partir de las 23:00 UTC
    max_signals_per_day: int = 2


@dataclass(frozen=True)
class Signal:
    symbol: str
    side: str                        # "LONG" | "SHORT"
    bar_time_ms: int                 # hora de APERTURA de la vela de señal
    close: float
    level: float
    stop: float
    risk_dist: float
    atr: float
    atr_pct: float
    stop_pct: float
    cost_r: float
    adr: float
    adr_pct: float
    dm_adr: float
    room_adr: float
    day_open: float
    rank_today: int


def atr_rma(high: pd.Series, low: pd.Series, close: pd.Series, n: int) -> pd.Series:
    """ATR de Wilder (RMA), equivalente a ta.atr de Pine."""
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def daily_stats(daily: pd.DataFrame, today_start_ms: int, adr_len: int, min_days: int = 10):
    """(ADR, rango de ayer) con velas diarias COMPLETAS (excluye el día en curso)."""
    if daily is None or daily.empty:
        return None
    d = daily[daily["time"] < today_start_ms]
    if len(d) < min_days:
        return None
    ranges = (d["high"] - d["low"]).to_numpy(dtype="float64")
    adr = float(np.mean(ranges[-adr_len:]))
    if not adr > 0:
        return None
    return adr, float(ranges[-1])


def in_hours(hour: int, start: int, end: int) -> bool:
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end


def evaluate(symbol: str, df: pd.DataFrame, adr: float | None, prev_rng: float | None, p: Params) -> Signal | None:
    """Devuelve una Signal si la ÚLTIMA vela cerrada de df es una señal; si no, None."""
    n = len(df)
    need = max(p.atr_len * 4, 60, (p.roll_len + 2) if p.level_mode == "rolling" else 0)
    if n < need or adr is None or not adr > 0:
        return None

    t = df["time"].to_numpy(dtype="int64")
    o = df["open"].to_numpy(dtype="float64")
    h = df["high"].to_numpy(dtype="float64")
    l = df["low"].to_numpy(dtype="float64")
    cl = df["close"].to_numpy(dtype="float64")
    last = n - 1

    day_id = t // DAY_MS
    start = int(np.argmax(day_id == day_id[last]))
    atr = atr_rma(df["high"], df["low"], df["close"], p.atr_len).to_numpy(dtype="float64")

    if p.level_mode == "rolling":
        hi_roll = df["high"].rolling(p.roll_len).max().shift(1).to_numpy(dtype="float64")
        lo_roll = df["low"].rolling(p.roll_len).min().shift(1).to_numpy(dtype="float64")
    else:
        hi_roll = lo_roll = None

    quiet = prev_rng is not None and prev_rng < p.quiet_span * adr
    day_open = float(o[start])
    run_hi, run_lo = -math.inf, math.inf
    arm_l = arm_s = False
    arm_lvl_l = arm_lvl_s = math.nan
    cnt_l = cnt_s = 0
    events: list[tuple] = []

    for i in range(start, n):
        k = i - start
        prev_hi = run_hi if k > 0 else math.nan      # máximo del día hasta la vela anterior
        prev_lo = run_lo if k > 0 else math.nan
        run_hi = max(run_hi, h[i])
        run_lo = min(run_lo, l[i])

        if p.level_mode == "day":
            lvl_hi, lvl_lo = prev_hi, prev_lo
            ready = (k + 1) > p.warmup_bars
        else:
            lvl_hi, lvl_lo = hi_roll[i], lo_roll[i]
            ready = True
        c = cl[i]

        # --- máquina de armado/persistencia (idéntica a la versión Pine) ---
        if arm_l:
            if c > arm_lvl_l:
                cnt_l += 1
            else:
                arm_l, cnt_l = False, 0
        elif ready and not math.isnan(lvl_hi) and c > lvl_hi:
            arm_l, arm_lvl_l, cnt_l = True, lvl_hi, 1
        sig_l = arm_l and cnt_l == p.persist_bars

        if arm_s:
            if c < arm_lvl_s:
                cnt_s += 1
            else:
                arm_s, cnt_s = False, 0
        elif ready and not math.isnan(lvl_lo) and c < lvl_lo:
            arm_s, arm_lvl_s, cnt_s = True, lvl_lo, 1
        sig_s = arm_s and cnt_s == p.persist_bars

        if not (sig_l or sig_s):
            continue

        # --- filtros ---
        hour = int((t[i] // 3_600_000) % 24)
        if p.eod_block and hour >= 23:
            continue
        if p.use_hours and not in_hours(hour, p.hours_from, p.hours_to):
            continue
        if p.use_quiet and quiet:
            continue
        a = atr[i]
        if not a > 0:
            continue
        risk = p.stop_atr * a
        cost_r = (p.rt_cost_pct / 100.0) * c / risk
        if p.use_cost_filter and cost_r > p.max_cost_r:
            continue

        if sig_l and p.allow_long:
            dm = (c - day_open) / adr
            room = (c - run_lo) / adr
            if (not p.use_dm or dm >= p.dm_min) and (not p.use_room or room <= p.room_thr):
                events.append((i, "LONG", arm_lvl_l, c, a, risk, cost_r, dm, room))
                continue
        if sig_s and p.allow_short:
            dm = (day_open - c) / adr
            room = (run_hi - c) / adr
            if (not p.use_dm or dm >= p.dm_min) and (not p.use_room or room <= p.room_thr):
                events.append((i, "SHORT", arm_lvl_s, c, a, risk, cost_r, dm, room))

    if not events:
        return None
    idx, side, level, c, a, risk, cost_r, dm, room = events[-1]
    rank = len(events)
    if idx != last or rank > p.max_signals_per_day:
        return None

    stop = c - risk if side == "LONG" else c + risk
    return Signal(
        symbol=symbol, side=side, bar_time_ms=int(t[idx]), close=float(c), level=float(level),
        stop=float(stop), risk_dist=float(risk), atr=float(a), atr_pct=float(a / c * 100.0),
        stop_pct=float(risk / c * 100.0), cost_r=float(cost_r), adr=float(adr),
        adr_pct=float(adr / c * 100.0), dm_adr=float(dm), room_adr=float(room),
        day_open=day_open, rank_today=rank,
    )
