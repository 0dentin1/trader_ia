from __future__ import annotations
"""Testes de Risco, Proteção de Capital, Travas Persistentes e Separação de P&L (Parte 2 e Parte 3)."""
from pathlib import Path
import pytest
from app.config import MODES
from app.risk import (
    build_plan,
    compute_financial_breakdown,
    evaluate_portfolio_protection,
    is_ai_attributed,
    is_position_sl_confirmed_safe,
    usd_exposure_dir,
)
from app.settings_store import SettingsStore, compute_trading_day, compute_trading_week


def test_persistent_daily_lock_survives_settings_update_and_ai_enable(tmp_path: Path):
    store_file = tmp_path / "settings.json"
    store = SettingsStore(store_file)

    server_time = 1700000000
    day_id = compute_trading_day(server_time, 0)
    week_id = compute_trading_week(server_time, 0)

    # 1. Aciona trava diária
    lock = store.trigger_risk_lock(
        lock_type="DAILY_LOSS_LOCK",
        reason="Limite diário de perda atingido",
        server_day=day_id,
        server_week=week_id,
        scope="TRADER_IA_MAGIC",
    )
    assert lock["active"] is True
    assert store.is_lock_active(day_id, week_id)["active"] is True

    # 2. Atualizar configurações NÃO PODE limpar a trava nem redefinir baseline
    orig_base = store.get("daily_loss_baseline")
    ok, msg = store.update_user(
        {"daily_loss_limit": 100.0, "daily_gain_target": 200.0},
        current_day_total=-60.0,
    )
    assert ok is True
    assert store.is_lock_active(day_id, week_id)["active"] is True
    assert store.get("daily_loss_baseline") == orig_base

    # 3. Desbloqueio manual auditado funciona
    unl_ok, unl_msg = store.manual_unlock_risk_lock(
        operator_note="Desbloqueio autorizado para teste",
        current_day_total=-60.0,
        reset_baseline=True,
    )
    assert unl_ok is True
    assert store.is_lock_active(day_id, week_id)["active"] is False
    assert store.get("daily_loss_baseline") == -60.0


def test_ai_vs_account_pnl_separation():
    magic = 202610
    deals = [
        {"ticket": 1, "position_id": 10, "type_raw": 0, "entry": "IN", "magic": magic, "profit": 0, "swap": 0, "commission": -1, "fee": 0, "time": 100},
        {"ticket": 2, "position_id": 10, "type_raw": 1, "entry": "OUT", "magic": magic, "profit": 50, "swap": 0, "commission": -1, "fee": 0, "time": 200},
        # Deal manual / externo (sem magic da IA)
        {"ticket": 3, "position_id": 20, "type_raw": 0, "entry": "IN", "magic": 0, "profit": 0, "swap": 0, "commission": -2, "fee": 0, "time": 300},
        {"ticket": 4, "position_id": 20, "type_raw": 1, "entry": "OUT", "magic": 0, "profit": -200, "swap": 0, "commission": -2, "fee": 0, "time": 400},
    ]
    open_positions = [
        {"ticket": 101, "magic": magic, "symbol": "EURUSD", "profit": 15.0, "swap": 0.0},
        {"ticket": 202, "magic": 0, "symbol": "PETR4", "profit": -50.0, "swap": 0.0},
    ]
    account = {"balance": 1000.0, "equity": 965.0, "profit": -35.0, "currency": "USD"}
    settings = {"magic": magic, "protect_whole_account": False, "daily_loss_baseline": 0.0, "broker_rollover_hour": 0}

    # Escopo padrão: Apenas Trader IA (magic)
    fin_ai = compute_financial_breakdown(
        all_deals=deals,
        open_positions=open_positions,
        account=account,
        settings=settings,
        magic=magic,
        server_time=500,
    )
    assert fin_ai["ai_realized_today"] == 48.0
    assert fin_ai["ai_floating"] == 15.0
    assert fin_ai["ai_day_total"] == 63.0
    # O resultado governado segue o Trader IA
    assert fin_ai["total"] == 63.0
    assert fin_ai["account_day_total"] == -191.0  # Conta total teve prejuízo manual

    # Escopo governado: Conta Inteira
    settings_whole = dict(settings, protect_whole_account=True)
    fin_whole = compute_financial_breakdown(
        all_deals=deals,
        open_positions=open_positions,
        account=account,
        settings=settings_whole,
        magic=magic,
        server_time=500,
    )
    assert fin_whole["total"] == -191.0
    assert fin_whole["scope_label"] == "CONTA_INTEIRA"


def test_independent_risk_gatekeeper_blocks_excessive_risk_min_lot(mock_bridge):
    # Cenário de Pequena Conta: capital $50 USD
    account = {"balance": 50.0, "equity": 50.0, "currency": "USD", "trade_allowed": True, "trade_expert": True}
    sym = {
        "digits": 5,
        "point": 0.0001,
        "stops_level": 5,
        "volume_min": 0.01,
        "volume_max": 10.0,
        "volume_step": 0.01,
        "trade_mode": 4,
    }
    tick = {"bid": 1.1000, "ask": 1.1001, "time": 1000}
    settings = {
        "account_profile": "SMALL_ACCOUNT_PROTECTION",
        "risk_pct": {"LEVE": 0.25},
        "max_spread_points": 20,
        "daily_loss_limit": 5.0,
        "deviation_points": 20,
    }

    # Com ATR de 0.0050 (50 pips), o risco de 0.01 lote seria ~$5.00 USD (10% da conta de $50!),
    # enquanto o teto máximo permitido para pequena conta é 0.50% ($0.25 USD).
    # O Guardião DEVE bloquear imediatamente com BLOCKED_MIN_LOT em vez de forçar o lote mínimo!
    plan, err = build_plan(
        bridge=mock_bridge,
        symbol="EURUSD",
        sym=sym,
        tick=tick,
        side="BUY",
        atr=0.0050,
        mode=MODES["LEVE"],
        settings=settings,
        account=account,
        server_now=1000,
    )
    assert plan is None
    assert "lote mínimo" in err.lower() or "ultrapassa o risco máximo" in err.lower()


def test_portfolio_protection_and_usd_correlation_block(mock_bridge):
    # Já existem duas posições abertas apostando na alta do USD sem Break-Even confirmado
    open_positions = [
        {"ticket": 101, "symbol": "USDJPY", "type": "BUY", "price_open": 150.0, "sl": 149.0, "volume": 0.01, "profit": 2.0},
        {"ticket": 102, "symbol": "USDCAD", "type": "BUY", "price_open": 1.350, "sl": 1.340, "volume": 0.01, "profit": 1.0},
    ]
    # Ambas estão com SL abaixo da entrada, portanto NÃO estão protegidas no 0x0
    assert not is_position_sl_confirmed_safe(open_positions[0])
    assert not is_position_sl_confirmed_safe(open_positions[1])

    # Candidato 3: EURUSD Venda (aposta em alta do USD!)
    assert usd_exposure_dir("EURUSD", "SELL") == 1

    res = evaluate_portfolio_protection(
        bridge=mock_bridge,
        open_positions=open_positions,
        candidate_symbol="EURUSD",
        candidate_side="SELL",
        max_same_currency_unprotected=2,
    )
    assert res["correlation_blocked_reason"] is not None
    assert "Concentração/correlação cambial" in res["correlation_blocked_reason"]

    # Se a posição 101 tiver SL movido para o preço de entrada (protegida):
    open_positions[0]["sl"] = 150.0
    assert is_position_sl_confirmed_safe(open_positions[0])
    res_ok = evaluate_portfolio_protection(
        bridge=mock_bridge,
        open_positions=open_positions,
        candidate_symbol="EURUSD",
        candidate_side="SELL",
        max_same_currency_unprotected=2,
    )
    assert res_ok["correlation_blocked_reason"] is None
