"""Cliente mínimo de los endpoints PÚBLICOS de BingX (perpetuos USDT-M). Sin claves API."""
from __future__ import annotations

import logging
import threading
import time

import pandas as pd
import requests
from requests.adapters import HTTPAdapter

log = logging.getLogger(__name__)


class BingXError(RuntimeError):
    pass


class RateLimiter:
    """Limita las peticiones por segundo entre todos los hilos."""

    def __init__(self, rate_per_sec: float):
        self._interval = 1.0 / max(rate_per_sec, 0.1)
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = (self._next if delay > 0 else now) + self._interval
        if delay > 0:
            time.sleep(delay)


def parse_klines(data) -> pd.DataFrame:
    """Normaliza velas (dict o lista) a columnas time(ms), open, high, low, close, volume."""
    rows = []
    for item in data or []:
        if isinstance(item, dict):
            t = item.get("time", item.get("openTime", item.get("t")))
            rows.append((t, item.get("open"), item.get("high"), item.get("low"), item.get("close"), item.get("volume", 0)))
        else:  # lista: [time, open, high, low, close, volume]
            rows.append((item[0], item[1], item[2], item[3], item[4], item[5] if len(item) > 5 else 0))
    cols = ["time", "open", "high", "low", "close", "volume"]
    df = pd.DataFrame(rows, columns=cols)
    if df.empty:
        return df
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["time", "open", "high", "low", "close"])
    df["time"] = df["time"].astype("int64")
    return df.drop_duplicates("time").sort_values("time").reset_index(drop=True)


class BingXClient:
    BASE_URL = "https://open-api.bingx.com"
    KLINES_V3 = "/openApi/swap/v3/quote/klines"
    KLINES_V2 = "/openApi/swap/v2/quote/klines"

    def __init__(self, req_per_sec: float = 8.0, timeout: float = 10.0, klines_path: str | None = None):
        self._session = requests.Session()
        adapter = HTTPAdapter(pool_connections=16, pool_maxsize=16)
        self._session.mount("https://", adapter)
        self._limiter = RateLimiter(req_per_sec)
        self._timeout = timeout
        self._klines_path = klines_path or self.KLINES_V3

    def _get(self, path: str, params: dict | None = None):
        last: Exception | None = None
        for attempt in range(3):
            self._limiter.wait()
            try:
                r = self._session.get(self.BASE_URL + path, params=params, timeout=self._timeout)
                if r.status_code == 429:
                    time.sleep(1.5 * (attempt + 1))
                    last = BingXError("HTTP 429")
                    continue
                r.raise_for_status()
                payload = r.json()
            except (requests.RequestException, ValueError) as exc:
                last = exc
                time.sleep(0.5 * (attempt + 1))
                continue
            if payload.get("code", 0) != 0:
                raise BingXError(f"{path}: code={payload.get('code')} msg={payload.get('msg')}")
            return payload.get("data")
        raise BingXError(f"{path}: {type(last).__name__ if last else 'error'}")

    def contracts(self) -> list[dict]:
        return self._get("/openApi/swap/v2/quote/contracts") or []

    def quote_volumes(self) -> dict[str, float]:
        """Volumen 24h en USDT por símbolo (si el endpoint lo permite; si no, {})."""
        try:
            data = self._get("/openApi/swap/v2/quote/ticker")
        except BingXError as exc:
            log.warning("No se pudo leer el ticker 24h: %s", exc)
            return {}
        if isinstance(data, dict):
            data = [data]
        out: dict[str, float] = {}
        for row in data or []:
            sym = row.get("symbol")
            try:
                if row.get("quoteVolume") is not None:
                    out[sym] = float(row["quoteVolume"])
                else:
                    out[sym] = float(row["volume"]) * float(row["lastPrice"])
            except (KeyError, TypeError, ValueError):
                continue
        return out

    def klines(self, symbol: str, interval: str = "5m", limit: int = 400) -> pd.DataFrame:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        paths = [self._klines_path] + [p for p in (self.KLINES_V3, self.KLINES_V2) if p != self._klines_path]
        last: BingXError | None = None
        for path in paths:
            try:
                df = parse_klines(self._get(path, params))
            except BingXError as exc:
                last = exc
                continue
            if path != self._klines_path and not df.empty:
                log.warning("Usando %s para velas (fallback)", path)
                self._klines_path = path
            return df
        raise last or BingXError("klines: sin respuesta")
