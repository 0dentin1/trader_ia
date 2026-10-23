"""Configuração estática do motor: Mega Brain V5 Quantitativo — Gestão de Risco Independente,
Proteção de Pequenas Contas, Memória Persistente SQLite, Adaptação Estatística e Backtesting."""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SETTINGS_FILE = DATA_DIR / "settings.json"
QUANT_DB_FILE = DATA_DIR / "quant_memory.db"

ALGO_VERSION = "5.0.0-quant"
REFERENCE_ALGO_VERSION = "4.0.0-reference"

# Ciclo do motor (leitura MT5 + análise + decisão) e da transmissão WebSocket.
ENGINE_CYCLE_S = 0.10
BROADCAST_INTERVAL_S = 0.10
RECONNECT_INTERVAL_S = 2.0

# Arquivo opcional escrito pelo EA "TraderIA_SymbolSync.mq5" (pasta Common\Files do MT5)
ACTIVE_SYMBOL_FILE = "trader_ia_active_symbol.txt"

# Credenciais opcionais. Se vazias, conecta ao terminal MT5 já aberto e logado.
MT5_PATH = os.environ.get("MT5_PATH") or None
MT5_LOGIN = int(os.environ["MT5_LOGIN"]) if os.environ.get("MT5_LOGIN") else None
MT5_PASSWORD = os.environ.get("MT5_PASSWORD") or None
MT5_SERVER = os.environ.get("MT5_SERVER") or None

# Segurança opcional para acesso de rede/WebSocket
API_AUTH_TOKEN = os.environ.get("TRADER_IA_API_TOKEN") or None
LOCAL_OPERATOR_TOKEN = API_AUTH_TOKEN
ALLOWED_ORIGINS = [
    o.strip()
    for o in (
        os.environ.get(
            "TRADER_IA_ALLOWED_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000",
        )
    ).split(",")
    if o.strip()
]

TF_SECONDS = {"M1": 60, "M2": 120, "M5": 300, "M15": 900}
TF_BARS = {"M1": 600, "M2": 500, "M5": 400, "M15": 300}

# Limite de operações simultâneas em moedas distintas
MAX_CONCURRENT_TRADES = 4
SNIPER_BASE_MIN_SCORE = 86.0

# Idade máxima permitida para cotação/tick (em segundos) antes de considerar dado desatualizado
MAX_TICK_AGE_S = 15

# Modos de operação da Memória Quantitativa e Adaptação
ADAPTIVE_MODES = ("OBSERVATION", "SHADOW", "ACTIVE")
ACCOUNT_PROFILES = ("SMALL_ACCOUNT_PROTECTION", "STANDARD")
DRAWDOWN_STATES = ("NORMAL", "CAUTION", "REDUCED_EXPOSURE", "TRADING_LOCKED", "REVIEW_REQUIRED")

# Parâmetros iniciais conservadores para proteção de pequenas contas (Parte 3.4)
SMALL_ACCOUNT_DEFAULTS = {
    "target_risk_pct": 0.25,          # Risco-alvo por operação: até 0,25% da equity de referência
    "max_planned_risk_pct": 0.50,     # Teto de risco planejado por operação: 0,50%
    "max_aggregate_risk_pct": 0.75,   # Teto inicial de risco agregado das posições abertas: 0,75%
    "session_loss_limit_pct": 1.00,   # Limite de perda da sessão: 1,00% da equity inicial da sessão
    "weekly_drawdown_limit_pct": 3.00,# Limite semanal de drawdown: 3,00% da equity inicial da semana
    "max_cost_to_risk_ratio": 0.30,   # Custos (spread+comissão+slippage) máx 30% do risco planejado
}

STANDARD_ACCOUNT_DEFAULTS = {
    "target_risk_pct": 0.40,
    "max_planned_risk_pct": 0.75,
    "max_aggregate_risk_pct": 1.50,
    "session_loss_limit_pct": 2.00,
    "weekly_drawdown_limit_pct": 5.00,
    "max_cost_to_risk_ratio": 0.35,
}

PILLAR_NAMES = (
    "Estratégia Institucional & Anatomia da Vela",
    "Alinhamento Obrigatório de Tendência (M1 + M5 + M15)",
    "Espaço Estrutural até Suporte/Resistência (R/R Positivo)",
    "Fluxo Real de Ticks & Ignição de Volume",
    "Eficiência Matemática (Custos & Spread vs Alvo)",
    "Timing de Entrada (Pullback / Sem Esticamento)",
)


@dataclass(frozen=True)
class ModeConfig:
    key: str
    label: str
    subtitle: str
    objective: str
    timeframe: str
    htf: str | None
    min_score: float
    risk_min: float
    risk_max: float
    risk_default: float
    sl_atr: float
    tp_atr: float
    weights: tuple[float, float, float, float, float, float]
    rvol_min: float
    adx_min: float
    min_green_pillars: int
    be_mode: str            # "atr" -> gatilho em múltiplos de ATR | "target_frac" -> fração do alvo
    be_value: float
    trail_mode: str         # "atr" | "ema9" | "atr_tick"
    trail_value: float      # distância (ATR) ou buffer (ATR) da EMA9
    trail_min_step_atr: float
    modify_interval_s: float
    rules: tuple[str, ...]

    def to_public(self) -> dict:
        d = asdict(self)
        d["weights"] = list(self.weights)
        d["rules"] = list(self.rules)
        return d


MODES: dict[str, ModeConfig] = {
    "LEVE": ModeConfig(
        key="LEVE",
        label="Mega Brain · Conservador (Score ≥ 88)",
        subtitle="Filtro Estrito de Confluência · Risco Alvo 0,25% · Proteção de Pequenas Contas",
        objective="Prioriza preservação de capital, exigindo alinhamento completo M1+M5+M15 e custos reduzidos.",
        timeframe="M1",
        htf="M5",
        min_score=88.0,
        risk_min=0.10,
        risk_max=0.50,
        risk_default=0.25,
        sl_atr=1.35,
        tp_atr=1.90,
        weights=(2.5, 2.5, 1.8, 1.4, 1.0, 1.3),
        rvol_min=0.80,
        adx_min=15.0,
        min_green_pillars=5,
        be_mode="target_frac",
        be_value=0.55,
        trail_mode="atr_tick",
        trail_value=0.70,
        trail_min_step_atr=0.05,
        modify_interval_s=0.5,
        rules=(
            "Exige dados válidos e atualizados de M1, M5 e M15 (ausência de HTF bloqueia entrada)",
            "5 famílias de estratégias avaliadas individualmente e registradas em banco SQLite",
            "Bloqueia entrada se o lote mínimo da corretora exceder o orçamento de risco da conta",
            "Pontuação heurística de confluência (≥ 88) separada de probabilidade estatística calibrada",
            "Break-Even aos 55% do alvo e Trailing Stop configurável por ATR ou EMA9",
        ),
    ),
    "MEDIANO": ModeConfig(
        key="MEDIANO",
        label="Mega Brain · Equilibrado (Score ≥ 86)",
        subtitle="5 Estratégias Institucionais + Favor da Tendência + Validação de Risco",
        objective="Opera a favor da tendência M5/M15 quando o espaço estrutural e o custo de execução são favoráveis.",
        timeframe="M1",
        htf="M5",
        min_score=86.0,
        risk_min=0.10,
        risk_max=1.00,
        risk_default=0.25,
        sl_atr=1.30,
        tp_atr=1.80,
        weights=(2.5, 2.5, 1.8, 1.4, 1.0, 1.3),
        rvol_min=0.75,
        adx_min=14.0,
        min_green_pillars=5,
        be_mode="target_frac",
        be_value=0.55,
        trail_mode="atr_tick",
        trail_value=0.65,
        trail_min_step_atr=0.05,
        modify_interval_s=0.4,
        rules=(
            "1 Cérebro por moeda operando a favor da tendência confirmada em M5 e M15",
            "Camada de risco independente valida lote mínimo, margem, custos e risco agregado da carteira",
            "Confirmação obrigatória de SL/TP no MT5 após envio da ordem",
            "Espaço estrutural verificado contra suportes e resistências reais (sem presumir 2.20 ATR)",
            "Memória quantitativa em modo OBSERVATION por padrão (sem aumentar lote após perdas)",
        ),
    ),
    "ARRISCADO": ModeConfig(
        key="ARRISCADO",
        label="Mega Brain · Dinâmico (Score ≥ 84)",
        subtitle="Ignição de Vela a Favor da Tendência M5 · Respeito Estrito ao Teto de Risco",
        objective="Aceita pontuação de confluência a partir de 84, mantendo todas as travas de proteção de capital.",
        timeframe="M1",
        htf="M5",
        min_score=84.0,
        risk_min=0.10,
        risk_max=1.50,
        risk_default=0.40,
        sl_atr=1.25,
        tp_atr=1.70,
        weights=(2.6, 2.4, 1.8, 1.5, 1.0, 1.2),
        rvol_min=0.70,
        adx_min=13.0,
        min_green_pillars=5,
        be_mode="target_frac",
        be_value=0.52,
        trail_mode="atr_tick",
        trail_value=0.60,
        trail_min_step_atr=0.04,
        modify_interval_s=0.35,
        rules=(
            "Proibido operar contra o fluxo de M5 — exige dados válidos nos tempos gráficos superiores",
            "Controle de exposição cambial e risco agregado máximo da carteira",
            "Stop estrutural calculado pelas condições reais do mercado (sem redução artificial)",
            "Trava diária e semanal persistentes que sobrevivem à reinicialização e reativação",
            "Nenhuma regra adaptativa ou modo dinâmico pode ignorar a camada de risco",
        ),
    ),
}

DEFAULT_SETTINGS: dict = {
    "mode": "MEDIANO",
    "symbol": None,
    "auto_select_symbol": True,
    "account_profile": "SMALL_ACCOUNT_PROTECTION",  # "SMALL_ACCOUNT_PROTECTION" | "STANDARD"
    "limit_mode": "MONETARY",                       # "MONETARY" | "PCT"
    "daily_loss_limit": 800.0,                      # limite monetário de perda diária
    "daily_loss_pct": 1.0,                          # limite percentual de perda da sessão (1.0% da equity inicial)
    "daily_loss_baseline": 0.0,                     # linha de base do dia de negociação
    "daily_gain_target": 5000.0,                    # meta monetária de ganho diário (0 = desativado)
    "daily_gain_pct": 2.0,                          # meta percentual de ganho (quando limit_mode == "PCT")
    "weekly_drawdown_limit_pct": 3.0,               # limite semanal de drawdown (%)
    "max_planned_risk_pct": 0.50,                   # teto de risco planejado por operação (%)
    "max_aggregate_risk_pct": 0.75,                 # teto de risco agregado da carteira aberta (%)
    "protect_whole_account": False,                 # False = gerencia/zera apenas posições do próprio magic number
    "adaptive_mode": "OBSERVATION",                 # "OBSERVATION" | "SHADOW" | "ACTIVE"
    "session_rollover_hour": 0,                     # hora do servidor da corretora que inicia novo dia operacional
    "max_spread_points": 25,
    "risk_pct": {k: m.risk_default for k, m in MODES.items()},
    "lot_multiplier": 1.0,
    "aggressive_rr": 1.5,
    "sync_chart_symbol": False,
    "deviation_points": 20,
    "magic": 550055,
    "risk_lock": None,
    "session_state": {
        "trading_day": None,
        "trading_week": None,
        "session_start_equity": 0.0,
        "week_start_equity": 0.0,
        "peak_equity": 0.0,
        "drawdown_state": "NORMAL",
        "manual_unlock_audit": [],
    },
}
