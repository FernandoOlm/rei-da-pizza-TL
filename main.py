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
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:5173").rstrip("/")
REI_DA_PIZZA_API_TOKEN = os.getenv("REI_DA_PIZZA_API_TOKEN")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Estados da conversa
ASK_NAME, ASK_AMOUNT, ASK_DATE, ASK_CATEGORY, ASK_COST_CENTER = range(5)

def build_headers():
    return {
        "Authorization": f"Bearer {REI_DA_PIZZA_API_TOKEN}",
        "X-Telegram-Api-Token": REI_DA_PIZZA_API_TOKEN,
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
    
    logger.info(f"Usuário {user_id} acessou o menu principal.")
    
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
    
    # Mapear a ação para o período
    period = "month"
    if action == "report_week":
        period = "week"
    elif action == "report_summary":
        period = "custom"
        
    logger.info(f"Usuário {user_id} solicitou relatório: {action}. Fazendo GET para summary com period={period}")
    try:
        params = {"telegram_user_id": user_id, "period": period}
        if period == "custom":
            params["start_date"] = "2000-01-01"
            params["end_date"] = "2100-01-01"
            
        response = requests.get(
            f"{API_BASE_URL}/api/public/telegram/summary",
            headers=build_headers(),
            params=params
        )
        logger.info(f"API retornou status {response.status_code} para {action}.")
        
        if not response.ok:
            err_text = response.text[:200]
            logger.error(f"Erro na API ({action}): {err_text}")
            await query.edit_message_text(f"❌ Erro API ({response.status_code}): {err_text}")
            return
            
        data = response.json()["data"]
        
        start_date = data.get("start_date", "")
        end_date = data.get("end_date", "")
        
        # Formatar datas para exibição (YYYY-MM-DD -> DD/MM/YYYY)
        def fmt_date(d_str):
            if len(d_str) == 10:
                parts = d_str.split('-')
                return f"{parts[2]}/{parts[1]}/{parts[0]}"
            return d_str
            
        if action == "report_summary":
            title = "📊 *Resumo Geral (Todo o período)*"
            date_str = ""
        elif action == "report_month":
            title = "📊 *Resumo do Mês*"
            date_str = f"_{fmt_date(start_date)} a {fmt_date(end_date)}_\n\n"
        else:
            title = "📊 *Resumo da Semana*"
            date_str = f"_{fmt_date(start_date)} a {fmt_date(end_date)}_\n\n"
            
        total_paid = data.get('total_paid', 0)
        total_received = data.get('total_received', 0)
        balance = data.get('balance', 0)
        pending_payables = data.get('pending_payables', 0)
        pending_receivables = data.get('pending_receivables', 0)
        
        msg = f"{title}\n{date_str}"
        
        if action in ["report_month", "report_week"]:
            msg += (
                f"🟢 *Recebido*: R$ {total_received:.2f}\n"
                f"🔴 *Pago*: R$ {total_paid:.2f}\n"
                f"💰 *Saldo do Período*: R$ {balance:.2f}\n\n"
            )
            
        msg += (
            f"⏳ *Pendente a Receber*: R$ {pending_receivables:.2f}\n"
            f"⏳ *Pendente a Pagar*: R$ {pending_payables:.2f}"
        )

        keyboard = [[InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="back_to_menu")]]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Falha de comunicação no {action}: {e}", exc_info=True)
        await query.edit_message_text(f"❌ Falha de comunicação: {e}")

# --- FLUXO DE CONVERSA: PAGAR / RECEBER ---
async def start_transaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    action = query.data # "start_payable" ou "start_receivable"
    context.user_data['action_type'] = action
    
    tipo_nome = "fornecedor" if action == "start_payable" else "cliente"
    
    logger.info(f"Usuário iniciou fluxo de transação: {action}. Perguntando nome do {tipo_nome}.")
    await query.edit_message_text(f"📝 Qual é o nome do *{tipo_nome}*?\n_(Digite no chat ou envie /cancelar para desistir)_", parse_mode="Markdown")
    return ASK_NAME

async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "/cancelar":
        logger.info("Usuário cancelou no passo ASK_NAME.")
        await update.message.reply_text("Operação cancelada.")
        await start_or_menu(update, context)
        return ConversationHandler.END
        
    context.user_data['name'] = text
    logger.info(f"Nome recebido: {text}. Perguntando valor.")
    await update.message.reply_text("💰 Qual o *valor*?\n_(Exemplo: 250.50)_\n\n_(Ou envie /cancelar)_", parse_mode="Markdown")
    return ASK_AMOUNT

async def ask_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "/cancelar":
        logger.info("Usuário cancelou no passo ASK_AMOUNT.")
        await update.message.reply_text("Operação cancelada.")
        await start_or_menu(update, context)
        return ConversationHandler.END
        
    text = text.replace(',', '.')
    try:
        valor = float(text)
    except ValueError:
        logger.warning(f"Usuário enviou valor inválido: {text}")
        await update.message.reply_text("❌ Valor inválido. Por favor, digite apenas números, usando ponto ou vírgula (Ex: 100.50).")
        return ASK_AMOUNT
        
    try:
        context.user_data['amount'] = valor
        logger.info(f"Valor recebido: {valor}. Perguntando data.")
        
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
    except Exception as e:
        import traceback
        err_msg = f"❌ CRITICAL ERROR in ask_amount:\n{e}\n{traceback.format_exc()}"
        logger.error(err_msg)
        await update.message.reply_text(err_msg)
        return ConversationHandler.END

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
    
    keyboard = []
    
    try:
        # Extraímos das transações históricas já que não temos rota dedicada
        params = {"telegram_user_id": user_id, "limit": 1000}
        payables_resp = requests.get(f"{API_BASE_URL}/api/public/telegram/payables", headers=build_headers(), params=params)
        receivables_resp = requests.get(f"{API_BASE_URL}/api/public/telegram/receivables", headers=build_headers(), params=params)
        
        categories = set()
        action_type = context.user_data.get('action_type')
        
        # Se for pagar, pega as categorias de despesas antigas. Se for receber, pega de receitas antigas.
        if action_type == "start_payable" and payables_resp.ok:
            for item in payables_resp.json().get("data", []):
                if item.get("category"):
                    categories.add(item.get("category"))
        elif action_type == "start_receivable" and receivables_resp.ok:
            for item in receivables_resp.json().get("data", []):
                if item.get("category"):
                    categories.add(item.get("category"))
                    
        if categories:
            row = []
            for cat_name in sorted(list(categories)):
                row.append(InlineKeyboardButton(cat_name, callback_data=f"cat_{cat_name[:40]}"))
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
    except Exception as e:
        logger.warning(f"Erro ao buscar categorias: {e}")

    keyboard.append([InlineKeyboardButton("⏭️ Pular Categoria", callback_data="skip_category")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await msg_func("📂 Qual a *Categoria* dessa transação? (Selecione abaixo ou digite o nome)\n_(Ou clique em pular)_", reply_markup=reply_markup, parse_mode="Markdown")
    return ASK_CATEGORY

async def ask_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        data = update.callback_query.data
        if data == "skip_category":
            context.user_data['category'] = None
        else:
            context.user_data['category'] = data.replace("cat_", "", 1)
        user_id = update.effective_user.id
        msg_func = update.callback_query.edit_message_text
    else:
        text = update.message.text
        if text == "/cancelar":
            await update.message.reply_text("Operação cancelada.")
            await start_or_menu(update, context)
            return ConversationHandler.END
        context.user_data['category'] = text
        user_id = update.effective_user.id
        msg_func = update.message.reply_text
        
    keyboard = []
    
    try:
        params = {"telegram_user_id": user_id, "limit": 1000}
        payables_resp = requests.get(f"{API_BASE_URL}/api/public/telegram/payables", headers=build_headers(), params=params)
        receivables_resp = requests.get(f"{API_BASE_URL}/api/public/telegram/receivables", headers=build_headers(), params=params)
        
        cost_centers = set()
        if payables_resp.ok:
            for item in payables_resp.json().get("data", []):
                if item.get("cost_center"):
                    cost_centers.add(item.get("cost_center"))
        if receivables_resp.ok:
            for item in receivables_resp.json().get("data", []):
                if item.get("cost_center"):
                    cost_centers.add(item.get("cost_center"))
                    
        if cost_centers:
            row = []
            for cc_name in sorted(list(cost_centers)):
                row.append(InlineKeyboardButton(cc_name, callback_data=f"cc_{cc_name[:40]}"))
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
    except Exception as e:
        logger.warning(f"Erro ao buscar centros de custo: {e}")

    keyboard.append([InlineKeyboardButton("⏭️ Pular Centro de Custo", callback_data="skip_cost_center")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await msg_func("🏢 Qual o *Centro de Custo*? (Selecione abaixo ou digite o nome)\n_(Ou clique em pular)_", reply_markup=reply_markup, parse_mode="Markdown")
    return ASK_COST_CENTER

async def process_transaction_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        data = update.callback_query.data
        if data == "skip_cost_center":
            context.user_data['cost_center'] = None
        else:
            context.user_data['cost_center'] = data.replace("cc_", "", 1)
        msg_func = update.callback_query.edit_message_text
        user_id = update.effective_user.id
    else:
        text = update.message.text
        if text == "/cancelar":
            await update.message.reply_text("Operação cancelada.")
            await start_or_menu(update, context)
            return ConversationHandler.END
        context.user_data['cost_center'] = text
        msg_func = update.message.reply_text
        user_id = update.effective_user.id

    action_type = context.user_data['action_type']
    name = context.user_data['name']
    amount = context.user_data['amount']
    vencimento = context.user_data['date']
    category = context.user_data.get('category')
    cost_center = context.user_data.get('cost_center')
    
    endpoint = "payables" if action_type == "start_payable" else "receivables"
    payload = {
        "telegram_user_id": str(user_id),
        "amount": amount,
        "due_date": vencimento
    }
    if category:
        payload["category"] = category
    if cost_center:
        payload["cost_center"] = cost_center
        
    extra_info = ""
    if category: extra_info += f"\nCategoria: {category}"
    if cost_center: extra_info += f"\nCentro de Custo: {cost_center}"
    
    if action_type == "start_payable":
        payload["supplier"] = name
        success_msg = f"✅ *Despesa registrada!*\nFornecedor: {name}\nValor: R$ {amount:.2f}\nVencimento: {vencimento}{extra_info}"
    else:
        payload["customer"] = name
        success_msg = f"✅ *Receita registrada!*\nCliente: {name}\nValor: R$ {amount:.2f}\nVencimento: {vencimento}{extra_info}"

    logger.info(f"Enviando POST para {API_BASE_URL}/api/public/telegram/{endpoint} com payload: {payload}")

    try:
        response = requests.post(
            f"{API_BASE_URL}/api/public/telegram/{endpoint}",
            headers=build_headers(),
            json=payload
        )
        logger.info(f"API retornou status {response.status_code} para registro de transação.")
        
        if response.ok:
            data = response.json().get("data", {})
            warnings = ""
            if category and data.get("category_id") is None:
                warnings += f"\n\n⚠️ *Aviso*: A categoria '{category}' não existe no sistema e foi ignorada (ficou vazia)."
            if cost_center and data.get("cost_center_id") is None:
                warnings += f"\n\n⚠️ *Aviso*: O centro de custo '{cost_center}' não existe no sistema e foi ignorado (ficou vazio)."
                
            final_msg = success_msg + warnings
            keyboard = [[InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="back_to_menu")]]
            await msg_func(final_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            logger.info("Transação finalizada com sucesso.")
        else:
            err = response.text[:200]
            logger.error(f"Erro retornado pela API: {err}")
            await msg_func(f"❌ *Erro na API*: {err}", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Erro de Comunicação na transação: {e}", exc_info=True)
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
        logger.error("Faltam configurações no arquivo .env")
        print("❌ ERRO: Faltam configurações no arquivo .env")
        return
        
    logger.info("Iniciando construção da aplicação do bot...")
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
            ASK_CATEGORY: [
                CallbackQueryHandler(ask_category, pattern="^(skip_category|cat_.*)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_category)
            ],
            ASK_COST_CENTER: [
                CallbackQueryHandler(process_transaction_final, pattern="^(skip_cost_center|cc_.*)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_transaction_final)
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
    
    logger.info("Bot interativo iniciado e aguardando comandos...")
    print("🤖 Bot interativo iniciado e aguardando comandos...")
    application.run_polling()

if __name__ == '__main__':
    main()
