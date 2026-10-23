"""Servidor FastAPI: WebSocket bidirecional local (ws://127.0.0.1:8000/ws) com validação de Origin,
validação rigorosa de comandos, token local opcional e endpoints de saúde e relatório quantitativo."""
from __future__ import annotations

import asyncio
import hmac
import json
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .config import (
    ADAPTIVE_MODES,
    ALGO_VERSION,
    ALLOWED_ORIGINS,
    BROADCAST_INTERVAL_S,
    LOCAL_OPERATOR_TOKEN,
    MODES,
)
from .engine import Engine

engine = Engine()

ALLOWED_ACTIONS = {
    "set_symbol",
    "set_auto_symbol",
    "set_mode",
    "set_ai",
    "panic_close",
    "update_settings",
    "unlock_risk_lock",
    "set_adaptive_mode",
    "run_backtest",
    "refresh_symbols",
}

CRITICAL_ACTIONS = {
    "set_ai",
    "panic_close",
    "update_settings",
    "unlock_risk_lock",
    "set_adaptive_mode",
}


def validate_ws_origin(origin: str | None) -> bool:
    """
    Valida o cabeçalho Origin no WebSocket (Parte 8.1).
    Permite conexões sem Origin (clientes de teste/scripts locais) ou de origens locais confiáveis
    (localhost, 127.0.0.1) e origens listadas em ALLOWED_ORIGINS.
    """
    if not origin:
        return True
    origin_clean = origin.strip().rstrip("/")
    if origin_clean in ALLOWED_ORIGINS:
        return True
    try:
        parsed = urlparse(origin_clean)
        if parsed.scheme in ("http", "https") and parsed.hostname in ("127.0.0.1", "localhost"):
            return True
    except Exception:  # noqa: BLE001
        return False
    return False


def validate_operator_token(provided_token: str | None) -> bool:
    """Se LOCAL_OPERATOR_TOKEN estiver configurado no ambiente, exige comparação em tempo constante."""
    if not LOCAL_OPERATOR_TOKEN:
        return True
    if not provided_token or not isinstance(provided_token, str):
        return False
    return hmac.compare_digest(provided_token.strip(), LOCAL_OPERATOR_TOKEN)


def validate_command_payload(cmd: object, ws_token: str | None = None) -> tuple[bool, str]:
    """
    Valida rigorosamente estrutura, tipos e permissões de cada comando recebido via WebSocket (Parte 8.1).
    """
    if not isinstance(cmd, dict):
        return False, "Payload de comando inválido: esperado objeto JSON."
    action = cmd.get("action")
    if not isinstance(action, str) or action not in ALLOWED_ACTIONS:
        return False, f"Ação não autorizada ou desconhecida: {action!r}"

    if action in CRITICAL_ACTIONS:
        tok = cmd.get("token") or ws_token
        if not validate_operator_token(str(tok) if tok is not None else None):
            return False, "Token de operador local inválido ou ausente para comando crítico."

    if action == "set_symbol":
        sym = cmd.get("symbol")
        if not isinstance(sym, str) or not (1 <= len(sym.strip()) <= 32):
            return False, "Parâmetro 'symbol' inválido."
    elif action == "set_auto_symbol":
        if not isinstance(cmd.get("enabled"), bool):
            return False, "Parâmetro 'enabled' deve ser booleano."
    elif action == "set_mode":
        mode = str(cmd.get("mode") or "").upper()
        if mode not in MODES:
            return False, f"Modo inválido: {mode!r}"
    elif action == "set_ai":
        if not isinstance(cmd.get("enabled"), bool):
            return False, "Parâmetro 'enabled' deve ser booleano."
    elif action == "panic_close":
        tkt = cmd.get("ticket")
        if tkt is not None and (not isinstance(tkt, int) or tkt <= 0):
            return False, "Parâmetro 'ticket' deve ser inteiro positivo."
    elif action == "update_settings":
        patch = cmd.get("settings")
        if not isinstance(patch, dict) or len(patch) == 0 or len(patch) > 25:
            return False, "Parâmetro 'settings' deve ser um objeto JSON válido."
    elif action == "unlock_risk_lock":
        reason = cmd.get("reason")
        if reason is not None and (not isinstance(reason, str) or len(reason) > 250):
            return False, "Motivo de desbloqueio inválido."
    elif action == "set_adaptive_mode":
        amode = str(cmd.get("adaptive_mode") or "").upper()
        if amode not in ADAPTIVE_MODES:
            return False, f"Modo adaptativo inválido: {amode!r}"

    return True, "OK"


class Client:
    def __init__(self, ws: WebSocket, token: str | None = None) -> None:
        self.ws = ws
        self.token = token
        self.lock = asyncio.Lock()
        self.alive = True

    async def send_many(self, messages: list[str]) -> None:
        if not self.alive:
            return
        try:
            async with self.lock:
                for m in messages:
                    await asyncio.wait_for(self.ws.send_text(m), timeout=2.0)
        except Exception:  # noqa: BLE001 — cliente lento/desconectado é descartado
            self.alive = False


clients: set[Client] = set()


async def broadcaster() -> None:
    sent = {"meta": 0, "series": 0, "history": 0, "snapshot": 0}
    log_seq = 0
    while True:
        await asyncio.sleep(BROADCAST_INTERVAL_S)
        msgs: list[str] = []
        for key in ("meta", "series", "history", "snapshot"):
            ver = getattr(engine, f"{key}_ver")
            payload = getattr(engine, f"{key}_json")
            if ver != sent[key] and payload:
                sent[key] = ver
                msgs.append(payload)
        new_logs = engine.logs.since(log_seq)
        if new_logs:
            log_seq = new_logs[-1]["id"]
            msgs.append(json.dumps({"type": "logs", "entries": new_logs}, ensure_ascii=False))
        if not msgs or not clients:
            continue
        current = list(clients)
        await asyncio.gather(*(c.send_many(msgs) for c in current))
        for c in current:
            if not c.alive:
                clients.discard(c)


@asynccontextmanager
async def lifespan(_: FastAPI):
    engine.start(asyncio.get_running_loop())
    task = asyncio.create_task(broadcaster())
    try:
        yield
    finally:
        task.cancel()
        engine.stop()


app = FastAPI(title="Trader IA — MT5 Autonomous Quantitative Terminal", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Operator-Token"],
)


@app.get("/api/health")
async def health() -> dict:
    code, msg = engine.bridge.last_error
    return {
        "backend": "ok",
        "algo_version": ALGO_VERSION,
        "mt5_connected": engine.bridge.connected,
        "last_error": {"code": code, "message": msg},
        "symbol": engine.symbol,
        "ai_enabled": engine.brain.enabled,
        "ai_state": engine.brain.state,
        "adaptive_mode": engine.store.get("adaptive_mode"),
        "account_profile": engine.store.get("account_profile"),
    }


@app.get("/api/quant/report")
async def quant_report(request: Request) -> dict:
    token = request.headers.get("X-Operator-Token") or request.query_params.get("token")
    if not validate_operator_token(token):
        raise HTTPException(status_code=403, detail="Token de operador local inválido.")
    engine._refresh_quant_report()
    return engine.quant_summary


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    origin = ws.headers.get("origin")
    if not validate_ws_origin(origin):
        await ws.close(code=1008, reason="Origin não autorizada.")
        return

    ws_token = ws.query_params.get("token") or ws.headers.get("x-operator-token")
    if LOCAL_OPERATOR_TOKEN and not validate_operator_token(ws_token):
        await ws.close(code=1008, reason="Token de operador inválido.")
        return

    try:
        await ws.accept()
    except Exception:  # noqa: BLE001
        return
    client = Client(ws, token=ws_token)
    initial = [m for m in (engine.meta_json, engine.series_json, engine.history_json) if m]
    initial.append(json.dumps({"type": "logs", "entries": engine.logs.all(), "backlog": True}, ensure_ascii=False))
    if engine.snapshot_json:
        initial.append(engine.snapshot_json)
    await client.send_many(initial)
    if not client.alive:
        return
    clients.add(client)
    try:
        while client.alive:
            text = await ws.receive_text()
            if len(text) > 16384:
                await client.send_many([
                    json.dumps(
                        {"type": "ack", "id": None, "action": None, "ok": False, "message": "Payload muito grande."},
                        ensure_ascii=False,
                    )
                ])
                continue
            try:
                cmd = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(cmd, dict):
                continue
            rid = cmd.get("id")
            valid, v_msg = validate_command_payload(cmd, ws_token=client.token)
            if not valid:
                await client.send_many([
                    json.dumps(
                        {"type": "ack", "id": rid, "action": cmd.get("action"), "ok": False, "message": v_msg},
                        ensure_ascii=False,
                    )
                ])
                continue
            try:
                ok, message = await asyncio.wait_for(engine.submit(cmd), timeout=15.0)
            except asyncio.TimeoutError:
                ok, message = False, "Tempo esgotado aguardando o motor."
            await client.send_many([
                json.dumps(
                    {"type": "ack", "id": rid, "action": cmd.get("action"), "ok": ok, "message": message},
                    ensure_ascii=False,
                )
            ])
    except (WebSocketDisconnect, Exception):  # noqa: BLE001
        pass
    finally:
        client.alive = False
        clients.discard(client)
