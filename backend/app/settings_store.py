"""Persistência local das preferências do operador, estado de sessão e Circuito de Proteção Persistente."""
from __future__ import annotations

import copy
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import (
    ACCOUNT_PROFILES,
    ADAPTIVE_MODES,
    DATA_DIR,
    DEFAULT_SETTINGS,
    MODES,
    SETTINGS_FILE,
)


def compute_trading_day(server_time: int, rollover_hour: int = 0) -> int:
    """Calcula o identificador único do dia de negociação usando o horário do servidor da corretora."""
    if not server_time or server_time <= 0:
        return 0
    shifted = int(server_time) - int(rollover_hour) * 3600
    return shifted // 86400


def compute_trading_week(server_time: int, rollover_hour: int = 0) -> int:
    """Calcula a semana de negociação no horário do servidor (1970-01-01 foi quinta-feira -> +3 dias p/ segunda)."""
    day = compute_trading_day(server_time, rollover_hour)
    if day <= 0:
        return 0
    return (day + 3) // 7


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._path = path or SETTINGS_FILE
        self._data: dict = copy.deepcopy(DEFAULT_SETTINGS)
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for k in DEFAULT_SETTINGS:
            if k in raw:
                self._data[k] = raw[k]
        rp = copy.deepcopy(DEFAULT_SETTINGS["risk_pct"])
        if isinstance(raw.get("risk_pct"), dict):
            rp.update({k: v for k, v in raw["risk_pct"].items() if k in MODES})
        self._data["risk_pct"] = rp
        ss = copy.deepcopy(DEFAULT_SETTINGS["session_state"])
        if isinstance(raw.get("session_state"), dict):
            ss.update(raw["session_state"])
        self._data["session_state"] = ss
        if self._data.get("mode") not in MODES:
            self._data["mode"] = "MEDIANO"
        if self._data.get("account_profile") not in ACCOUNT_PROFILES:
            self._data["account_profile"] = "SMALL_ACCOUNT_PROTECTION"
        if self._data.get("adaptive_mode") not in ADAPTIVE_MODES:
            self._data["adaptive_mode"] = "OBSERVATION"

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return copy.deepcopy(self._data.get(key, default))

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = copy.deepcopy(value)
            self._save()

    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)

    # ------------------------------------------------------------------ gestão de trava de risco persistente
    def is_lock_active(self, server_day: int | None, server_week: int | None = None) -> dict:
        """
        Verifica se há bloqueio de risco ativo para o dia/semana atuais do servidor.
        Sobrevive a reinicializações, desligar/ligar a IA e edições de configuração.
        """
        with self._lock:
            lock = self._data.get("risk_lock")
            if not isinstance(lock, dict):
                return {"active": False, "lock_type": None, "reason": None, "at": None, "details": None}

            lock_type = str(lock.get("lock_type") or "DAILY_LOSS")
            lock_day = lock.get("day")
            lock_week = lock.get("week")

            if lock_type == "CRITICAL_EXECUTION_FAILURE":
                active = True
            elif lock_type == "WEEKLY_DRAWDOWN":
                if server_week is not None and lock_week is not None:
                    active = int(lock_week) == int(server_week)
                elif server_day is not None and lock_day is not None:
                    active = int(lock_day) == int(server_day)
                else:
                    active = True
            else:
                # DAILY_LOSS ou DAILY_GAIN: permanece ativo durante todo o dia de negociação do servidor
                if server_day is None or lock_day is None:
                    active = True
                else:
                    active = int(lock_day) == int(server_day)

            return {
                "active": active,
                "lock_type": lock_type if active else None,
                "reason": lock.get("reason") if active else None,
                "at": lock.get("at") if active else None,
                "details": copy.deepcopy(lock) if active else None,
            }

    def trigger_risk_lock(
        self,
        lock_type: str,
        reason: str,
        server_day: int | None,
        server_week: int | None = None,
        pnl_at_lock: float = 0.0,
        limit_value: float = 0.0,
        baseline: float = 0.0,
        server_time: int = 0,
        scope: str = "TRADER_IA_MAGIC",
    ) -> dict:
        """Registra e persiste imediatamente um bloqueio de circuito (Circuit Breaker)."""
        with self._lock:
            now_iso = datetime.now(timezone.utc).isoformat()
            lock_obj = {
                "active": True,
                "lock_type": lock_type,
                "day": int(server_day) if server_day is not None else 0,
                "week": int(server_week) if server_week is not None else 0,
                "reason": reason,
                "at": now_iso,
                "scope": scope,
                "server_time": int(server_time or 0),
                "pnl_at_lock": round(float(pnl_at_lock), 2),
                "limit_value": round(float(limit_value), 2),
                "baseline": round(float(baseline), 2),
            }
            self._data["risk_lock"] = lock_obj
            if lock_type in ("DAILY_LOSS", "DAILY_LOSS_LOCK", "WEEKLY_DRAWDOWN", "WEEKLY_LOSS_LOCK", "DRAWDOWN_LOCK"):
                self._data["session_state"]["drawdown_state"] = "TRADING_LOCKED"
            elif lock_type in ("CRITICAL_EXECUTION_FAILURE", "EXECUTION_LOCK"):
                self._data["session_state"]["drawdown_state"] = "REVIEW_REQUIRED"
            self._save()
            return copy.deepcopy(lock_obj)

    def sync_session_rollover(
        self,
        server_time: int,
        current_equity: float = 0.0,
        current_ai_day_pnl: float = 0.0,
        current_day_total: float = 0.0,
        current_week_total: float = 0.0,
        **extra,
    ) -> dict:
        """
        Sincroniza o relógio do servidor com a sessão atual:
        - Inicializa equity de referência no início do dia e da semana.
        - Só destrava bloqueios diários quando um NOVO dia de negociação se inicia no servidor.
        - Só destrava bloqueios semanais quando uma NOVA semana se inicia no servidor.
        """
        with self._lock:
            rollover_h = int(self._data.get("session_rollover_hour") or 0)
            s_day = compute_trading_day(server_time, rollover_h)
            s_week = compute_trading_week(server_time, rollover_h)
            ss = self._data["session_state"]
            changed = False
            lock_cleared = False

            if s_day > 0 and ss.get("trading_day") != s_day:
                prev_day = ss.get("trading_day")
                ss["trading_day"] = s_day
                if current_equity > 0:
                    ss["session_start_equity"] = round(float(current_equity), 2)
                    ss["peak_equity"] = max(float(ss.get("peak_equity") or 0.0), float(current_equity))
                # Novo dia de negociação: zera baseline diário e limpa apenas travas de dia anterior
                self._data["daily_loss_baseline"] = 0.0
                lock = self._data.get("risk_lock")
                if isinstance(lock, dict):
                    lt = lock.get("lock_type")
                    ld = int(lock.get("day") or 0)
                    if lt in ("DAILY_LOSS", "DAILY_GAIN") and prev_day is not None and ld < s_day:
                        self._data["risk_lock"] = None
                        lock_cleared = True
                        if ss.get("drawdown_state") == "TRADING_LOCKED":
                            ss["drawdown_state"] = "NORMAL"
                changed = True

            if s_week > 0 and ss.get("trading_week") != s_week:
                prev_week = ss.get("trading_week")
                ss["trading_week"] = s_week
                if current_equity > 0:
                    ss["week_start_equity"] = round(float(current_equity), 2)
                lock = self._data.get("risk_lock")
                if isinstance(lock, dict):
                    if lock.get("lock_type") == "WEEKLY_DRAWDOWN" and prev_week is not None and int(lock.get("week") or 0) < s_week:
                        self._data["risk_lock"] = None
                        lock_cleared = True
                        ss["drawdown_state"] = "NORMAL"
                changed = True

            if current_equity > 0:
                if float(ss.get("session_start_equity") or 0.0) <= 0:
                    ss["session_start_equity"] = round(float(current_equity), 2)
                    changed = True
                if float(ss.get("week_start_equity") or 0.0) <= 0:
                    ss["week_start_equity"] = round(float(current_equity), 2)
                    changed = True
                if float(current_equity) > float(ss.get("peak_equity") or 0.0):
                    ss["peak_equity"] = round(float(current_equity), 2)
                    changed = True

            if changed:
                self._save()
            res = copy.deepcopy(ss)
            res["lock_cleared"] = lock_cleared
            return res

    def manual_unlock_risk_lock(
        self,
        confirm_token: str = "UNLOCK_CONFIRMED",
        operator_reason: str = "",
        server_day: int | None = None,
        current_day_total: float = 0.0,
        operator_note: str = "",
        reset_baseline: bool = True,
    ) -> tuple[bool, str]:
        """
        Ação explícita, separada, protegida e auditável para desbloqueio manual excepcional.
        Nunca ocorre como efeito colateral de ligar a IA ou salvar configurações.
        """
        clean_reason = (operator_reason or operator_note or "").strip()
        if len(clean_reason) < 5:
            return False, "Informe uma justificativa auditável (mínimo 5 caracteres) para o desbloqueio manual."

        with self._lock:
            lock = self._data.get("risk_lock")
            if not lock:
                return True, "Nenhum bloqueio ativo no momento."
            audit_entry = {
                "unlocked_at": datetime.now(timezone.utc).isoformat(),
                "server_day": server_day,
                "operator_reason": clean_reason,
                "previous_lock": copy.deepcopy(lock),
                "day_pnl_at_unlock": round(float(current_day_total), 2),
            }
            audit_list = list(self._data["session_state"].get("manual_unlock_audit") or [])
            audit_list.append(audit_entry)
            self._data["session_state"]["manual_unlock_audit"] = audit_list[-50:]
            self._data["session_state"]["drawdown_state"] = "CAUTION"
            if reset_baseline:
                self._data["daily_loss_baseline"] = round(float(current_day_total), 2)
            self._data["risk_lock"] = None
            self._save()
            return True, f"Desbloqueio manual auditado registrado ({clean_reason}). Nova linha de base: {self._data['daily_loss_baseline']:+.2f}."

    def update_user(
        self,
        patch: dict,
        current_day_total: float | None = None,
        server_day: int | None = None,
    ) -> tuple[bool, str]:
        """
        Valida e aplica alterações de configuração vindas da interface.
        IMPORTANTE (Parte 2.1 e 2.3):
        - Alterar configurações ou a meta de ganho NUNCA remove uma trava de perda (DAILY_LOSS / WEEKLY_DRAWDOWN / CRITICAL_EXECUTION_FAILURE).
        - Alterar configurações comuns NUNCA redefine silenciosamente o daily_loss_baseline.
        """
        with self._lock:
            d = copy.deepcopy(self._data)
            existing_lock = d.get("risk_lock")
            lock_type = existing_lock.get("lock_type") if isinstance(existing_lock, dict) else None
            lock_same_day = bool(
                isinstance(existing_lock, dict)
                and (server_day is None or int(existing_lock.get("day") or 0) == int(server_day))
            )
            loss_locked = lock_same_day and lock_type in ("DAILY_LOSS", "WEEKLY_DRAWDOWN", "CRITICAL_EXECUTION_FAILURE")

            try:
                if "account_profile" in patch:
                    prof = str(patch["account_profile"]).upper()
                    if prof not in ACCOUNT_PROFILES:
                        return False, f"Perfil de conta inválido: {prof}."
                    d["account_profile"] = prof
                if "limit_mode" in patch:
                    lm = str(patch["limit_mode"]).upper()
                    if lm not in ("MONETARY", "PCT"):
                        return False, "Modo de limite deve ser MONETARY ou PCT."
                    d["limit_mode"] = lm
                if "adaptive_mode" in patch:
                    am = str(patch["adaptive_mode"]).upper()
                    if am not in ADAPTIVE_MODES:
                        return False, f"Modo adaptativo inválido: {am}."
                    d["adaptive_mode"] = am
                if "protect_whole_account" in patch:
                    d["protect_whole_account"] = bool(patch["protect_whole_account"])
                if "session_rollover_hour" in patch:
                    rh = int(float(patch["session_rollover_hour"]))
                    if not (0 <= rh <= 23):
                        return False, "Hora de virada da sessão deve estar entre 0 e 23."
                    d["session_rollover_hour"] = rh
                if "daily_loss_limit" in patch:
                    v = float(patch["daily_loss_limit"])
                    if v < 0:
                        return False, "Stop diário não pode ser negativo."
                    d["daily_loss_limit"] = v
                    # NÃO apaga risk_lock de perda nem redefine daily_loss_baseline silenciosamente!
                if "daily_loss_pct" in patch:
                    v = float(patch["daily_loss_pct"])
                    if v <= 0 or v > 25.0:
                        return False, "Stop diário percentual deve estar entre 0,05% e 25%."
                    d["daily_loss_pct"] = v
                if "weekly_drawdown_limit_pct" in patch:
                    v = float(patch["weekly_drawdown_limit_pct"])
                    if v <= 0 or v > 40.0:
                        return False, "Limite de drawdown semanal deve estar entre 0,1% e 40%."
                    d["weekly_drawdown_limit_pct"] = v
                if "max_planned_risk_pct" in patch:
                    v = float(patch["max_planned_risk_pct"])
                    if v <= 0 or v > 5.0:
                        return False, "Teto de risco por operação deve estar entre 0,05% e 5%."
                    d["max_planned_risk_pct"] = v
                if "max_aggregate_risk_pct" in patch:
                    v = float(patch["max_aggregate_risk_pct"])
                    if v <= 0 or v > 10.0:
                        return False, "Teto de risco agregado deve estar entre 0,1% e 10%."
                    d["max_aggregate_risk_pct"] = v
                if "daily_gain_target" in patch:
                    v = float(patch["daily_gain_target"])
                    if v < 0:
                        return False, "Meta diária não pode ser negativa."
                    d["daily_gain_target"] = v
                    # Só libera trava se a trava anterior era EXCLUSIVAMENTE de meta de ganho (DAILY_GAIN)
                    # e a nova meta é maior que o resultado atual (ou desativada = 0).
                    # Jamais apaga trava de perda (DAILY_LOSS / WEEKLY_DRAWDOWN / CRITICAL_EXECUTION_FAILURE)!
                    if not loss_locked and lock_type == "DAILY_GAIN":
                        if v == 0 or (current_day_total is not None and current_day_total < v):
                            d["risk_lock"] = None
                if "daily_gain_pct" in patch:
                    v = float(patch["daily_gain_pct"])
                    if v < 0 or v > 100.0:
                        return False, "Meta diária percentual inválida."
                    d["daily_gain_pct"] = v
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

            # Garantia inviolável: se havia trava de perda ativa no dia, preserva-a intacta
            if loss_locked:
                d["risk_lock"] = existing_lock

            self._data = d
            self._save()
            if loss_locked:
                return True, "Configurações salvas (Atenção: bloqueio de perda diária permanece ativo até o próximo dia)."
            return True, "Configurações salvas."
