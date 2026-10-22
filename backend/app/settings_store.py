"""Persistência local das preferências do operador (modo, travas, risco)."""
from __future__ import annotations

import copy
import json
import threading
from typing import Any

from .config import DATA_DIR, DEFAULT_SETTINGS, MODES, SETTINGS_FILE


class SettingsStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict = copy.deepcopy(DEFAULT_SETTINGS)
        self._load()

    def _load(self) -> None:
        if not SETTINGS_FILE.exists():
            return
        try:
            raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for k in DEFAULT_SETTINGS:
            if k in raw:
                self._data[k] = raw[k]
        rp = copy.deepcopy(DEFAULT_SETTINGS["risk_pct"])
        if isinstance(raw.get("risk_pct"), dict):
            rp.update({k: v for k, v in raw["risk_pct"].items() if k in MODES})
        self._data["risk_pct"] = rp
        if self._data.get("mode") not in MODES:
            self._data["mode"] = "LEVE"

    def _save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(SETTINGS_FILE)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return copy.deepcopy(self._data.get(key, default))

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value
            self._save()

    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)

    def update_user(self, patch: dict, current_day_total: float | None = None) -> tuple[bool, str]:
        """Valida e aplica alterações vindas da interface."""
        with self._lock:
            d = copy.deepcopy(self._data)
            try:
                if "daily_loss_limit" in patch:
                    v = float(patch["daily_loss_limit"])
                    if v < 0:
                        return False, "Stop diário não pode ser negativo."
                    d["daily_loss_limit"] = v
                    if current_day_total is not None:
                        d["daily_loss_baseline"] = round(float(current_day_total), 2)
                    d["risk_lock"] = None
                if "daily_gain_target" in patch:
                    v = float(patch["daily_gain_target"])
                    if v < 0:
                        return False, "Meta diária não pode ser negativa."
                    d["daily_gain_target"] = v
                    d["risk_lock"] = None
                if "max_spread_points" in patch:
                    v = int(float(patch["max_spread_points"]))
                    if v <= 0:
                        return False, "Spread máximo deve ser maior que zero."
                    d["max_spread_points"] = v
                if "risk_pct" in patch and isinstance(patch["risk_pct"], dict):
                    for mk, val in patch["risk_pct"].items():
                        if mk not in MODES:
                            continue
                        m = MODES[mk]
                        d["risk_pct"][mk] = min(max(float(val), m.risk_min), m.risk_max)
                if "lot_multiplier" in patch:
                    d["lot_multiplier"] = min(max(float(patch["lot_multiplier"]), 0.1), 10.0)
                if "aggressive_rr" in patch:
                    d["aggressive_rr"] = min(max(float(patch["aggressive_rr"]), 1.0), 1.5)
                if "deviation_points" in patch:
                    d["deviation_points"] = min(max(int(float(patch["deviation_points"])), 1), 500)
                if "sync_chart_symbol" in patch:
                    d["sync_chart_symbol"] = bool(patch["sync_chart_symbol"])
                if "auto_select_symbol" in patch:
                    d["auto_select_symbol"] = bool(patch["auto_select_symbol"])
            except (TypeError, ValueError):
                return False, "Valor inválido nas configurações."
            self._data = d
            self._save()
            return True, "Configurações salvas."
