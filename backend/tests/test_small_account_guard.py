from __future__ import annotations
"""Testes de Proteção de Pequenas Contas (R$ 50, 100, 500, 1000), Estados de Drawdown e Zero Martingale (Parte 3)."""
import pytest
from app.small_account_guard import (
    classify_drawdown_state,
    evaluate_small_account_guard,
    required_recovery_gain_pct,
)


def test_required_recovery_gain_pct_asymmetry():
    # Perda de 5% requer ganho de ~5.26%
    assert round(required_recovery_gain_pct(5.0), 2) == 5.26
    # Perda de 10% requer ganho de 11.11%
    assert round(required_recovery_gain_pct(10.0), 2) == 11.11
    # Perda de 50% requer ganho de 100.00%
    assert round(required_recovery_gain_pct(50.0), 2) == 100.00


def test_progressive_drawdown_states():
    # 1. Normal (perda diária $3 em limite de $10)
    s1, scale1, _, _, _, _ = classify_drawdown_state(
        current_equity=1000.0,
        session_start_equity=1000.0,
        week_start_equity=1000.0,
        peak_equity=1000.0,
        session_loss_pnl=-3.0,
        weekly_loss_pnl=-5.0,
        session_limit_money=10.0,
        weekly_limit_money=30.0,
    )
    assert s1 == "NORMAL"
    assert scale1 == 1.0

    # 2. Caution (atingiu 50% do limite da sessão: perda de $6 em limite de $10)
    s2, scale2, _, _, _, _ = classify_drawdown_state(
        current_equity=994.0,
        session_start_equity=1000.0,
        week_start_equity=1000.0,
        peak_equity=1000.0,
        session_loss_pnl=-6.0,
        weekly_loss_pnl=-6.0,
        session_limit_money=10.0,
        weekly_limit_money=30.0,
    )
    assert s2 == "CAUTION"
    assert scale2 == 0.75

    # 3. Reduced exposure (atingiu 75% do limite da sessão: perda de $8 em limite de $10)
    s3, scale3, _, _, _, _ = classify_drawdown_state(
        current_equity=992.0,
        session_start_equity=1000.0,
        week_start_equity=1000.0,
        peak_equity=1000.0,
        session_loss_pnl=-8.0,
        weekly_loss_pnl=-8.0,
        session_limit_money=10.0,
        weekly_limit_money=30.0,
    )
    assert s3 == "REDUCED_EXPOSURE"
    assert scale3 == 0.50

    # 4. Trading locked (perda >= limite da sessão de 1.0%)
    s4, scale4, _, _, _, _ = classify_drawdown_state(
        current_equity=989.0,
        session_start_equity=1000.0,
        week_start_equity=1000.0,
        peak_equity=1000.0,
        session_loss_pnl=-11.0,
        weekly_loss_pnl=-11.0,
        session_limit_money=10.0,
        weekly_limit_money=30.0,
    )
    assert s4 == "TRADING_LOCKED"
    assert scale4 == 0.0


@pytest.mark.parametrize("capital, currency", [
    (50.0, "BRL"),
    (100.0, "BRL"),
    (500.0, "BRL"),
    (1000.0, "BRL"),
    (100.0, "USD"),
])
def test_small_account_guard_profiles(capital: float, currency: str):
    account = {"balance": capital, "equity": capital, "currency": currency}
    sym = {"volume_min": 0.01, "volume_max": 10.0, "point": 0.0001}
    settings = {
        "account_profile": "SMALL_ACCOUNT_PROTECTION",
        "session_loss_limit_pct": 1.0,
        "weekly_drawdown_limit_pct": 3.0,
    }

    # Se a perda no stop for minúscula (adequada ao capital de 0.25%)
    target_risk_money = capital * 0.0025
    eval_safe = evaluate_small_account_guard(
        account=account,
        sym=sym,
        settings=settings,
        requested_risk_pct=0.25,
        loss_per_lot_at_sl=target_risk_money / 0.01,
        estimated_costs_per_lot=(target_risk_money * 0.1) / 0.01,
        final_volume=0.01,
        margin_required=0.0,
        open_portfolio_risk_money=0.0,
        session_pnl=0.0,
        weekly_pnl=0.0,
    )
    assert eval_safe.approved is True
    assert eval_safe.target_risk_pct <= 0.25

    # Se a perda no stop do lote mínimo exceder o teto seguro (ex: R$ 5 em conta de R$ 50 = 10%!)
    eval_blocked = evaluate_small_account_guard(
        account=account,
        sym=sym,
        settings=settings,
        requested_risk_pct=0.25,
        loss_per_lot_at_sl=500.0,  # 0.01 * 500 = 5.0 da moeda da conta
        estimated_costs_per_lot=50.0,
        final_volume=0.01,
        margin_required=0.0,
        open_portfolio_risk_money=0.0,
        session_pnl=0.0,
        weekly_pnl=0.0,
    )
    if 5.5 > (capital * 0.0050):
        assert eval_blocked.approved is False
        assert eval_blocked.status == "BLOCKED_MIN_LOT"
