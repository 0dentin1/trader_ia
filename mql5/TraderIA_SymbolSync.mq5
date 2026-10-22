//+------------------------------------------------------------------+
//| TraderIA_SymbolSync.mq5                                          |
//| EA auxiliar OPCIONAL: publica o símbolo do gráfico ativo do MT5   |
//| em Common\Files\trader_ia_active_symbol.txt para o backend Python |
//| (a API Python do MT5 não expõe qual gráfico está em foco).        |
//| Não envia ordens. Anexe a QUALQUER gráfico e mantenha-o aberto.   |
//+------------------------------------------------------------------+
#property copyright "Trader IA"
#property version   "1.00"
#property strict

input int InpTimerMs = 500; // Intervalo de publicação (ms)

const string OUT_FILE = "trader_ia_active_symbol.txt";
string g_last = "";

int OnInit()
  {
   EventSetMillisecondTimer(MathMax(InpTimerMs, 100));
   Publish(true);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
  }

void OnTick() {}

void OnTimer()
  {
   Publish(false);
  }

void OnChartEvent(const int id, const long &lparam, const double &dparam, const string &sparam)
  {
   Publish(false);
  }

//--- Retorna o símbolo do gráfico que está em primeiro plano no terminal
string ActiveChartSymbol()
  {
   long chart = ChartFirst();
   while(chart >= 0)
     {
      if(ChartGetInteger(chart, CHART_BRING_TO_TOP) != 0)
         return(ChartSymbol(chart));
      chart = ChartNext(chart);
     }
   return(_Symbol);
  }

void Publish(const bool force)
  {
   string sym = ActiveChartSymbol();
   // Reescreve sempre (o backend usa a data de modificação para saber que o EA está vivo)
   int h = FileOpen(OUT_FILE, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE)
     {
      if(force)
         Print("TraderIA_SymbolSync: falha ao abrir arquivo, erro ", GetLastError());
      return;
     }
   FileWriteString(h, sym + "|" + IntegerToString((long)TimeLocal()));
   FileClose(h);
   if(sym != g_last)
     {
      g_last = sym;
      Print("TraderIA_SymbolSync: gráfico ativo = ", sym);
     }
  }
//+------------------------------------------------------------------+
