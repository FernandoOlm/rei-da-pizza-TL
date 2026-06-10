"""Handler de mensagens de texto livre — processadas pela IA com contexto do VPS."""
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from core.auth import is_owner
from services import pm2, system, gemini_ai
from config import OWNER_TELEGRAM_ID
from utils.logger import get_logger

log = get_logger(__name__)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Processa mensagens de texto livre.
    
    Fluxo:
    1. Bloqueia silenciosamente não-donos
    2. Caso especial: se OWNER_ID ainda não configurado (=0), /myid funciona
    3. Coleta contexto do VPS em tempo real
    4. Envia para IA com contexto completo
    """
    user = update.effective_user
    message = update.message

    if user is None or message is None:
        return

    # Bloqueio silencioso — não responde para estranhos
    if user.id != OWNER_TELEGRAM_ID:
        # Caso especial: owner ainda não configurou o ID
        if OWNER_TELEGRAM_ID == 0:
            await message.reply_text(
                f"⚠️ *Bot não configurado!*\n\n"
                f"Seu Telegram ID é: `{user.id}`\n\n"
                f"Adicione ao `.env`:\n`OWNER_TELEGRAM_ID={user.id}`\n\n"
                f"Depois reinicie o bot com `pm2 restart monit-bot`",
                parse_mode=ParseMode.MARKDOWN,
            )
        return  # Silêncio total para outros

    text = message.text or ""
    if not text.strip():
        return

    log.info(f"Mensagem livre: '{text[:80]}'")
    typing_msg = await message.reply_text("🤔 Deixa eu pensar, chefe...")

    # Coleta contexto atual do VPS para enriquecer a resposta da IA
    try:
        processes = pm2.get_processes()
        sys_info = system.get_system_info()
        vps_context = {
            "processos_pm2": processes,
            "sistema": sys_info,
        }
    except Exception as e:
        log.warning(f"Erro ao coletar contexto VPS para IA: {e}")
        vps_context = None

    response = await gemini_ai.ask_ai(text, vps_context=vps_context)

    if len(response) > 4000:
        response = response[:4000] + "\n\n_[Resposta truncada]_"

    await typing_msg.edit_text(response, parse_mode=ParseMode.MARKDOWN)
