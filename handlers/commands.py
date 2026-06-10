"""Handlers de comandos Telegram."""
import re
import asyncio
import io
import os
import subprocess

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

from core.auth import owner_only
from services import pm2, memory, system, gemini_ai
from utils.formatter import format_process_table, format_system_status
from config import OWNER_TELEGRAM_ID

# ─── Estados da ConversationHandler ───────────────────────────────────────────
AGUARDANDO_GIT = 0
AGUARDANDO_TEMPLATE = 1
AGUARDANDO_NOME_PROJETO = 2
AGUARDANDO_GITHUB_TOKEN = 3
AGUARDANDO_PM2_CONFIRM = 4
AGUARDANDO_GIT_SELECT = 5


# ══════════════════════════════════════════════════════════════════════════════
#   Helpers: QR Code ASCII → Imagem PNG
# ══════════════════════════════════════════════════════════════════════════════

_ANSI_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
_PM2_PREFIX_RE = re.compile(
    r'^\s*\d+\|[\w_.-]+\s*\|\s*(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}:\s*)?'
)


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub('', text)


def _extract_qr_lines(log_text: str) -> list[str]:
    """
    Remove prefixos do PM2 e códigos ANSI, depois extrai o bloco
    de caracteres do QR Code (linhas com █, ▄, ▀).
    Garante extrair apenas o QR Code mais recente (o último nos logs).
    """
    qr_chars = set('█▄▀')
    lines = log_text.splitlines()
    
    # Processa de trás para frente para achar o QR Code mais recente
    reversed_lines = []
    in_qr = False
    blank_count = 0
    
    for raw_line in reversed(lines):
        line = _strip_ansi(raw_line)
        line = _PM2_PREFIX_RE.sub('', line)
        
        has_qr = any(c in line for c in qr_chars)
        
        if has_qr:
            in_qr = True
            blank_count = 0
            reversed_lines.append(line)
        elif in_qr:
            # Toleramos até 1 linha em branco dentro do bloco QR
            if line.strip() == '':
                blank_count += 1
                if blank_count <= 1:
                    reversed_lines.append(line)
                else:
                    break
            else:
                break
                
    # Como lemos de trás para frente, as linhas estão invertidas.
    # Colocamos na ordem correta (de cima para baixo)
    result = list(reversed(reversed_lines))
    return result


def _render_qr_image(qr_lines: list[str]) -> io.BytesIO | None:
    """
    Converte o bloco de block-chars (█▄▀) em PNG real.
    Cada char representa 2 linhas de pixel (half-block encoding).
    Retorna BytesIO com PNG, ou None em caso de falha.
    """
    # █ = preto/preto  ▄ = branco/preto  ▀ = preto/branco  ' '= branco/branco
    CHAR_MAP: dict[str, tuple[int, int]] = {
        '█': (1, 1),
        '▄': (0, 1),
        '▀': (1, 0),
        ' ': (0, 0),
    }

    # Remove linhas em branco no final
    while qr_lines and not qr_lines[-1].strip():
        qr_lines.pop()

    if not qr_lines:
        return None

    try:
        from PIL import Image
    except ImportError:
        return None

    # Monta grid de pixels (cada linha de QR gera 2 linhas de pixel)
    pixel_rows: list[list[int]] = []
    for line in qr_lines:
        top_row, bot_row = [], []
        for ch in line:
            top, bot = CHAR_MAP.get(ch, (0, 0))
            top_row.append(top)
            bot_row.append(bot)
        pixel_rows.append(top_row)
        pixel_rows.append(bot_row)

    height = len(pixel_rows)
    width  = max((len(r) for r in pixel_rows), default=0)

    if width == 0 or height == 0:
        return None

    scale = 12  # pixels por célula QR — ajusta o tamanho final da imagem

    img = Image.new('RGB', (width * scale, height * scale), (255, 255, 255))
    pixels = img.load()

    for y, row in enumerate(pixel_rows):
        for x, val in enumerate(row):
            color = (0, 0, 0) if val else (255, 255, 255)
            for dy in range(scale):
                for dx in range(scale):
                    pixels[x * scale + dx, y * scale + dy] = color

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf



def get_start_text() -> str:
    """Retorna o texto de apresentação do bot com a lista de comandos."""
    return (
        "👋 *Olá, chefe!* Sou o *Ferdinando Monitor*, seu estagiário de TI.\n\n"
        "Estou de olho no VPS pra você. Aqui está o que sei fazer:\n\n"
        "Seleciona uma opção abaixo ali\n"
        "ou /start para mandar novo menu"
    )


def get_main_keyboard() -> InlineKeyboardMarkup:
    """Gera o teclado inline do menu principal."""
    keyboard = [
        [
            InlineKeyboardButton("📊 Status VPS", callback_data="menu:status"),
            InlineKeyboardButton("⚙️ Processos PM2", callback_data="menu:processes"),
        ],
        [
            InlineKeyboardButton("🧠 Memória", callback_data="menu:memory"),
        ],
        [
            InlineKeyboardButton("📋 Ver Logs", callback_data="select:logs"),
            InlineKeyboardButton("🧹 Limpar Logs", callback_data="select:flush"),
        ],
        [
            InlineKeyboardButton("🔄 Reiniciar", callback_data="select:restart"),
            InlineKeyboardButton("🛑 Parar", callback_data="select:stop"),
        ],
        [
            InlineKeyboardButton("🚀 Novo Bot", callback_data="menu:novobot"),
            InlineKeyboardButton("🌟 Novo Bot Exclusivo", callback_data="menu:novobot_exclusivo"),
        ],
        [
            InlineKeyboardButton("🏗️ Novo Projeto", callback_data="menu:novoprojeto"),
        ],
        [
            InlineKeyboardButton("🔍 Buscar Git", callback_data="menu:buscargit"),
            InlineKeyboardButton("🔑 GitHub Token", callback_data="menu:gitconect"),
        ],
        [
            InlineKeyboardButton("📂 Projetos VPS", callback_data="menu:projetos"),
            InlineKeyboardButton("🖼️ Criar Imagem", callback_data="menu:criar_imagem"),
        ],
        [
            InlineKeyboardButton("🖼️ Criar Imagem", callback_data="menu:criar_imagem"),
            InlineKeyboardButton("🆔 Meu ID", callback_data="menu:myid"),
        ],
        [
            InlineKeyboardButton("❓ Ajuda", callback_data="menu:main"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


@owner_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Apresentação do estagiário com menu de botões."""
    import logging
    log_cmd = logging.getLogger(__name__)
    log_cmd.info(f"Start command received with args: {context.args}")
    
    # Trata parâmetros de deep-linking para sincronização de dados (ex: /start export_projeto)
    args = context.args
    if args:
        param = args[0]
        if param.startswith("export_"):
            folder = param.replace("export_", "")
            log_cmd.info(f"Iniciando exportação automática para a pasta: {folder}")
            await _processar_exportacao(update, context, folder)
            return

    import config
    warning = ""
    if not getattr(config, "GITHUB_TOKEN", ""):
        warning = (
            "⚠️ *Aviso de Configuração:*\n"
            "Você ainda não configurou o seu *GitHub Token* nesta VPS!\n"
            "Sem ele, você não conseguirá criar novos projetos a partir de repositórios privados.\n"
            "👉 Clique em '🔑 GitHub Token' abaixo ou use `/gitconect` para configurar agora.\n\n"
            "───────────────────\n\n"
        )
    text = warning + get_start_text()
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_keyboard())


@owner_only
async def cmd_novobot_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o fluxo de deploy de um novo bot via botão inline."""
    query = update.callback_query
    await query.answer()
    context.user_data["is_exclusivo"] = False
    import config
    warning = ""
    if not getattr(config, "GITHUB_TOKEN", ""):
        warning = (
            "⚠️ *Nota:* Você não tem um Token do GitHub configurado nesta VPS. "
            "Se o repositório for privado, o deploy falhará. Recomenda-se configurar usando `/gitconect` primeiro.\n\n"
        )
    await query.edit_message_text(
        f"{warning}🤖 *Novo Bot — Deploy Guiado*\n\n"
        "Me manda o comando `git clone` do repositório\n"
        "_(ex: git clone git@github.com:Ferdinandobot/meu-bot.git)_\n\n"
        "Ou /cancelar para abortar.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return AGUARDANDO_GIT


@owner_only
async def cmd_novobot_exclusivo_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o fluxo de deploy de um novo bot exclusivo via botão inline."""
    query = update.callback_query
    await query.answer()
    context.user_data["is_exclusivo"] = True
    import config
    warning = ""
    if not getattr(config, "GITHUB_TOKEN", ""):
        warning = (
            "⚠️ *Nota:* Você não tem um Token do GitHub configurado nesta VPS. "
            "Se o repositório for privado, o deploy falhará. Recomenda-se configurar usando `/gitconect` primeiro.\n\n"
        )
    await query.edit_message_text(
        f"{warning}🌟 *Novo Bot Exclusivo — Deploy Guiado*\n\n"
        "Me manda o comando `git clone` do repositório\n"
        "_(ex: git clone git@github.com:Ferdinandobot/meu-bot.git)_\n\n"
        "Ou /cancelar para abortar.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return AGUARDANDO_GIT


@owner_only
async def cmd_novoprojeto_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o fluxo para criar um novo projeto a partir de um template via botão inline."""
    query = update.callback_query
    await query.answer()
    import config
    warning = ""
    if not getattr(config, "GITHUB_TOKEN", ""):
        warning = (
            "⚠️ *Nota:* Você não tem um Token do GitHub configurado nesta VPS. "
            "Se o repositório template for privado, o clone falhará. Recomenda-se configurar usando `/gitconect` primeiro.\n\n"
        )
    await query.edit_message_text(
        f"{warning}🏗️ *Novo Projeto — Clone de Template*\n\n"
        "Me mande a URL do repositório template no GitHub.\n"
        "_(ex: https://github.com/Usuario/meu-template)_\n\n"
        "Ou /cancelar para abortar.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return AGUARDANDO_TEMPLATE


@owner_only
async def cmd_gitconect_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o fluxo para configurar o token do GitHub via botão inline."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔑 *Configuração do GitHub*\n\n"
        "Envie o seu **Personal Access Token** do GitHub.\n"
        "Eu irei salvá-lo e **apagar sua mensagem** logo em seguida por segurança.\n\n"
        "Ou /cancelar para abortar.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return AGUARDANDO_GITHUB_TOKEN


@owner_only
async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Retorna o Telegram ID do usuário — útil para configuração inicial."""
    user = update.effective_user
    await update.message.reply_text(
        f"🆔 Seu Telegram ID: `{user.id}`\n"
        f"👤 Username: @{user.username or 'sem username'}\n\n"
        f"Cole esse ID no seu arquivo `.env` em `OWNER_TELEGRAM_ID`",
        parse_mode=ParseMode.MARKDOWN,
    )


@owner_only
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dashboard completo: sistema + processos PM2."""
    msg = await update.message.reply_text("🔍 Coletando dados do VPS...")

    sys_info = system.get_system_info()
    processes = pm2.get_processes()

    sys_text = format_system_status(sys_info)
    proc_text = format_process_table(processes)

    full_text = f"{sys_text}\n\n{proc_text}"

    # Telegram tem limite de 4096 chars — trunca se necessário
    if len(full_text) > 4000:
        full_text = full_text[:4000] + "\n\n_[Truncado — use /processos para ver tudo]_"

    await msg.edit_text(full_text, parse_mode=ParseMode.MARKDOWN)


@owner_only
async def cmd_processos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista detalhada dos processos PM2."""
    msg = await update.message.reply_text("⚙️ Buscando processos PM2...")
    processes = pm2.get_processes()
    text = format_process_table(processes)

    if len(text) > 4000:
        text = text[:4000] + "\n\n_[Truncado]_"

    await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)


@owner_only
async def cmd_memoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Análise detalhada de memória com recomendações."""
    msg = await update.message.reply_text("🧠 Analisando memória dos processos...")

    report = memory.get_memory_report()
    text = memory.format_memory_report(report)

    # Se há alertas, adiciona botões inline para ação rápida
    keyboard = []
    for alert_proc in report.get("alerts", [])[:5]:  # máx 5 botões
        keyboard.append([
            InlineKeyboardButton(
                f"🧹 Limpar logs: {alert_proc['name']}",
                callback_data=f"flush:{alert_proc['name']}",
            ),
            InlineKeyboardButton(
                f"🔄 Restart: {alert_proc['name']}",
                callback_data=f"restart:{alert_proc['name']}",
            ),
        ])

    markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)


@owner_only
async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Busca logs de um processo específico."""
    args = context.args
    if not args:
        await update.message.reply_text(
            "📋 Uso: `/logs \\[nome_do_processo\\]`\n"
            "Exemplo: `/logs rota\\-16`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    name = args[0]
    msg = await update.message.reply_text(f"📋 Buscando logs de `{name}`...")
    logs = pm2.get_logs(name, lines=25)

    # Logs são texto puro — usa code block
    if len(logs) > 3800:
        logs = "..." + logs[-3800:]

    await msg.edit_text(f"📋 *Logs: {name}*\n\n```\n{logs}\n```", parse_mode=ParseMode.MARKDOWN)


@owner_only
async def cmd_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Solicita confirmação antes de reiniciar um processo."""
    args = context.args
    if not args:
        await update.message.reply_text(
            "🔄 Uso: `/restart \\[nome_do_processo\\]`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    name = args[0]
    proc = pm2.get_process_by_name(name)
    info = f"Memória: `{proc['memory_mb']:.1f} MB` | Status: `{proc['status']}`" if proc else "_Processo não encontrado_"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirmar Restart", callback_data=f"restart:{name}"),
            InlineKeyboardButton("❌ Cancelar", callback_data="cancel"),
        ]
    ])
    await update.message.reply_text(
        f"⚠️ *Confirmar reinicialização?*\n\n"
        f"Processo: *{name}*\n{info}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )


@owner_only
async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Solicita confirmação antes de parar um processo."""
    args = context.args
    if not args:
        await update.message.reply_text(
            "🛑 Uso: `/stop \\[nome_do_processo\\]`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    name = args[0]
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirmar Stop", callback_data=f"stop:{name}"),
            InlineKeyboardButton("❌ Cancelar", callback_data="cancel"),
        ]
    ])
    await update.message.reply_text(
        f"🛑 *Tem certeza que quer PARAR o processo?*\n\n"
        f"Processo: *{name}*\n⚠️ _Ele ficará offline até ser reiniciado manualmente_",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )


@owner_only
async def cmd_limpar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Solicita confirmação antes de limpar logs de um processo."""
    args = context.args
    target = args[0] if args else None
    label = f"processo *{target}*" if target else "*todos os processos*"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Limpar Logs", callback_data=f"flush:{target or 'ALL'}"),
            InlineKeyboardButton("❌ Cancelar", callback_data="cancel"),
        ]
    ])
    await update.message.reply_text(
        f"🧹 *Confirmar limpeza de logs?*\n\n"
        f"Alvo: {label}\n"
        f"_Isso remove os arquivos de log do PM2_",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )



@owner_only
async def cmd_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe lista de comandos disponíveis."""
    await cmd_start(update, context)


@owner_only
async def cmd_criar_imagem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gera uma imagem com Gemini Imagen a partir de um prompt de texto."""
    prompt = " ".join(context.args) if context.args else ""

    if not prompt:
        await update.message.reply_text(
            "🖼️ *Uso:* `/criar_imagem <descrição>`\n"
            "_Exemplo:_ `/criar_imagem um gato astronauta na lua`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    msg = await update.message.reply_text(
        f"🎨 Gerando imagem com Gemini Imagen...\n"
        f'💬 Prompt: _"{prompt}"_',
        parse_mode=ParseMode.MARKDOWN,
    )

    image_buf = await gemini_ai.generate_image(prompt)

    if image_buf:
        await update.message.reply_photo(
            photo=image_buf,
            caption=f"🖼️ *Imagem gerada pelo Gemini Imagen*\n💬 _{prompt}_",
            parse_mode=ParseMode.MARKDOWN,
        )
        await msg.delete()
    else:
        await msg.edit_text(
            "❌ Não consegui gerar a imagem.\n"
            "Verifique se a `GEMINI_API_KEY` tem acesso ao Imagen e tente novamente."
        )


# ══════════════════════════════════════════════════════════════════════════════
#   /novobot — Deploy de novo bot na VPS via conversa guiada
# ══════════════════════════════════════════════════════════════════════════════

@owner_only
async def cmd_novobot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o fluxo de deploy de um novo bot."""
    context.user_data["is_exclusivo"] = False
    import config
    warning = ""
    if not getattr(config, "GITHUB_TOKEN", ""):
        warning = (
            "⚠️ *Nota:* Você não tem um Token do GitHub configurado nesta VPS. "
            "Se o repositório for privado, o deploy falhará. Recomenda-se configurar usando `/gitconect` primeiro.\n\n"
        )
    await update.message.reply_text(
        f"{warning}🤖 *Novo Bot — Deploy Guiado*\n\n"
        "Me manda o comando `git clone` do repositório\n"
        "_(ex: git clone git@github.com:Ferdinandobot/meu-bot.git)_\n\n"
        "Ou /cancelar para abortar.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return AGUARDANDO_GIT


@owner_only
async def cmd_novobot_exclusivo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o fluxo de deploy de um novo bot exclusivo."""
    context.user_data["is_exclusivo"] = True
    import config
    warning = ""
    if not getattr(config, "GITHUB_TOKEN", ""):
        warning = (
            "⚠️ *Nota:* Você não tem um Token do GitHub configurado nesta VPS. "
            "Se o repositório for privado, o deploy falhará. Recomenda-se configurar usando `/gitconect` primeiro.\n\n"
        )
    await update.message.reply_text(
        f"{warning}🌟 *Novo Bot Exclusivo — Deploy Guiado*\n\n"
        "Me manda o comando `git clone` do repositório\n"
        "_(ex: git clone git@github.com:Ferdinandobot/meu-bot.git)_\n\n"
        "Ou /cancelar para abortar.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return AGUARDANDO_GIT


async def novobot_recebe_git(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o git clone URL e solicita as variáveis de ambiente."""
    user = update.effective_user
    if user.id != OWNER_TELEGRAM_ID:
        return ConversationHandler.END

    text = (update.message.text or "").strip()

    # Aceita tanto "git clone <url>" quanto a URL direta
    match = re.search(r"git clone\s+(\S+)", text)
    if match:
        git_url = match.group(1)
    elif text.startswith("git@") or text.startswith("https://"):
        git_url = text
    else:
        await update.message.reply_text(
            "❌ Não reconheci o comando.\n"
            "Manda assim: `git clone git@github.com:Usuario/repo.git`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return AGUARDANDO_GIT

    # Extrai nome do repo (último segmento sem .git)
    repo_name = git_url.rstrip("/").split("/")[-1].replace(".git", "")

    context.user_data["git_url"]   = git_url
    context.user_data["repo_name"] = repo_name
    context.user_data["is_template"] = False

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚀 Sim, Rodar no PM2", callback_data="pm2_confirm:yes")
        ],
        [
            InlineKeyboardButton("⏸️ Criar no PM2 (Pausado)", callback_data="pm2_confirm:paused")
        ],
        [
            InlineKeyboardButton("🛑 Não, apenas preparar pasta", callback_data="pm2_confirm:no")
        ]
    ])
    await update.message.reply_text(
        f"✅ Repositório detectado: `{repo_name}`\n\n"
        f"❓ *Deseja colocar este bot para rodar no PM2 automaticamente após o deploy?*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )
    return AGUARDANDO_PM2_CONFIRM


async def novobot_recebe_pm2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe a resposta sobre rodar ou não no PM2 e inicia o deploy."""
    query = update.callback_query
    await query.answer()
    
    choice = query.data.split(":")[-1]  # "yes", "no" ou "paused"
    context.user_data["rodar_no_pm2"] = choice
    
    # Remove os botões da mensagem
    await query.edit_message_reply_markup(reply_markup=None)
    
    # Executa o deploy
    return await _executar_deploy(update, context)


# ══════════════════════════════════════════════════════════════════════════════
#   /novoprojeto — Criação de novo projeto a partir de template GitHub
# ══════════════════════════════════════════════════════════════════════════════

@owner_only
async def cmd_novoprojeto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o fluxo para criar um novo projeto a partir de um template."""
    import config
    warning = ""
    if not getattr(config, "GITHUB_TOKEN", ""):
        warning = (
            "⚠️ *Nota:* Você não tem um Token do GitHub configurado nesta VPS. "
            "Se o repositório template for privado, o clone falhará. Recomenda-se configurar usando `/gitconect` primeiro.\n\n"
        )
    await update.message.reply_text(
        f"{warning}🏗️ *Novo Projeto — Clone de Template*\n\n"
        "Me mande a URL do repositório template no GitHub.\n"
        "_(ex: https://github.com/Usuario/meu-template)_\n\n"
        "Ou /cancelar para abortar.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return AGUARDANDO_TEMPLATE


async def novoprojeto_recebe_template(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe a URL do template e pede o nome do novo projeto."""
    user = update.effective_user
    if user.id != OWNER_TELEGRAM_ID:
        return ConversationHandler.END

    text = (update.message.text or "").strip()

    # Pega apenas a URL
    match = re.search(r"git clone\s+(\S+)", text)
    if match:
        git_url = match.group(1)
    elif text.startswith("git@") or text.startswith("https://"):
        git_url = text
    else:
        await update.message.reply_text(
            "❌ Não reconheci a URL.\n"
            "Manda assim: `https://github.com/Usuario/template`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return AGUARDANDO_TEMPLATE

    context.user_data["git_url"] = git_url

    await update.message.reply_text(
        f"✅ Template reconhecido!\n\n"
        f"Agora, qual será o *nome do novo projeto*? (Apenas letras minúsculas, números e hífens)\n"
        f"_(ex: meu-novo-bot)_",
        parse_mode=ParseMode.MARKDOWN,
    )
    return AGUARDANDO_NOME_PROJETO


async def novoprojeto_recebe_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o nome do projeto e dispara o deploy."""
    user = update.effective_user
    if user.id != OWNER_TELEGRAM_ID:
        return ConversationHandler.END

    repo_name = (update.message.text or "").strip().lower()
    
    # Valida nome simples
    if not re.match(r"^[a-z0-9-]+$", repo_name):
        await update.message.reply_text(
            "❌ Nome inválido. Use apenas letras minúsculas, números e hífens.\n"
            "Tente novamente:",
            parse_mode=ParseMode.MARKDOWN,
        )
        return AGUARDANDO_NOME_PROJETO

    context.user_data["repo_name"] = repo_name
    context.user_data["is_template"] = True

    await update.message.reply_text(
        f"✅ Nome do projeto: `{repo_name}`\n\n"
        f"⏳ Iniciando clone e deploy...",
        parse_mode=ParseMode.MARKDOWN,
    )
    return await _executar_deploy(update, context)


# ══════════════════════════════════════════════════════════════════════════════
#   /gitconect — Configuração do Token do GitHub
# ══════════════════════════════════════════════════════════════════════════════

@owner_only
async def cmd_gitconect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o fluxo para configurar o token do GitHub."""
    await update.message.reply_text(
        "🔑 *Configuração do GitHub*\n\n"
        "Envie o seu **Personal Access Token** do GitHub.\n"
        "Eu irei salvá-lo e **apagar sua mensagem** logo em seguida por segurança.\n\n"
        "Ou /cancelar para abortar.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return AGUARDANDO_GITHUB_TOKEN


async def gitconect_recebe_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o token, salva no .env e apaga a mensagem do usuário."""
    user = update.effective_user
    if user.id != OWNER_TELEGRAM_ID:
        return ConversationHandler.END

    token = (update.message.text or "").strip()
    
    # Apagar a mensagem do usuário por segurança
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=update.message.message_id
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Não foi possível apagar a mensagem do token: {e}")

    # Salva no .env
    env_path = os.path.join(os.getcwd(), ".env")
    
    try:
        from dotenv import set_key
        set_key(env_path, "GITHUB_TOKEN", token)
    except ImportError:
        # Fallback manual se set_key não estiver disponível
        env_content = ""
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                env_content = f.read()
        
        lines = env_content.splitlines()
        new_lines = [line for line in lines if not line.startswith("GITHUB_TOKEN=")]
        new_lines.append(f"GITHUB_TOKEN={token}")
        
        with open(env_path, "w") as f:
            f.write("\n".join(new_lines) + "\n")

    # Atualiza em memória para a execução atual (recarrega config de forma simplificada)
    import config
    config.GITHUB_TOKEN = token

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="✅ *Token do GitHub salvo com sucesso!*\nSua mensagem com o token foi apagada.\n\nAgora o bot usará este token automaticamente ao clonar repositórios HTTPS.",
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END


async def _executar_deploy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Executa todos os passos de deploy e retorna logs ao owner."""
    git_url     = context.user_data["git_url"]
    repo_name   = context.user_data["repo_name"]
    is_template = context.user_data.get("is_template", False)
    rodar_no_pm2 = context.user_data.get("rodar_no_pm2", True)
    is_exclusivo = context.user_data.get("is_exclusivo", False)
    
    if is_exclusivo:
        env_content = f"""# ============================================
# INTEGRAÇÃO COM LOVABLE CLOUD (bot-sync)
# ============================================

# URL da Edge Function que recebe os updates do bot (pública)
BOT_SYNC_URL=https://dmovmwxsmzieothuymfh.supabase.co/functions/v1/bot-sync

# Chave compartilhada bot ↔ edge function (A MESMA DO SECRETS DO LOVABLE)
BOT_API_KEY=qE.v!kpro]jfSR$9!!Ip%lvqTPy*zi%

# Nome único desta instância do bot (mesmo nome usado no PM2)
# Exemplo: pm2 start src/core/index.js --name bot-instancia-01
PM2_PROCESS_NAME={repo_name}


# ============================================
# DEMAIS VARIÁVEIS DO BOT (EXISTENTES)
# ============================================

GROQ_API_KEY=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
ROOT_ID=554792671477
SALT_SECRETO=uma_frase_aleatoria_para_seguranca
DASHBOARD_WEBHOOK_URL=https://project--9a6fe77a-f1e3-41a8-8fab-fdcad12687e3.lovable.app/api/public/webhook
DASHBOARD_API_KEY=ferdinando_secret"""
    else:
        env_content = """GROQ_API_KEY=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
ROOT_ID=554792671477
SALT_SECRETO=uma_frase_aleatoria_para_seguranca
DASHBOARD_WEBHOOK_URL=https://project--9a6fe77a-f1e3-41a8-8fab-fdcad12687e3.lovable.app/api/public/webhook
DASHBOARD_API_KEY=ferdinando_secret"""

    # Suporta tanto chamadas via mensagem direta quanto via CallbackQuery (após o botão PM2)
    if update.callback_query:
        msg = await update.callback_query.message.reply_text(
            f"🚀 *Iniciando deploy de `{repo_name}`...*\n\n"
            "⏳ Clonando repositório...",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        msg = await update.message.reply_text(
            f"🚀 *Iniciando deploy de `{repo_name}`...*\n\n"
            "⏳ Clonando repositório...",
            parse_mode=ParseMode.MARKDOWN,
        )

    log_lines = []

    async def run(cmd, cwd=None):
        """Executa um comando de shell de forma assíncrona."""
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode(errors="replace").strip()
        return proc.returncode, output

    import os
    from config import GITHUB_TOKEN
    home = os.path.expanduser("~")
    repo_path = os.path.join(home, repo_name)

    # Prepara a URL com token caso seja HTTPS e tenhamos um GITHUB_TOKEN configurado
    final_git_url = git_url
    if GITHUB_TOKEN and final_git_url.startswith("https://"):
        # Remove https:// e injeta o token
        url_without_protocol = final_git_url[8:]
        final_git_url = f"https://{GITHUB_TOKEN}@{url_without_protocol}"

    # ── 1. Git Clone ─────────────────────────────────────────────────────────
    # Incluímos o repo_name no comando para garantir que ele seja clonado
    # na pasta com o nome exato (útil para o /novoprojeto)
    code, out = await run(f"git clone {final_git_url} {repo_name}", cwd=home)
    log_lines.append(f"📦 git clone → {'✅' if code == 0 else '❌'}\n{out[:500]}")

    if code != 0:
        dica = ""
        if "could not read Username" in out or "terminal prompts disabled" in out or "Authentication failed" in out:
            if not GITHUB_TOKEN:
                dica = (
                    "\n\n💡 *Dica:* Este repositório parece ser privado ou requer autenticação, "
                    "mas o seu *GitHub Token* não está configurado nesta VPS!\n"
                    "Use o comando `/gitconect` primeiro para configurar seu Personal Access Token e tente novamente."
                )
            else:
                dica = (
                    "\n\n💡 *Dica:* O clone falhou mesmo com o token do GitHub configurado.\n"
                    "Verifique se o seu Token do GitHub é válido, se ele tem a permissão de leitura (`repo`) no repositório "
                    "e se a URL do repositório está correta."
                )
        await msg.edit_text(
            f"❌ *Erro no git clone:*\n```\n{out[:1500]}\n```{dica}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END

    if is_template and GITHUB_TOKEN:
        await msg.edit_text(
            f"🚀 *Deploy: `{repo_name}`*\n\n✅ Clone OK\n⏳ Criando repositório no seu GitHub...",
            parse_mode=ParseMode.MARKDOWN,
        )
        import httpx
        import shutil
        
        # 1. Deletar a pasta .git local (para desvincular do template original)
        git_dir = os.path.join(repo_path, ".git")
        if os.path.exists(git_dir):
            shutil.rmtree(git_dir)
            
        # 2. Fazer requisição para criar novo repositório privado na conta
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        data = {
            "name": repo_name,
            "private": True
        }
        
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post("https://api.github.com/orgs/Ferdinandobot/repos", headers=headers, json=data)
                
            if resp.status_code in (200, 201):
                repo_info = resp.json()
                new_clone_url = repo_info.get("clone_url", "")
                
                # Injeta token na nova URL
                if new_clone_url.startswith("https://"):
                    url_without_protocol = new_clone_url[8:]
                    new_clone_url_with_token = f"https://{GITHUB_TOKEN}@{url_without_protocol}"
                    
                    await msg.edit_text(
                        f"🚀 *Deploy: `{repo_name}`*\n\n✅ Clone OK\n✅ Repo criado no GitHub!\n⏳ Enviando código...",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                    
                    # Re-inicializa o git e faz o push
                    await run("git init", cwd=repo_path)
                    await run("git branch -m main", cwd=repo_path)
                    
                    # Garante que .env está no .gitignore
                    gitignore_path = os.path.join(repo_path, ".gitignore")
                    try:
                        with open(gitignore_path, "a") as f:
                            f.write("\n.env\n")
                    except:
                        pass
                        
                    await run("git add .", cwd=repo_path)
                    # Precisamos de user.email e user.name configurados, mas caso não tenha, o git config resolve localmente:
                    await run('git config user.email "bot@antigravity.local"', cwd=repo_path)
                    await run('git config user.name "Ferdinando Bot"', cwd=repo_path)
                    await run('git commit -m "Initial commit from template"', cwd=repo_path)
                    await run(f"git remote add origin {new_clone_url_with_token}", cwd=repo_path)
                    await run("git push -u origin main", cwd=repo_path)
            else:
                import logging
                log = logging.getLogger(__name__)
                log.error(f"GitHub API Error: {resp.status_code} - {resp.text}")
                
                await msg.edit_text(
                    f"❌ *Erro ao criar repositório no GitHub!*\n\nStatus: `{resp.status_code}`\nErro: `{resp.text}`\n\n_O deploy local vai continuar, mas o GitHub não foi atualizado. Verifique se o Token tem a permissão 'repo'._",
                    parse_mode=ParseMode.MARKDOWN,
                )
                await asyncio.sleep(5)
        except Exception as e:
            import logging
            log = logging.getLogger(__name__)
            log.exception(f"Exception calling GitHub API: {e}")
            
            await msg.edit_text(
                f"❌ *Exceção ao criar repositório no GitHub!*\n\nErro: `{str(e)}`\n\n_O deploy local vai continuar..._",
                parse_mode=ParseMode.MARKDOWN,
            )
            await asyncio.sleep(5)

    await msg.edit_text(
        f"🚀 *Deploy: `{repo_name}`*\n\n✅ Clone OK\n⏳ Criando `.env`...",
        parse_mode=ParseMode.MARKDOWN,
    )

    # ── 2. Criar .env ────────────────────────────────────────────────────────
    if env_content:
        env_path = os.path.join(repo_path, ".env")
        try:
            with open(env_path, "w") as f:
                f.write(env_content + "\n")
            log_lines.append("📝 .env → ✅")
        except Exception as e:
            log_lines.append(f"📝 .env → ❌ {e}")

    await msg.edit_text(
        f"🚀 *Deploy: `{repo_name}`*\n\n✅ Clone OK\n✅ .env criado\n⏳ npm install...",
        parse_mode=ParseMode.MARKDOWN,
    )

    # ── 3. npm install ───────────────────────────────────────────────────────
    code, out = await run("npm install", cwd=repo_path)
    log_lines.append(f"📦 npm install → {'✅' if code == 0 else '❌'}\n{out[-300:]}")

    if code != 0:
        await msg.edit_text(
            f"❌ *Erro no npm install:*\n```\n{out[:1500]}\n```",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END

    await msg.edit_text(
        f"🚀 *Deploy: `{repo_name}`*\n\n✅ Clone OK\n✅ .env criado\n✅ npm install OK\n⏳ Iniciando PM2...",
        parse_mode=ParseMode.MARKDOWN,
    )

    # ── 4. PM2 start / Finalização ───────────────────────────────────────────
    if rodar_no_pm2 == "no" or rodar_no_pm2 is False:
        # Finaliza o deploy sem iniciar no PM2
        await msg.edit_text(
            f"🚀 *Deploy de `{repo_name}` Concluído!*\n\n"
            f"✅ Clone do repositório: OK\n"
            f"✅ Arquivo `.env` configurado: OK\n"
            f"✅ Instalação de dependências (`npm install`): OK\n\n"
            f"📂 *Pasta do bot preparada:* `~/{repo_name}`\n"
            f"ℹ️ Conforme solicitado, o bot *NÃO* foi adicionado ao PM2.",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    elif rodar_no_pm2 == "paused":
        # Finaliza o deploy adicionando no PM2 em modo pausado (inicia e pára imediatamente)
        pm2_cmd = f"pm2 start src/core/index.js --name {repo_name}"
        code, out = await run(pm2_cmd, cwd=repo_path)
        log_lines.append(f"⚙️ pm2 start (paused) → {'✅' if code == 0 else '❌'}\n{out[-300:]}")

        if code != 0:
            await msg.edit_text(
                f"❌ *Erro ao criar no PM2:* \n```\n{out[:1500]}\n```",
                parse_mode=ParseMode.MARKDOWN,
            )
            return ConversationHandler.END

        # Envia o comando pm2 stop imediatamente para deixar o processo pausado
        await run(f"pm2 stop {repo_name}")

        # pm2 save
        await run("pm2 save")

        await msg.edit_text(
            f"🚀 *Deploy de `{repo_name}` Concluído!*\n\n"
            f"✅ Clone do repositório: OK\n"
            f"✅ Arquivo `.env` configurado: OK\n"
            f"✅ Instalação de dependências (`npm install`): OK\n"
            f"✅ Adicionado ao PM2 (Pausado): OK\n\n"
            f"📂 *Pasta do bot preparada:* `~/{repo_name}`\n"
            f"ℹ️ O processo foi criado no PM2 sob o nome `{repo_name}`, mas está *pausado/stopped*. "
            f"Para iniciá-lo futuramente, use o comando `/restart {repo_name}`.",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    pm2_cmd = f"pm2 start src/core/index.js --name {repo_name}"
    code, out = await run(pm2_cmd, cwd=repo_path)
    log_lines.append(f"⚙️ pm2 start → {'✅' if code == 0 else '❌'}\n{out[-300:]}")

    if code != 0:
        await msg.edit_text(
            f"❌ *Erro no PM2 start:*\n```\n{out[:1500]}\n```",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END

    # pm2 save
    await run("pm2 save")

    await msg.edit_text(
        f"🚀 *Deploy: `{repo_name}`*\n\n✅ Clone OK\n✅ .env criado\n✅ npm install OK\n✅ PM2 iniciado\n⏳ Coletando logs (QR Code)...",
        parse_mode=ParseMode.MARKDOWN,
    )

    # ── 5. Logs / QR Code (Monitoramento Proativo) ───────────────────────────
    await msg.edit_text(
        f"🚀 *Deploy de `{repo_name}` em andamento...*\n\n"
        "✅ Clone OK\n"
        "✅ .env criado\n"
        "✅ npm install OK\n"
        "✅ PM2 iniciado!\n\n"
        "⏳ Monitorando logs para extrair o QR Code de conexão...",
        parse_mode=ParseMode.MARKDOWN,
    )

    qr_message = None
    last_qr_content = None
    max_attempts = 50  # 50 tentativas x 6 segundos = 300 segundos (5 minutos)
    connected = False

    for attempt in range(max_attempts):
        await asyncio.sleep(6)
        
        # 1. Busca os logs mais recentes do PM2
        code, logs_out = await run(f"pm2 logs {repo_name} --lines 100 --nostream")
        logs_clean = _strip_ansi(logs_out)
        
        # 2. Verifica se a conexão com o WhatsApp foi estabelecida
        # Buscamos palavras-chaves comuns em logs de Baileys/Bots de WhatsApp
        if (
            "conectado e pronto" in logs_clean.lower() or 
            "conexão estabelecida" in logs_clean.lower() or 
            "pronto!" in logs_clean.lower() or 
            "connection opened" in logs_clean.lower() or
            "conectado!" in logs_clean.lower() or
            "conexão com o whatsapp aberta" in logs_clean.lower()
        ):
            connected = True
            break
            
        # 3. Tenta extrair o QR Code
        qr_lines = _extract_qr_lines(logs_out)
        if qr_lines:
            qr_content = "\n".join(qr_lines)
            
            # Se o QR Code mudou (ou é o primeiro), nós geramos a nova imagem
            if qr_content != last_qr_content:
                last_qr_content = qr_content
                qr_image = _render_qr_image(qr_lines)
                
                if qr_image:
                    caption_text = (
                        f"📱 *QR Code — {repo_name}*\n"
                        f"Escaneie com o seu WhatsApp para conectar o bot.\n\n"
                        f"⏳ _Código atualizado em tempo real. Tentativa {attempt + 1}/{max_attempts}_"
                    )
                    
                    if not qr_message:
                        # Envia a primeira mensagem com o QR Code
                        try:
                            qr_message = await update.message.reply_photo(
                                photo=qr_image,
                                caption=caption_text,
                                parse_mode=ParseMode.MARKDOWN,
                            )
                        except Exception as e:
                            import logging
                            logging.getLogger(__name__).error(f"Erro ao enviar o primeiro QR Code: {e}")
                    else:
                        # Edita a foto da mensagem existente!
                        from telegram import InputMediaPhoto
                        try:
                            await qr_message.edit_media(
                                media=InputMediaPhoto(media=qr_image, caption=caption_text),
                            )
                        except Exception as e:
                            import logging
                            logging.getLogger(__name__).warning(f"Erro ao editar mensagem de QR Code, enviando uma nova: {e}")
                            try:
                                qr_message = await update.message.reply_photo(
                                    photo=qr_image,
                                    caption=caption_text,
                                    parse_mode=ParseMode.MARKDOWN,
                                )
                            except Exception as e2:
                                logging.getLogger(__name__).error(f"Erro ao reenviar QR Code: {e2}")

    # Fora do loop: finaliza e atualiza o status do deploy
    if connected:
        success_text = (
            f"✅ *WhatsApp Conectado com Sucesso!*\n\n"
            f"O seu novo bot *{repo_name}* foi configurado com sucesso e já está ativo e pronto para uso no PM2 da VPS!\n\n"
            f"Você já pode usá-lo diretamente no WhatsApp."
        )
        if qr_message:
            try:
                # Se tínhamos um QR Code na tela, atualizamos a legenda dele para indicar sucesso!
                await qr_message.edit_caption(
                    caption=success_text,
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                await update.message.reply_text(success_text, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(success_text, parse_mode=ParseMode.MARKDOWN)
            
        await msg.edit_text(
            f"✅ *Deploy de `{repo_name}` concluído com sucesso!*\n"
            f"Bot conectado e online.",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        # Se esgotou o tempo limite de 5 minutos
        timeout_text = (
            f"⚠️ *Tempo Limite de Conexão Esgotado*\n\n"
            f"O processo do bot *{repo_name}* continua rodando no PM2 da VPS, mas não detectamos a conexão do WhatsApp a tempo.\n\n"
            f"Se você não conseguiu escanear a tempo ou o QR Code expirou, você pode:\n"
            f"1. Ver os logs e escanear usando o comando `/logs {repo_name}`\n"
            f"2. Reiniciar o processo usando `/restart {repo_name}` para gerar outro QR Code."
        )
        if qr_message:
            try:
                await qr_message.edit_caption(
                    caption=timeout_text,
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                await update.message.reply_text(timeout_text, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(timeout_text, parse_mode=ParseMode.MARKDOWN)

        await msg.edit_text(
            f"❌ *Deploy de `{repo_name}`:* Tempo limite para conexão do WhatsApp atingido.",
            parse_mode=ParseMode.MARKDOWN,
        )

    return ConversationHandler.END


async def novobot_cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela o fluxo de deploy."""
    user = update.effective_user
    if user.id != OWNER_TELEGRAM_ID:
        return ConversationHandler.END
    context.user_data.clear()
    
    query = update.callback_query
    if query:
        await query.answer()
        try:
            await query.edit_message_text("❌ Operação cancelada.")
        except Exception:
            pass
    else:
        if update.message:
            await update.message.reply_text("❌ Operação cancelada.")
            
    return ConversationHandler.END


@owner_only
async def cmd_buscargit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o fluxo para listar repositórios do GitHub e clonar."""
    from config import GITHUB_TOKEN
    
    if not GITHUB_TOKEN:
        await update.message.reply_text(
            "⚠️ *Token do GitHub não configurado* ⚠️\n\n"
            "Para buscar seus repositórios no GitHub, você precisa primeiro configurar seu Token.\n"
            "Use o comando `/gitconect` para cadastrar seu Personal Access Token e tente novamente!",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
        
    msg = await update.message.reply_text(
        "🔍 *Buscando seus repositórios no GitHub...*\n\n"
        "⏳ Isso pode levar alguns segundos dependendo da quantidade de repositórios...",
        parse_mode=ParseMode.MARKDOWN
    )
    
    return await _buscar_e_listar_repos(msg, context)


@owner_only
async def cmd_buscargit_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o fluxo via callback query do menu principal."""
    query = update.callback_query
    await query.answer()
    
    from config import GITHUB_TOKEN
    
    if not GITHUB_TOKEN:
        back_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data="menu:main")]])
        await query.edit_message_text(
            "⚠️ *Token do GitHub não configurado* ⚠️\n\n"
            "Para buscar seus repositórios no GitHub, você precisa primeiro configurar seu Token.\n"
            "Use o comando `/gitconect` para cadastrar seu Personal Access Token e tente novamente!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_keyboard
        )
        return ConversationHandler.END
        
    await query.edit_message_text(
        "🔍 *Buscando seus repositórios no GitHub...*\n\n"
        "⏳ Isso pode levar alguns segundos...",
        parse_mode=ParseMode.MARKDOWN
    )
    
    return await _buscar_e_listar_repos(query.message, context)


async def _buscar_e_listar_repos(message, context: ContextTypes.DEFAULT_TYPE):
    """Auxiliar que chama a API do GitHub, popula context.user_data e exibe a lista de donos/empresas."""
    from config import GITHUB_TOKEN
    import httpx
    
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    
    url = "https://api.github.com/user/repos?per_page=100&sort=updated"
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers)
            
        if resp.status_code != 200:
            await message.edit_text(
                f"❌ *Erro ao consultar o GitHub:* HTTP {resp.status_code}\n\n"
                f"Verifique se o seu Token do GitHub é válido.",
                parse_mode=ParseMode.MARKDOWN
            )
            return ConversationHandler.END
            
        repos_raw = resp.json()
        if not repos_raw:
            await message.edit_text(
                "ℹ️ *Nenhum repositório encontrado no seu GitHub.*",
                parse_mode=ParseMode.MARKDOWN
            )
            return ConversationHandler.END
            
        fetched_repos = []
        for r in repos_raw:
            fetched_repos.append({
                "name": r.get("name"),
                "full_name": r.get("full_name"),
                "ssh_url": r.get("ssh_url"),
                "clone_url": r.get("clone_url"),
                "owner": r.get("owner", {}).get("login"),
                "owner_type": r.get("owner", {}).get("type")
            })
            
        context.user_data["fetched_repos"] = fetched_repos
        
        # Agrupa donos únicos
        owners = sorted(list(set(r["owner"] for r in fetched_repos)))
        
        if len(owners) == 1:
            # Só tem um dono, lista os repositórios diretamente
            return await _mostrar_repos_do_dono(message, context, owners[0])
            
        # Apresenta os donos (empresas/organizações)
        keyboard = []
        for owner in owners:
            repo_sample = next(r for r in fetched_repos if r["owner"] == owner)
            emoji = "🏢 " if repo_sample["owner_type"] == "Organization" else "👤 "
            keyboard.append([InlineKeyboardButton(f"{emoji}{owner}", callback_data=f"gitlist:owner:{owner}")])
            
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="novobot_cancelar")])
        
        await message.edit_text(
            "🏢 *Buscar Git — Empresas/Donos*\n\n"
            "Selecione o dono ou organização do repositório que deseja fazer deploy:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return AGUARDANDO_GIT_SELECT
        
    except Exception as e:
        await message.edit_text(
            f"❌ *Erro ao listar repositórios:* `{e}`",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END


async def _mostrar_repos_do_dono(message, context: ContextTypes.DEFAULT_TYPE, owner: str):
    """Gera o teclado com repositórios pertencentes ao dono selecionado."""
    fetched_repos = context.user_data.get("fetched_repos", [])
    
    keyboard = []
    # Cria os botões passando o índice para não estourar os 64 bytes do callback_data
    for i, r in enumerate(fetched_repos):
        if r["owner"] == owner:
            keyboard.append([InlineKeyboardButton(f"📁 {r['name']}", callback_data=f"gitlist:repo:{i}")])
            
    # Botão para voltar para a seleção de donos se houver mais de um dono
    owners = sorted(list(set(r["owner"] for r in fetched_repos)))
    if len(owners) > 1:
        keyboard.append([InlineKeyboardButton("⬅️ Voltar para Empresas", callback_data="gitlist:owners_back")])
        
    keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="novobot_cancelar")])
    
    await message.edit_text(
        f"📂 *Repositórios em `{owner}`*\n\n"
        f"Selecione qual repositório você deseja trazer para a VPS:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return AGUARDANDO_GIT_SELECT


async def buscargit_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Trata as seleções de donos e repositórios durante a listagem do Git."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    _, action_type, val = data.split(":")
    
    if action_type == "owner":
        # Selecionou o dono, mostra seus repositórios
        return await _mostrar_repos_do_dono(query.message, context, val)
        
    elif action_type == "owners_back":
        # Voltou para a lista de donos
        fetched_repos = context.user_data.get("fetched_repos", [])
        owners = sorted(list(set(r["owner"] for r in fetched_repos)))
        
        keyboard = []
        for owner in owners:
            repo_sample = next(r for r in fetched_repos if r["owner"] == owner)
            emoji = "🏢 " if repo_sample["owner_type"] == "Organization" else "👤 "
            keyboard.append([InlineKeyboardButton(f"{emoji}{owner}", callback_data=f"gitlist:owner:{owner}")])
            
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="novobot_cancelar")])
        
        await query.edit_message_text(
            "🏢 *Buscar Git — Empresas/Donos*\n\n"
            "Selecione o dono ou organização do repositório que deseja fazer deploy:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return AGUARDANDO_GIT_SELECT
        
    elif action_type == "repo":
        # Selecionou o repositório por index
        idx = int(val)
        fetched_repos = context.user_data.get("fetched_repos", [])
        
        if idx >= len(fetched_repos):
            await query.edit_message_text("❌ *Erro:* Seleção inválida. Tente novamente.")
            return ConversationHandler.END
            
        repo = fetched_repos[idx]
        
        # Guarda as variáveis de deploy
        context.user_data["git_url"] = repo["ssh_url"] or repo["clone_url"]
        context.user_data["repo_name"] = repo["name"]
        context.user_data["is_template"] = False
        
        # Solicita confirmação do PM2
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🚀 Sim, Rodar no PM2", callback_data="pm2_confirm:yes")
            ],
            [
                InlineKeyboardButton("⏸️ Criar no PM2 (Pausado)", callback_data="pm2_confirm:paused")
            ],
            [
                InlineKeyboardButton("🛑 Não, apenas preparar pasta", callback_data="pm2_confirm:no")
            ]
        ])
        await query.edit_message_text(
            f"✅ Repositório selecionado: `{repo['full_name']}`\n\n"
            f"❓ *Deseja colocar este bot para rodar no PM2 automaticamente após o deploy?*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
        return AGUARDANDO_PM2_CONFIRM


def get_projects_keyboard() -> InlineKeyboardMarkup:
    """Escaneia a pasta home (~) e gera botões com as pastas encontradas."""
    import os
    home = os.path.expanduser("~")
    try:
        items = os.listdir(home)
    except Exception as e:
        return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="menu:main")]])
        
    keyboard = []
    # Filtra apenas pastas que não começam com "."
    folders = [item for item in items if os.path.isdir(os.path.join(home, item)) and not item.startswith(".")]
    
    # Ordena alfabeticamente para organização premium
    folders.sort()
    
    # Adiciona as pastas em formato de botão
    for folder in folders:
        keyboard.append([InlineKeyboardButton(f"📁 {folder}", callback_data=f"proj:view:{folder}")])
        
    keyboard.append([InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="menu:main")])
    return InlineKeyboardMarkup(keyboard)


@owner_only
async def cmd_projetos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista todos os projetos/pastas na VPS do usuário."""
    markup = get_projects_keyboard()
    await update.message.reply_text(
        "📂 *Gerenciador de Projetos VPS*\n\n"
        "Selecione uma das pastas abaixo para gerenciar ou realizar ações nela (Git Pull, Deletar):",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=markup
    )


async def _processar_exportacao(update: Update, context: ContextTypes.DEFAULT_TYPE, folder: str):
    """Localiza as pastas de dados de um projeto, compacta em zip e envia diretamente para o outro bot."""
    import os
    import zipfile
    import io
    import httpx
    from config import OTHER_BOT_TOKEN, OWNER_TELEGRAM_ID
    
    home = os.path.expanduser("~")
    folder_path = os.path.join(home, folder)
    
    # Mensagem proativa inicial mostrando caminho absoluto na VPS de origem
    await update.message.reply_text(
        f"🔍 *Solicitação de Sincronização Ativa!*\n\n"
        f"• *Projeto:* `{folder}`\n"
        f"• *Origem na VPS:* `{folder_path}`\n\n"
        f"⏳ Varrendo o diretório em busca de `Data_local` e `data`...",
        parse_mode=ParseMode.MARKDOWN
    )
    
    if not os.path.exists(folder_path):
        await update.message.reply_text(f"❌ *Erro:* A pasta do projeto `{folder}` não foi encontrada nesta VPS.")
        return
        
    # Identifica as pastas de dados (Data_local e data) no root ou na pasta src
    data_paths = []
    for sub in ["", "src"]:
        for d in ["Data_local", "data"]:
            p = os.path.join(folder_path, sub, d)
            if os.path.isdir(p):
                # Guarda o nome da pasta (ex: Data_local) e o caminho completo
                data_paths.append((d, p))
                
    if not data_paths:
        await update.message.reply_text(
            f"⚠️ Nenhuma pasta de dados (`Data_local` ou `data`) foi encontrada no projeto `{folder}` nesta VPS."
        )
        return
        
    msg = await update.message.reply_text(f"📦 *Compactando dados do projeto `{folder}`...*")
    
    try:
        # Cria arquivo zip em memória
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            for name, path in data_paths:
                for root, dirs, files in os.walk(path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        # Mantém a estrutura de subpastas relativa (ex: Data_local/config.json)
                        rel_path = os.path.join(name, os.path.relpath(file_path, path))
                        zip_file.write(file_path, rel_path)
                        
        zip_buffer.seek(0)
        
        if OTHER_BOT_TOKEN:
            await msg.edit_text(f"🚀 *Enviando dados diretamente para a outra VPS...*")
            
            # Envia como documento usando o token do outro bot diretamente para o chat do dono
            url = f"https://api.telegram.org/bot{OTHER_BOT_TOKEN}/sendDocument"
            
            files = {
                "document": (f"{folder}_dados.zip", zip_buffer.getvalue(), "application/zip")
            }
            
            data = {
                "chat_id": OWNER_TELEGRAM_ID,
                "caption": (
                    f"📦 *Dados Recebidos — `{folder}`*\n\n"
                    f"Origem: VPS oposta\n\n"
                    f"Clique no botão abaixo para aplicar e substituir os dados locais (`Data_local`/`data`) deste projeto na outra VPS."
                ),
                "parse_mode": "Markdown",
                "reply_markup": __import__('json').dumps({
                    "inline_keyboard": [[
                        {
                            "text": "📥 Importar Dados nesta VPS",
                            "callback_data": f"proj:import:{folder}"
                        }
                    ]]
                })
            }
            
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, files=files, data=data)
                
            if resp.status_code in (200, 201):
                await msg.edit_text("✅ *Dados enviados com sucesso!* Abra o chat do outro bot na outra VPS para realizar a importação.")
            else:
                await msg.edit_text(
                    f"❌ *Erro ao enviar diretamente para o outro bot:* {resp.status_code}\n"
                    f"Tentando enviar localmente aqui no chat..."
                )
                zip_buffer.seek(0)
                await update.message.reply_document(
                    document=zip_buffer,
                    filename=f"{folder}_dados.zip",
                    caption=f"Encaminhe este arquivo manualmente para o outro bot."
                )
        else:
            await msg.edit_text("⚠️ `OTHER_BOT_TOKEN` não configurado. Enviando o arquivo aqui no chat, faça o encaminhamento manual:")
            await update.message.reply_document(
                document=zip_buffer,
                filename=f"{folder}_dados.zip",
                caption=f"Encaminhe este arquivo manualmente para o outro bot."
            )
            
    except Exception as e:
        await msg.edit_text(f"❌ *Erro ao compactar ou enviar os dados:* `{e}`")
