"""Conector nativo MetaTrader 5 (biblioteca oficial `MetaTrader5`, IPC com o terminal aberto).

IMPORTANTE: a biblioteca MetaTrader5 é bloqueante e não é thread-safe. Todas as chamadas desta
classe são feitas exclusivamente pela thread do motor (ver engine.py), nunca em paralelo.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

from .config import MT5_LOGIN, MT5_PASSWORD, MT5_PATH, MT5_SERVER
from .utils import floor_to_step, round_to_step

TIMEFRAMES = {
    "M1": mt5.TIMEFRAME_M1,
    "M2": mt5.TIMEFRAME_M2,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
}

# Constantes com fallback numérico (algumas versões da lib não expõem todas)
SYMBOL_FILLING_FOK = getattr(mt5, "SYMBOL_FILLING_FOK", 1)
SYMBOL_FILLING_IOC = getattr(mt5, "SYMBOL_FILLING_IOC", 2)
SYMBOL_TRADE_EXECUTION_MARKET = getattr(mt5, "SYMBOL_TRADE_EXECUTION_MARKET", 2)
SYMBOL_TRADE_MODE_DISABLED = getattr(mt5, "SYMBOL_TRADE_MODE_DISABLED", 0)
SYMBOL_TRADE_MODE_LONGONLY = getattr(mt5, "SYMBOL_TRADE_MODE_LONGONLY", 1)
SYMBOL_TRADE_MODE_SHORTONLY = getattr(mt5, "SYMBOL_TRADE_MODE_SHORTONLY", 2)
SYMBOL_TRADE_MODE_CLOSEONLY = getattr(mt5, "SYMBOL_TRADE_MODE_CLOSEONLY", 3)
COPY_TICKS_ALL = getattr(mt5, "COPY_TICKS_ALL", -1)

RET_DONE = {getattr(mt5, "TRADE_RETCODE_DONE", 10009), getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010),
            getattr(mt5, "TRADE_RETCODE_PLACED", 10008)}
RET_REQUOTE = {getattr(mt5, "TRADE_RETCODE_REQUOTE", 10004), getattr(mt5, "TRADE_RETCODE_PRICE_CHANGED", 10020),
               getattr(mt5, "TRADE_RETCODE_PRICE_OFF", 10021)}
RET_INVALID_FILL = getattr(mt5, "TRADE_RETCODE_INVALID_FILL", 10030)
RET_INVALID_STOPS = getattr(mt5, "TRADE_RETCODE_INVALID_STOPS", 10016)
RET_NO_CHANGES = getattr(mt5, "TRADE_RETCODE_NO_CHANGES", 10025)

RETCODE_TEXT = {
    10004: "Requote", 10006: "Requisição rejeitada", 10007: "Requisição cancelada pelo trader",
    10008: "Ordem colocada", 10009: "Requisição executada", 10010: "Executada parcialmente",
    10011: "Erro de processamento", 10012: "Timeout", 10013: "Requisição inválida",
    10014: "Volume inválido", 10015: "Preço inválido", 10016: "Stops inválidos",
    10017: "Negociação desabilitada", 10018: "Mercado fechado", 10019: "Saldo insuficiente",
    10020: "Preço mudou", 10021: "Sem cotação", 10022: "Expiração inválida",
    10023: "Estado da ordem mudou", 10024: "Requisições em excesso", 10025: "Sem alterações",
    10026: "Autotrading desabilitado pelo servidor", 10027: "Autotrading desabilitado no terminal (botão Algo Trading)",
    10028: "Requisição bloqueada para processamento", 10029: "Ordem/posição congelada",
    10030: "Tipo de preenchimento não suportado", 10031: "Sem conexão com o servidor de negociação",
    10032: "Operação permitida apenas em contas reais", 10033: "Limite de ordens pendentes atingido",
    10034: "Limite de volume atingido", 10035: "Tipo de ordem inválido", 10036: "Posição já fechada",
    10038: "Volume de fechamento excede a posição", 10039: "Ordem de fechamento já existe",
    10040: "Limite de posições atingido", 10044: "Somente fechamento permitido",
    10045: "Regra FIFO", 10046: "Hedge proibido",
}

DEAL_REASON = {0: "Manual", 1: "Mobile", 2: "Web", 3: "Robô", 4: "Stop Loss", 5: "Take Profit",
               6: "Stop Out", 7: "Rollover", 8: "Margem variável", 9: "Split"}
FILLING_NAME = {getattr(mt5, "ORDER_FILLING_FOK", 0): "FOK", getattr(mt5, "ORDER_FILLING_IOC", 1): "IOC",
                getattr(mt5, "ORDER_FILLING_RETURN", 2): "RETURN"}


@dataclass
class OrderResult:
    ok: bool
    retcode: int = 0
    message: str = ""
    order: int = 0
    deal: int = 0
    price: float = 0.0
    volume: float = 0.0
    filling: str = ""
    stops_deferred: bool = False
    request: dict = field(default_factory=dict)


def _nt(obj: Any) -> dict:
    return obj._asdict() if obj is not None else {}


class MT5Bridge:
    def __init__(self) -> None:
        self.connected = False
        self.last_error: tuple[int, str] = (0, "Ainda não inicializado")
        self._filling_cache: dict[str, int] = {}

    # ------------------------------------------------------------------ conexão
    def _capture_error(self, prefix: str = "") -> tuple[int, str]:
        code, msg = mt5.last_error()
        self.last_error = (int(code), f"{prefix}{msg}" if prefix else str(msg))
        return self.last_error

    def connect(self) -> bool:
        kwargs: dict[str, Any] = {}
        if MT5_LOGIN:
            kwargs.update(login=MT5_LOGIN, password=MT5_PASSWORD or "", server=MT5_SERVER or "")
        ok = mt5.initialize(MT5_PATH, **kwargs) if MT5_PATH else mt5.initialize(**kwargs)
        if not ok:
            fallback_path = MT5_PATH or r"C:\Program Files\MetaTrader 5\terminal64.exe"
            ok = mt5.initialize(fallback_path, portable=True, **kwargs)
        if not ok:
            self._capture_error("mt5.initialize() falhou: ")
            self.connected = False
            mt5.shutdown()
            return False
        if mt5.account_info() is None:
            self._capture_error("Terminal aberto, mas sem conta logada: ")
            self.connected = False
            mt5.shutdown()
            return False
        self.connected = True
        self.last_error = (0, "")
        return True

    def shutdown(self) -> None:
        try:
            mt5.shutdown()
        finally:
            self.connected = False

    def is_alive(self) -> bool:
        ti = mt5.terminal_info()
        if ti is None:
            self._capture_error("Conexão IPC com o MT5 perdida: ")
            self.shutdown()
            return False
        return True

    # ------------------------------------------------------------------ leitura
    def terminal(self) -> dict:
        ti = mt5.terminal_info()
        if ti is None:
            return {}
        t = _nt(ti)
        return {
            "name": t.get("name"), "company": t.get("company"), "connected": bool(t.get("connected")),
            "trade_allowed": bool(t.get("trade_allowed")), "ping_ms": (t.get("ping_last") or 0) / 1000.0,
            "commondata_path": t.get("commondata_path"), "build": t.get("build"),
        }

    def account(self) -> dict:
        ai = mt5.account_info()
        if ai is None:
            self._capture_error("account_info(): ")
            return {}
        a = _nt(ai)
        trade_mode = {0: "DEMO", 1: "CONTEST", 2: "REAL"}.get(a.get("trade_mode"), "?")
        return {
            "login": a.get("login"), "name": a.get("name"), "server": a.get("server"),
            "company": a.get("company"), "currency": a.get("currency"), "leverage": a.get("leverage"),
            "balance": a.get("balance"), "equity": a.get("equity"), "profit": a.get("profit"),
            "margin": a.get("margin"), "margin_free": a.get("margin_free"),
            "margin_level": a.get("margin_level"), "trade_mode": trade_mode,
            "trade_allowed": bool(a.get("trade_allowed")), "trade_expert": bool(a.get("trade_expert")),
            "margin_mode": a.get("margin_mode"),  # 0 netting(exchange/retail) | 2 hedging
        }

    def visible_symbols(self) -> list[dict]:
        syms = mt5.symbols_get()
        if syms is None:
            self._capture_error("symbols_get(): ")
            return []
        out = []
        for s in syms:
            if not s.visible:
                continue
            out.append({"name": s.name, "description": s.description, "digits": s.digits, "path": s.path})
        return out

    def select_symbol(self, symbol: str) -> dict | None:
        if not mt5.symbol_select(symbol, True):
            self._capture_error(f"symbol_select({symbol}): ")
            return None
        return self.symbol_info(symbol)

    def symbol_info(self, symbol: str) -> dict | None:
        si = mt5.symbol_info(symbol)
        if si is None:
            self._capture_error(f"symbol_info({symbol}): ")
            return None
        s = _nt(si)
        tick_size = s.get("trade_tick_size") or s.get("point")
        return {
            "name": s["name"], "description": s.get("description"), "digits": s["digits"],
            "point": s["point"], "tick_size": tick_size, "tick_value": s.get("trade_tick_value"),
            "tick_value_loss": s.get("trade_tick_value_loss"), "contract_size": s.get("trade_contract_size"),
            "volume_min": s["volume_min"], "volume_max": s["volume_max"], "volume_step": s["volume_step"],
            "stops_level": s.get("trade_stops_level", 0), "freeze_level": s.get("trade_freeze_level", 0),
            "filling_mode": s.get("filling_mode", 0), "trade_mode": s.get("trade_mode"),
            "exemode": s.get("trade_exemode"), "currency_profit": s.get("currency_profit"),
            "spread_float": bool(s.get("spread_float")),
        }

    def tick(self, symbol: str) -> dict | None:
        t = mt5.symbol_info_tick(symbol)
        if t is None:
            self._capture_error(f"symbol_info_tick({symbol}): ")
            return None
        d = _nt(t)
        return {"time": d["time"], "time_msc": d["time_msc"], "bid": d["bid"], "ask": d["ask"],
                "last": d.get("last", 0.0), "volume": d.get("volume_real") or d.get("volume", 0), "flags": d.get("flags", 0)}

    def ticks_since(self, symbol: str, from_sec: int, count: int = 5000) -> np.ndarray | None:
        arr = mt5.copy_ticks_from(symbol, int(max(from_sec, 0)), count, COPY_TICKS_ALL)
        if arr is None:
            self._capture_error("copy_ticks_from(): ")
            return None
        return arr

    def rates(self, symbol: str, tf: str, count: int) -> pd.DataFrame | None:
        arr = mt5.copy_rates_from_pos(symbol, TIMEFRAMES[tf], 0, count)
        if arr is None or len(arr) == 0:
            self._capture_error(f"copy_rates_from_pos({symbol},{tf}): ")
            return None
        df = pd.DataFrame(arr)
        df["time"] = df["time"].astype("int64")
        return df

    @staticmethod
    def _pos_dict(p: Any) -> dict:
        d = _nt(p)
        return {
            "ticket": d["ticket"], "symbol": d["symbol"], "type": "BUY" if d["type"] == mt5.POSITION_TYPE_BUY else "SELL",
            "volume": d["volume"], "price_open": d["price_open"], "price_current": d["price_current"],
            "sl": d["sl"], "tp": d["tp"], "profit": d["profit"], "swap": d["swap"], "time": d["time"],
            "magic": d["magic"], "comment": d["comment"], "identifier": d.get("identifier", d["ticket"]),
        }

    def positions(self, symbol: str | None = None) -> list[dict] | None:
        ps = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        if ps is None:
            code, _ = self._capture_error("positions_get(): ")
            return [] if code == 1 else None
        return [self._pos_dict(p) for p in ps]

    @staticmethod
    def _deal_dict(x: Any) -> dict:
        d = _nt(x)
        tname = {0: "BUY", 1: "SELL"}.get(d["type"], str(d["type"]))
        ename = {0: "IN", 1: "OUT", 2: "INOUT", 3: "OUT_BY"}.get(d["entry"], str(d["entry"]))
        return {
            "ticket": d["ticket"], "order": d["order"], "time": d["time"], "time_msc": d.get("time_msc"),
            "type": tname, "type_raw": d["type"], "entry": ename, "symbol": d["symbol"], "volume": d["volume"],
            "price": d["price"], "profit": d["profit"], "commission": d.get("commission", 0.0),
            "swap": d.get("swap", 0.0), "fee": d.get("fee", 0.0), "magic": d["magic"],
            "comment": d["comment"], "position_id": d["position_id"],
            "reason": DEAL_REASON.get(d.get("reason", -1), str(d.get("reason"))),
        }

    def deals_between(self, t_from: int, t_to: int) -> list[dict] | None:
        from datetime import datetime, timezone
        dt_from = datetime.fromtimestamp(max(int(t_from), 946684800), tz=timezone.utc)
        dt_to = datetime.fromtimestamp(int(t_to), tz=timezone.utc)
        ds = mt5.history_deals_get(dt_from, dt_to)
        if ds is None:
            ds = mt5.history_deals_get(int(t_from), int(t_to))
        if ds is None:
            self._capture_error("history_deals_get(): ")
            return None
        return [self._deal_dict(d) for d in ds]

    def deals_for_position(self, position_id: int) -> list[dict]:
        ds = mt5.history_deals_get(position=int(position_id))
        return [self._deal_dict(d) for d in ds] if ds else []

    # ------------------------------------------------------------------ cálculos de risco
    def loss_per_lot(self, symbol: str, side: str, entry: float, sl: float, sym: dict) -> float | None:
        otype = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
        p = mt5.order_calc_profit(otype, symbol, 1.0, entry, sl)
        if p is not None and p != 0:
            return abs(float(p))
        tv = sym.get("tick_value_loss") or sym.get("tick_value")
        ts = sym.get("tick_size")
        if tv and ts:
            return abs(entry - sl) / ts * tv
        return None

    def calc_profit(self, symbol: str, side: str, volume: float, entry: float, close_price: float) -> float | None:
        if not close_price or close_price <= 0:
            return None
        otype = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
        p = mt5.order_calc_profit(otype, symbol, float(volume), float(entry), float(close_price))
        return float(p) if p is not None else None

    def margin_for(self, symbol: str, side: str, volume: float, price: float) -> float | None:
        otype = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
        m = mt5.order_calc_margin(otype, symbol, float(volume), float(price))
        return float(m) if m is not None else None

    # ------------------------------------------------------------------ execução
    def filling_candidates(self, symbol: str, sym: dict) -> list[int]:
        fok = mt5.ORDER_FILLING_FOK
        ioc = mt5.ORDER_FILLING_IOC
        ret = mt5.ORDER_FILLING_RETURN
        cands: list[int] = []
        if symbol in self._filling_cache:
            cands.append(self._filling_cache[symbol])
        fm = int(sym.get("filling_mode") or 0)
        if fm & SYMBOL_FILLING_FOK:
            cands.append(fok)
        if fm & SYMBOL_FILLING_IOC:
            cands.append(ioc)
        if sym.get("exemode") != SYMBOL_TRADE_EXECUTION_MARKET:
            cands.append(ret)
        for f in (fok, ioc, ret):  # fallback completo, caso a corretora reporte flags incompletas
            cands.append(f)
        seen: list[int] = []
        for c in cands:
            if c not in seen:
                seen.append(c)
        return seen

    def _send(self, request: dict, sym: dict) -> OrderResult:
        symbol = request["symbol"]
        last: OrderResult | None = None
        for filling in self.filling_candidates(symbol, sym):
            req = dict(request, type_filling=filling)
            res = mt5.order_send(req)
            if res is None:
                code, msg = self._capture_error("order_send(): ")
                return OrderResult(False, code, msg, request=req)
            rc = int(res.retcode)
            fname = FILLING_NAME.get(filling, str(filling))
            out = OrderResult(rc in RET_DONE, rc, f"{RETCODE_TEXT.get(rc, rc)} ({res.comment})", int(res.order),
                              int(res.deal), float(res.price), float(res.volume), fname, request=req)
            if rc == RET_INVALID_FILL:
                last = out
                continue
            if out.ok:
                self._filling_cache[symbol] = filling
            return out
        return last or OrderResult(False, RET_INVALID_FILL, "Nenhum tipo de preenchimento aceito pela corretora")

    def market_order(self, symbol: str, side: str, volume: float, sl: float, tp: float, deviation: int,
                     magic: int, comment: str, sym: dict) -> OrderResult:
        otype = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
        deferred = False
        res = OrderResult(False, 0, "não enviado")
        for attempt in range(3):
            t = self.tick(symbol)
            if t is None:
                return OrderResult(False, self.last_error[0], self.last_error[1])
            price = t["ask"] if side == "BUY" else t["bid"]
            req = {
                "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": float(volume), "type": otype,
                "price": float(price), "deviation": int(deviation), "magic": int(magic),
                "comment": comment[:28], "type_time": mt5.ORDER_TIME_GTC,
            }
            if not deferred:
                req["sl"] = float(sl)
                req["tp"] = float(tp)
            res = self._send(req, sym)
            if res.ok:
                res.stops_deferred = deferred
                return res
            if res.retcode == RET_INVALID_STOPS and not deferred:
                # Algumas corretoras (execução a mercado) não aceitam SL/TP na abertura:
                # abre sem stops e define via TRADE_ACTION_SLTP logo em seguida.
                deferred = True
                continue
            if res.retcode in RET_REQUOTE:
                time.sleep(0.05)
                continue
            return res
        return res

    def modify_sltp(self, symbol: str, ticket: int, sl: float, tp: float, magic: int, sym: dict) -> OrderResult:
        req = {"action": mt5.TRADE_ACTION_SLTP, "symbol": symbol, "position": int(ticket),
               "sl": float(sl), "tp": float(tp), "magic": int(magic)}
        res = mt5.order_send(req)
        if res is None:
            code, msg = self._capture_error("order_send(SLTP): ")
            return OrderResult(False, code, msg, request=req)
        rc = int(res.retcode)
        return OrderResult(rc in RET_DONE, rc, f"{RETCODE_TEXT.get(rc, rc)} ({res.comment})", request=req)

    def close_position(self, pos: dict, deviation: int, magic: int, comment: str, sym: dict) -> OrderResult:
        symbol = pos["symbol"]
        res = OrderResult(False, 0, "não enviado")
        for _ in range(3):
            t = self.tick(symbol)
            if t is None:
                return OrderResult(False, self.last_error[0], self.last_error[1])
            is_buy = pos["type"] == "BUY"
            req = {
                "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": float(pos["volume"]),
                "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY, "position": int(pos["ticket"]),
                "price": float(t["bid"] if is_buy else t["ask"]), "deviation": int(deviation),
                "magic": int(magic), "comment": comment[:28], "type_time": mt5.ORDER_TIME_GTC,
            }
            res = self._send(req, sym)
            if res.ok or res.retcode not in RET_REQUOTE:
                return res
            time.sleep(0.05)
        return res

    # ------------------------------------------------------------------ helpers de preço/volume
    @staticmethod
    def norm_price(price: float, sym: dict) -> float:
        return round_to_step(price, float(sym["tick_size"] or sym["point"]), int(sym["digits"]))

    @staticmethod
    def norm_volume(volume: float, sym: dict) -> float:
        return floor_to_step(volume, float(sym["volume_step"]))
