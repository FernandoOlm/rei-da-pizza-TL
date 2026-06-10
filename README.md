# 🍕 Bot Financeiro - Rei da Pizza (Telegram)

Este é o bot do Telegram que se integra à API do **Finance-flow-hub** (Rei da Pizza). Ele permite que administradores autorizados consultem o saldo e registrem novas despesas e receitas diretamente pelo Telegram.

## 🚀 Deploy no VPS (Linux)

### 1. Clonar o repositório
```bash
git clone https://github.com/FernandoOlm/rei-da-pizza-TL.git
cd rei-da-pizza-TL
```

### 2. Criar ambiente virtual e instalar dependências
Recomenda-se usar um ambiente virtual (venv) para evitar conflitos de dependências no seu servidor.
```bash
# Criar o ambiente virtual (venv)
python3 -m venv venv

# Ativar o ambiente virtual
source venv/bin/activate

# Instalar as bibliotecas necessárias
pip install -r requirements.txt
```

### 3. Configurar variáveis de ambiente
Crie o arquivo `.env` baseado no arquivo de exemplo e preencha com as suas chaves.
```bash
cp .env.example .env
nano .env
```

Edite o arquivo `.env` para ficar assim:
```env
TELEGRAM_BOT_TOKEN="O token gerado pelo @BotFather"
REI_DA_PIZZA_API_TOKEN="O token gerado no painel 'Bots Telegram' do seu sistema web"
API_BASE_URL="http://IP_DO_SEU_SERVIDOR_WEB:PORTA" # Ex: https://sua-api.com ou http://localhost:5173
```

> **⚠️ IMPORTANTE:** Após configurar os tokens, lembre-se de ir até o painel web (Rei da Pizza) na página `/telegram` e **adicionar o seu Telegram ID** como um Usuário Autorizado, concedendo permissões de Leitura e Escrita. Para descobrir seu Telegram ID, envie uma mensagem para `@userinfobot`.

### 4. Rodar o Bot em Background
Você pode rodar o bot usando o **PM2** (se já o tiver instalado no servidor) para garantir que ele reinicie automaticamente caso o servidor caia.

**Se tiver o PM2 instalado:**
```bash
# Iniciar o bot pelo PM2 usando o python do ambiente virtual
pm2 start ./venv/bin/python --name rei-da-pizza-bot -- main.py

# Salvar o bot na lista de inicialização
pm2 save

# Ver os logs
pm2 logs rei-da-pizza-bot
```

**Se não tiver o PM2 (Usando nohup):**
```bash
nohup ./venv/bin/python main.py > bot_output.log 2>&1 &
```

---

## 📋 Comandos Disponíveis no Telegram

| Comando | Formato | Descrição | Permissão Exigida |
|---|---|---|---|
| `/saldo` | `/saldo` | Mostra um resumo do saldo a pagar/receber e os valores atrasados. | **Leitura** |
| `/pagar` | `/pagar <fornecedor> <valor> <YYYY-MM-DD>` | Lança uma nova conta a pagar pendente. | **Escrita** |
| `/receber` | `/receber <cliente> <valor> <YYYY-MM-DD>` | Lança uma nova conta a receber pendente. | **Escrita** |

*Exemplos práticos:*
- `/pagar Mercado 250.50 2026-06-20`
- `/receber Joao 150.00 2026-06-21`