import { memo, useEffect, useState } from "react";
import { Save, ShieldAlert, Lock, CheckCircle2, Unlock, AlertTriangle } from "lucide-react";
import type { DayFinancials, MetaMsg, ModeKey, SmallAccountGuardSummary } from "../types";
import type { TerminalApi } from "../hooks/useTerminal";
import { cx } from "../lib/format";

interface Props {
  meta: MetaMsg | null;
  mode: ModeKey | undefined;
  currency: string;
  spreadNow: number | null | undefined;
  lock: { active: boolean; reason: string | null; lock_type?: string } | undefined;
  guard?: SmallAccountGuardSummary;
  day?: DayFinancials;
  send: TerminalApi["send"];
}

interface Form {
  daily_loss_limit: string;
  daily_gain_target: string;
  weekly_loss_limit: string;
  max_spread_points: string;
  risk: string;
  lot_multiplier: string;
  aggressive_rr: string;
  protect_whole_account: boolean;
  sync_chart_symbol: boolean;
  account_profile: string;
  adaptive_mode: string;
}

const DD_BADGES: Record<string, { label: string; cls: string }> = {
  NORMAL: { label: "Seguro (Normal)", cls: "bg-bull/20 text-bull border-bull/40" },
  CAUTION: { label: "Atenção (Risco -25%)", cls: "bg-amber-400/20 text-amber-300 border-amber-400/40" },
  REDUCED_EXPOSURE: { label: "Reduzido (Risco -50%)", cls: "bg-orange-500/20 text-orange-400 border-orange-500/40" },
  TRADING_LOCKED: { label: "Travado (Limite Atingido)", cls: "bg-bear/20 text-bear border-bear/50 font-bold" },
  REVIEW_REQUIRED: { label: "Revisão Obrigatória", cls: "bg-purple-500/20 text-purple-300 border-purple-500/50" },
};

function RiskPanelImpl({ meta, mode, currency, spreadNow, lock, guard, day, send }: Props) {
  const s = meta?.settings;
  const m = meta?.modes.find((x) => x.key === mode);
  const [form, setForm] = useState<Form | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [unlocking, setUnlocking] = useState(false);

  useEffect(() => {
    if (!s || !mode || dirty) return;
    setForm({
      daily_loss_limit: String(s.daily_loss_limit),
      daily_gain_target: String(s.daily_gain_target),
      weekly_loss_limit: String(s.weekly_loss_limit ?? (s.daily_loss_limit * 2.5)),
      max_spread_points: String(s.max_spread_points),
      risk: String(s.risk_pct[mode]),
      lot_multiplier: String(s.lot_multiplier),
      aggressive_rr: String(s.aggressive_rr),
      protect_whole_account: Boolean(s.protect_whole_account),
      sync_chart_symbol: s.sync_chart_symbol,
      account_profile: String(s.account_profile || "SMALL_ACCOUNT_PROTECTION"),
      adaptive_mode: String(s.adaptive_mode || "OBSERVATION"),
    });
  }, [s, mode, dirty]);

  if (!form || !m || !mode) {
    return <div className="panel p-3 text-xs text-slate-500">Carregando governança de risco…</div>;
  }

  const upd = (k: keyof Form, v: string | boolean) => {
    setForm({ ...form, [k]: v });
    setDirty(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      const ack = await send("update_settings", {
        settings: {
          daily_loss_limit: Number(form.daily_loss_limit),
          daily_gain_target: Number(form.daily_gain_target),
          weekly_loss_limit: Number(form.weekly_loss_limit),
          max_spread_points: Number(form.max_spread_points),
          risk_pct: { [mode]: Number(form.risk) },
          lot_multiplier: Number(form.lot_multiplier),
          aggressive_rr: Number(form.aggressive_rr),
          protect_whole_account: form.protect_whole_account,
          sync_chart_symbol: form.sync_chart_symbol,
          account_profile: form.account_profile,
          adaptive_mode: form.adaptive_mode,
        },
      });
      if (ack.ok) setDirty(false);
    } finally {
      setSaving(false);
    }
  };

  const unlockLock = async () => {
    setUnlocking(true);
    try {
      await send("unlock_risk_lock", {
        reason: "Desbloqueio manual auditado pelo operador",
        reset_baseline: false,
      });
    } finally {
      setUnlocking(false);
    }
  };

  const lossMissing = !(Number(form.daily_loss_limit) > 0);
  const ddBadge = DD_BADGES[guard?.drawdown_state || "NORMAL"] || DD_BADGES.NORMAL;
  const isMinLotBlocked = guard?.status === "BLOCKED_MIN_LOT";
  const refEquity = day?.reference_equity ?? guard?.reference_equity ?? 0;

  return (
    <div className="panel flex h-full flex-col justify-between p-2.5">
      {/* CABEÇALHO */}
      <div className="mb-1.5 flex flex-wrap items-center justify-between gap-1.5 text-[11px]">
        <div className="flex items-center gap-1.5">
          <ShieldAlert size={14} className="text-warn shrink-0" />
          <span className="font-extrabold uppercase tracking-wider text-accent">
            Guardião de Risco Quantitativo
          </span>
          <span className={cx("num rounded border px-1.5 py-0.2 text-[9.5px] font-bold", ddBadge.cls)}>
            {ddBadge.label}
          </span>
        </div>
        <button
          onClick={() => void save()}
          disabled={!dirty || saving}
          className={cx(
            "flex items-center gap-1 rounded px-2.5 py-0.5 text-[11px] font-bold transition",
            dirty
              ? "bg-bull text-ink-950 shadow hover:bg-bull/90"
              : "bg-ink-800 text-slate-400 opacity-60",
          )}
        >
          <Save size={11} /> {dirty ? "Salvar Limites" : "Salvo"}
        </button>
      </div>

      {/* METRICAS DE CAPITAL & GUARDA DE PEQUENA CONTA */}
      <div className="mb-2 grid grid-cols-2 gap-1.5 rounded border border-ink-700 bg-ink-900/80 p-2 text-[10px]">
        <div>
          <span className="text-slate-400">Capital de Referência:</span>
          <div className="num font-extrabold text-white">
            {refEquity.toFixed(2)} {currency}
          </div>
        </div>
        <div>
          <span className="text-slate-400">Risco Efetivo / Teto:</span>
          <div className="num font-bold text-accent">
            {guard?.effective_risk_pct?.toFixed(2) ?? Number(form.risk).toFixed(2)}% (máx {guard?.max_planned_risk_pct?.toFixed(2) ?? 0.50}%)
          </div>
        </div>
        <div>
          <span className="text-slate-400">Risco Agregado da Carteira:</span>
          <div className="num font-semibold text-slate-200">
            {guard?.open_portfolio_risk_money?.toFixed(2) ?? "0.00"} {currency} ({guard?.open_portfolio_risk_pct?.toFixed(2) ?? "0.00"}% / máx {guard?.max_aggregate_risk_pct?.toFixed(2) ?? "0.75"}%)
          </div>
        </div>
        <div>
          <span className="text-slate-400">Lote Mínimo ({guard?.volume_min ?? 0.01}):</span>
          <div className={cx("num font-semibold", isMinLotBlocked ? "text-bear font-bold" : "text-slate-200")}>
            {guard?.min_lot_risk_money?.toFixed(2) ?? "—"} {currency} ({guard?.min_lot_risk_pct?.toFixed(2) ?? "—"}%)
          </div>
        </div>
      </div>

      {isMinLotBlocked && (
        <div className="mb-1.5 flex items-center gap-1.5 rounded border border-bear/50 bg-bear/10 px-2 py-1 text-[10px] text-bear">
          <AlertTriangle size={12} className="shrink-0" />
          <span><b>Lote Mínimo Incompatível:</b> O lote {guard?.volume_min} excede o orçamento de risco seguro para o capital atual ({refEquity.toFixed(2)} {currency}).</span>
        </div>
      )}

      {/* CAMPOS DE CONFIGURAÇÃO */}
      <div className="grid grid-cols-2 gap-x-2.5 gap-y-1.5 text-[10.5px]">
        <label className="flex flex-col gap-0.5">
          <span className={cx("truncate font-medium text-slate-300", lossMissing && "text-bear")}>
            🛑 Stop Diário ({currency || "USD"})
          </span>
          <input
            type="number"
            min={0}
            step="any"
            placeholder="Ex: 50"
            className={cx("field num font-bold", lossMissing && "border-bear")}
            value={form.daily_loss_limit}
            onChange={(e) => upd("daily_loss_limit", e.target.value)}
          />
        </label>

        <label className="flex flex-col gap-0.5">
          <span className="truncate font-medium text-slate-300">
            🎯 Meta do Dia ({currency || "USD"})
          </span>
          <input
            type="number"
            min={0}
            step="any"
            placeholder="0 = livre"
            className="field num font-bold"
            value={form.daily_gain_target}
            onChange={(e) => upd("daily_gain_target", e.target.value)}
          />
        </label>

        <label className="flex flex-col gap-0.5">
          <span className="truncate text-slate-400">
            Semanal Máx. ({currency || "USD"})
          </span>
          <input
            type="number"
            min={0}
            step="any"
            className="field num"
            value={form.weekly_loss_limit}
            onChange={(e) => upd("weekly_loss_limit", e.target.value)}
          />
        </label>

        <label className="flex flex-col gap-0.5">
          <span className="truncate text-slate-400">
            Spread máx. · <b className="num text-slate-200">{spreadNow ?? "—"} pts</b>
          </span>
          <input
            type="number"
            min={1}
            step={1}
            className="field num"
            value={form.max_spread_points}
            onChange={(e) => upd("max_spread_points", e.target.value)}
          />
        </label>
      </div>

      {/* PERFIL E ESCOPO */}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 border-t border-ink-800 pt-1.5 text-[10px]">
        <label className="flex items-center gap-1.5 text-slate-300 cursor-pointer">
          <input
            type="checkbox"
            checked={form.protect_whole_account}
            onChange={(e) => upd("protect_whole_account", e.target.checked)}
          />
          <span>Governar Conta Inteira (Stop Global)</span>
        </label>
        <span className="num font-bold text-slate-400">
          Escopo: <b className="text-white">{form.protect_whole_account ? "Conta Inteira" : "Trader IA (Magic)"}</b>
        </span>
      </div>

      {/* STATUS DA TRAVA / MENSAGENS */}
      <div className="mt-1.5 flex items-center justify-between border-t border-ink-700/80 pt-1 text-[10.5px]">
        {lock?.active ? (
          <div className="flex w-full items-center justify-between gap-1">
            <span className="flex items-center gap-1 font-semibold text-bear">
              <Lock size={12} className="shrink-0" /> {lock.reason}
            </span>
            <button
              onClick={() => void unlockLock()}
              disabled={unlocking}
              className="flex items-center gap-1 rounded bg-amber-500/20 border border-amber-500/40 px-2 py-0.5 text-[10px] font-bold text-amber-300 hover:bg-amber-500/30"
              title="Desbloqueio manual auditado de emergência"
            >
              <Unlock size={10} /> Desbloquear
            </button>
          </div>
        ) : lossMissing ? (
          <span className="font-semibold text-bear">
            ⚠️ Defina o valor em &ldquo;Stop Diário&rdquo; e clique em Salvar.
          </span>
        ) : dirty ? (
          <span className="font-semibold text-amber-300">
            ⚠️ Clique em &ldquo;Salvar Limites&rdquo; acima para aplicar.
          </span>
        ) : (
          <span className="flex items-center gap-1 text-bull">
            <CheckCircle2 size={11} /> Governança de risco ativa e calibrada.
          </span>
        )}
      </div>
    </div>
  );
}

export const RiskPanel = memo(RiskPanelImpl);
