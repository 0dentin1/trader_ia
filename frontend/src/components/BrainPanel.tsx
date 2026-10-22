import { memo, useEffect, useRef, useState } from "react";
import {
  Activity,
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Cpu,
  Flame,
  Gauge,
  ListChecks,
  ScrollText,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
  XCircle,
} from "lucide-react";
import type { AIState, AIStatus, Analysis, LogEntry, ModeConfig, RadarEntry } from "../types";
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
  send?: TerminalApi["send"];
}

const FLOW_STATES: { key: AIState; label: string; desc: string }[] = [
  { key: "STUDYING_MARKET", label: "1. Multi-Cérebros", desc: "Escaneando todas as moedas em M1/M2/M5" },
  { key: "EVALUATING_CONFLUENCE", label: "2. Tempo & Vela", desc: "Calculando certeza e validade da vela" },
  { key: "EXECUTING_TRADE", label: "3. Tiro Sniper", desc: "Disparando ordem no momento imperdível" },
  { key: "MANAGING_POSITION", label: "4. Colheita Ativa", desc: "Vigiando validade da vela e lucro" },
  { key: "COOLDOWN", label: "5. Pausa Tática", desc: "Aguardando próxima vela limpa" },
  { key: "RISK_LOCK", label: "6. Meta/Stop Dia", desc: "Operações encerradas hoje" },
];

const SIMPLE_PILLAR_INFO: Record<number, { title: string; subtitle: string }> = {
  1: {
    title: "1. Estratégia Institucional & Anatomia da Vela",
    subtitle: "SMC Liquidity Sweep, Pullback EMA 9/21, Squeeze Breakout, Defesa VWAP e Pavios",
  },
  2: {
    title: "2. Alinhamento Estrito Multi-Timeframe (M1+M5+M15)",
    subtitle: "Proíbe operar contra a tendência do M5 e exige confluência direcional limpa",
  },
  3: {
    title: "3. Espaço Livre até Liquidez / Topo / Fundo",
    subtitle: "Garante alvo maior que o stop sem bater em resistência ou suporte próximo",
  },
  4: {
    title: "4. Fluxo Institucional de Ticks & Agressão",
    subtitle: "Confirma agressão real dos compradores/vendedores neste exato segundo",
  },
  5: {
    title: "5. Assimetria Positiva (Alvo vs Custo de Spread)",
    subtitle: "Bloqueia moedas paradas (< 6 pts ATR) ou onde o spread come mais de 16% do alvo",
  },
  6: {
    title: "6. Força Limpa sem Exaustão (RSI / ADX / VWAP)",
    subtitle: "Garante espaço para o preço andar sem sobrecompra ou sobrevenda extrema",
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
  REVERSAL_UP: "🔄 Virada Compradora (Rejeição de Fundo / Pavio)",
  REVERSAL_DOWN: "🔄 Virada Vendedora (Rejeição de Topo / Pavio)",
  RANGE: "↔️ Mercado Lateral / Consolidação",
  HIGH_VOL: "⚡ Explosão de Volatilidade / Rompimento",
  UNKNOWN: "⏳ Carregando histórico do gráfico…",
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
            {off ? "⏸️ Mega Brain Pausado (Modo Leitura)" : `🧠 ${ai?.state_label}`}
          </span>
        </div>
        <div className="mt-0.5 truncate text-[11px] text-slate-300">{ai?.detail || "—"}</div>
      </div>

      {rec?.active && (
        <div className="flex items-center gap-1.5 rounded border border-amber-400/50 bg-amber-400/10 px-2.5 py-1.5 text-[10.5px] text-amber-300">
          <ShieldAlert size={13} className="shrink-0" />
          <span>
            <b>Modo Recuperação Sniper Ativo:</b> exige +2% de certeza, bloqueia repetição de erro e colhe lucro rápido!
          </span>
        </div>
      )}
    </div>
  );
}

function Thermometer({ a, mode, ai }: { a: Analysis; mode: ModeConfig | undefined; ai: AIStatus | undefined }) {
  const baseMin = Math.max(82, mode?.min_score ?? 85);
  const min = ai?.recovery?.active ? Math.min(91, baseMin + 2) : baseMin;
  const score = a.score ?? 0;
  const hit = score >= min;
  const dir =
    a.direction === "BUY" ? "COMPRA (Apostar na Subida)" : a.direction === "SELL" ? "VENDA (Apostar na Queda)" : "—";
  const allGatesOk = a.gates.every((g) => g.ok);
  const missing = Math.max(0, min - score);
  const hz = a.horizon;

  return (
    <div className="mx-3 mt-2 rounded border border-ink-700 bg-ink-850 p-2.5">
      <div className="flex items-end justify-between">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
            Certeza Sniper desta Moeda · Melhor Lado:
          </div>
          <div className={cx("text-xs font-extrabold", a.direction === "BUY" ? "text-bull" : "text-bear")}>{dir}</div>
        </div>
        <div className="text-right">
          <div className={cx("num text-xl font-extrabold leading-none", hit ? "text-bull" : "text-white")}>
            {score.toFixed(0)}%
          </div>
          <div className="text-[10px] text-slate-400">Sniper ≥ {min}%</div>
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
          title={`Certeza Sniper exigida: ${min}%`}
        />
      </div>

      <div className="num mt-1 flex justify-between text-[10px] text-slate-400">
        <span>
          Compra: <b className="text-bull">{fmtNum(a.score_buy, 0)}%</b> · Venda:{" "}
          <b className="text-bear">{fmtNum(a.score_sell, 0)}%</b>
        </span>
        <span>Horizonte: <b className="text-amber-300">{hz?.short_label ?? "⚡ 1 Vela (60s)"}</b></span>
      </div>

      <div className="mt-1.5 rounded bg-ink-900 px-2 py-1 text-[11px]">
        {a.signal && hit ? (
          <span className="font-bold text-bull">
            ⚡ OPORTUNIDADE IMPERDÍVEL DE {a.signal === "BUY" ? "COMPRA" : "VENDA"}! ({hz?.label ?? "1 Vela"})
          </span>
        ) : !hit ? (
          <span className="text-slate-300">
            ⏳ Faltam <b className="num text-white">{missing.toFixed(0)}%</b> para ser Imperdível nesta moeda (demais cérebros escaneando em paralelo).
          </span>
        ) : !allGatesOk ? (
          <span className="text-amber-300">
            ⚠️ Nota atingida ({score.toFixed(0)}%), aguardando liberação de espaço livre/vela abaixo.
          </span>
        ) : null}
      </div>
    </div>
  );
}

function CandleAndHorizonBox({ a }: { a: Analysis }) {
  const cdl = a.candle;
  const hz = a.horizon;
  if (!cdl) return null;
  const up = cdl.prob_up >= cdl.prob_down;
  const bestProb = up ? cdl.prob_up : cdl.prob_down;
  return (
    <div className="mx-3 mt-2 rounded border border-ink-700 bg-ink-900/90 p-2.5 text-[11px]">
      <div className="flex flex-wrap items-center justify-between gap-1.5 border-b border-ink-800 pb-1.5">
        <span className="flex items-center gap-1 font-extrabold uppercase tracking-wider text-accent">
          <Flame size={12} /> Vela & Tempo da Previsão
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
            Próx. Vela: {bestProb.toFixed(0)}% {up ? "ALTA ↑" : "BAIXA ↓"}
          </span>
        </div>
      </div>

      <div className="mt-1.5 space-y-1 text-[10.5px] leading-snug">
        {(hz?.strategy || cdl.best_strategy) && (
          <div>
            <span className="font-semibold text-accent">Estratégia Institucional: </span>
            <span className="font-bold text-white">{hz?.strategy ?? cdl.best_strategy}</span>
          </div>
        )}
        {hz && (
          <div>
            <span className="font-semibold text-amber-300">Tempo Escolhido pela IA: </span>
            <span className="font-bold text-white">{hz.label}</span>{" "}
            <span className="text-slate-400">({hz.reason})</span>
          </div>
        )}
        <div>
          <span className="font-semibold text-slate-400">Vela anterior: </span>
          <span className="text-slate-200">{cdl.prev_desc}</span>
        </div>
        <div>
          <span className="font-semibold text-slate-400">Vela atual: </span>
          <span className="text-slate-200">{cdl.curr_desc}</span>
        </div>
        <div>
          <span className="font-semibold text-slate-400">Rabos (Pavios): </span>
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
  send,
}: Props) {
  const [subTab, setSubTab] = useState<"radar" | "criteria" | "logs">("radar");
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

  return (
    <aside className="panel flex w-full flex-col overflow-hidden">
      <div className="panel-title">
        <Brain size={13} className="text-accent" /> Mega Brain V4 · 1 Cérebro por Moeda
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

          {/* CABO DE GUERRA COMPRADORES VS VENDEDORES */}
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

          {/* SELETOR INTERNO: CÉREBROS POR MOEDA vs 6 PILARES vs DIÁRIO */}
          <div className="mt-2.5 flex items-center gap-1 border-y border-ink-700 bg-ink-850 px-2.5 py-1.5 text-[10.5px]">
            <button
              onClick={() => setSubTab("radar")}
              className={cx(
                "flex flex-1 items-center justify-center gap-1 rounded px-2 py-1 font-extrabold transition",
                subTab === "radar"
                  ? "bg-accent text-white shadow"
                  : "bg-ink-800 text-slate-300 hover:bg-ink-700 hover:text-white",
              )}
            >
              <Cpu size={12} /> Cérebros ({radar.length})
            </button>
            <button
              onClick={() => setSubTab("criteria")}
              className={cx(
                "flex flex-1 items-center justify-center gap-1 rounded px-2 py-1 font-extrabold transition",
                subTab === "criteria"
                  ? "bg-accent text-white shadow"
                  : "bg-ink-800 text-slate-300 hover:bg-ink-700 hover:text-white",
              )}
            >
              <Gauge size={12} /> 6 Pilares ({okCount}/{totalPillars})
            </button>
            <button
              onClick={() => setSubTab("logs")}
              className={cx(
                "flex flex-1 items-center justify-center gap-1 rounded px-2 py-1 font-extrabold transition",
                subTab === "logs"
                  ? "bg-accent text-white shadow"
                  : "bg-ink-800 text-slate-300 hover:bg-ink-700 hover:text-white",
              )}
            >
              <ScrollText size={12} /> Diário ({logs.length})
            </button>
          </div>

          {subTab === "radar" ? (
            <div className="space-y-1.5 p-2.5">
              <div className="flex items-center justify-between text-[10px] text-slate-400">
                <span>
                  {autoSymbol
                    ? "🧠 1 Cérebro por moeda (opera até 4 simultâneas c/ trava cambial):"
                    : "📌 Gráfico fixo (clique em AUTO no topo p/ liberar todos):"}
                </span>
                <span>Sniper ≥ {Math.max(85, mode?.min_score ?? 86)}%</span>
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
                              ⚡ IMPERDÍVEL
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
                          {r.score.toFixed(0)}%
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
                  <ListChecks size={11} /> Travas Eliminatórias do Mega Brain
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

      {/* BARRA DE RODAPÉ SEMPRE VISÍVEL COM A ÚLTIMA AÇÃO DA IA */}
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
