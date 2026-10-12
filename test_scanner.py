import pandas as pd

from bot.config import load_settings
from bot.scanner import Scanner
from bot.strategy import BAR_MS, DAY_MS
from tests.test_strategy import T0, build, long_closes


class FakeClient:
    def contracts(self):
        return [
            {"symbol": "AAA-USDT", "status": 1},
            {"symbol": "BBB-USDT", "status": 1},      # poco volumen: se filtra
            {"symbol": "OLD-USDT", "status": 0},      # fuera de servicio: se ignora
            {"symbol": "EURUSD", "status": 1},        # no es -USDT: se ignora
        ]

    def quote_volumes(self):
        return {"AAA-USDT": 9e6, "BBB-USDT": 1e6, "OLD-USDT": 9e6}

    def klines(self, symbol, interval="5m", limit=400):
        if interval == "1d":
            days = 25
            t = [T0 - (days - i) * DAY_MS for i in range(days)]
            return pd.DataFrame({"time": t, "open": 100.0, "high": 101.5, "low": 98.5, "close": 100.0, "volume": 1.0})
        df = build(long_closes())
        # vela EN CURSO (aún sin cerrar): debe ignorarse
        live = pd.DataFrame([{"time": T0 + 62 * BAR_MS, "open": 101.2, "high": 110.0, "low": 90.0, "close": 105.0, "volume": 1.0}])
        return pd.concat([df, live], ignore_index=True)


def make_scanner(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    sc = Scanner(load_settings())
    sc.client = FakeClient()
    sent = []
    sc.tg.send = lambda text: sent.append(text) or True
    return sc, sent


def test_universe_filters(monkeypatch):
    sc, _ = make_scanner(monkeypatch)
    sc.refresh_universe()
    assert sc.symbols == ["AAA-USDT"]


def test_scan_sends_signal_once(monkeypatch):
    sc, sent = make_scanner(monkeypatch)
    sc.refresh_universe()
    now = (T0 + 62 * BAR_MS) / 1000.0 + 10          # 10 s después del cierre de la vela de señal
    found = sc.scan_once(now)
    assert len(found) == 1 and found[0].side == "LONG"
    assert len(sent) == 1 and "AAA-USDT" in sent[0]
    sc.scan_once(now + 20)                           # misma vela: no se repite
    assert len(sent) == 1


def test_stale_data_is_ignored(monkeypatch):
    sc, sent = make_scanner(monkeypatch)
    sc.refresh_universe()
    now = (T0 + 62 * BAR_MS) / 1000.0 + 3600         # los datos tienen 1 h de retraso
    assert sc.scan_once(now) == []
    assert sent == []
