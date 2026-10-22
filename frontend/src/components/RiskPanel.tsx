import { memo, useEffect, useState } from "react";
import { Save, ShieldAlert, Lock, CheckCircle2 } from "lucide-react";
import type { MetaMsg, ModeKey } from "../types";
import type { TerminalApi } from "../hooks/useTerminal";
import { cx } from "../lib/format";

interface Props {
  meta: MetaMsg | null;
  mode: ModeKey | undefined;
  currency: string;
  spreadNow: number | null | undefined;
  lock: { active: boolean; reason: string | null } | undefined;
  send: TerminalApi["send"];
}

interface Form {
  daily_loss_limit: string;
  daily_gain_target: string;
  max_spread_points: string;
  risk: string;
  lot_multiplier: string;
  aggressive_rr: string;
  sync_chart_symbol: boolean;
}

function RiskPanelImpl({ meta, mode, currency, spreadNow, lock, send }: Props) {
  const s = meta?.settings;
  const m = meta?.modes.find((x) => x.key === mode);
  const [form, setForm] = useState<Form | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!s || !mode || dirty) return;
    setForm({
      daily_loss_limit: String(s.daily_loss_limit),
      daily_gain_target: String(s.daily_gain_target),
      max_spread_points: String(s.max_spread_points),
      risk: String(s.risk_pct[mode]),
      lot_multiplier: String(s.lot_multiplier),
      aggressive_rr: String(s.aggressive_rr),
      sync_chart_symbol: s.sync_chart_symbol,
    });
  }, [s, mode, dirty]);

  if (!form || !m || !mode) {
    return <div className="panel p-3 text-xs text-slate-500">Carregando limites de segurança…</div>;
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
          max_spread_points: Number(form.max_spread_points),
          risk_pct: { [mode]: Number(form.risk) },
          lot_multiplier: Number(form.lot_multiplier),
          aggressive_rr: Number(form.aggressive_rr),
          sync_chart_symbol: form.sync_chart_symbol,
        },
      });
      if (ack.ok) setDirty(false);
    } finally {
      setSaving(false);
    }
  };

  const lossMissing = !(Number(form.daily_loss_limit) > 0);

  return (
    <div className="panel flex h-full flex-col justify-between p-2.5">
      <div className="mb-1.5 flex items-center justify-between gap-2 text-[11px]">
        <span className="flex items-center gap-1.5 font-bold uppercase tracking-wider text-accent">
          <ShieldAlert size={13} className="text-warn" />
          Limites de Proteção Diária
        </span>
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

      <div className="grid grid-cols-2 gap-x-2.5 gap-y-1.5 text-[10.5px]">
        <label className="flex flex-col gap-0.5">
          <span className={cx("truncate font-medium text-slate-300", lossMissing && "text-bear")}>
            🛑 Parar se perder ({currency || "USD"})
          </span>
          <input
            type="number"
            min={0}
            step="any"
            placeholder="Ex: 500"
            className={cx("field num font-bold", lossMissing && "border-bear")}
            value={form.daily_loss_limit}
            onChange={(e) => upd("daily_loss_limit", e.target.value)}
          />
        </label>

        <label className="flex flex-col gap-0.5">
          <span className="truncate font-medium text-slate-300">
            🎯 Meta do dia ({currency || "USD"})
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

        <label className="flex flex-col justify-between gap-0.5">
          <span className="truncate text-slate-400">
            Risco por Entrada: <b className="num text-white">{Number(form.risk).toFixed(2)}%</b>
          </span>
          <input
            type="range"
            min={m.risk_min}
            max={m.risk_max}
            step={0.05}
            value={form.risk}
            onChange={(e) => upd("risk", e.target.value)}
            className="my-1 accent-accent"
          />
        </label>
      </div>

      <div className="mt-1.5 flex items-center justify-between border-t border-ink-700/80 pt-1 text-[10.5px]">
        {lock?.active ? (
          <span className="flex items-center gap-1 font-semibold text-bear">
            <Lock size={11} /> {lock.reason}
          </span>
        ) : lossMissing ? (
          <span className="font-semibold text-bear">
            ⚠️ Defina o valor em &ldquo;Parar se perder&rdquo; e clique em Salvar.
          </span>
        ) : dirty ? (
          <span className="font-semibold text-amber-300">
            ⚠️ Clique em &ldquo;Salvar Limites&rdquo; acima para aplicar.
          </span>
        ) : (
          <span className="flex items-center gap-1 text-bull">
            <CheckCircle2 size={11} /> Proteções ativas e salvas.
          </span>
        )}
      </div>
    </div>
  );
}

export const RiskPanel = memo(RiskPanelImpl);
