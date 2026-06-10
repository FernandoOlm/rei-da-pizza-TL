"""Entrypoint principal do Ferdinando Monitor Bot."""
import asyncio
import sys
from core.bot import build_app
from config import TELEGRAM_BOT_TOKEN, OWNER_TELEGRAM_ID, GEMINI_API_KEY
from utils.logger import get_logger

log = get_logger(__name__)


def validate_config():
    """Valida configurações obrigatórias antes de iniciar."""
    errors = []

    if not TELEGRAM_BOT_TOKEN:
        errors.append("❌ TELEGRAM_BOT_TOKEN não configurado no .env")

    if not GEMINI_API_KEY:
        errors.append("❌ GEMINI_API_KEY não configurado no .env")

    if OWNER_TELEGRAM_ID == 0:
        log.warning(
            "⚠️  OWNER_TELEGRAM_ID = 0 — Bot iniciará em modo de configuração.\n"
            "   Envie qualquer mensagem para o bot para descobrir seu Telegram ID.\n"
            "   Após configurar, reinicie o bot."
        )

    if errors:
        for e in errors:
            print(e)
        sys.exit(1)


def main():
    validate_config()

    log.info("=" * 50)
    log.info("🤖 Ferdinando Monitor Bot iniciando...")
    log.info(f"   Owner ID  : {OWNER_TELEGRAM_ID or 'NÃO CONFIGURADO'}")
    log.info(f"   Mem Alert : {__import__('config').MEMORY_ALERT_THRESHOLD_MB} MB")
    log.info(f"   Intervalo : {__import__('config').MONITOR_INTERVAL_SECONDS}s")
    log.info("=" * 50)

    app = build_app()

    log.info("✅ Bot online! Aguardando mensagens...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
