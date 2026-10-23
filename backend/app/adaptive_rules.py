"""Regras Adaptativas Estatísticas (Sem Machine Learning) com Modos OBSERVATION, SHADOW e ACTIVE (Partes 5.6 e 5.7).

Princípios obrigatórios:
- Padrão é `OBSERVATION` (apenas registra decisões e resultados).
- `SHADOW` calcula o que as regras adaptativas teriam feito sem alterar ordens reais.
- `ACTIVE` aplica somente regras previamente validadas com amostra mínima (`n >= 20`) e habilitadas explicitamente.
- Uma única perda NUNCA altera a estratégia.
- A adaptação JAMAIS aumenta o risco ou ignora a camada de risco.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from .performance import MIN_RELIABLE_SAMPLE, compute_group_metrics
from .trade_journal import TradeJournal


@dataclass
class AdaptiveRule:
    rule_id: str
    version: int
    strategy_id: str
    regime_code: str
    symbol: str
    status: str         # "EXPERIMENTAL" | "APPROVED" | "UNDER_OBSERVATION"
    action: str         # "NONE" | "RECOMMEND_BLOCK" | "RAISE_SCORE_FLOOR"
    sample_size: int
    expectancy: float
    std_error: float
    profit_factor: float
    enabled_in_active: bool
    reason: str
    updated_at: str

    def to_dict(self) -> dict:
        return asdict(self)


class AdaptiveRulesEngine:
    def __init__(
        self,
        journal: TradeJournal,
        min_sample_size: int = MIN_RELIABLE_SAMPLE,
        mode: str = "OBSERVATION",
    ) -> None:
        self.journal = journal
        self.min_sample_size = max(10, int(min_sample_size))
        self.mode = mode.upper() if mode else "OBSERVATION"
        self._rules_cache: dict[str, AdaptiveRule] = {}
        self.refresh_from_history()

    def set_mode(self, mode: str) -> None:
        self.mode = (mode or "OBSERVATION").upper()

    def refresh_from_history(self, closed_trades: list[dict] | None = None) -> list[dict]:
        """
        Analisa o histórico real (`is_simulated = 0`) por combinação `(strategy_id, regime_code)`
        e atualiza o registro versionado de regras adaptativas no SQLite.
        """
        trades = (
            closed_trades
            if closed_trades is not None
            else self.journal.fetch_closed_trades(is_simulated=False, source="LIVE_MT5", limit=2000)
        )
        groups: dict[tuple[str, str], list[dict]] = {}
        for t in trades:
            sid = str(t.get("primary_strategy_id") or t.get("primary_strategy") or "UNKNOWN")
            reg = str(t.get("regime_code") or "UNKNOWN")
            groups.setdefault((sid, reg), []).append(t)

        now_iso = datetime.now(timezone.utc).isoformat()
        updated_rules: list[AdaptiveRule] = []

        with self.journal._lock:
            try:
                with self.journal._connect() as conn:
                    existing_rows = {
                        r["rule_id"]: dict(r)
                        for r in conn.execute("SELECT * FROM adaptive_rules_state;").fetchall()
                    }

                    for (sid, reg), grp in groups.items():
                        rule_id = f"{sid}::{reg}"
                        m = compute_group_metrics(grp)
                        n = int(m["sample_size"])
                        exp = float(m["expectancy"])
                        se = float(m["std_error"])
                        pf = float(m["profit_factor"])

                        prev = existing_rows.get(rule_id)
                        prev_ver = int(prev["version"]) if prev else 1
                        prev_enabled = bool(prev["enabled_in_active"]) if prev else False

                        if n < self.min_sample_size:
                            status = "EXPERIMENTAL"
                            action = "NONE"
                            reason = f"Amostra insuficiente ({n}/{self.min_sample_size} op.) — coletando dados em observação."
                            enabled = False
                        elif exp + se < 0.0 and pf < 0.85:
                            status = "UNDER_OBSERVATION"
                            action = "RECOMMEND_BLOCK"
                            reason = (
                                f"Expectativa líquida negativa consistente ({exp:+.2f} ± {se:.2f}, PF={pf:.2f} em {n} op.) "
                                f"— bloqueio recomendado."
                            )
                            enabled = prev_enabled
                        elif exp < 0.0 or m.get("recent_deterioration"):
                            status = "UNDER_OBSERVATION"
                            action = "RAISE_SCORE_FLOOR"
                            reason = f"Desempenho sob observação (E={exp:+.2f}, PF={pf:.2f} em {n} op.)."
                            enabled = prev_enabled
                        else:
                            status = "APPROVED"
                            action = "NONE"
                            reason = f"Expectativa líquida positiva (E={exp:+.2f}, PF={pf:.2f} em {n} op.)."
                            enabled = prev_enabled

                        new_ver = prev_ver + 1 if (prev and (prev["status"] != status or prev["action"] != action)) else prev_ver
                        rule = AdaptiveRule(
                            rule_id=rule_id,
                            version=new_ver,
                            strategy_id=sid,
                            regime_code=reg,
                            symbol="*",
                            status=status,
                            action=action,
                            sample_size=n,
                            expectancy=exp,
                            std_error=se,
                            profit_factor=pf,
                            enabled_in_active=enabled,
                            reason=reason,
                            updated_at=now_iso,
                        )
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO adaptive_rules_state (
                                rule_id, version, strategy_id, regime_code, symbol,
                                status, action, sample_size, expectancy, std_error,
                                profit_factor, enabled_in_active, reason, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                            """,
                            (
                                rule.rule_id,
                                rule.version,
                                rule.strategy_id,
                                rule.regime_code,
                                rule.symbol,
                                rule.status,
                                rule.action,
                                rule.sample_size,
                                rule.expectancy,
                                rule.std_error,
                                rule.profit_factor,
                                1 if rule.enabled_in_active else 0,
                                rule.reason,
                                rule.updated_at,
                            ),
                        )
                        self._rules_cache[rule_id] = rule
                        updated_rules.append(rule)
                    conn.commit()
            except Exception as exc:  # noqa: BLE001
                print(f"[AdaptiveRules] Erro ao atualizar regras: {exc!r}", flush=True)

        return [r.to_dict() for r in updated_rules]

    def set_rule_active_approval(self, rule_id: str, enabled: bool) -> tuple[bool, str]:
        """Habilita ou desabilita explicitamente uma regra validada para uso no modo ACTIVE."""
        rule = self._rules_cache.get(rule_id)
        if not rule:
            return False, f"Regra '{rule_id}' não encontrada."
        if enabled and rule.sample_size < self.min_sample_size:
            return (
                False,
                f"Não é permitido ativar a regra '{rule_id}' sem amostra mínima ({rule.sample_size}/{self.min_sample_size}).",
            )
        rule.enabled_in_active = bool(enabled)
        rule.version += 1
        rule.updated_at = datetime.now(timezone.utc).isoformat()
        with self.journal._lock:
            with self.journal._connect() as conn:
                conn.execute(
                    "UPDATE adaptive_rules_state SET enabled_in_active = ?, version = ?, updated_at = ? WHERE rule_id = ?;",
                    (1 if enabled else 0, rule.version, rule.updated_at, rule_id),
                )
                conn.commit()
        return True, f"Regra '{rule_id}' (v{rule.version}) {'habilitada' if enabled else 'desabilitada'} para modo ACTIVE."

    def evaluate_candidate(
        self,
        *,
        strategy_id: str = "",
        regime_code: str = "",
        symbol: str = "*",
        strategy: str = "",
        regime: str = "",
        horizon: str = "",
        base_min_score: float = 85.0,
        adaptive_mode: str | None = None,
    ) -> dict:
        """
        Avalia um setup candidato de acordo com o modo da memória (`OBSERVATION`, `SHADOW`, `ACTIVE`).
        - Em `OBSERVATION`: nunca bloqueia nem modifica (apenas informa status estatístico).
        - Em `SHADOW`: calcula `shadow_would_block` e `shadow_reason` sem bloquear a ordem real.
        - Em `ACTIVE`: aplica o bloqueio ou +2 pts de score exigido somente se a regra tiver amostra suficiente e estiver habilitada.
        """
        mode = (adaptive_mode or self.mode or "OBSERVATION").upper()
        sid = strategy_id or strategy or "UNKNOWN"
        reg = regime_code or regime or "UNKNOWN"
        rule_id = f"{sid}::{reg}"
        rule = self._rules_cache.get(rule_id)

        if rule is None or rule.sample_size < self.min_sample_size:
            return {
                "mode": mode,
                "allowed": True,
                "score_adjustment": 0.0,
                "effective_min_score": float(base_min_score),
                "shadow_would_block": False,
                "shadow_reason": "",
                "status": "EXPERIMENTAL",
                "sample_size": rule.sample_size if rule else 0,
                "reason": (
                    f"Amostra insuficiente ({rule.sample_size if rule else 0}/{self.min_sample_size}) — mantendo observação."
                ),
                "block_reason": "",
            }

        would_block = rule.action == "RECOMMEND_BLOCK"
        score_bump = 2.0 if rule.action == "RAISE_SCORE_FLOOR" else 0.0

        if mode == "OBSERVATION":
            return {
                "mode": "OBSERVATION",
                "allowed": True,
                "score_adjustment": 0.0,
                "effective_min_score": float(base_min_score),
                "shadow_would_block": False,
                "shadow_reason": "",
                "status": rule.status,
                "sample_size": rule.sample_size,
                "reason": rule.reason,
                "block_reason": "",
            }

        if mode == "SHADOW":
            return {
                "mode": "SHADOW",
                "allowed": True,  # SHADOW nunca altera ordens reais!
                "score_adjustment": 0.0,
                "effective_min_score": float(base_min_score),
                "shadow_would_block": would_block,
                "shadow_reason": rule.reason if would_block else "",
                "status": rule.status,
                "sample_size": rule.sample_size,
                "reason": f"[SHADOW] {rule.reason}",
                "block_reason": "",
            }

        # Modo ACTIVE: só bloqueia se explicitamente validada e habilitada
        if mode == "ACTIVE" and rule.enabled_in_active:
            if would_block:
                return {
                    "mode": "ACTIVE",
                    "allowed": False,
                    "score_adjustment": 0.0,
                    "effective_min_score": float(base_min_score),
                    "shadow_would_block": True,
                    "shadow_reason": rule.reason,
                    "status": rule.status,
                    "sample_size": rule.sample_size,
                    "reason": f"[ACTIVE BLOCK v{rule.version}] {rule.reason}",
                    "block_reason": f"[ACTIVE BLOCK v{rule.version}] {rule.reason}",
                }
            return {
                "mode": "ACTIVE",
                "allowed": True,
                "score_adjustment": score_bump,
                "effective_min_score": float(base_min_score + score_bump),
                "shadow_would_block": False,
                "shadow_reason": "",
                "status": rule.status,
                "sample_size": rule.sample_size,
                "reason": f"[ACTIVE v{rule.version}] {rule.reason}",
                "block_reason": "",
            }

        return {
            "mode": mode,
            "allowed": True,
            "score_adjustment": 0.0,
            "effective_min_score": float(base_min_score),
            "shadow_would_block": would_block,
            "shadow_reason": rule.reason if would_block else "",
            "status": rule.status,
            "sample_size": rule.sample_size,
            "reason": rule.reason,
            "block_reason": "",
        }

    def list_rules(self) -> list[dict]:
        return [r.to_dict() for r in self._rules_cache.values()]
