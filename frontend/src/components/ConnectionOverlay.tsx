import { AlertTriangle, Loader2, ServerCrash } from "lucide-react";
import type { WsStatus } from "../hooks/useTerminal";
import type { SnapshotMsg } from "../types";

interface Props {
  wsStatus: WsStatus;
  wsUrl: string;
  snap: SnapshotMsg | null;
}

/** Bloqueia a interface enquanto o backend ou o MetaTrader 5 estiverem indisponíveis (erro real exibido). */
export function ConnectionOverlay({ wsStatus, wsUrl, snap }: Props) {
  const backendDown = wsStatus !== "open";
  const mt5Down = !backendDown && (!snap || !snap.conn.mt5);
  if (!backendDown && !mt5Down) return null;

  const err = snap?.conn.error;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/90 backdrop-blur-sm">
      <div className="w-[560px] rounded-lg border border-bear/40 bg-ink-900 p-6 shadow-2xl">
        <div className="flex items-center gap-3">
          {backendDown ? (
            <ServerCrash className="text-bear" size={28} />
          ) : (
            <AlertTriangle className="text-bear" size={28} />
          )}
          <div>
            <div className="text-lg font-bold text-white">
              {backendDown ? "Backend indisponível" : "MetaTrader 5 desconectado"}
            </div>
            <div className="text-xs text-slate-400">
              Interface bloqueada até a reconexão. Nenhum dado é exibido sem fonte real.
            </div>
          </div>
        </div>

        <div className="num mt-4 rounded border border-ink-700 bg-ink-950 p-3 text-xs text-slate-300">
          {backendDown ? (
            <>
              <div>
                WebSocket: <span className="text-bear">{wsStatus === "connecting" ? "conectando…" : "fechado"}</span>
              </div>
              <div>URL: {wsUrl}</div>
            </>
          ) : !snap ? (
            <div>Aguardando o primeiro snapshot do motor…</div>
          ) : (
            <>
              <div className="text-slate-500">mt5.last_error()</div>
              <div className="text-bear">
                ({err?.code ?? "?"}) {err?.message || "Sem detalhes"}
              </div>
            </>
          )}
        </div>

        <ul className="mt-4 list-disc space-y-1 pl-5 text-xs text-slate-400">
          {backendDown ? (
            <>
              <li>
                Inicie o backend: <code className="text-slate-200">cd backend && python run.py</code>
              </li>
              <li>A biblioteca MetaTrader5 exige Windows (nativo, VM ou Python Windows sob Wine).</li>
            </>
          ) : (
            <>
              <li>Abra o terminal MetaTrader 5 e faça login na conta.</li>
              <li>Confirme que o Python do backend roda na mesma máquina/usuário do terminal.</li>
              <li>Para executar ordens, ative o botão “Algo Trading” no MT5.</li>
            </>
          )}
        </ul>

        <div className="mt-4 flex items-center gap-2 text-xs text-slate-500">
          <Loader2 size={14} className="animate-spin" /> Tentando reconectar automaticamente…
        </div>
      </div>
    </div>
  );
}
