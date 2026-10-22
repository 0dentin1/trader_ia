"""Ponto de entrada do backend: python run.py [--host 127.0.0.1] [--port 8000]"""
from __future__ import annotations

import argparse
import sys

import uvicorn


def main() -> None:
    if sys.platform != "win32":
        print("[AVISO] A biblioteca oficial MetaTrader5 só funciona no Windows (ou Python Windows sob Wine). "
              "Execute este backend na mesma máquina/VM onde o terminal MT5 está aberto.", flush=True)
    parser = argparse.ArgumentParser(description="Trader IA — backend MT5")
    parser.add_argument("--host", default="127.0.0.1", help="Use 0.0.0.0 para acessar o terminal de outra máquina")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("app.server:app", host=args.host, port=args.port, log_level="warning", ws_ping_interval=20)


if __name__ == "__main__":
    main()
