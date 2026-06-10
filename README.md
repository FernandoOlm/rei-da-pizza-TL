# 🤖 Ferdinando Monitor Bot

Seu estagiário de TI no VPS. Monitora processos PM2, gerencia memória, detecta crashes e responde com inteligência artificial (Groq LLaMA).

## 🚀 Deploy no VPS (Linux)

### 1. Clonar e entrar na pasta
```bash
git clone <seu-repo> bot_create
cd bot_create
```

### 2. Instalar dependências Python
```bash
pip3 install -r requirements.txt
```

### 3. Configurar variáveis de ambiente
```bash
cp .env.example .env   # ou edite o .env diretamente
nano .env
```

> **⚠️ IMPORTANTE:** `OWNER_TELEGRAM_ID` deve ser o seu ID do Telegram.
> Se não souber, deixe como `0`, inicie o bot e envie qualquer mensagem — ele vai te dizer seu ID.

### 4. Iniciar com PM2
```bash
pm2 start ecosystem.config.js
pm2 save
pm2 logs monit-bot
```

### 5. Verificar no Telegram
Abra o chat com [@Ferdinando_monit_bot](https://t.me/Ferdinando_monit_bot) e envie `/start`

---

## 📋 Comandos

| Comando | Descrição |
|---|---|
| `/start` | Apresentação e lista de comandos |
| `/status` | Dashboard: CPU, RAM, disco + todos os processos |
| `/processos` | Lista detalhada dos processos PM2 |
| `/memoria` | Análise de memória com alertas e botões de ação |
| `/logs [nome]` | Últimas 25 linhas de log de um processo |
| `/restart [nome]` | Reinicia processo (com confirmação) |
| `/stop [nome]` | Para processo (com confirmação) |
| `/limpar [nome]` | Limpa logs do processo (com confirmação) |
| `/analise` | IA analisa todo o VPS e dá recomendações |
| `/myid` | Retorna seu Telegram ID |
| `/ajuda` | Lista todos os comandos |

---

## 🔔 Alertas Automáticos

O bot monitora proativamente e avisa **sem você precisar perguntar**:

| Alerta | Frequência | Condição |
|---|---|---|
| 🚨 Memória alta | 5 min | Processo > 500 MB |
| 💥 Crash/Erro | 2 min | Status `errored` |
| 🔥 CPU alta | 5 min | CPU > 85% |
| ☀️ Relatório diário | Diário (8h) | Sempre |

Todos os alertas incluem **botões de ação** (Limpar / Restart / Analisar com IA / Ignorar).

---

## ⚙️ Configuração (.env)

```env
TELEGRAM_BOT_TOKEN=...
GROQ_API_KEY=...
OWNER_TELEGRAM_ID=SEU_ID_AQUI

MEMORY_ALERT_THRESHOLD_MB=500
CPU_ALERT_THRESHOLD_PERCENT=85
MONITOR_INTERVAL_SECONDS=300
CRASH_CHECK_INTERVAL_SECONDS=120
DAILY_REPORT_HOUR=8
```