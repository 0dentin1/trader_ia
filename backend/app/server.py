"""Servidor FastAPI: WebSocket bidirecional local (ws://localhost:8000/ws) + endpoints de saúde."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .config import BROADCAST_INTERVAL_S
from .engine import Engine

engine = Engine()


class Client:
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
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


app = FastAPI(title="Trader IA — MT5 Autonomous Terminal", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
async def health() -> dict:
    code, msg = engine.bridge.last_error
    return {"backend": "ok", "mt5_connected": engine.bridge.connected, "last_error": {"code": code, "message": msg},
            "symbol": engine.symbol, "ai_enabled": engine.brain.enabled, "ai_state": engine.brain.state}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    try:
        await ws.accept()
    except Exception:  # noqa: BLE001
        return
    client = Client(ws)
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
            try:
                cmd = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(cmd, dict):
                continue
            rid = cmd.get("id")
            try:
                ok, message = await asyncio.wait_for(engine.submit(cmd), timeout=15.0)
            except asyncio.TimeoutError:
                ok, message = False, "Tempo esgotado aguardando o motor."
            await client.send_many([json.dumps({"type": "ack", "id": rid, "action": cmd.get("action"), "ok": ok,
                                                "message": message}, ensure_ascii=False)])
    except (WebSocketDisconnect, Exception):  # noqa: BLE001
        pass
    finally:
        client.alive = False
        clients.discard(client)
