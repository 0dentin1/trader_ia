"""Configuração estática do motor: Mega Brain V4 Multi-Cérebros, 5 Estratégias Institucionais e constantes."""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SETTINGS_FILE = DATA_DIR / "settings.json"

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

TF_SECONDS = {"M1": 60, "M2": 120, "M5": 300, "M15": 900}
TF_BARS = {"M1": 600, "M2": 500, "M5": 400, "M15": 300}

# Limite de operações simultâneas em moedas distintas pelo Mega Brain V4
MAX_CONCURRENT_TRADES = 4
SNIPER_BASE_MIN_SCORE = 86.0

PILLAR_NAMES = (
    "Estratégia Institucional & Anatomia da Vela",
    "Alinhamento Obrigatório de Tendência (M1 + M5 + M15)",
    "Espaço Livre até Topo/Fundo (R/R Positivo)",
    "Fluxo Real de Ticks & Ignição de Volume",
    "Eficiência Matemática (Spread vs Alvo)",
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
        label="Mega Brain · Institucional 88%",
        subtitle="Proibido Contra-Tendência · Só Entra em 88%+ (R/R Positivo)",
        objective="Opera exclusivamente a favor da tendência M5/M15 após pullback ou varredura de liquidez.",
        timeframe="M1",
        htf="M5",
        min_score=88.0,
        risk_min=0.2,
        risk_max=1.0,
        risk_default=0.35,
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
            "Proibido operar contra a tendência de M5/M15 (Zero adivinhação de topo/fundo)",
            "5 Estratégias Institucionais: Pullback EMA9/21, SMC Sweep, Squeeze Breakout, VWAP e MTF",
            "Até 4 moedas simultâneas com lote blindado (seguro para bancas de €100 a $100k)",
            "Alvo sempre maior que o Stop (ganhos completos, sem enforcar lucro com +2 pts)",
            "Break-Even só após 55% do caminho para não ser violinado pelo ruído",
        ),
    ),
    "MEDIANO": ModeConfig(
        key="MEDIANO",
        label="Mega Brain · Sniper 86%",
        subtitle="5 Estratégias Institucionais + Favor da Tendência + Até 4 Moedas",
        objective="Foco em 2 a 3 vitórias para cada loss, operando apenas a favor da força institucional M5/M15.",
        timeframe="M1",
        htf="M5",
        min_score=86.0,
        risk_min=0.2,
        risk_max=1.5,
        risk_default=0.40,
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
            "1 Cérebro por moeda operando exclusivamente a favor da tendência M5/M15",
            "Até 4 operações simultâneas em moedas distintas quando o sinal for ≥ 86%",
            "Lote blindado com teto de alavancagem (protege bancas pequenas de R$50/€100 e grandes)",
            "Ganhos maiores que as perdas: não fecha operação com +2 pontos nem no prejuízo por tempo",
            "Trava Zero a Zero em +25% do alvo quando o preço atinge 55% da meta",
        ),
    ),
    "ARRISCADO": ModeConfig(
        key="ARRISCADO",
        label="Mega Brain · Dinâmico 84%",
        subtitle="Ignição de Vela a Favor da Tendência M5 · Até 4 Moedas",
        objective="Aproveita explosões rápidas de vela sempre a favor da tendência principal com lote protegido.",
        timeframe="M1",
        htf="M5",
        min_score=84.0,
        risk_min=0.2,
        risk_max=2.0,
        risk_default=0.50,
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
            "Proibido operar contra o fluxo de M5 — só entra a favor da tendência",
            "Até 4 moedas simultâneas com filtro de correlação cambial do Dólar",
            "Stop estrutural protegido atrás do pavio (nunca usa stop curto de 4 pts que toma violino)",
            "Colheita inteligente apenas quando o lucro já atingiu ≥ 65% da meta",
            "Banca protegida para qualquer capital inicial (R$50, €100 ou $100.000)",
        ),
    ),
}

DEFAULT_SETTINGS: dict = {
    "mode": "MEDIANO",
    "symbol": None,
    "auto_select_symbol": True,
    "daily_loss_limit": 800.0,    # limite de perda a partir do momento salvo
    "daily_loss_baseline": 0.0,   # P&L acumulado no momento em que o usuário salvou o limite
    "daily_gain_target": 5000.0,  # 0 = desativado
    "max_spread_points": 25,
    "risk_pct": {k: m.risk_default for k, m in MODES.items()},
    "lot_multiplier": 1.0,
    "aggressive_rr": 1.5,
    "sync_chart_symbol": False,
    "deviation_points": 20,
    "magic": 550055,
    "risk_lock": None,
}
