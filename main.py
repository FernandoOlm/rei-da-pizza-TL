import os
import logging
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:5173")
REI_DA_PIZZA_API_TOKEN = os.getenv("REI_DA_PIZZA_API_TOKEN")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Estados da conversa
ASK_NAME, ASK_AMOUNT, ASK_DATE = range(3)

def build_headers():
    return {
        "Authorization": f"Bearer {REI_DA_PIZZA_API_TOKEN}",
        "Content-Type": "application/json"
    }

# --- MENU PRINCIPAL ---
async def start_or_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = [
        [
            InlineKeyboardButton("💸 Nova Despesa (Pagar)", callback_data="start_payable"),
            InlineKeyboardButton("💰 Nova Receita (Receber)", callback_data="start_receivable"),
        ],
        [
            InlineKeyboardButton("📊 Relatórios Financeiros", callback_data="menu_reports")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    msg = (
        f"🍕 *Painel Financeiro - Rei da Pizza*\n"
        f"ID: `{user_id}`\n\n"
        f"Selecione uma opção abaixo:"
    )
    
    if update.message:
        await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.callback_query.edit_message_text(msg, reply_markup=reply_markup, parse_mode="Markdown")

# --- RELATÓRIOS ---
async def menu_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("Resumo Geral (Pendente/Atrasado)", callback_data="report_summary")],
        [InlineKeyboardButton("Resumo do Mês", callback_data="report_month")],
        [InlineKeyboardButton("Resumo da Semana", callback_data="report_week")],
        [InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="back_to_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("📈 *Relatórios Disponíveis*\nSelecione o tipo de resumo:", reply_markup=reply_markup, parse_mode="Markdown")

async def report_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    action = query.data
    user_id = update.effective_user.id
    
    if action == "report_summary":
        try:
            response = requests.get(
                f"{API_BASE_URL}/api/public/telegram/summary",
                headers=build_headers(),
                params={"telegram_user_id": user_id}
            )
            if not response.ok:
                await query.edit_message_text(f"❌ Erro ao consultar a API. Confirme no Lovable se as rotas de servidor estão rodando.")
                return
                
            data = response.json()["data"]
            msg = (
                f"📊 *Resumo Geral (Em Aberto)*\n\n"
                f"🔴 A Pagar: R$ {data['total_payable_pending']:.2f} "
                f"(Atrasado: R$ {data['overdue_payable']:.2f})\n"
                f"🟢 A Receber: R$ {data['total_receivable_pending']:.2f} "
                f"(Atrasado: R$ {data['overdue_receivable']:.2f})"
            )
            keyboard = [[InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="back_to_menu")]]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        except Exception as e:
            await query.edit_message_text(f"❌ Falha de comunicação: {e}")
            
    elif action in ["report_month", "report_week"]:
        msg = (
            "🚧 *Recurso em Construção no Lovable*\n\n"
            "Atualmente, a API suporta apenas o Resumo Geral de tudo que está pendente.\n"
            "Um endpoint para Fluxo de Caixa Mensal/Semanal precisa ser criado no seu painel web."
        )
        keyboard = [[InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="back_to_menu")]]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# --- FLUXO DE CONVERSA: PAGAR / RECEBER ---
async def start_transaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    action = query.data # "start_payable" ou "start_receivable"
    context.user_data['action_type'] = action
    
    tipo_nome = "fornecedor" if action == "start_payable" else "cliente"
    
    await query.edit_message_text(f"📝 Qual é o nome do *{tipo_nome}*?\n_(Digite no chat ou envie /cancelar para desistir)_", parse_mode="Markdown")
    return ASK_NAME

async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "/cancelar":
        await update.message.reply_text("Operação cancelada.")
        await start_or_menu(update, context)
        return ConversationHandler.END
        
    context.user_data['name'] = text
    await update.message.reply_text("💰 Qual o *valor*?\n_(Exemplo: 250.50)_\n\n_(Ou envie /cancelar)_", parse_mode="Markdown")
    return ASK_AMOUNT

async def ask_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "/cancelar":
        await update.message.reply_text("Operação cancelada.")
        await start_or_menu(update, context)
        return ConversationHandler.END
        
    text = text.replace(',', '.')
    try:
        valor = float(text)
    except ValueError:
        await update.message.reply_text("❌ Valor inválido. Por favor, digite apenas números, usando ponto ou vírgula (Ex: 100.50).")
        return ASK_AMOUNT
        
    context.user_data['amount'] = valor
    
    hoje = datetime.now()
    amanha = hoje + timedelta(days=1)
    semana_q_vem = hoje + timedelta(days=7)
    
    keyboard = [
        [
            InlineKeyboardButton(f"Hoje ({hoje.strftime('%d/%m')})", callback_data=hoje.strftime("%Y-%m-%d")),
            InlineKeyboardButton(f"Amanhã ({amanha.strftime('%d/%m')})", callback_data=amanha.strftime("%Y-%m-%d")),
        ],
        [
            InlineKeyboardButton(f"Daqui a 7 dias ({semana_q_vem.strftime('%d/%m')})", callback_data=semana_q_vem.strftime("%Y-%m-%d"))
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text("📅 Selecione a *data de vencimento* nos botões abaixo ou digite no formato AAAA-MM-DD:", reply_markup=reply_markup, parse_mode="Markdown")
    return ASK_DATE

async def process_transaction_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Pode vir de um clique no botão ou texto digitado
    if update.callback_query:
        await update.callback_query.answer()
        vencimento = update.callback_query.data
        user_id = update.effective_user.id
        msg_func = update.callback_query.edit_message_text
    else:
        text = update.message.text
        if text == "/cancelar":
            await update.message.reply_text("Operação cancelada.")
            await start_or_menu(update, context)
            return ConversationHandler.END
        vencimento = text
        user_id = update.effective_user.id
        msg_func = update.message.reply_text
    
    context.user_data['date'] = vencimento
    
    action_type = context.user_data['action_type']
    name = context.user_data['name']
    amount = context.user_data['amount']
    
    endpoint = "payables" if action_type == "start_payable" else "receivables"
    payload = {
        "telegram_user_id": str(user_id),
        "amount": amount,
        "due_date": vencimento
    }
    
    if action_type == "start_payable":
        payload["supplier"] = name
        success_msg = f"✅ *Despesa registrada!*\nFornecedor: {name}\nValor: R$ {amount:.2f}\nVencimento: {vencimento}"
    else:
        payload["customer"] = name
        success_msg = f"✅ *Receita registrada!*\nCliente: {name}\nValor: R$ {amount:.2f}\nVencimento: {vencimento}"

    try:
        response = requests.post(
            f"{API_BASE_URL}/api/public/telegram/{endpoint}",
            headers=build_headers(),
            json=payload
        )
        if response.ok:
            keyboard = [[InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="back_to_menu")]]
            await msg_func(success_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            err = response.json().get("error", "Erro da API")
            await msg_func(f"❌ *Erro na API*: {err}", parse_mode="Markdown")
    except Exception as e:
        await msg_func(f"❌ *Erro de Comunicação*: {e}", parse_mode="Markdown")

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operação cancelada.")
    await start_or_menu(update, context)
    return ConversationHandler.END

# --- HANDLER CALLBACK GENÉRICO ---
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "back_to_menu":
        await query.answer()
        await start_or_menu(update, context)

def main():
    if not TELEGRAM_BOT_TOKEN or not REI_DA_PIZZA_API_TOKEN:
        print("❌ ERRO: Faltam configurações no arquivo .env")
        return
        
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_transaction, pattern="^(start_payable|start_receivable)$")
        ],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_amount)],
            ASK_DATE: [
                CallbackQueryHandler(process_transaction_date, pattern=r"^\d{4}-\d{2}-\d{2}$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_transaction_date)
            ],
        },
        fallbacks=[CommandHandler("cancelar", cancel)]
    )

    application.add_handler(CommandHandler("start", start_or_menu))
    application.add_handler(CommandHandler("menu", start_or_menu))
    
    application.add_handler(conv_handler)
    
    application.add_handler(CallbackQueryHandler(menu_reports, pattern="^menu_reports$"))
    application.add_handler(CallbackQueryHandler(report_action, pattern="^report_"))
    application.add_handler(CallbackQueryHandler(callback_router, pattern="^back_to_menu$"))
    
    print("🤖 Bot interativo iniciado e aguardando comandos...")
    application.run_polling()

if __name__ == '__main__':
    main()
