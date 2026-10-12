"""Escáner de todos los perpetuos USDT de BingX: evalúa la estrategia al cierre de cada vela de 5m."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .bingx import BingXClient, BingXError
from .config import Settings
from .messages import format_signal, format_startup
from .strategy import BAR_MS, DAY_MS, Signal, daily_stats, evaluate
from .telegram import Telegram

log = logging.getLogger(__name__)


class Scanner:
    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self.params = cfg.params
        self.client = BingXClient(cfg.req_per_sec, klines_path=cfg.klines_path or None)
        self.tg = Telegram(cfg.telegram_token, cfg.telegram_chat_ids, cfg.dry_run)
        self.symbols: list[str] = []
        self._daily: dict[str, tuple[int, tuple[float, float] | None]] = {}
        self._seen: dict[str, int] = {}
        self._last_alert = 0.0
        self._universe_ts = 0.0

    # ------------------------------------------------------------------ universo
    def refresh_universe(self) -> None:
        cfg = self.cfg
        vols: dict[str, float] = {}
        if cfg.symbols:
            syms = list(cfg.symbols)
        else:
            syms = []
            for c in self.client.contracts():
                sym = str(c.get("symbol", ""))
                if sym.endswith("-USDT") and str(c.get("status", "1")) == "1":
                    syms.append(sym)
            if cfg.min_quote_volume > 0:
                vols = self.client.quote_volumes()
                if vols:
                    syms = [s for s in syms if vols.get(s, 0.0) >= cfg.min_quote_volume]
                else:
                    log.warning("Sin datos de volumen 24h: no se filtra por liquidez")
        excluded = {s.upper() for s in cfg.exclude}
        syms = [s for s in syms if s.upper() not in excluded]
        syms.sort(key=lambda s: -vols.get(s, 0.0))
        self.symbols = syms[: cfg.max_symbols]
        self._universe_ts = time.time()
        log.info("Universo: %d pares", len(self.symbols))

    # ------------------------------------------------------------------ datos
    def _daily_stats(self, sym: str, day_start_ms: int):
        day_id = day_start_ms // DAY_MS
        cached = self._daily.get(sym)
        if cached and cached[0] == day_id:
            return cached[1]
        df = self.client.klines(sym, "1d", self.params.adr_len + 6)
        stats = daily_stats(df, day_start_ms, self.params.adr_len)
        self._daily[sym] = (day_id, stats)
        return stats

    def _work(self, sym: str, now_ms: int, day_start_ms: int):
        stats = self._daily_stats(sym, day_start_ms)
        if stats is None:
            return None, "sin ADR"
        df = self.client.klines(sym, "5m", self.cfg.klines_limit)
        df = df[df["time"] + BAR_MS <= now_ms]            # solo velas CERRADAS
        if df.empty:
            return None, "sin datos"
        age = now_ms - (int(df["time"].iloc[-1]) + BAR_MS)
        if age > self.cfg.max_age_bars * BAR_MS:
            return None, "datos viejos"
        return evaluate(sym, df.reset_index(drop=True), stats[0], stats[1], self.params), None

    # ------------------------------------------------------------------ escaneo
    def scan_once(self, now: float | None = None) -> list[Signal]:
        now = time.time() if now is None else now
        now_ms = int(now * 1000)
        day_start_ms = (now_ms // DAY_MS) * DAY_MS
        t0 = time.time()
        found: list[Signal] = []
        errors = skipped = 0

        with ThreadPoolExecutor(max_workers=self.cfg.workers) as ex:
            futures = {ex.submit(self._work, s, now_ms, day_start_ms): s for s in self.symbols}
            for fut in as_completed(futures):
                sym = futures[fut]
                try:
                    sig, why = fut.result()
                except BingXError as exc:
                    errors += 1
                    log.debug("%s: %s", sym, exc)
                    continue
                except Exception:
                    errors += 1
                    log.exception("%s: error inesperado", sym)
                    continue
                if why:
                    skipped += 1
                if sig is not None:
                    found.append(sig)

        sent = 0
        for sig in sorted(found, key=lambda s: s.symbol):
            key = f"{sig.symbol}:{sig.side}:{sig.bar_time_ms}"
            if key in self._seen:
                continue
            self._seen[key] = sig.bar_time_ms
            msg = format_signal(sig, self.cfg.account_usdt, self.cfg.risk_pct, self.cfg.max_leverage, self.cfg.tp_r)
            self.tg.send(msg)
            sent += 1
            log.info("Señal %s %s @ %s", sig.side, sig.symbol, sig.close)

        cutoff = now_ms - 2 * DAY_MS
        self._seen = {k: v for k, v in self._seen.items() if v >= cutoff}

        n = max(1, len(self.symbols))
        log.info("Escaneo: %d pares · %d señales nuevas · %d omitidos · %d errores · %.1fs",
                 len(self.symbols), sent, skipped, errors, time.time() - t0)
        if errors / n > 0.5:
            self._alert(f"⚠️ Fallan {errors}/{n} peticiones a BingX. Revisa los logs de Railway.")
        return found

    def _alert(self, text: str) -> None:
        if time.time() - self._last_alert > 1800:      # máx. 1 aviso cada 30 min
            self._last_alert = time.time()
            self.tg.send(text)

    # ------------------------------------------------------------------ bucle
    def run_forever(self) -> None:
        self.refresh_universe()
        self.tg.send(format_startup(len(self.symbols), self.params.level_mode, self.params.persist_bars, self.cfg.dry_run))
        while True:
            now = time.time()
            nxt = (now // 300 + 1) * 300 + self.cfg.scan_delay_sec
            time.sleep(max(0.0, nxt - now))
            if time.time() - self._universe_ts > self.cfg.universe_refresh_hours * 3600:
                try:
                    self.refresh_universe()
                except Exception:
                    log.exception("No se pudo refrescar el universo; se mantiene el anterior")
            try:
                self.scan_once()
            except Exception:
                log.exception("Fallo en el escaneo")
                self._alert("⚠️ Error inesperado en el escaneo. Revisa los logs de Railway.")
