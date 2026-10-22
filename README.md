# TRADER·IA — Terminal Autônomo de Análise e Execução em Tempo Real (MetaTrader 5)

Terminal operacional local de baixa latência, integrado nativamente ao **MetaTrader 5 (MT5)** via IPC oficial (`MetaTrader5`), sem tela de login, sem dados simulados (**zero mock data**) e dedicado a **um único ativo por vez** com piloto automático completo (**Full Autopilot**).

---

## Estrutura do Projeto

```text
trader_ia/
├── backend/
│   ├── requirements.txt          # Dependências Python
│   ├── run.py                    # Ponto de entrada Uvicorn/FastAPI (ws://127.0.0.1:8000/ws)
│   └── app/
│       ├── config.py             # Modos operacionais (Leve, Mediano, Arriscado) e constantes
│       ├── mt5_bridge.py         # Conector IPC nativo MetaTrader5 (conta, ticks, velas, ordens, SL/TP)
│       ├── indicators.py         # Indicadores vetorizados (VWAP Diária ±1σ/±2σ, EMAs 9/21/200, RSI, Estocástico, ADX, ATR, RVOL)
│       ├── flow.py               # Tape reading quantitativo (agressão de ticks e velocidade)
│       ├── analysis.py           # Diagnóstico de regime + 5 Pilares + Travas por modo
│       ├── risk.py               # Cálculo de lote por risco %, SL/TP em ATR e P&L diário real
│       ├── brain.py              # Máquina de estados autônoma (5 estados + Break-Even + Trailing Stop)
│       ├── engine.py             # Loop de 100ms dedicado à thread IPC do MT5 e limpeza de buffers na troca de ativo
│       ├── settings_store.py     # Persistência local das travas e parâmetros
│       ├── server.py             # Servidor FastAPI + WebSocket bidirecional (100ms)
│       └── utils.py              # Serialização JSON segura e LogBook em tempo real
├── frontend/
│   ├── package.json              # React 18 + TypeScript + TailwindCSS + lightweight-charts + Lucide
│   └── src/
│       ├── App.tsx               # Layout principal Dark Mode institucional (sem login)
│       ├── types.ts              # Contratos TypeScript do protocolo WebSocket
│       ├── hooks/useTerminal.ts  # Cliente WebSocket bidirecional com reconexão automática
│       ├── lib/format.ts         # Formatação numérica e monetária
│       └── components/
│           ├── Header.tsx            # Status MT5, seletor de ativo único, Saldo/Equity/Dia, Autopilot e Panic Close
│           ├── ModeSelector.tsx      # 3 Cards interativos (Leve, Mediano, Arriscado)
│           ├── RiskPanel.tsx         # Circuit Breakers (Stop Diário, Gain Diário, Spread Máximo, Risco %)
│           ├── PriceChart.tsx        # Gráfico TradingView lightweight-charts 60fps + VWAP + EMAs + linhas Entrada/SL/TP
│           ├── BrainPanel.tsx        # Máquina de estados, Regime, Termômetro 0-100%, 5 Pilares e Log da IA
│           ├── BottomPanel.tsx       # Posições Abertas tick a tick + Histórico Real do Dia (MT5)
│           └── ConnectionOverlay.tsx # Bloqueio total da UI quando MT5/Backend desconectado exibindo mt5.last_error()
├── mql5/
│   └── TraderIA_SymbolSync.mq5   # EA auxiliar opcional para detectar automaticamente a aba/gráfico em foco no MT5
├── start_windows.bat             # Inicialização rápida em 1 clique no Windows
└── start.sh                      # Inicialização rápida para macOS/Linux (frontend local + backend Windows/VM/Wine)
```

---

## Pré-requisitos no MetaTrader 5

1. Abra o **MetaTrader 5** na máquina e faça login na sua conta (Demo ou Real).
2. Na barra superior do MT5, ative o botão **`Algo Trading`** (Negociação Automatizada).
3. No painel **Observação do Mercado (`Market Watch`)**, mantenha visíveis os ativos que deseja operar.
4. *(Opcional)* Caso queira que o terminal troque de ativo automaticamente ao clicar em outra aba de gráfico dentro do MT5, compile e anexe o EA [`mql5/TraderIA_SymbolSync.mq5`](mql5/TraderIA_SymbolSync.mq5) a qualquer gráfico e marque **"Seguir o gráfico ativo do MT5"** no painel de Travas de Segurança.

---

## Instalação Manual e Inicialização Rápida

### 1. Instalar dependências do Backend (Python 3.11+)

```bash
pip install MetaTrader5 fastapi uvicorn pandas numpy pandas-ta websockets
```

> **Nota sobre Sistema Operacional:** O pacote oficial `MetaTrader5` utiliza IPC nativo do Windows para comunicar com o terminal `terminal64.exe`. Portanto, o backend deve ser executado no mesmo ambiente Windows onde o MT5 está aberto (Windows nativo, VM Parallels/UTM ou Python Windows sob Wine).

Para iniciar o servidor backend na porta `8000`:

```bash
cd backend
python run.py
```

*(Se o frontend estiver em outra máquina/sistema, use `python run.py --host 0.0.0.0`)*

### 2. Instalar dependências e iniciar o Frontend

Em outro terminal:

```bash
cd frontend
npm install
npm run dev
```

Abra **`http://127.0.0.1:5173`** no navegador.

### Inicialização em 1 Comando

- **Windows:** clique duas vezes em `start_windows.bat`.
- **macOS / Linux:** execute `./start.sh frontend` (ou `BACKEND_WS=ws://IP_DO_WINDOWS:8000/ws ./start.sh frontend`).

---

## Como Operar com Segurança

1. **Verifique a Conexão:** Se o MT5 estiver fechado ou desconectado, a tela ficará bloqueada pelo overlay exibindo o código e a mensagem exata de `mt5.last_error()`.
2. **Selecione o Ativo Único:** Escolha o ativo no seletor do topo. Todos os buffers de velas e fluxo de ticks anteriores são limpos imediatamente para dedicar 100% do processamento ao ativo escolhido.
3. **Escolha o Modo Operacional:**
   - **MODO 1 — LEVE (M5 / filtro M15):** Confluência mínima **85%**, ADX > 22, pullback na EMA 21, risco **0,5% a 1%**, SL `2.0x ATR`, TP `4.0x ATR` (1:2), Break-Even em `1.0x ATR`.
   - **MODO 2 — MEDIANO (M2 / contexto M5):** Confluência mínima **70%** (4/5 pilares), risco **1,5% a 2%**, SL `1.5x ATR`, TP `2.25x ATR` (1:1.5), Break-Even em 50% do alvo + Trailing Stop pela EMA 9.
   - **MODO 3 — ARRISCADO (M1 + Tape Reading):** Confluência mínima **60%** com peso 2× em Explosão de Volume (`RVOL > 1.8x`) e Rompimento de Microestrutura, risco **3% a 5%**, SL `1.0x ATR` e Trailing Stop tick a tick (`0.5x ATR`).
4. **Configure as Travas de Segurança (Circuit Breakers):**
   - Defina obrigatoriamente o **Stop Loss Diário Financeiro** (> 0), a **Meta de Gain Diário** e o **Filtro de Spread Máximo** e clique em **Salvar**.
5. **Ative o Piloto Automático:** Clique em **`[ LIGAR IA AUTÔNOMA ]`**. A qualquer momento, o botão **`[ ZERAR POSIÇÃO AGORA ]`** desliga a IA e fecha todas as posições abertas do ativo a mercado.
