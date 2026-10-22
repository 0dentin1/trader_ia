@echo off
REM ============================================================
REM  Trader IA - Inicializacao rapida (Windows, mesma maquina do MT5)
REM  1) cria venv + instala dependencias do backend
REM  2) instala dependencias do frontend
REM  3) abre backend (porta 8000) e frontend (porta 5173)
REM ============================================================
setlocal
cd /d "%~dp0"

where python >nul 2>nul || (echo [ERRO] Python 3.11+ nao encontrado no PATH. & pause & exit /b 1)
where npm >nul 2>nul || (echo [ERRO] Node.js 18+ / npm nao encontrado no PATH. & pause & exit /b 1)

if not exist backend\.venv (
  echo [1/4] Criando ambiente virtual Python...
  python -m venv backend\.venv || (pause & exit /b 1)
)
echo [2/4] Instalando dependencias do backend...
call backend\.venv\Scripts\python.exe -m pip install --upgrade pip >nul
call backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt || (pause & exit /b 1)

if not exist frontend\node_modules (
  echo [3/4] Instalando dependencias do frontend...
  pushd frontend
  call npm install || (popd & pause & exit /b 1)
  popd
)

echo [4/4] Iniciando servicos...
start "TraderIA Backend" cmd /k "cd /d %~dp0backend && .venv\Scripts\python.exe run.py"
start "TraderIA Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"
timeout /t 4 >nul
start "" http://127.0.0.1:5173
echo Terminal aberto em http://127.0.0.1:5173  (backend ws://localhost:8000/ws)
endlocal
