"""Módulo Independente de Proteção para Pequenas Contas e Controle Progressivo de Drawdown (Parte 3).

Avalia saldo, equity, moeda da conta, equity no início da sessão/semana, drawdown progressivo,
viabilidade econômica do lote mínimo da corretora, custos de execução, margem livre e risco agregado.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .config import SMALL_ACCOUNT_DEFAULTS, STANDARD_ACCOUNT_DEFAULTS

# Estados explícitos de decisão de risco (Parte 3.2)
STATUS_APPROVED = "APPROVED"
STATUS_REDUCED = "REDUCED"
STATUS_BLOCKED_MIN_LOT = "BLOCKED_MIN_LOT"
STATUS_BLOCKED_DAILY_LIMIT = "BLOCKED_DAILY_LIMIT"
STATUS_BLOCKED_DRAWDOWN = "BLOCKED_DRAWDOWN"
STATUS_BLOCKED_AGGREGATE_RISK = "BLOCKED_AGGREGATE_RISK"
STATUS_BLOCKED_COSTS = "BLOCKED_COSTS"
STATUS_BLOCKED_DATA = "BLOCKED_DATA"
STATUS_BLOCKED_MARGIN = "BLOCKED_MARGIN"
STATUS_BLOCKED_CORRELATION = "BLOCKED_CORRELATION"

# Estados progressivos de proteção contra drawdown (Parte 3.6)
DD_NORMAL = "NORMAL"                        # 1. Normal
DD_CAUTION = "CAUTION"                      # 2. Atenção
DD_REDUCED_EXPOSURE = "REDUCED_EXPOSURE"    # 3. Redução de novas exposições
DD_TRADING_LOCKED = "TRADING_LOCKED"        # 4. Bloqueio de negociação
DD_REVIEW_REQUIRED = "REVIEW_REQUIRED"      # 5. Revisão necessária antes de retomar


def required_recovery_gain_pct(loss_pct: float) -> float:
    """
    Calcula o retorno percentual necessário sobre o capital restante para recuperar uma perda percentual.
    Ex: perda de 10% -> 11.11%; perda de 20% -> 25.00%; perda de 50% -> 100.00%.
    Estritamente informativo (Parte 3.7): jamais usado para aumentar lote!
    """
    lp = max(0.0, min(99.9, float(loss_pct)))
    if lp <= 0.0:
        return 0.0
    return round((lp / (100.0 - lp)) * 100.0, 2)


@dataclass
class SmallAccountEvaluation:
    status: str
    approved: bool
    profile: str
    drawdown_state: str
    currency: str
    balance: float
    equity: float
    reference_equity: float
    session_start_equity: float
    week_start_equity: float
    target_risk_pct: float
    max_planned_risk_pct: float
    max_aggregate_risk_pct: float
    allowed_risk_money: float
    planned_risk_money: float
    effective_risk_money: float
    effective_risk_pct: float
    min_lot: float
    min_lot_risk_money: float
    min_lot_risk_pct: float
    aggregate_open_risk_money: float
    aggregate_open_risk_pct: float
    total_post_trade_risk_pct: float
    session_drawdown_pct: float
    weekly_drawdown_pct: float
    peak_drawdown_pct: float
    recovery_gain_needed_pct: float
    estimated_costs_money: float
    cost_to_risk_ratio: float
    risk_scale_factor: float
    reason: str
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def resolve_profile_limits(settings: dict) -> dict:
    """Retorna os limites percentuais ativos conforme o perfil configurado (`SMALL_ACCOUNT_PROTECTION` ou `STANDARD`)."""
    profile = str(settings.get("account_profile") or "SMALL_ACCOUNT_PROTECTION").upper()
    base = dict(SMALL_ACCOUNT_DEFAULTS if profile == "SMALL_ACCOUNT_PROTECTION" else STANDARD_ACCOUNT_DEFAULTS)

    if settings.get("max_planned_risk_pct") is not None:
        base["max_planned_risk_pct"] = float(settings["max_planned_risk_pct"])
    if settings.get("max_aggregate_risk_pct") is not None:
        base["max_aggregate_risk_pct"] = float(settings["max_aggregate_risk_pct"])
    if settings.get("daily_loss_pct") is not None:
        base["session_loss_limit_pct"] = float(settings["daily_loss_pct"])
    if settings.get("weekly_drawdown_limit_pct") is not None:
        base["weekly_drawdown_limit_pct"] = float(settings["weekly_drawdown_limit_pct"])

    # Em proteção de pequenas contas, garante que os tetos nunca excedam limites prudentes
    if profile == "SMALL_ACCOUNT_PROTECTION":
        base["target_risk_pct"] = min(base["target_risk_pct"], base["max_planned_risk_pct"])
    return base


def classify_drawdown_state(
    current_equity: float = 0.0,
    session_start_equity: float = 0.0,
    week_start_equity: float = 0.0,
    peak_equity: float = 0.0,
    session_loss_pnl: float = 0.0,
    weekly_loss_pnl: float = 0.0,
    session_limit_money: float = 0.0,
    weekly_limit_money: float = 0.0,
    has_critical_fault: bool = False,
    *,
    reference_equity: float | None = None,
    session_pnl: float | None = None,
    weekly_pnl: float | None = None,
    session_loss_limit_pct: float | None = None,
    weekly_drawdown_limit_pct: float | None = None,
    execution_failure: bool = False,
    **extra,
) -> tuple[str, float, float, float, float, str]:
    """
    Avalia os 5 estados progressivos de drawdown (Parte 3.6):
    Retorna: (drawdown_state, risk_scale, session_dd_pct, weekly_dd_pct, peak_dd_pct, reason)
    """
    if reference_equity is not None:
        current_equity = float(reference_equity)
    if session_pnl is not None:
        session_loss_pnl = float(session_pnl)
    if weekly_pnl is not None:
        weekly_loss_pnl = float(weekly_pnl)
    if execution_failure:
        has_critical_fault = True
    if session_loss_limit_pct is not None and session_limit_money <= 0:
        session_limit_money = max(session_start_equity, current_equity, 1e-9) * (float(session_loss_limit_pct) / 100.0)
    if weekly_drawdown_limit_pct is not None and weekly_limit_money <= 0:
        weekly_limit_money = max(week_start_equity, current_equity, 1e-9) * (float(weekly_drawdown_limit_pct) / 100.0)

    if has_critical_fault:
        return (
            DD_REVIEW_REQUIRED,
            0.0,
            0.0,
            0.0,
            0.0,
            "Falha crítica de execução ou reconciliação pendente — revisão necessária antes de retomar.",
        )

    s_eq = max(session_start_equity, current_equity, 1e-9)
    w_eq = max(week_start_equity, current_equity, 1e-9)
    p_eq = max(peak_equity, s_eq, w_eq, 1e-9)

    eq_session_loss = max(0.0, s_eq - current_equity)
    eq_weekly_loss = max(0.0, w_eq - current_equity)
    eff_session_loss = max(eq_session_loss, max(0.0, -session_loss_pnl))
    eff_weekly_loss = max(eq_weekly_loss, max(0.0, -weekly_loss_pnl))

    session_dd_pct = round(100.0 * eff_session_loss / s_eq, 2)
    weekly_dd_pct = round(100.0 * eff_weekly_loss / w_eq, 2)
    peak_dd_pct = round(100.0 * max(0.0, p_eq - current_equity) / p_eq, 2)

    s_ratio = (eff_session_loss / session_limit_money) if session_limit_money > 0 else 0.0
    w_ratio = (eff_weekly_loss / weekly_limit_money) if weekly_limit_money > 0 else 0.0
    worst_ratio = max(s_ratio, w_ratio)

    if worst_ratio >= 1.0:
        if w_ratio >= 1.0:
            return (
                DD_TRADING_LOCKED,
                0.0,
                session_dd_pct,
                weekly_dd_pct,
                peak_dd_pct,
                f"Limite semanal de drawdown atingido ({weekly_dd_pct:.2f}%).",
            )
        return (
            DD_TRADING_LOCKED,
            0.0,
            session_dd_pct,
            weekly_dd_pct,
            peak_dd_pct,
            f"Limite de perda da sessão atingido ({session_dd_pct:.2f}%).",
        )

    if worst_ratio >= 0.70:
        return (
            DD_REDUCED_EXPOSURE,
            0.50,
            session_dd_pct,
            weekly_dd_pct,
            peak_dd_pct,
            f"Drawdown em zona de Redução de Exposição ({worst_ratio * 100:.0f}% do limite) — lote reduzido em 50%.",
        )

    if worst_ratio >= 0.40:
        return (
            DD_CAUTION,
            0.75,
            session_dd_pct,
            weekly_dd_pct,
            peak_dd_pct,
            f"Drawdown em estado de Atenção ({worst_ratio * 100:.0f}% do limite) — lote reduzido em 25%.",
        )

    return DD_NORMAL, 1.0, session_dd_pct, weekly_dd_pct, peak_dd_pct, "Drawdown dentro da normalidade."


def evaluate_small_account_guard(
    *,
    account: dict,
    sym: dict,
    settings: dict,
    requested_risk_pct: float,
    loss_per_lot_at_sl: float | None,
    estimated_costs_per_lot: float,
    final_volume: float,
    margin_required: float | None,
    open_portfolio_risk_money: float,
    session_pnl: float,
    weekly_pnl: float,
    has_unprotected_position: bool = False,
    correlation_blocked_reason: str | None = None,
    data_invalid_reason: str | None = None,
    data_integrity_error: str | None = None,
    execution_failure: bool = False,
    **extra,
) -> SmallAccountEvaluation:
    """
    Executa a validação completa da camada de proteção de pequenas contas e carteira.
    Garante que o lote mínimo da corretora jamais force uma operação incompatível com a banca.
    """
    data_err = data_invalid_reason or data_integrity_error
    profile = str(settings.get("account_profile") or "SMALL_ACCOUNT_PROTECTION").upper()
    limits = resolve_profile_limits(settings)
    currency = str(account.get("currency") or "USD").upper()
    balance = float(account.get("balance") or 0.0)
    equity = float(account.get("equity") or 0.0)
    margin_free = float(account.get("margin_free") or 0.0)
    reference_equity = min(balance, equity) if (balance > 0 and equity > 0) else max(balance, equity, 0.0)

    ss = settings.get("session_state") or {}
    session_start_eq = float(ss.get("session_start_equity") or reference_equity or 0.0)
    week_start_eq = float(ss.get("week_start_equity") or reference_equity or 0.0)
    peak_eq = float(ss.get("peak_equity") or max(session_start_eq, week_start_eq, reference_equity))

    # Limites diário e semanal em moeda da conta
    limit_mode = str(settings.get("limit_mode") or "MONETARY").upper()
    monetary_loss_limit = float(settings.get("daily_loss_limit") or 0.0)
    pct_loss_limit_money = (session_start_eq * limits["session_loss_limit_pct"] / 100.0) if session_start_eq > 0 else 0.0

    if limit_mode == "PCT" or profile == "SMALL_ACCOUNT_PROTECTION":
        # Em proteção de pequenas contas, respeita o menor (mais conservador) entre o limite monetário e o percentual
        if monetary_loss_limit > 0 and pct_loss_limit_money > 0:
            session_limit_money = min(monetary_loss_limit, pct_loss_limit_money)
        else:
            session_limit_money = pct_loss_limit_money or monetary_loss_limit
    else:
        session_limit_money = monetary_loss_limit if monetary_loss_limit > 0 else pct_loss_limit_money

    weekly_limit_money = (week_start_eq * limits["weekly_drawdown_limit_pct"] / 100.0) if week_start_eq > 0 else 0.0

    dd_state, risk_scale, session_dd_pct, weekly_dd_pct, peak_dd_pct, dd_reason = classify_drawdown_state(
        current_equity=reference_equity,
        session_start_equity=session_start_eq,
        week_start_equity=week_start_eq,
        peak_equity=peak_eq,
        session_loss_pnl=session_pnl,
        weekly_loss_pnl=weekly_pnl,
        session_limit_money=session_limit_money,
        weekly_limit_money=weekly_limit_money,
        has_critical_fault=has_unprotected_position,
    )

    rec_needed = required_recovery_gain_pct(max(session_dd_pct, weekly_dd_pct, peak_dd_pct))
    min_lot = float(sym.get("volume_min") or 0.01) if sym else 0.01

    target_risk_pct = min(float(requested_risk_pct or limits["target_risk_pct"]), limits["max_planned_risk_pct"])
    scaled_target_pct = round(target_risk_pct * max(risk_scale, 0.0), 4)
    max_planned_pct = limits["max_planned_risk_pct"]
    max_agg_pct = limits["max_aggregate_risk_pct"]

    planned_risk_money = round(reference_equity * scaled_target_pct / 100.0, 4) if reference_equity > 0 else 0.0
    allowed_risk_money = round(reference_equity * max_planned_pct / 100.0, 4) if reference_equity > 0 else 0.0

    unit_loss = float(loss_per_lot_at_sl or 0.0) + max(0.0, float(estimated_costs_per_lot or 0.0))
    min_lot_risk_money = round(unit_loss * min_lot, 4) if unit_loss > 0 else 0.0
    min_lot_risk_pct = round(100.0 * min_lot_risk_money / reference_equity, 4) if reference_equity > 0 else 100.0

    eff_risk_money = round(unit_loss * final_volume, 4) if (unit_loss > 0 and final_volume > 0) else min_lot_risk_money
    eff_risk_pct = round(100.0 * eff_risk_money / reference_equity, 4) if reference_equity > 0 else 0.0
    est_costs_money = round(max(0.0, float(estimated_costs_per_lot or 0.0)) * max(final_volume, min_lot), 4)
    cost_to_risk = round(est_costs_money / max(eff_risk_money, 1e-9), 4) if eff_risk_money > 0 else 0.0

    agg_open_pct = round(100.0 * open_portfolio_risk_money / reference_equity, 4) if reference_equity > 0 else 0.0
    total_post_risk_money = round(open_portfolio_risk_money + eff_risk_money, 4)
    total_post_risk_pct = round(100.0 * total_post_risk_money / reference_equity, 4) if reference_equity > 0 else 0.0

    def _build(status: str, approved: bool, reason: str, suggestions: list[str] | None = None) -> SmallAccountEvaluation:
        return SmallAccountEvaluation(
            status=status,
            approved=approved,
            profile=profile,
            drawdown_state=dd_state,
            currency=currency,
            balance=round(balance, 2),
            equity=round(equity, 2),
            reference_equity=round(reference_equity, 2),
            session_start_equity=round(session_start_eq, 2),
            week_start_equity=round(week_start_eq, 2),
            target_risk_pct=round(scaled_target_pct, 3),
            max_planned_risk_pct=round(max_planned_pct, 3),
            max_aggregate_risk_pct=round(max_agg_pct, 3),
            allowed_risk_money=round(allowed_risk_money, 2),
            planned_risk_money=round(planned_risk_money, 2),
            effective_risk_money=round(eff_risk_money, 2),
            effective_risk_pct=round(eff_risk_pct, 3),
            min_lot=min_lot,
            min_lot_risk_money=round(min_lot_risk_money, 2),
            min_lot_risk_pct=round(min_lot_risk_pct, 3),
            aggregate_open_risk_money=round(open_portfolio_risk_money, 2),
            aggregate_open_risk_pct=round(agg_open_pct, 3),
            total_post_trade_risk_pct=round(total_post_risk_pct, 3),
            session_drawdown_pct=session_dd_pct,
            weekly_drawdown_pct=weekly_dd_pct,
            peak_drawdown_pct=peak_dd_pct,
            recovery_gain_needed_pct=rec_needed,
            estimated_costs_money=round(est_costs_money, 2),
            cost_to_risk_ratio=round(cost_to_risk, 3),
            risk_scale_factor=risk_scale,
            reason=reason,
            suggestions=suggestions or [],
        )

    # 1. Validação de dados obrigatórios
    if data_err:
        return _build(STATUS_BLOCKED_DATA, False, f"Operação bloqueada por dados incompletos: {data_err}")
    if reference_equity <= 0 or not loss_per_lot_at_sl or loss_per_lot_at_sl <= 0:
        return _build(
            STATUS_BLOCKED_DATA,
            False,
            "Operação bloqueada: capital de referência ou cálculo de perda por lote indisponível.",
        )

    # 2. Posição aberta sem SL/TP confirmado ou falha crítica
    if has_unprotected_position:
        return _build(
            STATUS_BLOCKED_DRAWDOWN,
            False,
            "Operação bloqueada: existe posição aberta sem confirmação de SL/TP ou falha crítica pendente.",
        )

    # 3. Limite diário ou drawdown semanal atingido
    if dd_state in (DD_TRADING_LOCKED, DD_REVIEW_REQUIRED):
        if weekly_limit_money > 0 and max(0.0, -weekly_pnl, week_start_eq - reference_equity) >= weekly_limit_money:
            return _build(STATUS_BLOCKED_DRAWDOWN, False, f"Operação bloqueada: {dd_reason}")
        return _build(STATUS_BLOCKED_DAILY_LIMIT, False, f"Operação bloqueada: {dd_reason}")

    if session_limit_money > 0 and session_pnl <= -session_limit_money:
        return _build(
            STATUS_BLOCKED_DAILY_LIMIT,
            False,
            f"Operação bloqueada: limite de perda da sessão atingido ({session_pnl:+.2f} {currency} <= -{session_limit_money:.2f} {currency}).",
        )

    # 4. Verificação estrita do Lote Mínimo da Corretora (Parte 2.5 e Parte 3.1/3.4)
    if min_lot_risk_money > allowed_risk_money + 1e-6:
        return _build(
            STATUS_BLOCKED_MIN_LOT,
            False,
            (
                "Operação bloqueada: o lote mínimo permitido neste ativo ultrapassa o risco máximo configurado para sua conta "
                f"(lote mín. {min_lot} arrisca {min_lot_risk_money:.2f} {currency} [{min_lot_risk_pct:.2f}%], "
                f"acima do orçamento máximo de {allowed_risk_money:.2f} {currency} [{max_planned_pct:.2f}%])."
            ),
            suggestions=[
                "Utilize instrumentos com menor valor por ponto/contrato (ex.: pares micro/cent) compatíveis com sua banca.",
                "Aguarde uma estrutura de mercado com menor volatilidade (ATR menor) sem encurtar artificialmente o stop.",
            ],
        )

    if final_volume < min_lot or eff_risk_money > allowed_risk_money + 1e-6:
        return _build(
            STATUS_BLOCKED_MIN_LOT,
            False,
            (
                "Operação bloqueada: o lote mínimo permitido neste ativo ultrapassa o risco máximo configurado para sua conta "
                f"(risco efetivo {eff_risk_money:.2f} {currency} [{eff_risk_pct:.2f}%] > orçamento {allowed_risk_money:.2f} {currency} [{max_planned_pct:.2f}%])."
            ),
        )

    # 5. Verificação se a nova operação poderia violar o limite restante da sessão
    if session_limit_money > 0:
        remaining_session_budget = session_limit_money + min(0.0, session_pnl)
        if eff_risk_money > remaining_session_budget + 1e-6:
            return _build(
                STATUS_BLOCKED_DAILY_LIMIT,
                False,
                (
                    f"Operação bloqueada: o risco efetivo ({eff_risk_money:.2f} {currency}) excede o orçamento "
                    f"restante até o limite de perda da sessão ({max(0.0, remaining_session_budget):.2f} {currency})."
                ),
            )

    # 6. Verificação de custos desproporcionais (spread + comissão + slippage estimado vs risco)
    if cost_to_risk > limits["max_cost_to_risk_ratio"]:
        return _build(
            STATUS_BLOCKED_COSTS,
            False,
            (
                f"Operação bloqueada: custos estimados de execução ({est_costs_money:.2f} {currency}) "
                f"representam {cost_to_risk * 100:.1f}% do risco da operação (máximo {limits['max_cost_to_risk_ratio'] * 100:.0f}%)."
            ),
        )

    # 7. Verificação de margem livre
    if margin_required is not None and margin_required > 0:
        if margin_free <= 0 or margin_required > margin_free * 0.80:
            return _build(
                STATUS_BLOCKED_MARGIN,
                False,
                f"Operação bloqueada: margem requerida ({margin_required:.2f} {currency}) excede 80% da margem livre ({margin_free:.2f} {currency}).",
            )

    # 8. Verificação de correlação e concentração cambial
    if correlation_blocked_reason:
        return _build(STATUS_BLOCKED_CORRELATION, False, f"Operação bloqueada: {correlation_blocked_reason}")

    # 9. Verificação de Risco Agregado da Carteira (Parte 2.6 e 3.4)
    max_agg_money = reference_equity * max_agg_pct / 100.0
    if total_post_risk_money > max_agg_money + 1e-6:
        return _build(
            STATUS_BLOCKED_AGGREGATE_RISK,
            False,
            (
                f"Operação bloqueada: risco agregado da carteira ({total_post_risk_money:.2f} {currency} / {total_post_risk_pct:.2f}%) "
                f"ultrapassaria o teto de {max_agg_money:.2f} {currency} ({max_agg_pct:.2f}%)."
            ),
        )

    # 10. Aprovado (Normal ou com Exposição Reduzida pelo controle de drawdown)
    if risk_scale < 1.0:
        return _build(
            STATUS_REDUCED,
            True,
            f"Operação aprovada com exposição reduzida ({int(risk_scale * 100)}%): {dd_reason}",
        )

    return _build(
        STATUS_APPROVED,
        True,
        f"Operação aprovada dentro dos limites ({eff_risk_money:.2f} {currency} = {eff_risk_pct:.2f}% da equity).",
    )
