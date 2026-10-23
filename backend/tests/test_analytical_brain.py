from __future__ import annotations
"""Testes do Cérebro Analítico, Espaço Estrutural Objetivo e Ausência de HTF (Parte 4)."""
import numpy as np
import pandas as pd
import pytest
from app import indicators
from app.analysis import analyze, classify_market_regime, classify_structural_room
from app.config import MODES


def test_missing_htf_blocks_trade():
    n = 200
    times = np.arange(1000, 1000 + n * 60, 60)
    closes = np.linspace(1.1000, 1.1050, n)
    df_raw = pd.DataFrame({
        "time": times,
        "open": closes - 0.0005,
        "high": closes + 0.0010,
        "low": closes - 0.0010,
        "close": closes,
        "tick_volume": np.ones(n) * 100,
    })
    df_m1 = indicators.compute(df_raw)
    tick = {"bid": closes[-1], "ask": closes[-1] + 0.0001, "time": times[-1]}
    sym = {"digits": 5, "point": 0.0001, "spread": 1}
    settings = {"max_spread_points": 25}

    # Quando HTF (M5) está AUSENTE (None), o sistema DEVE bloquear entradas (signal = None)
    res_no_htf = analyze(
        df=df_m1,
        htf_df=None,
        tick=tick,
        sym=sym,
        flow={},
        mode=MODES["LEVE"],
        settings=settings,
        server_now=int(times[-1]),
    )
    assert res_no_htf["signal"] is None
    assert "timeframe superior" in (res_no_htf.get("study_block") or "").lower()


def test_classify_structural_room_objective_levels():
    n = 50
    closes = np.linspace(1.1000, 1.1020, n)
    opens = closes - 0.0002
    highs = closes + 0.0005
    lows = closes - 0.0005
    atr = 0.0010

    # Cria swing high local recente
    highs[-10] = 1.1040
    lows[-15] = 1.0960

    # Para COMPRA (d = +1)
    htf = {"available": True, "trend": 1, "bias21": 1}
    room_buy = classify_structural_room(
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        atr=atr,
        d=1,
        htf_m5=htf,
    )
    assert "status" in room_buy
    assert room_buy["room_atr"] > 0

    # Para VENDA (d = -1)
    room_sell = classify_structural_room(
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        atr=atr,
        d=-1,
        htf_m5=htf,
    )
    assert "status" in room_sell
    assert room_sell["room_atr"] > 0


def test_market_regimes_deterministic():
    htf_up = {"available": True, "trend": 1, "bias21": 1, "rsi": 60.0}
    htf_down = {"available": True, "trend": -1, "bias21": -1, "rsi": 40.0}

    code_up, _ = classify_market_regime(
        price=1.1050,
        e9=1.1045,
        e21=1.1030,
        e200=1.0950,
        adx_v=30.0,
        pdi=28.0,
        mdi=12.0,
        atr=0.0010,
        atr_ratio=1.1,
        atr_points=10.0,
        spread_price=0.0001,
        spread_points=1,
        max_spread=25,
        htf_m5=htf_up,
        htf_m15=htf_up,
        flow_ok=True,
        tick_stale=False,
        buy_strats=[],
        sell_strats=[],
    )
    assert code_up == "TREND_UP"

    code_down, _ = classify_market_regime(
        price=1.0900,
        e9=1.0910,
        e21=1.0925,
        e200=1.1000,
        adx_v=32.0,
        pdi=10.0,
        mdi=30.0,
        atr=0.0010,
        atr_ratio=1.1,
        atr_points=10.0,
        spread_price=0.0001,
        spread_points=1,
        max_spread=25,
        htf_m5=htf_down,
        htf_m15=htf_down,
        flow_ok=True,
        tick_stale=False,
        buy_strats=[],
        sell_strats=[],
    )
    assert code_down == "TREND_DOWN"
