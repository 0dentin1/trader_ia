# TRADER·IA V5 QUANT — Terminal Autônomo e Sistema Quantitativo Institucional (MetaTrader 5)

Sistema quantitativo institucional e terminal operacional local de baixa latência, integrado nativamente ao **MetaTrader 5 (MT5)** via IPC oficial (`MetaTrader5`), com gestão matemática de risco de capital, proteção avançada para pequenas bancas (R$ 50 a R$ 1.000 / $50 a $1.000), memória persistente em SQLite WAL, validação walk-forward e execução auditada sem dados simulados na esteira de produção.

---

## Principais Inovações da Versão 5.0.0-Quant

1. **Proteção de Capital e Circuit Breaker Persistente:**
   - Travas diárias e semanais salvas em disco que sobrevivem a reinicializações e alterações acidentais de configuração.
   - Separação estrita de P&L: O robô monitora apenas as operações com seu `magic number`, sem fechar posições manuais do operador (a menos que a proteção global de conta seja explicitamente solicitada).
   - Gatekeeper independente de risco: bloqueio estrito `BLOCKED_MIN_LOT` caso o lote mínimo (0.01) exceda a perda máxima permitida para o saldo atual.
   - Zero Martingale ou aumento de lote em sequência de perdas.

2. **Guardião de Pequenas Bancas (Small Account Guard):**
   - 5 estados progressivos de drawdown com histerese matemática: `NORMAL`, `CAUTION`, `REDUCED_EXPOSURE`, `TRADING_LOCKED`, `REVIEW_REQUIRED`.
   - Cálculo da assimetria geométrica de recuperação: `Ganho Necessário = (1 / (1 - Drawdown)) - 1`.
   - Validação exaustiva para capitais de R$ 50, R$ 100, R$ 500, R$ 1.000 e equivalentes em USD/EUR.

3. **Reconciliação e Execução Blindada com SL/TP Confirmado:**
   - Protocolo de confirmação de SL/TP direto na corretora MT5. Se não confirmado em 5 segundos, dispara protocolo de fechamento emergencial (`EMERGENCY_CLOSE`).
   - Reconciliação multifatorial de tickets de ordem, deal e posição, com rastreamento real de derrapagem (*slippage*) e custos.

4. **Confluência Analítica e Estrutural:**
   - Exigência estrita de múltiplos tempos gráficos: contexto M5/M15 obrigatório para entradas em M1 (`NO_TRADE` se HTF indisponível).
   - Espaço estrutural objetivo calculado a partir de suportes, resistências e pivôs (sem assumir multiplicadores cegos).
   - Classificação determinística de regimes de mercado (Tendência de Alta/Baixa, Lateralidade Estreita/Ampla, Alta Volatilidade/Rompimento).

5. **Memória Quantitativa Persistente (`quant_memory.db` WAL):**
   - Rastreamento prospectivo de MFE (*Maximum Favorable Excursion*) e MAE (*Maximum Adverse Excursion*) tick a tick.
   - Registro de avaliações de sinais, decisões de veto, eventos de ciclo de vida (Break-Even, Trailing Stop) e análise contrafactual de sinais bloqueados.
   - Calibração de probabilidade empírica via Brier Score e Log Loss.

6. **Adaptação Estatística Controlada:**
   - 3 modos de transição: `OBSERVATION`, `SHADOW` e `ACTIVE` (com requisito de amostra mínima $n \ge 20$ e erro padrão para evitar *overfitting*).

7. **Laboratório de Backtesting Walk-Forward:**
   - Divisão cronológica estrita em 3 conjuntos: Desenvolvimento (50%), Validação (25%) e Teste Fora da Amostra (25%), com janela de purga (*purge gap*) de 15 barras.
   - Resolução conservadora de ambiguidade intrabarra: sempre assume que o Stop Loss foi atingido primeiro caso ambos SL e TP estejam dentro da mesma vela.

---

## Estrutura do Projeto

```text
trader_ia/
├── backend/
│   ├── requirements.txt          # Dependências Python
│   ├── run.py                    # Ponto de entrada Uvicorn/FastAPI (ws://127.0.0.1:8000/ws)
│   ├── tests/                    # Suíte completa de testes automatizados pytest
│   │   ├── test_risk_and_capital.py
│   │   ├── test_small_account_guard.py
│   │   ├── test_execution_and_bridge.py
│   │   ├── test_analytical_brain.py
│   │   ├── test_memory_and_performance.py
│   │   └── test_adaptation_and_backtest.py
│   └── app/
│       ├── config.py             # Configurações V5, constantes e perfis de conta
│       ├── mt5_bridge.py         # Conector IPC MetaTrader 5 com stub compatível macOS/Linux
│       ├── small_account_guard.py# Guardião de 5 estados de drawdown e limites de pequena banca
│       ├── indicators.py         # Indicadores vetorizados (VWAP, EMAs, RSI, ADX, ATR, RVOL)
│       ├── flow.py               # Tape reading quantitativo de agressão
│       ├── analysis.py           # Confluência multi-tempo, regimes e espaço estrutural
│       ├── risk.py               # Gatekeeper independente de risco, lote e correlação
│       ├── brain.py              # Máquina de estados autônoma e protocolo de execução
│       ├── engine.py             # Loop assíncrono de 100ms e despacho de ordens
│       ├── settings_store.py     # Armazenamento seguro e travas persistentes
│       ├── trade_journal.py      # Banco SQLite WAL da memória quantitativa
│       ├── performance.py        # Métricas estatísticas, Brier Score e calibração
│       ├── adaptive_rules.py     # Modos Observation, Shadow e Active
│       ├── backtest.py           # Laboratório Walk-Forward sem look-ahead bias
│       ├── server.py             # Servidor FastAPI + WebSocket de baixa latência
│       └── utils.py              # Utilitários e serialização JSON segura
├── frontend/
│   ├── package.json              # React 18 + TypeScript + TailwindCSS + lightweight-charts
│   └── src/
│       ├── App.tsx               # Terminal Dark Mode com abas de Terminal, Risco e Quant
│       ├── types.ts              # Contratos TypeScript completos da Versão 5
│       └── components/           # Componentes operacionais e quantitativos
├── start_windows.bat             # Inicialização rápida no Windows
└── start.sh                      # Inicialização rápida no macOS/Linux
```

---

## Execução dos Testes Automatizados

Para executar toda a suíte de testes unitários e de integração:

```bash
cd backend
./.venv/bin/pytest tests/ -v
```

Todos os 21 testes cobrem os pilares fundamentais da evolução quantitativa com 100% de sucesso.

---

## Compilação do Frontend

```bash
cd frontend
npm install
npm run build
```

---

## Inicialização do Sistema

- **Windows:** Duplo clique em `start_windows.bat`.
- **macOS / Linux:** Execute `./start.sh` (com `BACKEND_WS` configurado para a máquina Windows executando o MT5).

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
