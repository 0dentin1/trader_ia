import { useCallback, useEffect, useRef, useState } from "react";
import type {
  AckMsg,
  HistoryMsg,
  LogEntry,
  MetaMsg,
  SeriesMsg,
  ServerMsg,
  SnapshotMsg,
} from "../types";

const WS_URL: string =
  import.meta.env.VITE_BACKEND_WS || `ws://${window.location.hostname || "localhost"}:8000/ws`;

export type WsStatus = "connecting" | "open" | "closed";

export interface Toast {
  id: number;
  ok: boolean;
  message: string;
}

export interface TerminalApi {
  wsStatus: WsStatus;
  wsUrl: string;
  meta: MetaMsg | null;
  snap: SnapshotMsg | null;
  series: SeriesMsg | null;
  history: HistoryMsg | null;
  logs: LogEntry[];
  toasts: Toast[];
  send: (action: string, payload?: Record<string, unknown>) => Promise<AckMsg>;
}

export function useTerminal(): TerminalApi {
  const [wsStatus, setWsStatus] = useState<WsStatus>("connecting");
  const [meta, setMeta] = useState<MetaMsg | null>(null);
  const [snap, setSnap] = useState<SnapshotMsg | null>(null);
  const [series, setSeries] = useState<SeriesMsg | null>(null);
  const [history, setHistory] = useState<HistoryMsg | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const wsRef = useRef<WebSocket | null>(null);
  const reqId = useRef(1);
  const pending = useRef(new Map<number, (a: AckMsg) => void>());
  const retry = useRef(0);
  const disposed = useRef(false);

  const pushToast = useCallback((ok: boolean, message: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-3), { id, ok, message }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500);
  }, []);

  const handle = useCallback(
    (msg: ServerMsg) => {
      switch (msg.type) {
        case "snapshot":
          setSnap(msg);
          break;
        case "meta":
          setMeta(msg);
          break;
        case "series":
          setSeries(msg);
          break;
        case "history":
          setHistory(msg);
          break;
        case "logs":
          if (msg.backlog) setLogs(msg.entries.slice(-400));
          else setLogs((prev) => [...prev, ...msg.entries].slice(-400));
          break;
        case "ack": {
          const cb = msg.id !== null ? pending.current.get(msg.id) : undefined;
          if (cb && msg.id !== null) {
            pending.current.delete(msg.id);
            cb(msg);
          }
          pushToast(msg.ok, msg.message);
          break;
        }
      }
    },
    [pushToast],
  );

  useEffect(() => {
    disposed.current = false;
    let timer: number | undefined;

    const connect = () => {
      if (disposed.current) return;
      setWsStatus("connecting");
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;
      ws.onopen = () => {
        if (disposed.current || wsRef.current !== ws) {
          ws.close();
          return;
        }
        retry.current = 0;
        setWsStatus("open");
      };
      ws.onmessage = (ev) => {
        if (disposed.current || wsRef.current !== ws) return;
        try {
          handle(JSON.parse(ev.data as string) as ServerMsg);
        } catch {
          /* mensagem malformada é ignorada */
        }
      };
      ws.onclose = () => {
        if (wsRef.current !== ws) return;
        wsRef.current = null;
        setWsStatus("closed");
        pending.current.forEach((cb) =>
          cb({ type: "ack", id: null, action: "", ok: false, message: "Conexão com o backend perdida." }),
        );
        pending.current.clear();
        if (!disposed.current) {
          const delay = Math.min(5000, 500 * 2 ** retry.current++);
          timer = window.setTimeout(connect, delay);
        }
      };
      ws.onerror = () => {
        if (ws.readyState === WebSocket.OPEN) ws.close();
      };
    };

    connect();
    return () => {
      disposed.current = true;
      if (timer) window.clearTimeout(timer);
      const cur = wsRef.current;
      wsRef.current = null;
      if (cur && cur.readyState === WebSocket.OPEN) {
        cur.close();
      }
    };
  }, [handle]);

  const send = useCallback(
    (action: string, payload: Record<string, unknown> = {}) =>
      new Promise<AckMsg>((resolve) => {
        const ws = wsRef.current;
        if (!ws || ws.readyState !== WebSocket.OPEN) {
          const a: AckMsg = { type: "ack", id: null, action, ok: false, message: "Backend desconectado." };
          pushToast(false, a.message);
          resolve(a);
          return;
        }
        const id = reqId.current++;
        pending.current.set(id, resolve);
        ws.send(JSON.stringify({ id, action, ...payload }));
      }),
    [pushToast],
  );

  return { wsStatus, wsUrl: WS_URL, meta, snap, series, history, logs, toasts, send };
}
