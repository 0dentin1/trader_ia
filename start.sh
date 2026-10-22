#!/usr/bin/env bash
# ============================================================
#  Trader IA - Inicialização rápida (macOS com MetaTrader 5.app / Linux)
# ============================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
TARGET="${1:-all}"

if [ -d "$ROOT/.runtime/node/bin" ]; then
  export PATH="$ROOT/.runtime/node/bin:$PATH"
fi

MT5_APP="/Applications/MetaTrader 5.app"
WINE_BIN="$MT5_APP/Contents/SharedSupport/wine/bin/wine"
WINE_PREFIX="$HOME/Library/Application Support/net.metaquotes.wine.metatrader5"
WINE_PY="$WINE_PREFIX/drive_c/Python311/python.exe"

start_frontend() {
  command -v npm >/dev/null || { echo "[ERRO] Node.js 18+ não encontrado."; exit 1; }
  cd "$ROOT/frontend"
  [ -d node_modules ] || npm install
  if [ -n "${BACKEND_WS:-}" ]; then
    VITE_BACKEND_WS="$BACKEND_WS" npm run dev
  else
    npm run dev
  fi
}

start_backend() {
  if [ -x "$WINE_BIN" ] && [ -f "$WINE_PY" ]; then
    export WINEPREFIX="$WINE_PREFIX"
    export WINEDEBUG="-all"
    export MT5_PATH="${MT5_PATH:-C:\\Program Files\\MetaTrader 5\\terminal64.exe}"
    # Copia o EA opcional de sincronização de gráfico para a pasta Experts do MT5
    EXPERTS_DIR="$WINE_PREFIX/drive_c/Program Files/MetaTrader 5/MQL5/Experts"
    if [ -d "$EXPERTS_DIR" ] && [ -f "$ROOT/mql5/TraderIA_SymbolSync.mq5" ]; then
      cp -f "$ROOT/mql5/TraderIA_SymbolSync.mq5" "$EXPERTS_DIR/TraderIA_SymbolSync.mq5" || true
    fi
    WIN_BACKEND="Z:$(echo "$ROOT/backend" | tr '/' '\\')"
    cd "$ROOT/backend"
    exec "$WINE_BIN" "C:\\Python311\\python.exe" "$WIN_BACKEND\\run.py" "$@"
  else
    cd "$ROOT/backend"
    [ -d .venv ] || python3 -m venv .venv
    ./.venv/bin/pip install -r requirements.txt
    exec ./.venv/bin/python run.py "$@"
  fi
}

case "$TARGET" in
  frontend) start_frontend ;;
  backend) shift; start_backend "$@" ;;
  all)
    (start_backend) &
    BACK_PID=$!
    trap 'kill $BACK_PID 2>/dev/null || true' EXIT
    sleep 3
    start_frontend
    ;;
  *) echo "uso: ./start.sh [all|frontend|backend]"; exit 1 ;;
esac
