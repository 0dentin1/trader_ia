import { memo } from "react";
import { BrainCircuit, Clock, Cpu, ShieldCheck, Sparkles, Zap } from "lucide-react";
import type { AIStatus, Analysis, MetaMsg, ModeKey, RadarEntry } from "../types";
import type { TerminalApi } from "../hooks/useTerminal";
import { cx } from "../lib/format";

interface Props {
  meta: MetaMsg | null;
  active: ModeKey | undefined;
  send: TerminalApi["send"];
  locked: boolean;
  ai?: AIStatus;
  analysis?: Analysis | null;
  radar?: RadarEntry[];
}

function ModeSelectorImpl({ ai, analysis, radar }: Props) {
  const brainsCount = radar?.length || ai?.active_brains || 8;
  const hz = analysis?.horizon;
  const evalTfs = analysis?.evaluated_timeframes ?? [];
  const sniperReady = radar?.filter((r) => r.signal).length ?? 0;

  return (
    <div className="panel flex h-full flex-col justify-between p-2.5">
      <div className="mb-1.5 flex flex-wrap items-center justify-between gap-1 text-[11px]">
        <span className="flex items-center gap-1.5 font-extrabold uppercase tracking-wider text-accent">
          <BrainCircuit size={14} /> Mega Brain V4 Institucional · 5 Estratégias + Proteção Blindada de Banca
        </span>
        <span className="rounded bg-bull/15 px-2 py-0.5 text-[10px] font-bold text-bull">
          🛡️ Risco/Retorno Positivo (Alvo &gt; Stop) · Proibido Contra-Tendência M5 · Até 4 Moedas Simultâneas
        </span>
      </div>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        {/* CARD 1: MULTI-CÉREBROS PARALELOS (1 CÉREBRO POR MOEDA) */}
        <div className="flex flex-col justify-between gap-1.5 rounded-md border border-accent/40 bg-accent/5 p-2">
          <div>
            <div className="flex items-center justify-between gap-1">
              <span className="flex items-center gap-1.5 text-xs font-extrabold uppercase text-accent">
                <Cpu size={14} /> {brainsCount} Cérebros Paralelos
              </span>
              <span className="rounded bg-accent text-ink-950 px-1.5 py-0.5 text-[9.5px] font-extrabold">
                1 POR MOEDA
              </span>
            </div>
            <p className="mt-1 text-[10.5px] leading-snug text-slate-300">
              Cada moeda tem seu próprio cérebro analisando 5 estratégias institucionais (SMC, Pullback EMA, Squeeze, VWAP e Fluxo).
            </p>
          </div>
          <div className="flex items-center justify-between border-t border-ink-700/80 pt-1 text-[10px] text-slate-300">
            <span>Até <b>4 moedas simultâneas</b></span>
            <span className={cx("font-bold", sniperReady > 0 ? "text-bull" : "text-slate-400")}>
              {sniperReady > 0 ? `⚡ ${sniperReady} Sinal(is) Pronto(s)` : "Escaneando mercado..."}
            </span>
          </div>
        </div>

        {/* CARD 2: ESCOLHA AUTOMÁTICA DO TEMPO DA OPERAÇÃO (1 VELA A 5 MIN) */}
        <div className="flex flex-col justify-between gap-1.5 rounded-md border border-amber-400/40 bg-amber-400/5 p-2">
          <div>
            <div className="flex items-center justify-between gap-1">
              <span className="flex items-center gap-1.5 text-xs font-extrabold uppercase text-amber-300">
                <Clock size={14} /> Tempo & Estratégia
              </span>
              <span className="rounded bg-amber-400 text-ink-950 px-1.5 py-0.5 text-[9.5px] font-extrabold">
                {hz ? hz.short_label : "⚡ 1 Vela (60s)"}
              </span>
            </div>
            <p className="mt-1 text-[10.5px] leading-snug text-slate-300">
              Avalia <b>M1, M2, M5 e M15</b> juntos e nunca entra contra a tendência principal do M5.
            </p>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-1 border-t border-ink-700/80 pt-1 text-[10px]">
            {evalTfs.length > 0 ? (
              evalTfs.map((t) => (
                <span
                  key={t.tf}
                  className={cx(
                    "num rounded px-1.5 py-0.2 font-bold",
                    t.tf === analysis?.timeframe
                      ? "bg-amber-400/20 text-amber-300"
                      : "bg-ink-800 text-slate-400",
                  )}
                >
                  {t.tf}: {t.score.toFixed(0)}% ({t.duration_s}s)
                </span>
              ))
            ) : (
              <span className="text-amber-300">⚡ 1 Vela (45-75s) · 🎯 Impulso (2m) · 🚀 Onda (5m)</span>
            )}
          </div>
        </div>

        {/* CARD 3: PROTEÇÃO BLINDADA DE BANCA (€100 A $100K) & ASSIMETRIA POSITIVA */}
        <div className="flex flex-col justify-between gap-1.5 rounded-md border border-bull/40 bg-bull/5 p-2">
          <div>
            <div className="flex items-center justify-between gap-1">
              <span className="flex items-center gap-1.5 text-xs font-extrabold uppercase text-bull">
                <Sparkles size={14} /> Banca Blindada V4
              </span>
              <span className="rounded bg-bull text-ink-950 px-1.5 py-0.5 text-[9.5px] font-extrabold">
                SNIPER 86%+
              </span>
            </div>
            <p className="mt-1 text-[10.5px] leading-snug text-slate-300">
              Lote travado por alavancagem segura (protege de R$50/€100 a contas grandes) e alvo sempre maior que o stop.
            </p>
          </div>
          <div className="flex items-center justify-between border-t border-ink-700/80 pt-1 text-[10px] text-slate-300">
            <span className="flex items-center gap-1 text-bull">
              <Zap size={10} /> Lucro &gt; Perda (R/R Positivo)
            </span>
            <span className="flex items-center gap-1 text-slate-300">
              <ShieldCheck size={10} className="text-accent" /> Stop Estrutural
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

export const ModeSelector = memo(ModeSelectorImpl);
