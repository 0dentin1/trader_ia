"""Orquestrador do Motor V3 (MEGA BRAIN): 1 Cérebro Dedicado por Moeda (SymbolRuntime) com fluxo de ticks
próprio, leitura simultânea M1+M2+M5+M15, escolha automática de Horizonte (1 Vela a 5 min) e WebSocket."""
from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from . import indicators
from .analysis import analyze_multi_horizon
from .brain import Brain, Ctx
from .config import ACTIVE_SYMBOL_FILE, ENGINE_CYCLE_S, MODES, RECONNECT_INTERVAL_S, TF_BARS, TF_SECONDS
from .flow import TickFlow
from .mt5_bridge import MT5Bridge
from .risk import realized_today, summarize_trades
from .settings_store import SettingsStore
from .utils import LogBook, clean

SCAN_BARS_M1 = 320
SCAN_BARS_M2 = 300
SCAN_BARS_M5 = 280
SCAN_BARS_M15 = 250


@dataclass
class SymbolRuntime:
    """Cérebro de Dados Dedicado de uma Moeda (mantém fluxo de ticks e velas M1/M2/M5/M15 próprios)."""
    symbol: str
    flow: TickFlow = field(default_factory=TickFlow)
    info: dict | None = None
    tick: dict | None = None
    last_tick_msc: int = 0
    dfs: dict[str, pd.DataFrame | None] = field(
        default_factory=lambda: {"M1": None, "M2": None, "M5": None, "M15": None}
    )
    t_rates: dict[str, float] = field(
        default_factory=lambda: {"M1": 0.0, "M2": 0.0, "M5": 0.0, "M15": 0.0}
    )
    t_info: float = 0.0
    analysis: dict = field(default_factory=dict)


class Engine:
    def __init__(self) -> None:
        self.store = SettingsStore()
        self.logs = LogBook()
        self.bridge = MT5Bridge()
        self.brain = Brain(self.bridge, self.store, self.logs)
        self.loop: asyncio.AbstractEventLoop | None = None
        self._cmds: "queue.Queue[tuple[dict, asyncio.Future]]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = False

        # Payloads públicos (strings JSON prontas) + versões
        self.snapshot_json: str | None = None
        self.snapshot_ver = 0
        self.series_json: str | None = None
        self.series_ver = 0
        self.history_json: str | None = None
        self.history_ver = 0
        self.meta_json: str | None = None
        self.meta_ver = 0

        # Estado interno
        self.symbol: str | None = None
        self.sym: dict | None = None
        self.symbols: list[dict] = []
        self.account: dict = {}
        self.terminal: dict = {}
        self.tick: dict | None = None
        self.df: pd.DataFrame | None = None
        self.analysis: dict = {}
        self.positions: list[dict] = []       # todas as posições abertas na conta
        self.deals: list[dict] = []
        self.all_deals: list[dict] = []
        self._deals_map: dict[int, dict] = {}
        self._deals_login: int | None = None
        self.trade_summary: dict = {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "net_total": 0.0,
            "net_today": 0.0,
            "avg_duration_s": 0,
        }
        self.day = {
            "realized": 0.0,
            "floating": 0.0,
            "total": 0.0,
            "all_time": 0.0,
            "net_closed": 0.0,
            "trades_total": 0,
            "trades_wins": 0,
        }
        self.server_day: int | None = None
        self.server_offset_s: int = 0
        self._series_key: tuple | None = None
        self._series_id = ""
        self._series_seq = 0
        self._last_series_time = 0
        self._history_sig = ""

        # Multi-Cérebros: 1 SymbolRuntime permanente por moeda
        self.runtimes: dict[str, SymbolRuntime] = {}
        self.radar_map: dict[str, dict] = {}
        self.radar: list[dict] = []
        self._scan_idx = 0
        self._t = {
            k: 0.0
            for k in ("connect", "account", "symbols", "hist", "sync", "scan", "auto_switch")
        }

    # ------------------------------------------------------------------ ciclo de vida
    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self._running = True
        self._publish_meta()
        self._thread = threading.Thread(target=self._run, name="mt5-engine", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)

    def submit(self, cmd: dict) -> asyncio.Future:
        assert self.loop is not None
        fut = self.loop.create_future()
        self._cmds.put((cmd, fut))
        return fut

    def _run(self) -> None:
        self.logs.add("🧠 Mega Brain V3 iniciado. Conectando ao MetaTrader 5...", "info")
        while self._running:
            t0 = time.perf_counter()
            try:
                self._process_commands()
                self._cycle()
            except Exception as exc:  # noqa: BLE001
                tb = traceback.format_exc()
                print(tb, flush=True)
                self.logs.throttled("engine_exc", 10, f"Erro no ciclo do motor: {exc!r}", "error")
            time.sleep(max(0.005, ENGINE_CYCLE_S - (time.perf_counter() - t0)))
        self.bridge.shutdown()

    # ------------------------------------------------------------------ comandos
    def _resolve(self, fut: asyncio.Future, res: tuple[bool, str]) -> None:
        if not fut.done():
            fut.set_result(res)

    def _process_commands(self) -> None:
        while True:
            try:
                cmd, fut = self._cmds.get_nowait()
            except queue.Empty:
                return
            try:
                res = self._handle(cmd)
            except Exception as exc:  # noqa: BLE001
                res = (False, f"Erro interno: {exc!r}")
            if self.loop:
                self.loop.call_soon_threadsafe(self._resolve, fut, res)

    def _handle(self, cmd: dict) -> tuple[bool, str]:
        action = cmd.get("action")
        if action == "set_symbol":
            name = str(cmd.get("symbol") or "").strip()
            if not name:
                return False, "Símbolo vazio."
            if not self.bridge.connected:
                return False, "MT5 desconectado."
            if cmd.get("manual_lock"):
                self.store.set("auto_select_symbol", False)
            if name == self.symbol:
                self._publish_meta()
                return True, f"{name} já está no gráfico."
            return self._switch_symbol(name, "selecionado pelo operador")
        if action == "set_auto_symbol":
            enabled = bool(cmd.get("enabled"))
            self.store.set("auto_select_symbol", enabled)
            self._publish_meta()
            msg = (
                "🧠 Mega Brain Multi-Moedas ATIVO — todos os cérebros analisando e operando em paralelo."
                if enabled
                else f"Modo Foco Único — gráfico travado em {self.symbol}."
            )
            self.logs.add(msg, "info")
            return True, msg
        if action == "set_mode":
            key = str(cmd.get("mode") or "").upper()
            if key not in MODES:
                return False, "Filtro inválido."
            old = self.store.get("mode")
            self.store.set("mode", key)
            self.logs.add(
                f"Nível de Rigor do Mega Brain alterado: {MODES[old].label} → {MODES[key].label} "
                f"(Certeza Sniper ≥ {MODES[key].min_score:.0f}%)",
                "info",
                key,
            )
            self._publish_meta()
            return True, f"{MODES[key].label} ativo."
        if action == "set_ai":
            if bool(cmd.get("enabled")):
                return self.brain.try_enable(
                    self.bridge.connected,
                    self.account,
                    self.terminal,
                    self.sym,
                    self.store.snapshot(),
                    self.server_day,
                    current_day_total=float(self.day.get("total") or 0.0),
                )
            self.brain.disable("Desligada pelo operador.")
            return True, "Mega Brain desligado."
        if action == "panic_close":
            ticket_target = cmd.get("ticket")
            if not self.bridge.connected:
                return False, "MT5 desconectado — impossível zerar."
            positions = self.bridge.positions()
            if positions is None:
                return False, f"Falha ao ler posições: {self.bridge.last_error[1]}"
            if ticket_target:
                positions = [p for p in positions if int(p["ticket"]) == int(ticket_target)]
            else:
                self.brain.disable("FECHAMENTO IMEDIATO acionado pelo operador.")
            if not positions:
                return True, "Nenhuma posição aberta."
            ok_total = fail_total = 0
            for p in positions:
                p_sym = self.bridge.symbol_info(p["symbol"]) or self.sym
                ok, fail = self.brain.close_all(p["symbol"], [p], p_sym, self.store.snapshot(), "ENCERRAR AGORA")
                ok_total += ok
                fail_total += fail
            self.positions = self.bridge.positions() or []
            self._t["hist"] = 0.0
            return fail_total == 0, f"{ok_total} operação(ões) encerrada(s)" + (
                f", {fail_total} falha(s)" if fail_total else ""
            )
        if action == "update_settings":
            patch = cmd.get("settings") or {}
            ok, msg = self.store.update_user(patch, current_day_total=float(self.day.get("total") or 0.0))
            if ok:
                if self.brain.state == "RISK_LOCK" and self.store.get("risk_lock") is None:
                    self.brain.state = "STUDYING_MARKET" if self.brain.enabled else "OFF"
                    self.brain.detail = "Limites atualizados — pronto para operar."
                self.logs.add(f"Limites de proteção atualizados: {json.dumps(patch, ensure_ascii=False)}", "info")
                self._publish_meta()
            return ok, msg
        if action == "refresh_symbols":
            if not self.bridge.connected:
                return False, "MT5 desconectado."
            self.symbols = self.bridge.visible_symbols()
            self._publish_meta()
            return True, f"{len(self.symbols)} símbolos visíveis no Market Watch."
        return False, f"Ação desconhecida: {action}"

    # ------------------------------------------------------------------ gerenciamento de cérebros por moeda
    def _get_runtime(self, sym_name: str) -> SymbolRuntime:
        rt = self.runtimes.get(sym_name)
        if rt is None:
            rt = SymbolRuntime(symbol=sym_name)
            self.runtimes[sym_name] = rt
        return rt

    def _update_symbol_runtime(
        self, sym_name: str, mode, settings: dict, now: float, is_active: bool = False, has_open_pos: bool = False
    ) -> SymbolRuntime | None:
        """Atualiza ticks, velas multi-timeframe (M1/M2/M5/M15) e análise do Cérebro de uma moeda."""
        rt = self._get_runtime(sym_name)
        if rt.info is None or (now - rt.t_info >= (5.0 if is_active else 20.0)):
            info = self.bridge.symbol_info(sym_name)
            if info:
                rt.info = info
                rt.t_info = now
        if rt.info is None:
            return None

        tick = self.bridge.tick(sym_name)
        if tick is None:
            return None

        new_tick = int(tick.get("time_msc") or 0) != rt.last_tick_msc
        if new_tick:
            from_sec = (rt.flow.last_msc // 1000) if rt.flow.last_msc else int(tick["time"]) - 60
            rt.flow.ingest(self.bridge.ticks_since(sym_name, from_sec, 2500 if is_active else 800))
            rt.last_tick_msc = int(tick.get("time_msc") or 0)
        rt.tick = tick

        # Intervalos de atualização de velas por timeframe (mais rápido no ativo ativo ou com posição aberta)
        fast = is_active or has_open_pos
        m1_int = 0.8 if fast else 2.5
        m2_int = 2.0 if fast else 5.0
        m5_int = 4.0 if fast else 10.0
        m15_int = 10.0 if fast else 25.0

        if rt.dfs["M1"] is None or (new_tick and is_active) or (now - rt.t_rates["M1"] >= m1_int):
            raw_m1 = self.bridge.rates(sym_name, "M1", TF_BARS["M1"] if is_active else SCAN_BARS_M1)
            rt.t_rates["M1"] = now
            if raw_m1 is not None and len(raw_m1) >= 120:
                rt.dfs["M1"] = indicators.compute(raw_m1)

        if rt.dfs["M2"] is None or (now - rt.t_rates["M2"] >= m2_int):
            raw_m2 = self.bridge.rates(sym_name, "M2", SCAN_BARS_M2)
            rt.t_rates["M2"] = now
            if raw_m2 is not None and len(raw_m2) >= 120:
                rt.dfs["M2"] = indicators.compute(raw_m2)

        if rt.dfs["M5"] is None or (now - rt.t_rates["M5"] >= m5_int):
            raw_m5 = self.bridge.rates(sym_name, "M5", SCAN_BARS_M5)
            rt.t_rates["M5"] = now
            if raw_m5 is not None and len(raw_m5) >= 120:
                rt.dfs["M5"] = indicators.compute(raw_m5)

        if rt.dfs["M15"] is None or (now - rt.t_rates["M15"] >= m15_int):
            raw_m15 = self.bridge.rates(sym_name, "M15", SCAN_BARS_M15)
            rt.t_rates["M15"] = now
            if raw_m15 is not None and len(raw_m15) >= 120:
                rt.dfs["M15"] = indicators.compute(raw_m15)

        flow_m = rt.flow.metrics(int(tick["time_msc"]))
        rt.analysis = analyze_multi_horizon(
            rt.dfs, tick, rt.info, flow_m, mode, settings, server_now=int(tick["time"])
        )
        return rt

    def _switch_symbol(self, name: str, origin: str) -> tuple[bool, str]:
        info = self.bridge.select_symbol(name)
        if info is None:
            return False, f"Não foi possível selecionar {name}: {self.bridge.last_error[1]}"
        old = self.symbol
        self.symbol = name
        self.sym = info
        rt = self._get_runtime(name)
        rt.info = info
        self._series_key = None
        self._last_series_time = 0
        self.store.set("symbol", name)
        self.logs.add(f"Gráfico sincronizado ({origin}): {old or '—'} → {name}.", "info")
        self._publish_meta()
        return True, f"Ativo {name} em foco."

    def _choose_initial_symbol(self) -> None:
        names = [s["name"] for s in self.symbols]
        saved = self.store.get("symbol")
        if saved and (saved in names or self.bridge.symbol_info(saved)):
            self._switch_symbol(saved, "último ativo salvo")
        elif names:
            self._switch_symbol(names[0], "primeiro ativo do Market Watch")

    def _sync_chart_symbol(self) -> None:
        base = self.terminal.get("commondata_path")
        if not base:
            return
        path = Path(base) / "Files" / ACTIVE_SYMBOL_FILE
        try:
            if not path.exists() or time.time() - path.stat().st_mtime > 10:
                return
            raw = path.read_text(encoding="latin-1", errors="ignore").strip()
        except OSError:
            return
        name = raw.split("|")[0].strip()
        if not name or name == self.symbol:
            return
        self._switch_symbol(name, "gráfico ativo do MT5")

    # ------------------------------------------------------------------ scanner multi-cérebros
    def _scan_step(self, mode, settings: dict, server_now: int, open_syms: set[str]) -> None:
        """Atualiza os Cérebros Dedicados de todas as moedas em paralelo e reconstrói o Radar."""
        if not self.symbols:
            return
        now = time.monotonic()
        eff_min = self.brain.required_score(mode.min_score)

        # 1. Atualiza no Radar a moeda atualmente aberta no gráfico
        if self.symbol and self.analysis.get("ready"):
            tf_sec = TF_SECONDS.get(self.analysis.get("timeframe", "M1"), 60)
            self._update_radar_entry(self.symbol, self.analysis, eff_min, server_now, tf_sec)

        # 2. Sempre mantém atualizadas moedas que possuem operação aberta em segundo plano
        for osym in open_syms:
            if osym != self.symbol:
                rt_o = self._update_symbol_runtime(osym, mode, settings, now, is_active=False, has_open_pos=True)
                if rt_o and rt_o.analysis.get("ready"):
                    tf_s = TF_SECONDS.get(rt_o.analysis.get("timeframe", "M1"), 60)
                    self._update_radar_entry(osym, rt_o.analysis, eff_min, server_now, tf_s)

        # 3. Escaneia lote de 2 outras moedas a cada 0.25s (varre todo o Market Watch em ~1s)
        if now - self._t["scan"] < 0.25:
            return
        self._t["scan"] = now

        names = [s["name"] for s in self.symbols if s["name"] != self.symbol and s["name"] not in open_syms]
        if not names:
            self._rebuild_radar_list()
            return

        batch_size = min(2, len(names))
        for _ in range(batch_size):
            sym_name = names[self._scan_idx % len(names)]
            self._scan_idx += 1
            info = self.bridge.symbol_info(sym_name)
            t = self.bridge.tick(sym_name)
            if not info or not t:
                continue
            if server_now and abs(server_now - int(t.get("time") or 0)) > 300:
                self.radar_map.pop(sym_name, None)
                self.runtimes.pop(sym_name, None)
                continue
            if info.get("trade_mode") in (0, 3):
                self.radar_map.pop(sym_name, None)
                self.runtimes.pop(sym_name, None)
                continue
            point = float(info.get("point") or 1e-9)
            sp_pts = int(round((float(t["ask"]) - float(t["bid"])) / point))
            if sp_pts > int(settings.get("max_spread_points", 25)) * 2:
                self.radar_map.pop(sym_name, None)
                continue

            rt = self._update_symbol_runtime(sym_name, mode, settings, now, is_active=False, has_open_pos=False)
            if rt and rt.analysis.get("ready"):
                tf_s = TF_SECONDS.get(rt.analysis.get("timeframe", "M1"), 60)
                self._update_radar_entry(sym_name, rt.analysis, eff_min, server_now, tf_s)

        self._rebuild_radar_list()

    def _update_radar_entry(self, sym_name: str, a: dict, eff_min: float, server_now: int, tf_sec: int) -> None:
        score = float(a.get("score") or 0.0)
        direction = a.get("direction")
        cdl = a.get("candle") or {}
        hz = a.get("horizon") or {}
        prob_next = cdl.get("prob_up", 50.0) if direction == "BUY" else cdl.get("prob_down", 50.0)
        mem_ok, penalty, mem_reason = self.brain.evaluate_symbol_memory(
            sym_name, direction, score, eff_min, server_now, tf_sec
        )
        study_block = a.get("study_block")
        blocked = (not mem_ok) or bool(study_block)
        has_signal = bool(a.get("signal")) and score >= eff_min and mem_ok

        rank_score = score * 0.65 + prob_next * 0.35 - penalty
        if prob_next < 60.0:
            rank_score -= 10.0
        if blocked:
            rank_score -= 22.0
        if has_signal:
            rank_score += 18.0

        self.radar_map[sym_name] = {
            "symbol": sym_name,
            "direction": direction,
            "score": round(score, 1),
            "min_score": round(eff_min, 1),
            "next_prob": round(prob_next, 1),
            "rank_score": round(max(0.0, min(100.0, rank_score)), 1),
            "regime": a.get("regime", {}).get("label", "—"),
            "regime_code": a.get("regime", {}).get("code", "UNKNOWN"),
            "spread_points": a.get("spread_points", 0),
            "timeframe": a.get("timeframe", "M1"),
            "horizon_label": hz.get("short_label", "⚡ 1 Vela"),
            "duration_s": hz.get("duration_s", 60),
            "strategy": hz.get("strategy") or cdl.get("best_strategy") or "Confluência Institucional",
            "signal": a.get("signal") if has_signal else None,
            "blocked": blocked,
            "reason": mem_reason or study_block or cdl.get("prev_desc", ""),
        }

    def _rebuild_radar_list(self) -> None:
        items = list(self.radar_map.values())
        items.sort(
            key=lambda x: (1 if x.get("signal") else 0, x.get("rank_score", 0.0), x.get("score", 0.0)),
            reverse=True,
        )
        self.radar = items[:10]

    def _maybe_auto_switch_symbol(self, settings: dict) -> bool:
        """Sincroniza suavemente o gráfico com a melhor moeda sem ficar pulando freneticamente."""
        if not settings.get("auto_select_symbol", True):
            return False
        if not self.radar:
            return False

        # Se a moeda atual tem operação aberta, mantém o gráfico nela (a menos que outra acabe de disparar)
        if any(p["symbol"] == self.symbol for p in self.positions):
            return False

        now = time.monotonic()
        best = self.radar[0]
        best_sym = best["symbol"]
        if best_sym == self.symbol or best.get("blocked"):
            return False

        cur_entry = self.radar_map.get(self.symbol or "")
        cur_has_sig = bool(cur_entry and cur_entry.get("signal"))
        cur_rank = float(cur_entry.get("rank_score", 0.0)) if cur_entry else 0.0

        # Só troca de gráfico no máximo a cada 8s (para sinal confirmado) ou 15s (para acompanhar #1)
        if best.get("signal") and not cur_has_sig and (now - self._t["auto_switch"] >= 8.0):
            self._t["auto_switch"] = now
            ok, _ = self._switch_symbol(
                best_sym,
                f"Cérebro {best_sym}: SINAL SNIPER {best['signal']} ({best['score']:.0f}% · {best.get('horizon_label', '1 Vela')})",
            )
            return ok

        if now - self._t["auto_switch"] >= 15.0 and not cur_has_sig:
            if float(best.get("rank_score", 0.0)) >= cur_rank + 6.0:
                self._t["auto_switch"] = now
                ok, _ = self._switch_symbol(
                    best_sym,
                    f"Cérebro #1 do Radar ({best['score']:.0f}% · {best.get('horizon_label', '1 Vela')})",
                )
                return ok
        return False

    # ------------------------------------------------------------------ ciclo de mercado
    def _cycle(self) -> None:
        now = time.monotonic()
        if not self.bridge.connected:
            if now - self._t["connect"] >= RECONNECT_INTERVAL_S:
                self._t["connect"] = now
                if self.bridge.connect():
                    self._on_connected()
                else:
                    code, msg = self.bridge.last_error
                    self.logs.throttled("mt5_down", 30, f"MetaTrader 5 indisponível: [{code}] {msg}", "error")
            if not self.bridge.connected:
                self._publish_disconnected()
                return
        elif not self.bridge.is_alive():
            code, msg = self.bridge.last_error
            self.logs.add(f"Conexão com o MT5 perdida: [{code}] {msg}", "error")
            self._publish_disconnected()
            return

        if now - self._t["account"] >= 0.5 or not self.account:
            acc = self.bridge.account()
            if acc:
                self.account = acc
            self.terminal = self.bridge.terminal()
            self._t["account"] = now

        if now - self._t["symbols"] >= 15 or not self.symbols:
            syms = self.bridge.visible_symbols()
            self._t["symbols"] = now
            if syms and [s["name"] for s in syms] != [s["name"] for s in self.symbols]:
                self.symbols = syms
                self._publish_meta()

        if self.symbol is None:
            self._choose_initial_symbol()
            if self.symbol is None:
                self._publish_disconnected("Nenhum símbolo visível no Market Watch do MT5.")
                return

        # 1. Lê TODAS as posições abertas na conta (todas as moedas)
        all_pos = self.bridge.positions()
        if all_pos is not None:
            if len(all_pos) != len(self.positions):
                self._t["hist"] = 0.0
            # Ordena colocando a moeda do gráfico primeiro, depois por horário mais recente
            all_pos.sort(key=lambda p: (0 if p["symbol"] == self.symbol else 1, -int(p.get("time") or 0)))
            self.positions = all_pos

        settings = self.store.snapshot()
        mode = MODES[settings["mode"]]
        open_syms = {p["symbol"] for p in self.positions}

        # 2. Atualiza o Cérebro da Moeda ativa no gráfico (com M1, M2, M5, M15)
        rt_active = self._update_symbol_runtime(
            self.symbol, mode, settings, now, is_active=True, has_open_pos=(self.symbol in open_syms)
        )
        if rt_active is None or rt_active.info is None or rt_active.tick is None:
            self._publish_disconnected(f"Sem cotação para {self.symbol}: {self.bridge.last_error[1]}")
            return

        self.sym = rt_active.info
        self.tick = tick = rt_active.tick
        self.analysis = rt_active.analysis
        # Exibe no gráfico o timeframe escolhido pelo Cérebro para esta moeda (ou M1 por padrão)
        chart_tf = self.analysis.get("timeframe", "M1") if self.analysis.get("ready") else "M1"
        self.df = rt_active.dfs.get(chart_tf) if rt_active.dfs.get(chart_tf) is not None else rt_active.dfs.get("M1")
        self.server_day = int(tick["time"]) // 86400
        self.server_offset_s = int(round((int(tick["time"]) - time.time()) / 900.0) * 900)
        self._maybe_publish_series(chart_tf)

        # 3. Atualiza histórico real de trades
        login = int(self.account.get("login") or 0)
        if login and self._deals_login and login != self._deals_login:
            self._deals_map.clear()
            self._history_sig = ""
        if login:
            self._deals_login = login

        if now - self._t["hist"] >= 1.5 or not self.history_json:
            self._t["hist"] = now
            all_deals = self.bridge.deals_between(0, int(tick["time"]) + 86400)
            if all_deals:
                for d in all_deals:
                    tkt = int(d.get("ticket") or 0)
                    if tkt:
                        self._deals_map[tkt] = d
            if self._deals_map or all_deals is not None:
                self.all_deals = sorted(
                    self._deals_map.values(),
                    key=lambda d: (int(d.get("time_msc") or 0), int(d.get("time") or 0), int(d.get("ticket") or 0)),
                )
                day_start = self.server_day * 86400
                self.deals = [d for d in self.all_deals if int(d.get("time") or 0) >= day_start]
                self._publish_history(int(tick["time"]))

        realized = (
            max(realized_today(self.deals), float(self.trade_summary.get("net_today") or 0.0))
            if realized_today(self.deals) == 0.0 and self.trade_summary.get("net_today")
            else realized_today(self.deals)
        )
        floating = float(self.account.get("profit") or 0.0)
        net_all = float(self.trade_summary.get("net_total") or 0.0)
        self.day = {
            "realized": realized,
            "floating": floating,
            "total": realized + floating,
            "all_time": net_all + floating,
            "net_closed": net_all,
            "trades_total": int(self.trade_summary.get("total_trades") or 0),
            "trades_wins": int(self.trade_summary.get("wins") or 0),
        }

        # 4. Executa o Scanner Multi-Cérebros em paralelo
        self._scan_step(mode, settings, int(tick["time"]), open_syms)

        # 5. Monta o mapa de todos os Cérebros prontos para o MegaBrain decidir e gerenciar
        symbol_map: dict[str, dict] = {}
        for s_name, rt in self.runtimes.items():
            if rt.info and rt.tick and rt.analysis.get("ready"):
                s_tf = rt.analysis.get("timeframe", "M1")
                symbol_map[s_name] = {
                    "sym": rt.info,
                    "tick": rt.tick,
                    "analysis": rt.analysis,
                    "tf_seconds": TF_SECONDS.get(s_tf, 60),
                }

        # 6. Passo do MegaBrain (pode gerenciar e disparar em qualquer moeda do symbol_map!)
        opened_sym = self.brain.step(
            Ctx(
                symbol=self.symbol,
                sym=self.sym,
                tick=tick,
                analysis=self.analysis,
                positions=[p for p in self.positions if p["symbol"] == self.symbol],
                account=self.account,
                terminal=self.terminal,
                day=self.day,
                server_time=int(tick["time"]),
                server_day=self.server_day,
                mode=mode,
                settings=settings,
                tf_seconds=TF_SECONDS.get(chart_tf, 60),
                all_positions=self.positions,
                symbol_map=symbol_map,
            )
        )

        # Se o MegaBrain acabou de abrir ordem em outra moeda (ou se houver auto-switch), foca nela
        if opened_sym:
            self.positions = self.bridge.positions() or self.positions
            if opened_sym != self.symbol and settings.get("auto_select_symbol", True):
                self._t["auto_switch"] = now
                self._switch_symbol(opened_sym, f"Mega Brain disparou operação em {opened_sym}")
        else:
            self._maybe_auto_switch_symbol(settings)

        self._publish_snapshot(mode, chart_tf)

    def _on_connected(self) -> None:
        self.account = self.bridge.account()
        self.terminal = self.bridge.terminal()
        self.symbols = self.bridge.visible_symbols()
        a = self.account
        self.logs.add(
            f"Conectado ao MetaTrader 5 · {a.get('company')} · conta {a.get('login')} ({a.get('trade_mode')}) "
            f"· {len(self.symbols)} símbolos ativos para os Cérebros da IA",
            "success",
        )
        if self.symbol:
            info = self.bridge.select_symbol(self.symbol)
            if info:
                self.sym = info
            else:
                self.symbol = None
        self._publish_meta()

    # ------------------------------------------------------------------ publicação
    def _dump(self, obj: Any) -> str:
        return json.dumps(clean(obj), ensure_ascii=False, separators=(",", ":"))

    def _publish_meta(self) -> None:
        settings = self.store.snapshot()
        self.meta_json = self._dump({
            "type": "meta",
            "modes": [m.to_public() for m in MODES.values()],
            "settings": settings,
            "symbols": self.symbols,
            "symbol": self.symbol,
        })
        self.meta_ver += 1

    def _maybe_publish_series(self, tf: str) -> None:
        if self.df is None or self.df.empty or self.symbol is None:
            return
        key = (self.symbol, tf, self.server_offset_s)
        last_t = int(self.df["time"].iloc[-1])
        gap = self._last_series_time and last_t - self._last_series_time > TF_SECONDS[tf]
        if key != self._series_key or gap:
            self._series_key = key
            self._series_seq += 1
            self._series_id = f"{self.symbol}|{tf}|{self._series_seq}"
            self.series_json = self._dump({
                "type": "series",
                "series_id": self._series_id,
                "symbol": self.symbol,
                "timeframe": tf,
                "digits": self.sym["digits"] if self.sym else 5,
                "server_offset_s": self.server_offset_s,
                "bars": indicators.chart_rows(self.df),
            })
            self.series_ver += 1
        self._last_series_time = last_t

    def _publish_history(self, server_now: int = 0) -> None:
        max_ticket = max(self._deals_map.keys()) if self._deals_map else 0
        sig = f"{len(self._deals_map)}:{max_ticket}:{self.server_offset_s}"
        if sig == self._history_sig and self.history_json:
            return
        self._history_sig = sig
        magic = int(self.store.get("magic"))
        grouped = summarize_trades(self.all_deals, magic, self.server_offset_s)
        self.trade_summary = grouped["summary"]
        self.brain.sync_from_history(grouped["trades"], server_now)
        deals = sorted(self.all_deals, key=lambda d: d.get("time_msc") or d["time"], reverse=True)
        self.history_json = self._dump({
            "type": "history",
            "deals": deals,
            "trades": grouped["trades"],
            "summary": grouped["summary"],
            "realized": grouped["summary"]["net_total"],
        })
        self.history_ver += 1

    def _enrich_position(self, p: dict, magic: int, server_now: int) -> dict:
        side = p["type"]
        d = 1 if side == "BUY" else -1
        entry = float(p["price_open"])
        cur = float(p["price_current"])
        sl = float(p.get("sl") or 0.0)
        tp = float(p.get("tp") or 0.0)
        vol = float(p["volume"])
        tp_profit = self.bridge.calc_profit(p["symbol"], side, vol, entry, tp) if tp > 0 else None
        sl_profit = self.bridge.calc_profit(p["symbol"], side, vol, entry, sl) if sl > 0 else None
        tp_dist = abs(tp - entry) if tp > 0 else 0.0
        progress_pct = round(100.0 * d * (cur - entry) / tp_dist, 1) if tp_dist > 0 else 0.0
        be_protected = bool(sl > 0 and d * (sl - entry) >= 0)
        elapsed_s = max(0, server_now - int(p["time"])) if server_now else 0

        meta = self.brain.get_trade_meta(int(p["ticket"]))
        max_dur = meta.max_duration_s if meta else 90
        hz_label = meta.horizon_label if meta else "⚡ Tiro de 1 Vela (60s)"
        rem_s = max(0, max_dur - elapsed_s)
        p_sym_info = self.runtimes.get(p["symbol"]).info if p["symbol"] in self.runtimes else None
        p_digits = int(p_sym_info["digits"]) if p_sym_info and "digits" in p_sym_info else 5

        return dict(
            p,
            digits=p_digits,
            is_ai=p["magic"] == magic,
            open_time_local=int(p["time"]) - self.server_offset_s,
            elapsed_s=elapsed_s,
            max_duration_s=max_dur,
            remaining_s=rem_s,
            horizon_label=hz_label,
            net_profit=round(float(p.get("profit") or 0.0) + float(p.get("swap") or 0.0), 2),
            tp_profit=round(tp_profit, 2) if tp_profit is not None else None,
            sl_profit=round(sl_profit, 2) if sl_profit is not None else None,
            progress_pct=progress_pct,
            be_protected=be_protected,
        )

    def _publish_snapshot(self, mode, chart_tf: str = "M1") -> None:
        tick = self.tick or {}
        sym = self.sym or {}
        point = float(sym.get("point") or 1e-9)
        magic = int(self.store.get("magic"))
        server_now = int(tick.get("time") or 0)
        positions = [self._enrich_position(p, magic, server_now) for p in self.positions]
        tf_sec = TF_SECONDS.get(chart_tf, 60)
        bar_time = int(self.analysis.get("bar_time") or (server_now // tf_sec * tf_sec))
        bar_elapsed = max(0, server_now - bar_time) if server_now else 0
        bar_rem = max(0, tf_sec - bar_elapsed) if server_now else 0
        term = {k: v for k, v in self.terminal.items() if k != "commondata_path"}
        self.snapshot_json = self._dump({
            "type": "snapshot",
            "ts": time.time(),
            "conn": {"mt5": True, "error": None, "terminal": term},
            "account": self.account,
            "symbol": self.symbol,
            "symbol_info": {
                k: sym.get(k)
                for k in (
                    "name",
                    "description",
                    "digits",
                    "point",
                    "tick_size",
                    "volume_min",
                    "volume_max",
                    "volume_step",
                    "stops_level",
                    "currency_profit",
                    "trade_mode",
                )
            },
            "tick": {
                "bid": tick.get("bid"),
                "ask": tick.get("ask"),
                "last": tick.get("last"),
                "time": tick.get("time"),
                "time_msc": tick.get("time_msc"),
                "spread_points": int(round((float(tick.get("ask") or 0) - float(tick.get("bid") or 0)) / point))
                if tick
                else None,
            },
            "timing": {
                "tf": chart_tf,
                "tf_seconds": tf_sec,
                "bar_elapsed_s": bar_elapsed,
                "bar_remaining_s": bar_rem,
                "server_offset_s": self.server_offset_s,
            },
            "series_id": self._series_id,
            "bars": indicators.chart_rows(self.df, 2) if self.df is not None else [],
            "analysis": self.analysis,
            "mode": mode.key,
            "ai": self.brain.public(self.server_day, active_brains_count=len(self.radar)),
            "radar": self.radar,
            "positions": positions,
            "day": self.day,
        })
        self.snapshot_ver += 1

    def _publish_disconnected(self, message: str | None = None) -> None:
        code, msg = self.bridge.last_error
        if self.brain.state != "DISCONNECTED" and not self.bridge.connected:
            self.brain.on_disconnect()
        self.snapshot_json = self._dump({
            "type": "snapshot",
            "ts": time.time(),
            "conn": {"mt5": self.bridge.connected, "error": {"code": code, "message": message or msg}, "terminal": {}},
            "account": self.account if self.bridge.connected else {},
            "symbol": self.symbol,
            "symbol_info": {},
            "tick": {},
            "series_id": self._series_id,
            "bars": [],
            "analysis": {},
            "mode": self.store.get("mode"),
            "ai": self.brain.public(self.server_day, active_brains_count=0),
            "radar": [],
            "positions": [],
            "day": self.day,
        })
        self.snapshot_ver += 1
