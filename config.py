"""Configuración a partir de variables de entorno (ver .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass

from .strategy import Params


def _raw(name: str) -> str | None:
    v = os.getenv(name)
    return None if v is None or v.strip() == "" else v.strip()


def _bool(name: str, default: bool) -> bool:
    v = _raw(name)
    return default if v is None else v.lower() in {"1", "true", "yes", "y", "si", "sí", "on"}


def _float(name: str, default: float) -> float:
    v = _raw(name)
    if v is None:
        return default
    try:
        return float(v.replace(",", "."))
    except ValueError:
        raise ValueError(f"{name} debe ser un número, recibido: {v!r}") from None


def _int(name: str, default: int) -> int:
    return int(_float(name, default))


def _list(name: str) -> list[str]:
    v = _raw(name)
    return [] if v is None else [x.strip() for x in v.split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    telegram_chat_ids: list[str]
    dry_run: bool
    symbols: list[str]
    exclude: list[str]
    min_quote_volume: float
    max_symbols: int
    universe_refresh_hours: float
    req_per_sec: float
    workers: int
    scan_delay_sec: int
    klines_limit: int
    max_age_bars: int
    klines_path: str
    params: Params
    account_usdt: float
    risk_pct: float
    max_leverage: float
    tp_r: list[float]
    log_level: str


def load_settings() -> Settings:
    dry_run = _bool("DRY_RUN", False)
    token = _raw("TELEGRAM_BOT_TOKEN") or ""
    chats = _list("TELEGRAM_CHAT_ID")
    if not dry_run and (not token or not chats):
        raise ValueError(
            "Faltan TELEGRAM_BOT_TOKEN y/o TELEGRAM_CHAT_ID (o usa DRY_RUN=1 para probar sin Telegram)."
        )

    level_mode = (_raw("LEVEL_MODE") or "day").lower()
    if level_mode not in {"day", "rolling"}:
        raise ValueError("LEVEL_MODE debe ser 'day' o 'rolling'.")

    params = Params(
        level_mode=level_mode,
        roll_len=_int("ROLL_LEN", 288),
        warmup_bars=_int("WARMUP_BARS", 36),
        persist_bars=max(1, _int("PERSIST_BARS", 2)),
        allow_long=_bool("ALLOW_LONG", True),
        allow_short=_bool("ALLOW_SHORT", True),
        adr_len=_int("ADR_LEN", 20),
        use_dm=_bool("USE_DM", True),
        dm_min=_float("DM_MIN", 0.15),
        use_room=_bool("USE_ROOM", True),
        room_thr=_float("ROOM_THR", 1.0),
        use_quiet=_bool("USE_QUIET", True),
        quiet_span=_float("QUIET_SPAN", 0.6),
        atr_len=_int("ATR_LEN", 14),
        stop_atr=_float("STOP_ATR", 2.0),
        use_cost_filter=_bool("USE_COST_FILTER", True),
        rt_cost_pct=_float("RT_COST_PCT", 0.12),
        max_cost_r=_float("MAX_COST_R", 0.20),
        use_hours=_bool("USE_HOURS", False),
        hours_from=_int("HOURS_FROM", 7),
        hours_to=_int("HOURS_TO", 21),
        eod_block=_bool("EOD_BLOCK", True),
        max_signals_per_day=max(1, _int("MAX_SIGNALS_PER_DAY", 2)),
    )

    return Settings(
        telegram_token=token,
        telegram_chat_ids=chats,
        dry_run=dry_run,
        symbols=_list("SYMBOLS"),
        exclude=_list("EXCLUDE"),
        min_quote_volume=_float("MIN_QUOTE_VOLUME_USDT", 3_000_000.0),
        max_symbols=_int("MAX_SYMBOLS", 400),
        universe_refresh_hours=_float("UNIVERSE_REFRESH_HOURS", 6.0),
        req_per_sec=_float("REQ_PER_SEC", 8.0),
        workers=max(1, _int("WORKERS", 8)),
        scan_delay_sec=_int("SCAN_DELAY_SEC", 10),
        klines_limit=min(1440, max(300, _int("KLINES_LIMIT", 400))),
        max_age_bars=max(1, _int("MAX_AGE_BARS", 2)),
        klines_path=_raw("BINGX_KLINES_PATH") or "",
        params=params,
        account_usdt=_float("ACCOUNT_USDT", 1000.0),
        risk_pct=_float("RISK_PCT", 0.5),
        max_leverage=_float("MAX_LEVERAGE", 3.0),
        tp_r=[float(x.replace(",", ".")) for x in _list("TP_R")] or [2.0, 3.0],
        log_level=(_raw("LOG_LEVEL") or "INFO").upper(),
    )
