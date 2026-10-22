export function fmtMoney(v: number | null | undefined, currency = ""): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  const s = v.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return currency ? `${s} ${currency}` : s;
}

export function fmtSigned(v: number | null | undefined, currency = ""): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return sign + fmtMoney(v, currency);
}

export function fmtPrice(v: number | null | undefined, digits = 5): string {
  if (v === null || v === undefined || !Number.isFinite(v) || v === 0) return "—";
  return v.toFixed(digits);
}

export function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v.toFixed(digits);
}

/** Formata um timestamp epoch já ajustado para o fuso local do usuário (ex: "20/10 20:43:45"). */
export function fmtLocalDateTime(epochLocal: number | undefined, includeDate = true): string {
  if (!epochLocal) return "—";
  const d = new Date(epochLocal * 1000);
  const timeStr = d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  if (!includeDate) return timeStr;
  const dateStr = d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
  return `${dateStr} às ${timeStr}`;
}

/** Formata duração em segundos de forma humana (ex: "7m 35s", "42s", "1h 12m"). */
export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) return "—";
  const s = Math.floor(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const remS = s % 60;
  if (m < 60) return `${m}m ${String(remS).padStart(2, "0")}s`;
  const h = Math.floor(m / 60);
  const remM = m % 60;
  return `${h}h ${String(remM).padStart(2, "0")}m`;
}

/** Horário do servidor da corretora (fallback quando necessário). */
export function fmtServerTime(epoch: number | undefined): string {
  if (!epoch) return "—";
  const d = new Date(epoch * 1000);
  return d.toISOString().substring(11, 19);
}

export function pnlColor(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v) || v === 0) return "text-slate-300";
  return v > 0 ? "text-bull" : "text-bear";
}

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}
