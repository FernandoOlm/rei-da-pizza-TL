"""Setup do Application Telegram — registra handlers e configurações."""
import warnings
from telegram.warnings import PTBUserWarning

# Silencia o aviso PTBUserWarning sobre per_message=False ao usar CallbackQueryHandler em ConversationHandler
warnings.filterwarnings("ignore", category=PTBUserWarning)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
)

from config import TELEGRAM_BOT_TOKEN
from handlers import commands, callbacks, messages
from core.scheduler import register_jobs
from utils.logger import get_logger

log = get_logger(__name__)


async def post_init(application: Application) -> None:
    """Configurações adicionais executadas após inicializar o bot (ex: registrar comandos)."""
    from telegram import BotCommand
    
    bot_commands = [
        BotCommand("status", "Dashboard completo do VPS"),
        BotCommand("processos", "Lista processos PM2"),
        BotCommand("memoria", "Análise de memória"),
        BotCommand("logs", "Ver logs de um processo"),
        BotCommand("restart", "Reiniciar processo"),
        BotCommand("stop", "Parar processo"),
        BotCommand("limpar", "Limpar logs de processo"),
        BotCommand("criar_imagem", "Gera imagem com Gemini Imagen"),
        BotCommand("myid", "Ver seu Telegram ID"),
        BotCommand("novobot", "Deploy de novo bot na VPS"),
        BotCommand("buscargit", "Mapeia e clona repositórios do seu GitHub"),
        BotCommand("novoprojeto", "Clone de template do GitHub"),
        BotCommand("gitconect", "Configurar Token do GitHub"),
        BotCommand("projetos", "Gerenciar pastas e projetos na VPS"),
        BotCommand("ajuda", "Exibe menu de ajuda"),
    ]
    
    try:
        await application.bot.set_my_commands(bot_commands)
        log.info("✅ Comandos do bot registrados com sucesso no Telegram (estilo BotFather)!")
    except Exception as e:
        log.error(f"❌ Erro ao registrar comandos no Telegram: {e}")


def build_app() -> Application:
    """Constrói e configura o Application do python-telegram-bot."""
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # ─── Comandos ─────────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start",     commands.cmd_start))
    app.add_handler(CommandHandler("ajuda",     commands.cmd_ajuda))
    app.add_handler(CommandHandler("myid",      commands.cmd_myid))
    app.add_handler(CommandHandler("status",    commands.cmd_status))
    app.add_handler(CommandHandler("processos", commands.cmd_processos))
    app.add_handler(CommandHandler("memoria",   commands.cmd_memoria))
    app.add_handler(CommandHandler("logs",      commands.cmd_logs))
    app.add_handler(CommandHandler("restart",   commands.cmd_restart))
    app.add_handler(CommandHandler("stop",      commands.cmd_stop))
    app.add_handler(CommandHandler("limpar",    commands.cmd_limpar))
    app.add_handler(CommandHandler("criar_imagem",   commands.cmd_criar_imagem))
    app.add_handler(CommandHandler("projetos",   commands.cmd_projetos))

    # ─── /novobot — Deploy guiado de novo bot ──────────────────────────────────
    novobot_conv = ConversationHandler(
        entry_points=[
            CommandHandler("novobot", commands.cmd_novobot),
            CallbackQueryHandler(commands.cmd_novobot_cb, pattern="^menu:novobot$"),
            CommandHandler("novobot_exclusivo", commands.cmd_novobot_exclusivo),
            CallbackQueryHandler(commands.cmd_novobot_exclusivo_cb, pattern="^menu:novobot_exclusivo$")
        ],
        states={
            commands.AGUARDANDO_GIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, commands.novobot_recebe_git),
            ],
            commands.AGUARDANDO_PM2_CONFIRM: [
                CallbackQueryHandler(commands.novobot_recebe_pm2, pattern="^pm2_confirm:")
            ]
        },
        fallbacks=[CommandHandler("cancelar", commands.novobot_cancelar)],
        allow_reentry=True,
    )
    app.add_handler(novobot_conv)

    # ─── /buscargit — Busca e deploy de repositórios do GitHub ──────────────────
    buscargit_conv = ConversationHandler(
        entry_points=[
            CommandHandler("buscargit", commands.cmd_buscargit),
            CallbackQueryHandler(commands.cmd_buscargit_cb, pattern="^menu:buscargit$")
        ],
        states={
            commands.AGUARDANDO_GIT_SELECT: [
                CallbackQueryHandler(commands.buscargit_select, pattern="^gitlist:")
            ],
            commands.AGUARDANDO_PM2_CONFIRM: [
                CallbackQueryHandler(commands.novobot_recebe_pm2, pattern="^pm2_confirm:")
            ]
        },
        fallbacks=[
            CommandHandler("cancelar", commands.novobot_cancelar),
            CallbackQueryHandler(commands.novobot_cancelar, pattern="^novobot_cancelar$")
        ],
        allow_reentry=True,
    )
    app.add_handler(buscargit_conv)

    # ─── /novoprojeto — Criação de novo projeto a partir de template ────────────
    novoprojeto_conv = ConversationHandler(
        entry_points=[
            CommandHandler("novoprojeto", commands.cmd_novoprojeto),
            CallbackQueryHandler(commands.cmd_novoprojeto_cb, pattern="^menu:novoprojeto$")
        ],
        states={
            commands.AGUARDANDO_TEMPLATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, commands.novoprojeto_recebe_template),
            ],
            commands.AGUARDANDO_NOME_PROJETO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, commands.novoprojeto_recebe_nome),
            ],
        },
        fallbacks=[CommandHandler("cancelar", commands.novobot_cancelar)],
        allow_reentry=True,
    )
    app.add_handler(novoprojeto_conv)

    # ─── /gitconect — Configuração do Token do GitHub ───────────────────────────
    gitconect_conv = ConversationHandler(
        entry_points=[
            CommandHandler("gitconect", commands.cmd_gitconect),
            CallbackQueryHandler(commands.cmd_gitconect_cb, pattern="^menu:gitconect$")
        ],
        states={
            commands.AGUARDANDO_GITHUB_TOKEN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, commands.gitconect_recebe_token),
            ],
        },
        fallbacks=[CommandHandler("cancelar", commands.novobot_cancelar)],
        allow_reentry=True,
    )
    app.add_handler(gitconect_conv)

    # ─── Callbacks de botões inline ───────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(callbacks.handle_callback))

    # ─── Mensagens de texto livre → IA ────────────────────────────────────────
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, messages.handle_message))

    # ─── Jobs agendados ───────────────────────────────────────────────────────
    register_jobs(app)

    log.info("✅ Bot configurado com todos os handlers e jobs registrados")
    return app
