import os
import logging
import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

load_dotenv()

# Configurações
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:5173") # URL do Finance-flow-hub
REI_DA_PIZZA_API_TOKEN = os.getenv("REI_DA_PIZZA_API_TOKEN") # O token gerado no painel da empresa

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

def build_headers():
    return {
        "Authorization": f"Bearer {REI_DA_PIZZA_API_TOKEN}",
        "Content-Type": "application/json"
    }

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(
        f"Olá! Eu sou o assistente financeiro do Rei da Pizza.\n"
        f"Seu Telegram ID é: {user_id}\n\n"
        f"Comandos disponíveis:\n"
        f"/saldo - Ver resumo financeiro do mês\n"
        f"/pagar <fornecedor> <valor> <vencimento_YYYY-MM-DD> - Nova conta a pagar\n"
        f"/receber <cliente> <valor> <vencimento_YYYY-MM-DD> - Nova conta a receber"
    )

async def saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    try:
        response = requests.get(
            f"{API_BASE_URL}/api/public/telegram/summary",
            headers=build_headers(),
            params={"telegram_user_id": user_id}
        )
        data = response.json()
        
        if not response.ok:
            error_msg = data.get("error", "Erro desconhecido")
            await update.message.reply_text(f"❌ Erro ao consultar saldo: {error_msg}")
            return
            
        summary = data["data"]
        msg = (
            f"📊 **Resumo Financeiro**\n\n"
            f"🔴 A Pagar: R$ {summary['total_payable_pending']:.2f} "
            f"(Atrasado: R$ {summary['overdue_payable']:.2f})\n"
            f"🟢 A Receber: R$ {summary['total_receivable_pending']:.2f} "
            f"(Atrasado: R$ {summary['overdue_receivable']:.2f})"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
        
    except Exception as e:
        await update.message.reply_text(f"Erro de comunicação com o servidor: {e}")

async def pagar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    
    if len(args) < 3:
        await update.message.reply_text("Uso correto: /pagar <fornecedor> <valor> <vencimento_YYYY-MM-DD>\nEx: /pagar Mercado 250.50 2026-06-20")
        return
        
    fornecedor = args[0]
    try:
        valor = float(args[1])
    except ValueError:
        await update.message.reply_text("Valor inválido. Use formato 100.50")
        return
    vencimento = args[2]
    
    try:
        response = requests.post(
            f"{API_BASE_URL}/api/public/telegram/payables",
            headers=build_headers(),
            json={
                "telegram_user_id": str(user_id),
                "supplier": fornecedor,
                "amount": valor,
                "due_date": vencimento
            }
        )
        data = response.json()
        
        if not response.ok:
            error_msg = data.get("error", "Erro desconhecido")
            await update.message.reply_text(f"❌ Erro ao registrar despesa: {error_msg}")
            return
            
        await update.message.reply_text(f"✅ Conta a pagar registrada com sucesso!\nFornecedor: {fornecedor}\nValor: R$ {valor:.2f}\nVencimento: {vencimento}")
        
    except Exception as e:
        await update.message.reply_text(f"Erro de comunicação com o servidor: {e}")

async def receber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    
    if len(args) < 3:
        await update.message.reply_text("Uso correto: /receber <cliente> <valor> <vencimento_YYYY-MM-DD>\nEx: /receber João 150.00 2026-06-20")
        return
        
    cliente = args[0]
    try:
        valor = float(args[1])
    except ValueError:
        await update.message.reply_text("Valor inválido. Use formato 100.50")
        return
    vencimento = args[2]
    
    try:
        response = requests.post(
            f"{API_BASE_URL}/api/public/telegram/receivables",
            headers=build_headers(),
            json={
                "telegram_user_id": str(user_id),
                "customer": cliente,
                "amount": valor,
                "due_date": vencimento
            }
        )
        data = response.json()
        
        if not response.ok:
            error_msg = data.get("error", "Erro desconhecido")
            await update.message.reply_text(f"❌ Erro ao registrar recebimento: {error_msg}")
            return
            
        await update.message.reply_text(f"✅ Conta a receber registrada com sucesso!\nCliente: {cliente}\nValor: R$ {valor:.2f}\nVencimento: {vencimento}")
        
    except Exception as e:
        await update.message.reply_text(f"Erro de comunicação com o servidor: {e}")


def main():
    if not TELEGRAM_BOT_TOKEN or not REI_DA_PIZZA_API_TOKEN:
        print("❌ ERRO: Faltam configurações no arquivo .env (TELEGRAM_BOT_TOKEN e/ou REI_DA_PIZZA_API_TOKEN)")
        return
        
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("saldo", saldo))
    application.add_handler(CommandHandler("pagar", pagar))
    application.add_handler(CommandHandler("receber", receber))
    
    print("🤖 Bot iniciado e aguardando comandos...")
    application.run_polling()

if __name__ == '__main__':
    main()
