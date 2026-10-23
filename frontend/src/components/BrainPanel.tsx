import { memo, useEffect, useRef, useState } from "react";
import {
  Activity,
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Cpu,
  Database,
  Flame,
  Gauge,
  ListChecks,
  Play,
  ScrollText,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
  XCircle,
} from "lucide-react";
import type { AIState, AIStatus, Analysis, LogEntry, ModeConfig, QuantSummary, RadarEntry } from "../types";
import type { TerminalApi } from "../hooks/useTerminal";
import { cx, fmtNum } from "../lib/format";

interface Props {
  ai: AIStatus | undefined;
  analysis: Analysis | null;
  mode: ModeConfig | undefined;
  logs: LogEntry[];
  radar?: RadarEntry[];
  activeSymbol?: string | null;
  autoSymbol?: boolean;
  quant?: QuantSummary;
  send?: TerminalApi["send"];
}

const FLOW_STATES: { key: AIState; label: string; desc: string }[] = [
  { key: "STUDYING_MARKET", label: "1. Multi-Cérebros", desc: "Escaneando moedas em M1/M2/M5/M15" },
  { key: "EVALUATING_CONFLUENCE", label: "2. Confluência", desc: "Validando score heurístico e espaço estrutural" },
  { key: "EXECUTING_TRADE", label: "3. Execução", desc: "Validando risco independente e confirmando SL/TP" },
  { key: "MANAGING_POSITION", label: "4. Gestão MFE/MAE", desc: "Break-Even e Trailing Stop configurável" },
  { key: "COOLDOWN", label: "5. Pausa Tática", desc: "Aguardando próxima vela limpa" },
  { key: "RISK_LOCK", label: "6. Trava Sessão/Semana", desc: "Proteção de capital ativa" },
];

const SIMPLE_PILLAR_INFO: Record<number, { title: string; subtitle: string }> = {
  1: {
    title: "1. Estratégia Institucional & Anatomia da Vela",
    subtitle: "SMC Liquidity Sweep, Pullback EMA 9/21, Squeeze Breakout, Defesa VWAP e Pavios",
  },
  2: {
    title: "2. Alinhamento Estrito Multi-Timeframe (M1+M5+M15)",
    subtitle: "Proíbe operar contra tendência HTF; ausência de dados M5/M15 bloqueia entrada",
  },
  3: {
    title: "3. Espaço Estrutural Objetivo (Suporte / Resistência)",
    subtitle: "Verifica espaço livre sem presumir 2.20 ATR em toques/rompimentos não confirmados",
  },
  4: {
    title: "4. Fluxo Institucional de Ticks & Agressão",
    subtitle: "Confirma agressão real dos compradores/vendedores neste exato segundo",
  },
  5: {
    title: "5. Eficiência de Custos & Spread vs Alvo",
    subtitle: "Bloqueia entrada se spread/custos consumirem mais de 30% do risco planejado",
  },
  6: {
    title: "6. Timing de Entrada & Força Limpa",
    subtitle: "Garante pullback saudável sem esticamento ou exaustão de momentum",
  },
};

const REGIME_STYLE: Record<string, string> = {
  TREND_UP: "text-bull border-bull/40 bg-bull/10",
  TREND_DOWN: "text-bear border-bear/40 bg-bear/10",
  REVERSAL_UP: "text-bull border-bull/50 bg-bull/15",
  REVERSAL_DOWN: "text-bear border-bear/50 bg-bear/15",
  RANGE: "text-slate-300 border-ink-500 bg-ink-800",
  HIGH_VOL: "text-warn border-warn/40 bg-warn/10",
  UNKNOWN: "text-slate-500 border-ink-600 bg-ink-850",
};

const REGIME_FRIENDLY: Record<string, string> = {
  TREND_UP: "📈 Tendência de Alta Forte",
  TREND_DOWN: "📉 Tendência de Baixa Forte",
  REVERSAL_UP: "🔄 Reversão de Fundo / Rejeição por Pavio",
  REVERSAL_DOWN: "🔄 Reversão de Topo / Rejeição por Pavio",
  RANGE: "↔️ Consolidação / Mercado Lateral",
  HIGH_VOL: "⚡ Alta Volatilidade / Rompimento",
  UNKNOWN: "⏳ Carregando histórico multi-timeframe…",
};

const LOG_STYLE: Record<LogEntry["level"], string> = {
  info: "text-slate-300",
  warn: "text-warn",
  error: "text-bear",
  success: "text-bull font-semibold",
  action: "text-sky-300 font-semibold",
  think: "text-violet-300",
  state: "text-slate-500",
};

function StateMachine({ ai }: { ai: AIStatus | undefined }) {
  const state = ai?.state ?? "OFF";
  const off = state === "OFF" || state === "DISCONNECTED";
  const rec = ai?.recovery;
  return (
    <div className="space-y-1.5 px-3 pt-2.5">
      <div className="grid grid-cols-3 gap-1">
        {FLOW_STATES.map((s) => {
          const active = s.key === state;
          return (
            <div
              key={s.key}
              title={s.desc}
              className={cx(
                "truncate rounded border px-1.5 py-1 text-left text-[10px] transition",
                active
                  ? s.key === "RISK_LOCK"
                    ? "border-bear bg-bear/20 font-bold text-bear"
                    : s.key === "MANAGING_POSITION" || s.key === "EXECUTING_TRADE"
                      ? "border-bull bg-bull/20 font-bold text-bull"
                      : "border-accent bg-accent/20 font-bold text-sky-300"
                  : "border-ink-700 bg-ink-900/60 text-slate-500",
              )}
            >
              {s.label}
            </div>
          );
        })}
      </div>

      <div
        className={cx(
          "rounded border px-2.5 py-1.5 text-xs",
          off ? "border-ink-600 bg-ink-850 text-slate-300" : "border-accent/50 bg-accent/10 text-white",
        )}
      >
        <div className="flex items-center justify-between gap-2">
          <span className="font-bold text-accent">
            {off ? "⏸️ Mega Brain Quant Pausado (Somente Leitura)" : `🧠 ${ai?.state_label}`}
          </span>
        </div>
        <div className="mt-0.5 truncate text-[11px] text-slate-300">{ai?.detail || "—"}</div>
      </div>

      {rec?.active && (
        <div className="flex items-center gap-1.5 rounded border border-amber-400/50 bg-amber-400/10 px-2.5 py-1.5 text-[10.5px] text-amber-300">
          <ShieldAlert size={13} className="shrink-0" />
          <span>
            <b>Defesa Anti-Teimosia Ativa:</b> exige +2 pontos de score e bloqueia repetição no mesmo par.
          </span>
        </div>
      )}
    </div>
  );
}

function Thermometer({ a, mode, ai }: { a: Analysis; mode: ModeConfig | undefined; ai: AIStatus | undefined }) {
  const baseMin = Math.max(82, mode?.min_score ?? 86);
  const min = ai?.recovery?.active ? Math.min(91, baseMin + 2) : baseMin;
  const score = a.score ?? 0;
  const hit = score >= min;
  const dir =
    a.direction === "BUY" ? "COMPRA (Apostar na Subida)" : a.direction === "SELL" ? "VENDA (Apostar na Queda)" : "—";
  const allGatesOk = a.gates.every((g) => g.ok);
  const missing = Math.max(0, min - score);
  const hz = a.horizon;
  const calProb = a.calibrated_win_probability;

  return (
    <div className="mx-3 mt-2 rounded border border-ink-700 bg-ink-850 p-2.5">
      <div className="flex items-end justify-between">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
            Confluência Heurística · Sinal Atual:
          </div>
          <div className={cx("text-xs font-extrabold", a.direction === "BUY" ? "text-bull" : "text-bear")}>{dir}</div>
        </div>
        <div className="text-right">
          <div className={cx("num text-xl font-extrabold leading-none", hit ? "text-bull" : "text-white")}>
            {score.toFixed(0)}
          </div>
          <div className="text-[10px] text-slate-400">Score Confluência ≥ {min}</div>
        </div>
      </div>

      <div className="relative mt-1.5 h-3 overflow-hidden rounded-full bg-ink-950">
        <div
          className={cx(
            "h-full transition-all duration-300",
            hit ? "bg-bull" : score >= min * 0.85 ? "bg-warn" : "bg-accent",
          )}
          style={{ width: `${Math.min(100, Math.max(0, score))}%` }}
        />
        <div
          className="absolute top-0 h-full w-0.5 bg-white"
          style={{ left: `${min}%` }}
          title={`Score mínimo exigido: ${min}`}
        />
      </div>

      <div className="num mt-1.5 flex flex-wrap items-center justify-between gap-1 text-[10px] text-slate-400">
        <span>
          Compra: <b className="text-bull">{fmtNum(a.score_buy, 0)}</b> · Venda:{" "}
          <b className="text-bear">{fmtNum(a.score_sell, 0)}</b>
        </span>
        <div className="flex items-center gap-1.5">
          {calProb !== null && calProb !== undefined ? (
            <span className="rounded bg-sky-500/20 px-1.5 py-0.5 font-bold text-sky-300">
              Prob. Calibrada: {(calProb * 100).toFixed(0)}%
            </span>
          ) : (
            <span className="rounded bg-ink-800 px-1.5 py-0.5 text-slate-400">
              Heurístico (Sem Calibração OOS)
            </span>
          )}
          <span>Horizonte: <b className="text-amber-300">{hz?.short_label ?? "⚡ 1 Vela"}</b></span>
        </div>
      </div>

      <div className="mt-1.5 rounded bg-ink-900 px-2 py-1 text-[11px]">
        {a.signal && hit ? (
          <span className="font-bold text-bull">
            ⚡ SINAL SNIPER CONFIRMADO DE {a.signal === "BUY" ? "COMPRA" : "VENDA"}! ({hz?.label ?? "1 Vela"})
          </span>
        ) : !hit ? (
          <span className="text-slate-300">
            ⏳ Faltam <b className="num text-white">{missing.toFixed(0)} pts</b> para acionar Sniper nesta moeda.
          </span>
        ) : !allGatesOk ? (
          <span className="text-amber-300">
            ⚠️ Pontuação atingida ({score.toFixed(0)}), aguardando espaço estrutural livre.
          </span>
        ) : null}
      </div>
    </div>
  );
}

function CandleAndHorizonBox({ a }: { a: Analysis }) {
  const cdl = a.candle;
  const hz = a.horizon;
  const sr = a.structural_room;
  if (!cdl) return null;
  const up = cdl.prob_up >= cdl.prob_down;
  const bestProb = up ? cdl.prob_up : cdl.prob_down;
  return (
    <div className="mx-3 mt-2 rounded border border-ink-700 bg-ink-900/90 p-2.5 text-[11px]">
      <div className="flex flex-wrap items-center justify-between gap-1.5 border-b border-ink-800 pb-1.5">
        <span className="flex items-center gap-1 font-extrabold uppercase tracking-wider text-accent">
          <Flame size={12} /> Estrutura & Horizonte Temporal
        </span>
        <div className="flex items-center gap-1.5">
          {hz && (
            <span className="num flex items-center gap-1 rounded bg-amber-400/20 px-1.5 py-0.5 text-[10px] font-extrabold text-amber-300">
              <Clock size={10} /> Válido por {hz.duration_s}s
            </span>
          )}
          <span
            className={cx(
              "num rounded px-2 py-0.5 text-[10.5px] font-extrabold",
              up ? "bg-bull/20 text-bull" : "bg-bear/20 text-bear",
            )}
          >
            Viés Vela: {bestProb.toFixed(0)}% {up ? "ALTA ↑" : "BAIXA ↓"}
          </span>
        </div>
      </div>

      <div className="mt-1.5 space-y-1 text-[10.5px] leading-snug">
        {(hz?.strategy || cdl.best_strategy) && (
          <div>
            <span className="font-semibold text-accent">Estratégia: </span>
            <span className="font-bold text-white">{hz?.strategy ?? cdl.best_strategy}</span>
          </div>
        )}
        {sr && (
          <div>
            <span className="font-semibold text-slate-400">Espaço Estrutural: </span>
            <span className={cx("font-bold", sr.status === "ADEQUATE" ? "text-bull" : sr.status === "TIGHT" ? "text-amber-300" : "text-bear")}>
              {sr.status} ({sr.room_atr.toFixed(2)} ATR até {sr.level_type})
            </span>
          </div>
        )}
        <div>
          <span className="font-semibold text-slate-400">Vela anterior: </span>
          <span className="text-slate-200">{cdl.prev_desc}</span>
        </div>
        <div>
          <span className="font-semibold text-slate-400">Rabos / Pavios: </span>
          <span
            className={cx(
              cdl.wick_pressure >= 0.14
                ? "font-semibold text-bull"
                : cdl.wick_pressure <= -0.14
                  ? "font-semibold text-bear"
                  : "text-slate-300",
            )}
          >
            {cdl.wick_desc}
          </span>
        </div>
      </div>
    </div>
  );
}

function PillarRow({ p }: { p: Analysis["pillars"][number] }) {
  const [open, setOpen] = useState(false);
  const simple = SIMPLE_PILLAR_INFO[p.id] ?? { title: p.name, subtitle: p.value };
  const pct = Math.round((p.score ?? 0) * 100);
  return (
    <div className="rounded border border-ink-700 bg-ink-850">
      <button className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left" onClick={() => setOpen(!open)}>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 text-[11px] font-bold text-slate-100">
            <span className="truncate">{simple.title}</span>
          </div>
          <div className="truncate text-[10px] text-slate-400">{simple.subtitle}</div>
        </div>
        <span
          className={cx(
            "num shrink-0 rounded px-1.5 py-0.5 text-[9.5px] font-extrabold",
            p.ok ? "bg-bull/20 text-bull" : "bg-ink-800 text-slate-400",
          )}
        >
          {p.ok ? `✅ ${pct}%` : `⏳ ${pct}%`}
        </span>
        {open ? (
          <ChevronDown size={12} className="shrink-0 text-slate-500" />
        ) : (
          <ChevronRight size={12} className="shrink-0 text-slate-500" />
        )}
      </button>
      {open && (
        <div className="border-t border-ink-700 px-2.5 py-1.5">
          <div className="num mb-1 text-[10px] text-slate-400">{p.value}</div>
          <ul className="space-y-0.5">
            {p.checks.map((c) => (
              <li key={c.label} className="flex items-center gap-1.5 text-[10.5px]">
                {c.ok ? <CheckCircle2 size={11} className="text-bull" /> : <XCircle size={11} className="text-bear" />}
                <span className={c.ok ? "text-slate-200" : "text-slate-500"}>{c.label}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function BrainPanelImpl({
  ai,
  analysis,
  mode,
  logs,
  radar = [],
  activeSymbol,
  autoSymbol = true,
  quant,
  send,
}: Props) {
  const [subTab, setSubTab] = useState<"radar" | "criteria" | "quant" | "logs">("radar");
  const [runningBacktest, setRunningBacktest] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  const [follow, setFollow] = useState(true);

  useEffect(() => {
    const el = logRef.current;
    if (el && follow && subTab === "logs") el.scrollTop = el.scrollHeight;
  }, [logs, follow, subTab]);

  const a = analysis && analysis.regime ? analysis : null;
  const reg = a?.regime;
  const flow = a?.flow;
  const buyPct = flow && flow.buy + flow.sell > 0 ? Math.round((100 * flow.buy) / (flow.buy + flow.sell)) : 50;
  const sellPct = 100 - buyPct;
  const totalPillars = a?.pillars?.length ?? 6;
  const okCount = a?.pillars?.filter((p) => p.ok).length ?? 0;
  const lastLog = logs.length > 0 ? logs[logs.length - 1] : null;

  const runBacktest = async () => {
    if (!send) return;
    setRunningBacktest(true);
    try {
      await send("run_backtest", {});
    } finally {
      setRunningBacktest(false);
    }
  };

  const perf = quant?.performance;

  return (
    <aside className="panel flex w-full flex-col overflow-hidden">
      <div className="panel-title">
        <Brain size={13} className="text-accent" /> Mega Brain V5 Quant · Multi-Cérebros
        <span
          className={cx(
            "ml-auto rounded px-2 py-0.5 text-[9.5px] font-extrabold",
            ai?.enabled ? "bg-bull text-ink-950" : "bg-ink-700 text-slate-300",
          )}
        >
          {ai?.enabled ? "CAÇANDO OPORTUNIDADES" : "MODO LEITURA"}
        </span>
      </div>

      <StateMachine ai={ai} />

      <div className="px-3 pt-2">
        <div className="mb-1 flex items-center justify-between text-[10px] font-bold uppercase tracking-wider text-slate-400">
          <span className="flex items-center gap-1">
            <Activity size={11} /> Cérebro {activeSymbol ?? "Ativo"} ({a?.timeframe ?? "M1"} ·{" "}
            {a?.horizon?.short_label ?? "1 Vela"})
          </span>
        </div>
        <div className={cx("rounded border px-2.5 py-1.5", REGIME_STYLE[reg?.code ?? "UNKNOWN"])}>
          <div className="text-xs font-extrabold">{REGIME_FRIENDLY[reg?.code ?? "UNKNOWN"] ?? reg?.label}</div>
          {a?.study_block && <div className="mt-0.5 text-[11px] text-amber-300">🛡️ {a.study_block}</div>}
        </div>
      </div>

      {a?.ready ? (
        <>
          <Thermometer a={a} mode={mode} ai={ai} />
          <CandleAndHorizonBox a={a} />

          {/* FLUXO DE COMPRADORES VS VENDEDORES */}
          {flow && (
            <div className="px-3 pt-2">
              <div className="mb-1 flex justify-between text-[10px] font-bold uppercase tracking-wider text-slate-400">
                <span className="text-bull">Compradores {buyPct}%</span>
                <span className="text-bear">Vendedores {sellPct}%</span>
              </div>
              <div className="relative h-2 overflow-hidden rounded-full bg-bear/70">
                <div className="h-full bg-bull" style={{ width: `${buyPct}%` }} />
              </div>
            </div>
          )}

          {/* SELETOR INTERNO: CÉREBROS vs 6 PILARES vs MEMÓRIA QUANT vs DIÁRIO */}
          <div className="mt-2.5 flex items-center gap-1 border-y border-ink-700 bg-ink-850 px-2.5 py-1.5 text-[10px]">
            <button
              onClick={() => setSubTab("radar")}
              className={cx(
                "flex flex-1 items-center justify-center gap-1 rounded px-1.5 py-1 font-extrabold transition",
                subTab === "radar"
                  ? "bg-accent text-white shadow"
                  : "bg-ink-800 text-slate-300 hover:bg-ink-700 hover:text-white",
              )}
            >
              <Cpu size={11} /> Cérebros ({radar.length})
            </button>
            <button
              onClick={() => setSubTab("criteria")}
              className={cx(
                "flex flex-1 items-center justify-center gap-1 rounded px-1.5 py-1 font-extrabold transition",
                subTab === "criteria"
                  ? "bg-accent text-white shadow"
                  : "bg-ink-800 text-slate-300 hover:bg-ink-700 hover:text-white",
              )}
            >
              <Gauge size={11} /> Pilares ({okCount}/{totalPillars})
            </button>
            <button
              onClick={() => setSubTab("quant")}
              className={cx(
                "flex flex-1 items-center justify-center gap-1 rounded px-1.5 py-1 font-extrabold transition",
                subTab === "quant"
                  ? "bg-accent text-white shadow"
                  : "bg-ink-800 text-slate-300 hover:bg-ink-700 hover:text-white",
              )}
            >
              <Database size={11} /> Memória ({perf?.sample_size ?? 0})
            </button>
            <button
              onClick={() => setSubTab("logs")}
              className={cx(
                "flex flex-1 items-center justify-center gap-1 rounded px-1.5 py-1 font-extrabold transition",
                subTab === "logs"
                  ? "bg-accent text-white shadow"
                  : "bg-ink-800 text-slate-300 hover:bg-ink-700 hover:text-white",
              )}
            >
              <ScrollText size={11} /> Diário ({logs.length})
            </button>
          </div>

          {subTab === "radar" ? (
            <div className="space-y-1.5 p-2.5">
              <div className="flex items-center justify-between text-[10px] text-slate-400">
                <span>
                  {autoSymbol
                    ? "🧠 1 Cérebro por moeda (até 4 simultâneas com trava USD):"
                    : "📌 Gráfico fixo (clique em AUTO no topo p/ escanear todas):"}
                </span>
                <span>Sniper ≥ {Math.max(85, mode?.min_score ?? 86)}</span>
              </div>

              <div className="max-h-[260px] space-y-1 overflow-y-auto pr-0.5">
                {radar.length === 0 && (
                  <div className="py-4 text-center text-xs text-slate-500">Sincronizando cérebros das moedas…</div>
                )}
                {radar.map((r, idx) => {
                  const isCurrent = r.symbol === activeSymbol;
                  const isBuy = r.direction === "BUY";
                  return (
                    <button
                      key={r.symbol}
                      onClick={() => send && void send("set_symbol", { symbol: r.symbol })}
                      className={cx(
                        "flex w-full items-center justify-between gap-2 rounded border px-2.5 py-1.5 text-left text-xs transition",
                        r.signal
                          ? "border-bull bg-bull/15"
                          : isCurrent
                            ? "border-accent bg-accent/10"
                            : "border-ink-700 bg-ink-850 hover:border-ink-500",
                      )}
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="num text-[10px] font-bold text-slate-500">#{idx + 1}</span>
                          <b className="text-white">{r.symbol}</b>
                          <span className="rounded bg-amber-400/15 px-1.5 py-0.5 text-[9px] font-bold text-amber-300">
                            {r.horizon_label ?? "⚡ 1 Vela"}
                          </span>
                          {isCurrent && (
                            <span className="rounded bg-accent/25 px-1.5 py-0.5 text-[9px] font-extrabold text-accent">
                              NO GRÁFICO
                            </span>
                          )}
                          {r.signal && (
                            <span className="rounded bg-bull px-1.5 py-0.5 text-[9px] font-extrabold text-ink-950">
                              ⚡ SINAL
                            </span>
                          )}
                          <span
                            className={cx(
                              "inline-flex items-center gap-0.5 text-[10.5px] font-bold",
                              isBuy ? "text-bull" : "text-bear",
                            )}
                          >
                            {isBuy ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
                            {isBuy ? "COMPRA" : "VENDA"}
                          </span>
                        </div>
                        <div className="mt-0.5 truncate text-[10px] text-slate-400">
                          {r.regime} · {r.reason}
                        </div>
                      </div>

                      <div className="num shrink-0 text-right">
                        <div
                          className={cx(
                            "text-sm font-extrabold leading-none",
                            r.score >= r.min_score && !r.blocked ? "text-bull" : "text-slate-100",
                          )}
                        >
                          {r.score.toFixed(0)}
                        </div>
                        <div className="mt-0.5 text-[9.5px] text-slate-400">
                          Vela: <b className={isBuy ? "text-bull" : "text-bear"}>{r.next_prob.toFixed(0)}%</b>
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          ) : subTab === "criteria" ? (
            <div className="space-y-2 p-2.5">
              <div className="space-y-1.5">
                {a.pillars.map((p) => (
                  <PillarRow key={p.id} p={p} />
                ))}
              </div>

              <div>
                <div className="mb-1 flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                  <ListChecks size={11} /> Travas Eliminatórias
                </div>
                <ul className="space-y-1 rounded border border-ink-700 bg-ink-850 p-2">
                  {a.gates.map((g) => (
                    <li key={g.label} className="flex items-center gap-1.5 text-[10.5px]">
                      {g.ok ? (
                        <CheckCircle2 size={12} className="shrink-0 text-bull" />
                      ) : (
                        <XCircle size={12} className="shrink-0 text-bear" />
                      )}
                      <span className={g.ok ? "text-slate-200" : "text-slate-400"}>{g.label}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ) : subTab === "quant" ? (
            <div className="space-y-2 p-2.5 text-[10.5px]">
              {/* ESTATISTICAS DE MEMORIA SQLITE */}
              <div className="rounded border border-ink-700 bg-ink-850 p-2">
                <div className="flex items-center justify-between border-b border-ink-700 pb-1 font-bold text-accent">
                  <span>Memória Quantitativa (SQLite WAL)</span>
                  <span className="rounded bg-ink-700 px-1.5 py-0.5 text-[9px] text-slate-200">
                    Modo: {ai?.adaptive_mode ?? "OBSERVATION"}
                  </span>
                </div>
                <div className="num mt-1.5 grid grid-cols-2 gap-1.5 text-[10px]">
                  <div>
                    <span className="text-slate-400">Amostra Registrada: </span>
                    <b className="text-white">{perf?.sample_size ?? 0} op.</b>
                  </div>
                  <div>
                    <span className="text-slate-400">Acerto Real: </span>
                    <b className="text-white">{perf?.win_rate?.toFixed(1) ?? 0.0}%</b>
                  </div>
                  <div>
                    <span className="text-slate-400">Expectativa Líquida: </span>
                    <b className={cx((perf?.expectancy ?? 0) >= 0 ? "text-bull" : "text-bear")}>
                      {perf?.expectancy !== undefined ? `${perf.expectancy > 0 ? "+" : ""}${perf.expectancy.toFixed(2)}` : "—"}
                    </b>
                  </div>
                  <div>
                    <span className="text-slate-400">Fator de Lucro: </span>
                    <b className="text-white">{perf?.profit_factor?.toFixed(2) ?? "—"}</b>
                  </div>
                  <div>
                    <span className="text-slate-400">MFE Médio: </span>
                    <b className="text-bull">+{perf?.avg_mfe_points?.toFixed(1) ?? 0} pts</b>
                  </div>
                  <div>
                    <span className="text-slate-400">MAE Médio: </span>
                    <b className="text-bear">-{perf?.avg_mae_points?.toFixed(1) ?? 0} pts</b>
                  </div>
                </div>
              </div>

              {/* BOTÃO E RESULTADO DE BACKTEST WALK-FORWARD */}
              <div className="rounded border border-ink-700 bg-ink-850 p-2">
                <div className="flex items-center justify-between">
                  <span className="font-bold text-slate-200">Validação Walk-Forward OOS</span>
                  <button
                    onClick={() => void runBacktest()}
                    disabled={runningBacktest}
                    className="flex items-center gap-1 rounded bg-accent/20 border border-accent/40 px-2 py-0.5 text-[10px] font-bold text-accent hover:bg-accent/30 disabled:opacity-50"
                  >
                    <Play size={10} /> {runningBacktest ? "Rodando..." : "Executar"}
                  </button>
                </div>
                {quant?.backtest && (
                  <div className="mt-1.5 text-[10px] text-slate-300">
                    <div>Status: <b className="text-amber-300">{quant.backtest.verdict?.status ?? "—"}</b></div>
                    <div className="mt-0.5 text-slate-400">{quant.backtest.verdict?.summary}</div>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="flex flex-col p-2.5">
              <div className="mb-1.5 flex items-center justify-between text-[10px] text-slate-400">
                <span className="font-bold uppercase">Histórico de ações ao vivo</span>
                <label className="flex items-center gap-1">
                  <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> rolar
                  automático
                </label>
              </div>
              <div
                ref={logRef}
                className="num max-h-[260px] min-h-[200px] space-y-1 overflow-y-auto rounded border border-ink-700 bg-ink-950 p-2 text-[10.5px] leading-snug"
              >
                {logs.map((l) => (
                  <div key={l.id} className={LOG_STYLE[l.level] ?? "text-slate-300"}>
                    <span className="text-slate-500">[{l.ts}]</span> {l.msg}
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      ) : (
        <div className="p-3 text-[11px] text-slate-500">Carregando indicadores do MT5…</div>
      )}

      {lastLog && subTab !== "logs" && (
        <button
          onClick={() => setSubTab("logs")}
          title="Clique para abrir o Diário completo da IA"
          className="flex w-full items-center gap-2 border-t border-ink-700 bg-ink-950 px-3 py-2 text-left text-[10.5px] hover:bg-ink-850"
        >
          <ScrollText size={12} className="shrink-0 text-accent" />
          <span className={cx("num flex-1 truncate", LOG_STYLE[lastLog.level] ?? "text-slate-300")}>
            <span className="text-slate-500">[{lastLog.ts}]</span> {lastLog.msg}
          </span>
          <span className="shrink-0 text-[10px] font-bold text-accent">Diário →</span>
        </button>
      )}
    </aside>
  );
}

export const BrainPanel = memo(BrainPanelImpl);
