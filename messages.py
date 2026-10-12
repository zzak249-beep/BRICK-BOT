"""Formato de los mensajes de Telegram y tamaño de posición sugerido."""
from __future__ import annotations

import html
from datetime import datetime, timezone

from .strategy import BAR_MS, Signal


def fmt_price(x: float) -> str:
    ax = abs(x)
    if ax >= 100:
        dec = 2
    elif ax >= 1:
        dec = 4
    elif ax >= 0.01:
        dec = 6
    else:
        dec = 8
    return f"{x:.{dec}f}"


def suggest_size(sig: Signal, account: float, risk_pct: float, max_lev: float):
    """(cantidad, nocional, riesgo en USDT, limitado por apalancamiento)."""
    risk_usdt = account * risk_pct / 100.0
    qty = risk_usdt / sig.risk_dist
    notional = qty * sig.close
    cap = account * max_lev
    capped = False
    if notional > cap:
        qty = cap / sig.close
        notional = cap
        risk_usdt = qty * sig.risk_dist
        capped = True
    return qty, notional, risk_usdt, capped


def format_signal(sig: Signal, account: float, risk_pct: float, max_lev: float, tp_r: list[float]) -> str:
    is_long = sig.side == "LONG"
    sign = 1.0 if is_long else -1.0
    icon = "🟢" if is_long else "🔴"
    what = "máximo" if is_long else "mínimo"
    closed_at = datetime.fromtimestamp((sig.bar_time_ms + BAR_MS) / 1000.0, tz=timezone.utc).strftime("%H:%M")
    qty, notional, risk_usdt, capped = suggest_size(sig, account, risk_pct, max_lev)
    tps = " · ".join(f"TP {r:g}R: <code>{fmt_price(sig.close + sign * r * sig.risk_dist)}</code>" for r in tp_r)

    lines = [
        f"{icon} <b>{sig.side}</b> · <b>{html.escape(sig.symbol)}</b> · 5m",
        f"Ruptura del {what} del día: <code>{fmt_price(sig.level)}</code> (vela cerrada {closed_at} UTC)",
        f"Entrada ref.: <code>{fmt_price(sig.close)}</code>",
        f"Stop: <code>{fmt_price(sig.stop)}</code> ({sig.stop_pct:.2f}% · 2×ATR = {fmt_price(sig.risk_dist)})",
        tps,
        (
            f"Tamaño sugerido (riesgo {risk_pct:g}% de {account:g} USDT = {risk_usdt:.2f} USDT): "
            f"cant. ≈ <code>{qty:.6g}</code> · nocional ≈ {notional:.0f} USDT ({notional / account:.1f}x)"
            + (" · limitado por apalancamiento" if capped else "")
        ),
        (
            f"Contexto: ADR {sig.adr_pct:.1f}% · sesgo {sig.dm_adr:+.2f} ADR · espacio {sig.room_adr:.2f} ADR · "
            f"ATR {sig.atr_pct:.2f}% · coste {sig.cost_r:.2f} R · señal nº {sig.rank_today} del día"
        ),
        "Si sigue abierta, cierra antes de las 23:55 UTC.",
        "<i>Señal informativa, no es asesoramiento financiero. Verifica el precio en BingX antes de operar.</i>",
    ]
    return "\n".join(lines)


def format_startup(n_symbols: int, level_mode: str, persist: int, dry_run: bool) -> str:
    mode = "día UTC" if level_mode == "day" else "ventana móvil"
    extra = " · MODO PRUEBA (sin Telegram)" if dry_run else ""
    return (
        f"🤖 <b>Bot de señales activo</b> · {n_symbols} pares BingX · 5m\n"
        f"Ruptura del máximo/mínimo ({mode}), persistencia {persist}.{extra}"
    )
