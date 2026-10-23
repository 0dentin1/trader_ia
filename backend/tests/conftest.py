from __future__ import annotations
"""Configuração comum e fixtures do pytest para a suíte quantitativa Trader IA."""
import os
import sys
from pathlib import Path
import pytest

# Garante que 'backend' e o diretório de testes estejam no sys.path
TESTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TESTS_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.mt5_bridge import OrderResult


class MockBridge:
    """Ponte MT5 simulada em memória para testes unitários determinísticos sem MT5 real."""

    def __init__(self, connected: bool = True) -> None:
        self.connected = connected
        self.last_error = (0, "")
        self._positions: list[dict] = []
        self._deals: list[dict] = []
        self._order_counter = 1000

    def is_alive(self) -> bool:
        return self.connected

    def calc_profit(self, symbol: str, side: str, volume: float, price_open: float, price_close: float) -> float:
        d = 1.0 if side.upper() == "BUY" else -1.0
        contract_size = 100000.0 if "EUR" in symbol or "USD" in symbol else 100.0
        return round(d * (price_close - price_open) * volume * contract_size, 2)

    def loss_per_lot(self, symbol: str, side: str, price_open: float, price_sl: float, sym: dict) -> float:
        return abs(self.calc_profit(symbol, side, 1.0, price_open, price_sl))

    def norm_price(self, price: float, sym: dict) -> float:
        digits = int(sym.get("digits", 5))
        return round(float(price), digits)

    def norm_vol(self, lots: float, sym: dict) -> float:
        step = float(sym.get("volume_step", 0.01))
        vmin = float(sym.get("volume_min", 0.01))
        vmax = float(sym.get("volume_max", 100.0))
        snapped = round(round(lots / step) * step, 2)
        return max(vmin, min(vmax, snapped))

    def positions(self, symbol: str | None = None) -> list[dict]:
        if symbol:
            return [p for p in self._positions if p.get("symbol") == symbol]
        return list(self._positions)

    def close_position(self, pos: dict, deviation: int, magic: int, comment: str, sym: dict) -> OrderResult:
        ticket = int(pos.get("ticket", 0))
        self._positions = [p for p in self._positions if int(p.get("ticket", 0)) != ticket]
        return OrderResult(ok=True, retcode=10009, message="Closed", order=ticket, price=float(pos.get("price_current", 1.0)))

    def modify_sltp(self, symbol: str, ticket: int, sl: float, tp: float, magic: int, sym: dict) -> OrderResult:
        for p in self._positions:
            if int(p.get("ticket", 0)) == ticket:
                p["sl"] = float(sl)
                p["tp"] = float(tp)
                return OrderResult(ok=True, retcode=10009, message="Modified", order=ticket)
        return OrderResult(ok=False, retcode=10013, message="Position not found", order=ticket)

    def confirm_or_apply_sltp(
        self,
        symbol: str,
        ticket: int,
        desired_sl: float,
        desired_tp: float,
        magic: int,
        sym: dict,
        max_attempts: int = 3,
    ) -> tuple[bool, float, float, str]:
        for p in self._positions:
            if int(p.get("ticket", 0)) == ticket:
                p["sl"] = float(desired_sl)
                p["tp"] = float(desired_tp)
                return True, float(desired_sl), float(desired_tp), "Confirmado"
        return False, 0.0, 0.0, "Posição não localizada"

    def reconcile_position_after_order(
        self,
        symbol: str,
        magic: int,
        order_res: OrderResult,
        side: str,
        open_after_ts: int = 0,
    ) -> dict | None:
        for p in self._positions:
            if int(p.get("ticket", 0)) == order_res.order:
                return p
        return None


@pytest.fixture
def mock_bridge():
    return MockBridge()
