"""Callbacks de botões inline — navegação por menus e ações rápidas."""
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from core.auth import is_owner
from services import pm2, gemini_ai, system, memory
from utils.formatter import format_process_table, format_system_status
from utils.logger import get_logger

log = get_logger(__name__)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Roteador central de callbacks inline."""
    query = update.callback_query
    user = query.from_user

    # Segurança: só o dono pode usar botões
    if not is_owner(user.id):
        await query.answer("🚫 Acesso negado.", show_alert=True)
        return

    await query.answer()  # Remove o spinner do botão
    data = query.data

    # Botão de voltar ao menu principal simples
    back_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="menu:main")]])

    if data == "cancel":
        await query.edit_message_text("❌ *Operação cancelada.*", parse_mode=ParseMode.MARKDOWN, reply_markup=back_keyboard)
        return

    action, _, target = data.partition(":")

    try:
        if action == "menu":
            await _handle_menu_navigation(query, target)
        elif action == "select":
            await _handle_process_selection(query, target)
        elif action == "logs":
            await _show_logs(query, target)
        elif action == "restart_confirm":
            await _show_restart_confirm(query, target)
        elif action == "stop_confirm":
            await _show_stop_confirm(query, target)
        elif action == "flush_confirm":
            await _show_flush_confirm(query, target)
        elif action == "flush":
            await _do_flush(query, target)
        elif action == "restart":
            await _do_restart(query, target)
        elif action == "stop":
            await _do_stop(query, target)
        elif action == "ai_suggest":
            await _do_ai_suggest(query, target)
        elif action == "proj":
            await _handle_project_action(query, context, target)
        else:
            await query.edit_message_text("❓ Ação desconhecida.", reply_markup=back_keyboard)
    except Exception as e:
        log.exception(f"Erro ao processar callback {data}: {e}")
        try:
            await query.edit_message_text(
                f"💥 *Erro interno ao processar ação:* `{e}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_keyboard
            )
        except Exception:
            try:
                await query.edit_message_caption(
                    caption=f"💥 *Erro interno ao processar ação:* `{e}`",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=back_keyboard
                )
            except Exception:
                try:
                    await context.bot.send_message(
                        chat_id=user.id,
                        text=f"💥 *Erro interno ao processar ação:* `{e}`",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=back_keyboard
                    )
                except Exception:
                    pass


async def _handle_menu_navigation(query, target: str):
    """Trata a navegação de telas do menu principal."""
    from handlers.commands import get_start_text, get_main_keyboard
    
    back_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="menu:main")]])
    
    if target == "main":
        await query.edit_message_text(
            get_start_text(),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_main_keyboard()
        )
    elif target == "status":
        await query.edit_message_text("🔍 Coletando dados do VPS...")
        sys_info = system.get_system_info()
        processes = pm2.get_processes()
        sys_text = format_system_status(sys_info)
        proc_text = format_process_table(processes)
        full_text = f"{sys_text}\n\n{proc_text}"
        
        if len(full_text) > 4000:
            full_text = full_text[:4000] + "\n\n_[Truncado — use Processos para ver tudo]_"
            
        await query.edit_message_text(full_text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_keyboard)
    elif target == "processes":
        await query.edit_message_text("⚙️ Buscando processos PM2...")
        processes = pm2.get_processes()
        text = format_process_table(processes)
        
        if len(text) > 4000:
            text = text[:4000] + "\n\n_[Truncado]_"
            
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_keyboard)
    elif target == "memory":
        await query.edit_message_text("🧠 Analisando memória dos processos...")
        report = memory.get_memory_report()
        text = memory.format_memory_report(report)
        
        keyboard = []
        for alert_proc in report.get("alerts", [])[:5]:  # máx 5 botões
            keyboard.append([
                InlineKeyboardButton(
                    f"🧹 Limpar logs: {alert_proc['name']}",
                    callback_data=f"flush_confirm:{alert_proc['name']}",
                ),
                InlineKeyboardButton(
                    f"🔄 Restart: {alert_proc['name']}",
                    callback_data=f"restart_confirm:{alert_proc['name']}",
                ),
            ])
        keyboard.append([InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="menu:main")])
        markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)

    elif target == "myid":
        user = query.from_user
        await query.edit_message_text(
            f"🆔 Seu Telegram ID: `{user.id}`\n"
            f"👤 Username: @{user.username or 'sem username'}\n\n"
            f"Cole esse ID no seu arquivo `.env` em `OWNER_TELEGRAM_ID`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_keyboard
        )
    elif target == "criar_imagem":
        await query.edit_message_text(
            "🖼️ *Como criar imagens*\n\n"
            "O Gemini Imagen precisa de uma descrição textual para gerar a imagem. Por isso, envie um comando de texto no chat assim:\n\n"
            "`/criar_imagem um gato astronauta na lua`\n\n"
            "Eu farei a geração e te enviarei a imagem aqui!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_keyboard
        )
    elif target == "projetos":
        from handlers.commands import get_projects_keyboard
        await query.edit_message_text(
            "📂 *Gerenciador de Projetos VPS*\n\n"
            "Selecione uma das pastas abaixo para gerenciar ou realizar ações nela (Git Pull, Deletar):",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_projects_keyboard()
        )


async def _handle_process_selection(query, action_type: str):
    """Exibe um submenu com todos os processos PM2 para o usuário escolher."""
    processes = pm2.get_processes()
    
    if not processes:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="menu:main")]])
        await query.edit_message_text(
            "📭 *Nenhum processo PM2 em execução encontrado.*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
        return

    titles = {
        "logs": "📋 Selecione o processo para ver os *logs*:",
        "restart": "🔄 Selecione o processo para *reiniciar*:",
        "stop": "🛑 Selecione o processo para *parar*:",
        "flush": "🧹 Selecione o processo para *limpar logs*:"
    }
    
    next_callback_prefix = {
        "logs": "logs",
        "restart": "restart_confirm",
        "stop": "stop_confirm",
        "flush": "flush_confirm"
    }

    keyboard = []
    
    # Na limpeza de logs, permitimos a opção ALL
    if action_type == "flush":
        keyboard.append([InlineKeyboardButton("🧹 Todos os Processos", callback_data="flush_confirm:ALL")])
        
    for proc in processes:
        name = proc["name"]
        status_emoji = "🟢" if proc["status"] == "online" else "🔴"
        keyboard.append([
            InlineKeyboardButton(
                f"{status_emoji} {name} ({proc['memory_mb']:.1f} MB)",
                callback_data=f"{next_callback_prefix[action_type]}:{name}"
            )
        ])
        
    keyboard.append([InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="menu:main")])
    
    await query.edit_message_text(
        titles.get(action_type, "Selecione o processo:"),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _show_logs(query, name: str):
    """Busca e exibe logs de um processo com botão de atualizar e voltar."""
    await query.edit_message_text(f"📋 Buscando logs de `{name}`...")
    logs = pm2.get_logs(name, lines=25)
    
    if len(logs) > 3800:
        logs = "..." + logs[-3800:]
        
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Atualizar", callback_data=f"logs:{name}"),
            InlineKeyboardButton("🔙 Voltar", callback_data="select:logs"),
        ]
    ])
    
    await query.edit_message_text(
        f"📋 *Logs: {name}*\n\n```\n{logs}\n```",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )


async def _show_restart_confirm(query, name: str):
    """Exibe a tela de confirmação de restart."""
    proc = pm2.get_process_by_name(name)
    info = f"Memória: `{proc['memory_mb']:.1f} MB` | Status: `{proc['status']}`" if proc else "_Processo não encontrado_"
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirmar Restart", callback_data=f"restart:{name}"),
            InlineKeyboardButton("❌ Cancelar", callback_data="select:restart"),
        ]
    ])
    await query.edit_message_text(
        f"⚠️ *Confirmar reinicialização?*\n\n"
        f"Processo: *{name}*\n{info}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )


async def _show_stop_confirm(query, name: str):
    """Exibe a tela de confirmação de stop."""
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirmar Stop", callback_data=f"stop:{name}"),
            InlineKeyboardButton("❌ Cancelar", callback_data="select:stop"),
        ]
    ])
    await query.edit_message_text(
        f"🛑 *Tem certeza que quer PARAR o processo?*\n\n"
        f"Processo: *{name}*\n⚠️ _Ele ficará offline até ser reiniciado manualmente_",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )


async def _show_flush_confirm(query, name: str):
    """Exibe a tela de confirmação de limpeza de logs."""
    label = f"processo *{name}*" if name != "ALL" else "*todos os processos*"
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Limpar Logs", callback_data=f"flush:{name}"),
            InlineKeyboardButton("❌ Cancelar", callback_data="select:flush"),
        ]
    ])
    await query.edit_message_text(
        f"🧹 *Confirmar limpeza de logs?*\n\n"
        f"Alvo: {label}\n"
        f"_Isso remove os arquivos de log do PM2_",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )


async def _do_flush(query, target: str):
    """Executa limpeza de logs após confirmação."""
    name = None if target == "ALL" else target
    label = f"`{name}`" if name else "todos os processos"
    back_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="menu:main")]])

    await query.edit_message_text(f"🧹 Limpando logs de {label}...")
    ok, out = pm2.flush_logs(name)

    if ok:
        await query.edit_message_text(
            f"✅ *Logs limpos com sucesso!*\n\nAlvo: {label}\n"
            f"_A memória vai estabilizar nos próximos ciclos._",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_keyboard,
        )
    else:
        await query.edit_message_text(
            f"❌ *Erro ao limpar logs:*\n`{out}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_keyboard,
        )


async def _do_restart(query, name: str):
    """Executa restart após confirmação."""
    back_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="menu:main")]])
    
    # Se o bot estiver tentando reiniciar a si mesmo
    if pm2.get_my_process_name() == name:
        await query.edit_message_text(
            f"🔄 *Reiniciando a mim mesmo (`{name}`)!*\n\n"
            f"_O bot ficará offline por alguns segundos e voltará automaticamente._",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_keyboard,
        )
        import subprocess
        # Inicia o restart em modo desanexado para não travar aguardando o próprio fim
        subprocess.Popen(["pm2", "restart", name], start_new_session=True)
        return

    await query.edit_message_text(f"🔄 Reiniciando `{name}`...")
    ok, out = pm2.restart_process(name)

    if ok:
        # Busca status pós-restart
        proc = pm2.get_process_by_name(name)
        status = proc["status"] if proc else "unknown"
        await query.edit_message_text(
            f"✅ *Processo reiniciado!*\n\n"
            f"• Nome: `{name}`\n"
            f"• Status: `{status}`\n"
            f"_Use o painel para acompanhar a recuperação._",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_keyboard,
        )
    else:
        await query.edit_message_text(
            f"❌ *Erro ao reiniciar `{name}`:*\n`{out}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_keyboard,
        )


async def _do_stop(query, name: str):
    """Executa stop após confirmação."""
    back_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="menu:main")]])
    await query.edit_message_text(f"🛑 Parando `{name}`...")
    ok, out = pm2.stop_process(name)

    if ok:
        await query.edit_message_text(
            f"🔴 *Processo parado.*\n\n"
            f"• Nome: `{name}`\n"
            f"_Use o menu de reinicialização para subir novamente._",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_keyboard,
        )
    else:
        await query.edit_message_text(
            f"❌ *Erro ao parar `{name}`:*\n`{out}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_keyboard,
        )


async def _do_ai_suggest(query, name: str):
    """IA analisa um processo específico e sugere ação."""
    await query.edit_message_text(f"🤖 Analisando `{name}` com IA...")

    proc = pm2.get_process_by_name(name)
    if not proc:
        await query.edit_message_text(f"❌ Processo `{name}` não encontrado.")
        return

    suggestion = await gemini_ai.suggest_cleanup(proc)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🧹 Limpar Logs", callback_data=f"flush_confirm:{name}"),
            InlineKeyboardButton("🔄 Restart", callback_data=f"restart_confirm:{name}"),
        ],
        [InlineKeyboardButton("❌ Ignorar", callback_data="menu:main")],
    ])

    text = f"🤖 *Análise: {name}*\n\n{suggestion}"
    if len(text) > 4000:
        text = text[:4000]

    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)


async def _handle_project_action(query, context: ContextTypes.DEFAULT_TYPE, target: str):
    """Lida com as interações e operações do Gerenciador de Projetos VPS."""
    action_type, _, folder = target.partition(":")
    
    import os
    import shutil
    import asyncio
    
    home = os.path.expanduser("~")
    folder_path = os.path.join(home, folder)
    
    if action_type == "view":
        # Menu de visualização/gerenciamento do projeto selecionado
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🚀 Iniciar PM2", callback_data=f"proj:startpm2:{folder}"),
                InlineKeyboardButton("📱 Gerar QR Code", callback_data=f"proj:qrconfirm:{folder}"),
            ],
            [
                InlineKeyboardButton("📥 Fazer Git-Pull", callback_data=f"proj:pull:{folder}"),
                InlineKeyboardButton("🗑️ Apagar Pasta", callback_data=f"proj:delconfirm:{folder}"),
            ],
            [
                InlineKeyboardButton("📤 Enviar Dados", callback_data=f"proj:sendconfirm:{folder}"),
                InlineKeyboardButton("📥 Copiar Dados", callback_data=f"proj:copyconfirm:{folder}"),
            ],
            [InlineKeyboardButton("⬅️ Voltar", callback_data="menu:projetos")]
        ])
        await query.edit_message_text(
            f"📁 *Gerenciando Pasta: `{folder}`*\n\n"
            f"📍 Caminho na VPS: `~/{folder}`\n\n"
            f"Selecione a ação desejada abaixo:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
        
    elif action_type == "pull":
        # Executa git pull de forma assíncrona
        await query.edit_message_text(f"⏳ Executando `git pull` em `{folder}`...")
        
        proc = await asyncio.create_subprocess_shell(
            "git pull",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=folder_path
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode(errors="replace").strip()
        
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data=f"proj:view:{folder}")]])
        
        formatted_response = _format_git_pull_output(folder, output)
        await query.edit_message_text(
            formatted_response,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )

    elif action_type == "sendconfirm":
        # Tela de confirmação para enviar dados
        from config import OTHER_BOT_USERNAME, OTHER_BOT_TOKEN
        
        if not OTHER_BOT_USERNAME or not OTHER_BOT_TOKEN:
            back_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data=f"proj:view:{folder}")]])
            await query.edit_message_text(
                f"⚠️ *Configuração Pendente* ⚠️\n\n"
                f"Para enviar dados entre bots, você precisa configurar as variáveis no arquivo `.env` da VPS:\n\n"
                f"`OTHER_BOT_USERNAME=nome_do_outro_bot`\n"
                f"`OTHER_BOT_TOKEN=token_do_outro_bot`\n\n"
                f"Após preencher e reiniciar o bot, tente novamente!",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_keyboard
            )
            return
            
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📤 Sim, Enviar Agora", callback_data=f"proj:sendrun:{folder}"),
                InlineKeyboardButton("❌ Cancelar", callback_data=f"proj:view:{folder}"),
            ]
        ])
        await query.edit_message_text(
            f"📤 *Enviar Dados para outra VPS — `{folder}`*\n\n"
            f"Isso compactará as pastas `Data_local` e `data` deste projeto nesta VPS e enviará o pacote diretamente para o seu chat no outro bot.\n\n"
            f"Deseja prosseguir?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
        
    elif action_type == "sendrun":
        # Compacta e envia os dados diretamente para o outro bot
        msg = await query.edit_message_text(f"📦 *Compactando dados de `{folder}`...*")
        
        import os
        import zipfile
        import io
        import httpx
        from config import OTHER_BOT_TOKEN, OWNER_TELEGRAM_ID
        
        # Identifica pastas de dados
        data_paths = []
        for sub in ["", "src"]:
            for d in ["Data_local", "data"]:
                p = os.path.join(folder_path, sub, d)
                if os.path.isdir(p):
                    data_paths.append((d, p))
                    
        if not data_paths:
            back_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data=f"proj:view:{folder}")]])
            await msg.edit_text(
                f"⚠️ Nenhuma pasta de dados (`Data_local` ou `data`) foi encontrada no projeto `{folder}` nesta VPS.",
                reply_markup=back_keyboard
            )
            return
            
        try:
            # Cria zip em memória
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                for name, path in data_paths:
                    for root, dirs, files in os.walk(path):
                        for file in files:
                            file_path = os.path.join(root, file)
                            rel_path = os.path.join(name, os.path.relpath(file_path, path))
                            zip_file.write(file_path, rel_path)
                            
            zip_buffer.seek(0)
            data_bytes = zip_buffer.getvalue()
            file_size = len(data_bytes)
            chunk_size = 18 * 1024 * 1024  # 18MB
            
            if file_size > chunk_size:
                chunks = [data_bytes[i:i + chunk_size] for i in range(0, file_size, chunk_size)]
                await msg.edit_text(f"🚀 *Arquivo grande ({file_size / 1024 / 1024:.1f}MB).* Dividindo em {len(chunks)} partes para envio pelo Telegram...")
                
                message_ids = []
                url_send_doc = f"https://api.telegram.org/bot{OTHER_BOT_TOKEN}/sendDocument"
                
                async with httpx.AsyncClient(timeout=120.0) as client:
                    for idx, chunk in enumerate(chunks, 1):
                        part_name = f"{folder}_dados.part{idx}.bin"
                        files = {"document": (part_name, chunk, "application/octet-stream")}
                        data_payload = {"chat_id": OWNER_TELEGRAM_ID}
                        resp = await client.post(url_send_doc, files=files, data=data_payload)
                        if resp.status_code == 200:
                            message_ids.append(resp.json().get("result", {}).get("message_id"))
                        else:
                            raise Exception(f"Falha ao enviar parte {idx}: {resp.text}")
                            
                url_msg = f"https://api.telegram.org/bot{OTHER_BOT_TOKEN}/sendMessage"
                data_msg = {
                    "chat_id": OWNER_TELEGRAM_ID,
                    "text": (
                        f"📦 *Dados Recebidos — `{folder}`*\n\n"
                        f"Origem: VPS oposta\n"
                        f"Tamanho Total: {file_size / 1024 / 1024:.1f}MB em {len(chunks)} partes.\n"
                        f"IDs: {','.join(map(str, message_ids))}\n\n"
                        f"Clique no botão abaixo para aplicar e substituir os dados locais."
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
                    resp = await client.post(url_msg, data=data_msg)
            else:
                await msg.edit_text(f"🚀 *Enviando arquivo diretamente para o outro bot da VPS...*")
                url_send_doc = f"https://api.telegram.org/bot{OTHER_BOT_TOKEN}/sendDocument"
                files = {
                    "document": (f"{folder}_dados.zip", data_bytes, "application/zip")
                }
                data_payload = {
                    "chat_id": OWNER_TELEGRAM_ID,
                    "caption": (
                        f"📦 *Dados Recebidos — `{folder}`*\n\n"
                        f"Origem: VPS oposta\n\n"
                        f"Clique no botão abaixo para aplicar e substituir os dados locais."
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
                    resp = await client.post(url_send_doc, files=files, data=data_payload)
                    
            back_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar aos Projetos", callback_data="menu:projetos")]])
            
            if resp.status_code in (200, 201):
                await msg.edit_text(
                    f"✅ *Dados do projeto `{folder}` enviados com sucesso!*\n\n"
                    f"Abra o chat do seu outro bot na outra VPS. O arquivo de importação já estará lá esperando por você!",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=back_keyboard
                )
            else:
                await msg.edit_text(
                    f"❌ *Erro ao enviar para o outro bot:* {resp.status_code}\n\n"
                    f"Verifique se o `OTHER_BOT_TOKEN` está configurado corretamente no seu `.env`.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=back_keyboard
                )
                
        except Exception as e:
            back_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data=f"proj:view:{folder}")]])
            await msg.edit_text(
                f"❌ *Erro ao enviar os dados:* `{e}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_keyboard
            )

    elif action_type == "copyconfirm":
        from config import OTHER_BOT_USERNAME, OTHER_BOT_TOKEN
        
        if not OTHER_BOT_USERNAME or not OTHER_BOT_TOKEN:
            back_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data=f"proj:view:{folder}")]])
            await query.edit_message_text(
                f"⚠️ *Configuração Pendente* ⚠️\n\n"
                f"Para copiar dados entre bots, você precisa configurar as variáveis no arquivo `.env` da VPS:\n\n"
                f"`OTHER_BOT_USERNAME=nome_do_outro_bot`\n"
                f"`OTHER_BOT_TOKEN=token_do_outro_bot`\n\n"
                f"Após preencher e reiniciar o bot, tente novamente!",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_keyboard
            )
            return
            
        other_bot_user = OTHER_BOT_USERNAME.lstrip("@")
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📤 Solicitar da outra VPS", url=f"https://t.me/{other_bot_user}?start=export_{folder}"),
            ],
            [
                InlineKeyboardButton("❌ Cancelar", callback_data=f"proj:view:{folder}"),
            ]
        ])
        await query.edit_message_text(
            f"🔄 *Copiar Dados de outra VPS — `{folder}`*\n\n"
            f"Você irá solicitar as pastas `Data_local` e `data` deste mesmo projeto rodando na outra VPS.\n\n"
            f"Clique no botão abaixo para iniciar a solicitação no outro bot. Ele enviará o arquivo de volta para este chat automaticamente!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )

    elif action_type == "import":
        # Importação e extração: primeiro lista as pastas da VPS para o usuário escolher o destino
        msg_text = query.message.text or query.message.caption or ""
        msg_ids = None
        if "IDs: " in msg_text:
            msg_ids = msg_text.split("IDs: ")[1].split("\n")[0].strip()

        has_document = hasattr(query.message, "document") and query.message.document

        if not has_document and not msg_ids:
            try:
                await query.edit_message_text("❌ *Erro:* Nenhum documento anexado ou IDs de partes encontrados nesta mensagem.")
            except Exception:
                await query.edit_message_caption(caption="❌ *Erro:* Nenhum documento anexado ou IDs de partes encontrados nesta mensagem.")
            return
            
        # Salva o file_id ou IDs das partes em context.user_data
        if has_document:
            context.user_data["import_file_id"] = query.message.document.file_id
            context.user_data["import_msg_ids"] = None
        else:
            context.user_data["import_file_id"] = None
            context.user_data["import_msg_ids"] = msg_ids
        
        # Escaneia a pasta home (~) em busca de diretórios de destino
        try:
            items = os.listdir(home)
        except Exception as e:
            await query.edit_message_caption(
                caption=f"❌ *Erro ao listar pastas na VPS:* `{e}`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
            
        folders = [item for item in items if os.path.isdir(os.path.join(home, item)) and not item.startswith(".")]
        folders.sort()
        
        if not folders:
            await query.edit_message_caption(
                caption="⚠️ *Nenhuma pasta encontrada na VPS.* Crie uma pasta de projeto antes de importar.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
            
        keyboard = []
        # Para cada pasta encontrada na VPS, cria um botão para importar nela
        for fld in folders:
            # Destaque especial se for a pasta recomendada de origem (folder)
            emoji = "⭐ " if fld == folder else "📁 "
            keyboard.append([InlineKeyboardButton(f"{emoji}Importar em: {fld}", callback_data=f"proj:importrun:{fld}")])
            
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="menu:projetos")])
        markup = InlineKeyboardMarkup(keyboard)
        
        # Pergunta ao usuário onde ele deseja incorporar os dados
        text_content = (
            f"📥 *Importador de Dados Inter-VPS*\n\n"
            f"Detectamos um pacote de dados para o projeto `{folder}`.\n\n"
            f"👉 *Selecione em qual pasta/projeto nesta VPS você deseja incorporar estes dados:* "
        )
        if query.message.caption is not None or has_document:
            await query.edit_message_caption(caption=text_content, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
        else:
            await query.edit_message_text(text=text_content, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)

    elif action_type == "importrun":
        # Executa a extração do zip na pasta selecionada pelo usuário
        file_id = context.user_data.get("import_file_id")
        msg_ids_str = context.user_data.get("import_msg_ids")
        
        if not file_id and not msg_ids_str:
            msg_text = query.message.text or query.message.caption or ""
            if "IDs: " in msg_text:
                msg_ids_str = msg_text.split("IDs: ")[1].split("\n")[0].strip()
            elif query.message and hasattr(query.message, "document") and query.message.document:
                file_id = query.message.document.file_id
            else:
                back_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar aos Projetos", callback_data="menu:projetos")]])
                try:
                    await query.edit_message_caption(caption="❌ *Erro:* Sessão foi reiniciada e mensagens foram perdidas.", parse_mode=ParseMode.MARKDOWN, reply_markup=back_keyboard)
                except Exception:
                    await query.edit_message_text(text="❌ *Erro:* Sessão foi reiniciada e mensagens foram perdidas.", parse_mode=ParseMode.MARKDOWN, reply_markup=back_keyboard)
                return
                
        try:
            if query.message.caption is not None or query.message.document:
                await query.edit_message_caption(caption=f"⏳ *Baixando e processando arquivo(s) de dados para `{folder}`...*", parse_mode=ParseMode.MARKDOWN)
            else:
                await query.edit_message_text(text=f"⏳ *Baixando e processando arquivo(s) de dados para `{folder}`...*", parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass
        
        import io
        import zipfile
        
        try:
            zip_data = io.BytesIO()
            
            if file_id:
                # Arquivo único
                file_obj = await context.bot.get_file(file_id)
                await file_obj.download_to_memory(zip_data)
            elif msg_ids_str:
                # Múltiplas partes
                ids_list = [int(x) for x in msg_ids_str.split(",")]
                for idx, mid in enumerate(ids_list, 1):
                    # Avança a mensagem enviada de forma privada para o bot recuperar o arquivo e baixar
                    fwd_msg = await context.bot.forward_message(chat_id=query.from_user.id, from_chat_id=query.from_user.id, message_id=mid)
                    chunk_file_id = fwd_msg.document.file_id
                    
                    chunk_data = io.BytesIO()
                    file_obj = await context.bot.get_file(chunk_file_id)
                    await file_obj.download_to_memory(chunk_data)
                    zip_data.write(chunk_data.getvalue())
                    
                    # Apaga a mensagem encaminhada para manter o chat limpo
                    await context.bot.delete_message(chat_id=query.from_user.id, message_id=fwd_msg.message_id)
            
            zip_data.seek(0)
            
            try:
                if query.message.caption is not None or query.message.document:
                    await query.edit_message_caption(caption=f"⏳ *Extraindo dados na pasta `{folder}`...*", parse_mode=ParseMode.MARKDOWN)
                else:
                    await query.edit_message_text(text=f"⏳ *Extraindo dados na pasta `{folder}`...*", parse_mode=ParseMode.MARKDOWN)
            except Exception:
                pass
            
            # Determina o destino da extração (se tiver pasta src, extrai nela, senão no root do projeto)
            target_base = os.path.join(folder_path, "src") if os.path.isdir(os.path.join(folder_path, "src")) else folder_path
            
            # Se a pasta de destino não existir por qualquer motivo
            if not os.path.exists(target_base):
                os.makedirs(target_base, exist_ok=True)
                
            # Extrai o zip
            with zipfile.ZipFile(zip_data, "r") as zip_ref:
                zip_ref.extractall(target_base)
                
            context.user_data.pop("import_file_id", None)
            context.user_data.pop("import_msg_ids", None)
            
            back_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar aos Projetos", callback_data="menu:projetos")]])
            success_text = (
                f"✅ *Dados importados com sucesso!*\n\n"
                f"As pastas `Data_local` e `data` foram aplicadas com sucesso em `{folder}` nesta VPS."
            )
            try:
                if query.message.caption is not None or query.message.document:
                    await query.edit_message_caption(caption=success_text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_keyboard)
                else:
                    await query.edit_message_text(text=success_text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_keyboard)
            except Exception:
                pass
            
        except Exception as e:
            back_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar aos Projetos", callback_data="menu:projetos")]])
            error_text = f"❌ *Erro ao importar e extrair os dados em `{folder}`:* `{e}`"
            try:
                if query.message.caption is not None or query.message.document:
                    await query.edit_message_caption(caption=error_text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_keyboard)
                else:
                    await query.edit_message_text(text=error_text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_keyboard)
            except Exception:
                pass

    elif action_type == "startpm2":
        # Inicia o processo no PM2 (ou cria se não existir)
        msg = await query.edit_message_text(
            f"🚀 *Iniciando `{folder}` no PM2...*",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Verifica se o processo já está registrado no PM2
        proc = pm2.get_process_by_name(folder)
        if proc:
            ok, out = pm2.start_process(folder)
        else:
            # Se não existir, criamos o processo do zero
            import asyncio
            proc_shell = await asyncio.create_subprocess_shell(
                f"pm2 start src/core/index.js --name {folder}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=folder_path,
            )
            stdout_shell, _ = await proc_shell.communicate()
            code = proc_shell.returncode
            ok = (code == 0)
            out = stdout_shell.decode(errors="replace").strip()
            
        if not ok:
            back_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data=f"proj:view:{folder}")]])
            await query.edit_message_text(
                f"❌ *Erro ao iniciar o processo `{folder}` no PM2:*\n`{out}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_keyboard
            )
            return
            
        await msg.edit_text(
            f"🚀 *Bot `{folder}` iniciado com sucesso no PM2!*\n\n"
            f"⏳ Monitorando logs para verificar o status de conexão...",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Reutiliza o loop de monitoramento de logs
        from handlers.commands import _extract_qr_lines, _render_qr_image, _strip_ansi
        
        async def run_shell(cmd, cwd=None):
            proc_shell = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd,
            )
            stdout_shell, _ = await proc_shell.communicate()
            return stdout_shell.decode(errors="replace").strip()
            
        qr_message = None
        last_qr_content = None
        max_attempts = 50  # 50 tentativas x 6 segundos = 300 segundos (5 minutos)
        connected = False
        
        for attempt in range(max_attempts):
            await asyncio.sleep(6)
            
            logs_out = await run_shell(f"pm2 logs {folder} --lines 100 --nostream")
            logs_clean = _strip_ansi(logs_out)
            
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
                
            qr_lines = _extract_qr_lines(logs_out)
            if qr_lines:
                qr_content = "\n".join(qr_lines)
                if qr_content != last_qr_content:
                    last_qr_content = qr_content
                    qr_image = _render_qr_image(qr_lines)
                    
                    if qr_image:
                        caption_text = (
                            f"📱 *Novo QR Code — {folder}*\n"
                            f"Escaneie com o seu WhatsApp para conectar o bot.\n\n"
                            f"⏳ _Código atualizado em tempo real. Tentativa {attempt + 1}/{max_attempts}_"
                        )
                        
                        if not qr_message:
                            try:
                                qr_message = await query.message.reply_photo(
                                    photo=qr_image,
                                    caption=caption_text,
                                    parse_mode=ParseMode.MARKDOWN,
                                )
                            except Exception as e:
                                import logging
                                logging.getLogger(__name__).error(f"Erro ao enviar QR Code gerado: {e}")
                        else:
                            from telegram import InputMediaPhoto
                            try:
                                await qr_message.edit_media(
                                    media=InputMediaPhoto(media=qr_image, caption=caption_text),
                                )
                            except Exception as e:
                                import logging
                                logging.getLogger(__name__).warning(f"Erro ao editar QR Code, reenviando: {e}")
                                try:
                                    qr_message = await query.message.reply_photo(
                                        photo=qr_image,
                                        caption=caption_text,
                                        parse_mode=ParseMode.MARKDOWN,
                                    )
                                except Exception as e2:
                                    logging.getLogger(__name__).error(f"Erro ao reenviar QR Code: {e2}")
                                    
        if connected:
            success_text = (
                f"✅ *Bot `{folder}` está Online!*\n\n"
                f"O processo foi iniciado no PM2 e a conexão com o WhatsApp está ativa e pronta."
            )
            if qr_message:
                try:
                    await qr_message.edit_caption(caption=success_text, parse_mode=ParseMode.MARKDOWN)
                except Exception:
                    await query.message.reply_text(success_text, parse_mode=ParseMode.MARKDOWN)
            else:
                await msg.edit_text(success_text, parse_mode=ParseMode.MARKDOWN)
        else:
            timeout_text = (
                f"⚠️ *Monitoramento Concluído — `{folder}`*\n\n"
                f"O bot foi iniciado e continua rodando no PM2 da VPS, mas o tempo limite de verificação automática do WhatsApp expirou.\n\n"
                f"Caso precise conectar ou verificar o status:\n"
                f"1. Veja os logs usando `/logs {folder}`\n"
                f"2. Se precisar de um novo QR Code, clique em `📱 Gerar QR Code` no menu do projeto."
            )
            if qr_message:
                try:
                    await qr_message.edit_caption(caption=timeout_text, parse_mode=ParseMode.MARKDOWN)
                except Exception:
                    await query.message.reply_text(timeout_text, parse_mode=ParseMode.MARKDOWN)
            else:
                await msg.edit_text(timeout_text, parse_mode=ParseMode.MARKDOWN)

    elif action_type == "qrconfirm":
        # Tela de confirmação para gerar novo QR Code
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔄 Sim, Gerar QR Code", callback_data=f"proj:qrgen:{folder}"),
                InlineKeyboardButton("❌ Cancelar", callback_data=f"proj:view:{folder}"),
            ]
        ])
        await query.edit_message_text(
            f"📱 *Gerar Novo QR Code — `{folder}`*\n\n"
            f"⚠️ *Atenção:* Isso apagará a pasta de autenticação (`auth`) do bot, desconectará a sessão atual do WhatsApp e reiniciará o processo no PM2.\n\n"
            f"Você terá que escanear um novo QR Code para conectar. Deseja continuar?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
        
    elif action_type == "qrgen":
        # Executa a limpeza da pasta auth e reinicia o PM2, iniciando o loop de monitoramento
        msg = await query.edit_message_text(
            f"🔄 *Reiniciando `{folder}`...*\n"
            f"⏳ Limpando credenciais antigas (pasta `auth`)...",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # 1. Apaga a pasta auth
        auth_path = os.path.join(folder_path, "auth")
        try:
            if os.path.exists(auth_path):
                shutil.rmtree(auth_path)
        except Exception as e:
            # Continua mesmo se falhar ao apagar (caso esteja bloqueado ou já apagado)
            pass
            
        # 2. Reinicia o processo no PM2
        ok, out = pm2.restart_process(folder)
        if not ok:
            back_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data=f"proj:view:{folder}")]])
            await query.edit_message_text(
                f"❌ *Erro ao reiniciar o processo `{folder}` no PM2:*\n`{out}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_keyboard
            )
            return
            
        await msg.edit_text(
            f"🚀 *Bot `{folder}` reiniciado com sucesso!*\n\n"
            f"⏳ Monitorando logs para extrair o novo QR Code de conexão...",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # 3. Loop assíncrono de monitoramento (WhatsApp Refresher)
        # Importamos as funções utilitárias do commands.py
        from handlers.commands import _extract_qr_lines, _render_qr_image, _strip_ansi
        
        # Helper assíncrono para rodar comandos
        async def run_shell(cmd, cwd=None):
            proc_shell = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd,
            )
            stdout_shell, _ = await proc_shell.communicate()
            return stdout_shell.decode(errors="replace").strip()
            
        qr_message = None
        last_qr_content = None
        max_attempts = 50  # 50 tentativas x 6 segundos = 300 segundos (5 minutos)
        connected = False
        
        for attempt in range(max_attempts):
            await asyncio.sleep(6)
            
            # Busca logs recentes do PM2
            logs_out = await run_shell(f"pm2 logs {folder} --lines 100 --nostream")
            logs_clean = _strip_ansi(logs_out)
            
            # Verifica se conectou
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
                
            # Tenta extrair o QR Code
            qr_lines = _extract_qr_lines(logs_out)
            if qr_lines:
                qr_content = "\n".join(qr_lines)
                
                # Se o QR Code mudou (ou é o primeiro), geramos a nova imagem
                if qr_content != last_qr_content:
                    last_qr_content = qr_content
                    qr_image = _render_qr_image(qr_lines)
                    
                    if qr_image:
                        caption_text = (
                            f"📱 *Novo QR Code — {folder}*\n"
                            f"Escaneie com o seu WhatsApp para conectar o bot.\n\n"
                            f"⏳ _Código atualizado em tempo real. Tentativa {attempt + 1}/{max_attempts}_"
                        )
                        
                        if not qr_message:
                            try:
                                # Enviamos para o chat do Telegram usando query.message
                                qr_message = await query.message.reply_photo(
                                    photo=qr_image,
                                    caption=caption_text,
                                    parse_mode=ParseMode.MARKDOWN,
                                )
                            except Exception as e:
                                import logging
                                logging.getLogger(__name__).error(f"Erro ao enviar QR Code gerado: {e}")
                        else:
                            from telegram import InputMediaPhoto
                            try:
                                await qr_message.edit_media(
                                    media=InputMediaPhoto(media=qr_image, caption=caption_text),
                                )
                            except Exception as e:
                                import logging
                                logging.getLogger(__name__).warning(f"Erro ao editar QR Code, reenviando: {e}")
                                try:
                                    qr_message = await query.message.reply_photo(
                                        photo=qr_image,
                                        caption=caption_text,
                                        parse_mode=ParseMode.MARKDOWN,
                                    )
                                except Exception as e2:
                                    logging.getLogger(__name__).error(f"Erro ao reenviar QR Code: {e2}")
                                    
        # Finalização pós-loop
        if connected:
            success_text = (
                f"✅ *WhatsApp Conectado com Sucesso!*\n\n"
                f"O bot *{folder}* foi conectado com sucesso e já está ativo e pronto no PM2 da VPS!"
            )
            if qr_message:
                try:
                    await qr_message.edit_caption(caption=success_text, parse_mode=ParseMode.MARKDOWN)
                except Exception:
                    await query.message.reply_text(success_text, parse_mode=ParseMode.MARKDOWN)
            else:
                await query.message.reply_text(success_text, parse_mode=ParseMode.MARKDOWN)
                
            await msg.edit_text(
                f"✅ *Novo QR Code de `{folder}` conectado com sucesso!*\n"
                f"Bot online e ativo.",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            timeout_text = (
                f"⚠️ *Tempo Limite de Conexão Esgotado*\n\n"
                f"Não detectamos a conexão do WhatsApp a tempo para o bot *{folder}*.\n\n"
                f"Você pode gerar um novo QR Code novamente a qualquer momento ou ver os logs usando o comando `/logs {folder}`."
            )
            if qr_message:
                try:
                    await qr_message.edit_caption(caption=timeout_text, parse_mode=ParseMode.MARKDOWN)
                except Exception:
                    await query.message.reply_text(timeout_text, parse_mode=ParseMode.MARKDOWN)
            else:
                await query.message.reply_text(timeout_text, parse_mode=ParseMode.MARKDOWN)
                
            await msg.edit_text(
                f"❌ *Geração de QR Code para `{folder}`:* Tempo limite de conexão esgotado.",
                parse_mode=ParseMode.MARKDOWN,
            )
        
    elif action_type == "delconfirm":
        # Confirmação de segurança para exclusão de pasta
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔥 Sim, Deletar Tudo", callback_data=f"proj:delete:{folder}"),
                InlineKeyboardButton("❌ Cancelar", callback_data=f"proj:view:{folder}"),
            ]
        ])
        await query.edit_message_text(
            f"⚠️ *CONFIRMAR EXCLUSÃO* ⚠️\n\n"
            f"Você tem certeza que deseja **DELETAR** permanentemente a pasta `{folder}`?\n"
            f"Caminho: `~/{folder}`\n\n"
            f"Isso removerá todos os arquivos e subpastas de forma *irreversível*!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
        
    elif action_type == "delete":
        # Realiza a exclusão e para eventuais processos PM2
        await query.edit_message_text(f"🗑️ Deletando pasta e limpando processos PM2 para `{folder}`...")
        
        # Tenta parar e remover processo PM2 com o mesmo nome se houver
        pm2.stop_process(folder)
        try:
            # Comando extra para remover o processo da lista do PM2
            del_proc = await asyncio.create_subprocess_shell(
                f"pm2 delete {folder}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            await del_proc.communicate()
        except Exception:
            pass
            
        success = False
        error_msg = ""
        try:
            if os.path.exists(folder_path):
                shutil.rmtree(folder_path)
                success = True
            else:
                error_msg = "A pasta já não existia ou o caminho está incorreto."
        except Exception as e:
            error_msg = str(e)
            
        back_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar aos Projetos", callback_data="menu:projetos")]])
        
        if success:
            await query.edit_message_text(
                f"🗑️ *Deletado com Sucesso!*\n\n"
                f"A pasta `~/{folder}` e eventuais processos PM2 vinculados foram completamente removidos da VPS.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_keyboard
            )
        else:
            await query.edit_message_text(
                f"❌ *Erro ao deletar pasta:*\n`{error_msg}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_keyboard
            )


def _format_git_pull_output(folder: str, output: str) -> str:
    """Formata a saída do git pull de forma visualmente rica e informativa."""
    if "Already up to date." in output or "Já está atualizado." in output:
        return (
            f"🟢 *Seu projeto `{folder}` já está atualizado!*\n\n"
            f"📍 *Status:* Não há novas alterações pendentes no repositório remoto."
        )
    
    # Tenta extrair estatísticas de alterações (arquivos alterados, inserções, remoções)
    files_changed = ""
    insertions = ""
    deletions = ""
    
    for line in output.splitlines():
        if "file changed" in line or "files changed" in line:
            parts = [p.strip() for p in line.split(",")]
            for p in parts:
                if "changed" in p:
                    files_changed = p
                elif "insertion" in p or "insertions" in p:
                    insertions = p
                elif "deletion" in p or "deletions" in p:
                    deletions = p
            break
            
    header = f"📥 *Git Pull Concluído — `{folder}`*\n\n"
    resumo = ""
    if files_changed:
        resumo += f"📁 *Modificados:* `{files_changed}`\n"
    if insertions:
        resumo += f"📈 *Inserções:* `{insertions}`\n"
    if deletions:
        resumo += f"📉 *Deleções:* `{deletions}`\n"
        
    if not resumo:
        resumo = "🔄 *Novos commits mesclados com sucesso!*\n"
        
    return (
        f"{header}"
        f"{resumo}\n"
        f"📋 *Saída detalhada do Git:*\n"
        f"```\n{output[:3000]}\n```"
    )
