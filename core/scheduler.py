"""Jobs agendados — monitoramento proativo e alertas automáticos."""
import datetime
from telegram.ext import Application
from telegram.constants import ParseMode
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import (
    OWNER_TELEGRAM_ID,
    MEMORY_ALERT_THRESHOLD_MB,
    CPU_ALERT_THRESHOLD_PERCENT,
    MONITOR_INTERVAL_SECONDS,
    CRASH_CHECK_INTERVAL_SECONDS,
    DAILY_REPORT_HOUR,
)
from services import pm2, system, gemini_ai, memory
from utils.formatter import format_system_status, format_process_table
from utils.logger import get_logger

log = get_logger(__name__)

# Rastreia alertas já enviados para evitar spam
_alerted_processes: set[str] = set()
_crash_alerted: set[str] = set()


async def _send_to_owner(app: Application, text: str, markup=None, parse_mode=ParseMode.MARKDOWN):
    """Envia mensagem diretamente ao dono do VPS."""
    if OWNER_TELEGRAM_ID == 0:
        log.warning("OWNER_TELEGRAM_ID não configurado — alerta não enviado")
        return
    try:
        await app.bot.send_message(
            chat_id=OWNER_TELEGRAM_ID,
            text=text,
            parse_mode=parse_mode,
            reply_markup=markup,
        )
    except Exception as e:
        log.error(f"Erro ao enviar mensagem ao dono: {e}")


async def job_memory_monitor(context):
    """
    Job: Monitora memória a cada MONITOR_INTERVAL_SECONDS (5 min).
    Alerta quando processo ultrapassa MEMORY_ALERT_THRESHOLD_MB.
    """
    app: Application = context.application
    processes = pm2.get_processes()

    for proc in processes:
        name = proc["name"]
        mem_mb = proc["memory_mb"]

        if mem_mb >= MEMORY_ALERT_THRESHOLD_MB:
            if name not in _alerted_processes:
                _alerted_processes.add(name)
                log.info(f"Alerta memória: {name} = {mem_mb:.1f} MB")

                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("🤖 Analisar com IA", callback_data=f"ai_suggest:{name}"),
                        InlineKeyboardButton("🧹 Limpar Logs", callback_data=f"flush:{name}"),
                    ],
                    [
                        InlineKeyboardButton("🔄 Restart", callback_data=f"restart:{name}"),
                        InlineKeyboardButton("✅ Ignorar", callback_data="cancel"),
                    ],
                ])

                await _send_to_owner(
                    app,
                    f"🚨 *Alerta de Memória!*\n\n"
                    f"Processo: *{name}*\n"
                    f"💾 Memória: `{mem_mb:.1f} MB` (limite: {MEMORY_ALERT_THRESHOLD_MB} MB)\n"
                    f"⚙️ Status: `{proc['status']}`\n"
                    f"🔄 Restarts: `{proc['restarts']}`\n\n"
                    f"_O que devo fazer, chefe?_",
                    markup=keyboard,
                )
        else:
            # Remove do conjunto de alertas quando a memória normaliza
            _alerted_processes.discard(name)


async def job_crash_monitor(context):
    """
    Job: Monitora crashes a cada CRASH_CHECK_INTERVAL_SECONDS (2 min).
    Alerta imediatamente quando processo entra em estado 'errored'.
    """
    app: Application = context.application
    processes = pm2.get_processes()

    for proc in processes:
        name = proc["name"]
        status = proc["status"]

        if status in ("errored", "stopping") and name not in _crash_alerted:
            _crash_alerted.add(name)
            log.warning(f"Crash detectado: {name} status={status}")

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔄 Restart agora", callback_data=f"restart:{name}"),
                    InlineKeyboardButton("📋 Ver Logs", callback_data=f"logs:{name}"),
                ],
                [InlineKeyboardButton("✅ Ciente", callback_data="cancel")],
            ])

            await _send_to_owner(
                app,
                f"💥 *CRASH DETECTADO!*\n\n"
                f"Processo: *{name}* está `{status}`\n"
                f"🔄 Restarts totais: `{proc['restarts']}`\n"
                f"⏱ Uptime: `{proc['uptime']}`\n\n"
                f"_Preciso reiniciar, chefe?_",
                markup=keyboard,
            )
        elif status == "online":
            _crash_alerted.discard(name)


async def job_cpu_monitor(context):
    """Monitora CPU do sistema."""
    app: Application = context.application
    sys_info = system.get_system_info()
    cpu = sys_info.get("cpu_percent", 0)

    if cpu >= CPU_ALERT_THRESHOLD_PERCENT:
        log.warning(f"CPU alta: {cpu:.1f}%")
        await _send_to_owner(
            app,
            f"🔥 *CPU Alta no VPS!*\n\n"
            f"⚙️ CPU: `{cpu:.1f}%` (limite: {CPU_ALERT_THRESHOLD_PERCENT}%)\n"
            f"🧠 RAM: `{sys_info['ram_used_mb']:.0f} / {sys_info['ram_total_mb']:.0f} MB`\n\n"
            f"_Use /status para ver quais processos estão causando isso._",
        )


async def job_daily_report(context):
    """Job diário: relatório completo de saúde do VPS."""
    app: Application = context.application
    log.info("Enviando relatório diário...")

    processes = pm2.get_processes()
    sys_info = system.get_system_info()

    sys_text = format_system_status(sys_info)
    proc_text = format_process_table(processes)
    total_mem = sum(p["memory_mb"] for p in processes)

    analysis = await gemini_ai.analyze_vps(processes, sys_info)
    if len(analysis) > 1500:
        analysis = analysis[:1500] + "..."

    report = (
        f"☀️ *Bom dia, chefe! Relatório diário do VPS:*\n\n"
        f"{sys_text}\n"
        f"📦 Total memória PM2: `{total_mem:.1f} MB`\n\n"
        f"---\n\n"
        f"🤖 *Análise do Estagiário:*\n{analysis}"
    )

    if len(report) > 4000:
        report = report[:4000] + "\n\n_[Truncado — use /analise para ver completo]_"

    await _send_to_owner(app, report)


def register_jobs(app: Application):
    """Registra todos os jobs agendados no JobQueue do PTB."""
    jq = app.job_queue

    # Monitoramento de memória — a cada 5 minutos
    jq.run_repeating(
        job_memory_monitor,
        interval=MONITOR_INTERVAL_SECONDS,
        first=30,  # Primeira checagem 30s após iniciar
        name="memory_monitor",
    )

    # Monitoramento de crashes — a cada 2 minutos
    jq.run_repeating(
        job_crash_monitor,
        interval=CRASH_CHECK_INTERVAL_SECONDS,
        first=15,
        name="crash_monitor",
    )

    # Monitoramento de CPU — junto com memória
    jq.run_repeating(
        job_cpu_monitor,
        interval=MONITOR_INTERVAL_SECONDS,
        first=60,
        name="cpu_monitor",
    )

    # Relatório diário — todo dia no horário configurado
    jq.run_daily(
        job_daily_report,
        time=datetime.time(hour=DAILY_REPORT_HOUR, minute=0),
        name="daily_report",
    )

    log.info(
        f"✅ Jobs registrados: memória/CPU a cada {MONITOR_INTERVAL_SECONDS}s, "
        f"crashes a cada {CRASH_CHECK_INTERVAL_SECONDS}s, "
        f"relatório diário às {DAILY_REPORT_HOUR}h"
    )
