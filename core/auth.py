"""Autenticação — garante que apenas o dono do VPS interage com o bot."""
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes
from config import OWNER_TELEGRAM_ID
from utils.logger import get_logger

log = get_logger(__name__)


def owner_only(func):
    """Decorator que bloqueia silenciosamente qualquer não-dono."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if user is None or user.id != OWNER_TELEGRAM_ID:
            if user:
                log.warning(f"Acesso negado: user_id={user.id} username={user.username}")
            return  # Silêncio total — sem resposta para intrusos
        return await func(update, context, *args, **kwargs)
    return wrapper


def is_owner(user_id: int) -> bool:
    return user_id == OWNER_TELEGRAM_ID
