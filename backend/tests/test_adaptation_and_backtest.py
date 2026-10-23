from __future__ import annotations
"""Testes de Adaptação Controlada e Laboratório de Backtesting (Parte 6 e Parte 7)."""
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from app.adaptive_rules import AdaptiveRulesEngine
from app.backtest import BacktestConfig, run_backtest_segment, run_walk_forward_validation
from app.config import MODES
from app.trade_journal import TradeJournal


def test_adaptive_rules_modes_observation_shadow_active(tmp_path: Path):
    db_file = tmp_path / "test_rules.db"
    journal = TradeJournal(db_file)
    engine = AdaptiveRulesEngine(journal, min_sample_size=20)

    # Cria 25 trades simulados com prejuízo consistente para uma estratégia
    bad_trades = [
        {
            "primary_strategy_id": "BadStrategy",
            "primary_strategy": "BadStrategy",
            "regime_code": "TREND_UP",
            "net_profit": -10.0,
            "won": 0,
        }
        for _ in range(25)
    ]
    engine.refresh_from_history(bad_trades)

    # 1. Modo OBSERVATION: nunca bloqueia ordens reais
    res_obs = engine.evaluate_candidate(
        strategy_id="BadStrategy",
        regime_code="TREND_UP",
        symbol="EURUSD",
        adaptive_mode="OBSERVATION",
        base_min_score=86.0,
    )
    assert res_obs["allowed"] is True
    assert res_obs["effective_min_score"] == 86.0

    # 2. Modo SHADOW: nunca bloqueia ordens reais, mas marca shadow_would_block = True
    res_shadow = engine.evaluate_candidate(
        strategy_id="BadStrategy",
        regime_code="TREND_UP",
        symbol="EURUSD",
        adaptive_mode="SHADOW",
        base_min_score=86.0,
    )
    assert res_shadow["allowed"] is True
    assert res_shadow["shadow_would_block"] is True

    # 3. Modo ACTIVE: se não aprovada explicitamente, mantém allowed = True
    res_act_unapp = engine.evaluate_candidate(
        strategy_id="BadStrategy",
        regime_code="TREND_UP",
        symbol="EURUSD",
        adaptive_mode="ACTIVE",
        base_min_score=86.0,
    )
    assert res_act_unapp["allowed"] is True

    # Habilita explicitamente para ACTIVE: agora DEVE bloquear!
    ok, msg = engine.set_rule_active_approval("BadStrategy::TREND_UP", enabled=True)
    assert ok is True
    res_act_blocked = engine.evaluate_candidate(
        strategy_id="BadStrategy",
        regime_code="TREND_UP",
        symbol="EURUSD",
        adaptive_mode="ACTIVE",
        base_min_score=86.0,
    )
    assert res_act_blocked["allowed"] is False
    assert "ACTIVE BLOCK" in res_act_blocked["block_reason"]


def test_intrabar_ambiguity_conservative_sl_first():
    # Cria uma barra de teste com dados OHLC (>= 160 barras mínimas)
    n = 200
    times = np.arange(1000, 1000 + n * 60, 60)
    closes = np.linspace(1.1000, 1.1020, n)
    df = pd.DataFrame({
        "time": times,
        "open": closes,
        "high": closes + 0.0005,
        "low": closes - 0.0005,
        "close": closes,
        "tick_volume": np.ones(n) * 100,
        "spread": np.ones(n) * 1,
    })
    cfg = BacktestConfig(symbol="EURUSD", mode_key="LEVE", initial_capital=1000.0)
    settings = {"max_spread_points": 25, "risk_pct": {"LEVE": 0.25}, "daily_loss_limit": 50.0, "account_profile": "STANDARD"}

    res = run_backtest_segment(
        df_m1_raw=df,
        cfg=cfg,
        settings_override=settings,
    )
    assert res["ok"] is True
    assert "metrics" in res
    assert res["assumptions"]["intrabar_ambiguity_rule"] == "CONSERVATIVE_SL_FIRST"
