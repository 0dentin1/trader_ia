from __future__ import annotations
"""Testes de Execução, Reconciliação e Confirmação Efetiva de SL/TP (Partes 2.7 e 2.8)."""
import time
import pytest
from app.mt5_bridge import MT5Bridge, OrderResult
from app.risk import build_plan
from app.config import MODES, MAX_TICK_AGE_S


def test_stale_tick_data_blocks_entry(mock_bridge):
    now = int(time.time())
    stale_tick_time = now - (MAX_TICK_AGE_S + 5)
    account = {"balance": 1000.0, "equity": 1000.0, "currency": "USD"}
    sym = {"digits": 5, "point": 0.0001, "volume_min": 0.01, "stops_level": 5, "trade_mode": 2}
    tick = {"bid": 1.1000, "ask": 1.1001, "time": stale_tick_time}
    settings = {"account_profile": "STANDARD", "risk_pct": {"LEVE": 0.25}, "max_spread_points": 20, "daily_loss_limit": 50.0}

    plan, err = build_plan(
        bridge=mock_bridge,
        symbol="EURUSD",
        sym=sym,
        tick=tick,
        side="BUY",
        atr=0.0015,
        mode=MODES["LEVE"],
        settings=settings,
        account=account,
        server_now=now,
    )
    assert plan is None
    assert "desatualizada" in err.lower()


def test_reconcile_position_after_order():
    bridge = MT5Bridge()
    # Cria uma lista de posições simulada
    bridge.positions = lambda s=None: [
        {"ticket": 12345, "symbol": "EURUSD", "magic": 999, "type": "BUY", "volume": 0.02, "price_open": 1.0850, "time": 100},
        {"ticket": 99999, "symbol": "EURUSD", "magic": 888, "type": "BUY", "volume": 0.10, "price_open": 1.0850, "time": 90},
    ]

    order_res = OrderResult(ok=True, retcode=10009, order=12345, deal=55555, volume=0.02, price=1.0850)
    pos = bridge.reconcile_position_after_order(
        symbol="EURUSD",
        magic=999,
        order_res=order_res,
        side="BUY",
        open_after_ts=50,
    )
    assert pos is not None
    assert pos["ticket"] == 12345
    assert pos["magic"] == 999


def test_confirm_or_apply_sltp_verification():
    bridge = MT5Bridge()
    stored_pos = {"ticket": 5001, "symbol": "GBPUSD", "magic": 777, "type": "BUY", "sl": 0.0, "tp": 0.0}
    bridge.positions = lambda s=None: [stored_pos]
    
    # Mock do modify_sltp
    def fake_modify(symbol, ticket, sl, tp, magic, sym):
        stored_pos["sl"] = sl
        stored_pos["tp"] = tp
        return OrderResult(ok=True, retcode=10009, order=ticket)
    bridge.modify_sltp = fake_modify

    sym = {"digits": 5, "point": 0.0001, "stops_level": 5}
    ok, sl_conf, tp_conf, msg = bridge.confirm_or_apply_sltp(
        symbol="GBPUSD",
        ticket=5001,
        desired_sl=1.2500,
        desired_tp=1.2700,
        magic=777,
        sym=sym,
        max_attempts=2,
    )
    assert ok is True
    assert sl_conf == 1.2500
    assert tp_conf == 1.2700
    assert stored_pos["sl"] == 1.2500
