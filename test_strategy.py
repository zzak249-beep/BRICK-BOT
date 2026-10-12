import numpy as np
import pandas as pd
import pytest

from bot.bingx import parse_klines
from bot.messages import format_signal, suggest_size
from bot.strategy import BAR_MS, DAY_MS, Params, daily_stats, evaluate

T0 = 1_704_153_600_000  # 2024-01-02 00:00:00 UTC
ADR = 3.0


def build(closes, wick=0.2, start_ms=T0 - 288 * BAR_MS, first_open=None):
    closes = list(closes)
    opens = [closes[0] if first_open is None else first_open] + closes[:-1]
    hi = [max(o, c) + wick for o, c in zip(opens, closes)]
    lo = [min(o, c) - wick for o, c in zip(opens, closes)]
    t = [start_ms + i * BAR_MS for i in range(len(closes))]
    return pd.DataFrame({"time": t, "open": opens, "high": hi, "low": lo, "close": closes, "volume": 1.0})


def long_closes(prev_osc=True):
    # día anterior (288 velas) y 60 velas del día en curso oscilando alrededor de 100
    osc = [100.3, 99.7] * 144
    today = [100.3, 99.7] * 30
    return osc + today + [101.0, 101.2]          # velas 60 y 61: ruptura y persistencia


def mirror(df):
    m = df.copy()
    m["open"], m["close"] = 200 - df["open"], 200 - df["close"]
    m["high"], m["low"] = 200 - df["low"], 200 - df["high"]
    return m


def test_long_signal_on_second_close():
    df = build(long_closes())
    sig = evaluate("TEST-USDT", df, ADR, 3.0, Params())
    assert sig is not None and sig.side == "LONG"
    assert sig.bar_time_ms == int(df["time"].iloc[-1])
    assert sig.risk_dist == pytest.approx(2.0 * sig.atr)
    assert sig.stop == pytest.approx(sig.close - sig.risk_dist)
    assert sig.dm_adr >= 0.15 and 0 < sig.room_adr <= 1.0 and sig.rank_today == 1


def test_no_signal_on_first_close_with_persistence_2():
    df = build(long_closes()).iloc[:-1]
    assert evaluate("TEST-USDT", df, ADR, 3.0, Params()) is None


def test_persistence_1_signals_on_first_close():
    df = build(long_closes()).iloc[:-1]
    sig = evaluate("TEST-USDT", df, ADR, 3.0, Params(persist_bars=1))
    assert sig is not None and sig.side == "LONG"


def test_short_is_mirror_of_long():
    df = mirror(build(long_closes()))
    sig = evaluate("TEST-USDT", df, ADR, 3.0, Params())
    assert sig is not None and sig.side == "SHORT"
    assert sig.stop == pytest.approx(sig.close + sig.risk_dist)


def test_warmup_blocks_signal():
    df = build(long_closes())
    assert evaluate("TEST-USDT", df, ADR, 3.0, Params(warmup_bars=100)) is None


def test_quiet_day_blocks_signal():
    df = build(long_closes())
    assert evaluate("TEST-USDT", df, ADR, 1.0, Params()) is None          # ayer: 1.0 < 0.6*3.0 = 1.8
    assert evaluate("TEST-USDT", df, ADR, 1.0, Params(use_quiet=False)) is not None


def test_cost_filter_blocks_signal():
    df = build(long_closes())
    assert evaluate("TEST-USDT", df, ADR, 3.0, Params(max_cost_r=0.01)) is None
    assert evaluate("TEST-USDT", df, ADR, 3.0, Params(max_cost_r=0.01, use_cost_filter=False)) is not None


def test_bias_filter_blocks_signal():
    df = build(long_closes())
    assert evaluate("TEST-USDT", df, 50.0, 50.0, Params()) is None        # ADR enorme: sesgo insuficiente


def test_direction_toggles():
    df = build(long_closes())
    assert evaluate("TEST-USDT", df, ADR, 3.0, Params(allow_long=False)) is None


def test_eod_block():
    # día en curso largo: la vela de señal cae a las 23:05 UTC
    closes = [100.3, 99.7] * 144 + [100.3, 99.7] * 138 + [101.0, 101.2]
    df = build(closes)
    last_hour = (int(df["time"].iloc[-1]) // 3_600_000) % 24
    assert last_hour == 23
    assert evaluate("TEST-USDT", df, ADR, 3.0, Params()) is None                    # bloqueada por EOD
    assert evaluate("TEST-USDT", df, ADR, 3.0, Params(eod_block=False)) is not None  # sin el bloqueo sí hay señal


def test_signal_must_be_on_last_bar():
    df = build(long_closes() + [101.1])           # una vela más: la señal ya no es la última
    assert evaluate("TEST-USDT", df, ADR, 3.0, Params()) is None


def test_daily_stats_excludes_today():
    days = 25
    t = [T0 - (days - i) * DAY_MS for i in range(days)] + [T0]
    high = [102.0] * days + [150.0]
    low = [100.0] * days + [50.0]                 # la vela de HOY (rango 100) no debe contar
    d = pd.DataFrame({"time": t, "open": 101.0, "high": high, "low": low, "close": 101.0, "volume": 1.0})
    adr, prev = daily_stats(d, T0, 20)
    assert adr == pytest.approx(2.0) and prev == pytest.approx(2.0)
    assert daily_stats(d.iloc[:5], T0, 20) is None


def test_parse_klines_dict_and_list():
    rows = [
        {"open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "10", "time": 2000},
        {"open": "1", "high": "2", "low": "0.5", "close": "1.4", "volume": "10", "time": 1000},
        {"open": "1", "high": "2", "low": "0.5", "close": "1.4", "volume": "10", "time": 1000},   # duplicada
    ]
    df = parse_klines(rows)
    assert list(df["time"]) == [1000, 2000] and df["close"].iloc[1] == 1.5
    df2 = parse_klines([[1000, 1, 2, 0.5, 1.4, 10], [2000, 1, 2, 0.5, 1.5, 10]])
    assert list(df2["time"]) == [1000, 2000]
    assert parse_klines(None).empty


def test_size_cap_and_message():
    df = build(long_closes())
    sig = evaluate("BTC-USDT", df, ADR, 3.0, Params())
    qty, notional, risk, capped = suggest_size(sig, 1000.0, 0.5, 3.0)
    assert notional <= 3000.0 + 1e-6 and risk <= 5.0 + 1e-6
    qty2, notional2, risk2, capped2 = suggest_size(sig, 1000.0, 0.5, 0.01)
    assert capped2 and notional2 == pytest.approx(10.0)
    msg = format_signal(sig, 1000.0, 0.5, 3.0, [2.0, 3.0])
    assert "LONG" in msg and "BTC-USDT" in msg and "TP 2R" in msg and "TP 3R" in msg


def test_rolling_mode_runs():
    closes = [100.3, 99.7] * 200 + [101.0, 101.2]
    df = build(closes, start_ms=T0 - 400 * BAR_MS)
    sig = evaluate("TEST-USDT", df, ADR, 3.0, Params(level_mode="rolling", roll_len=288, dm_min=0.0))
    assert sig is None or sig.side == "LONG"
