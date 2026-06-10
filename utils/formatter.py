"""Formatação de mensagens para o Telegram (MarkdownV2 safe)."""
from typing import Any


def escape_md(text: str) -> str:
    """Escapa caracteres especiais do MarkdownV2 do Telegram."""
    special = r"\_*[]()~`>#+-=|{}.!"
    for ch in special:
        text = text.replace(ch, f"\\{ch}")
    return text


def format_process_table(processes: list[dict]) -> str:
    """Formata lista de processos PM2 como tabela Telegram-friendly."""
    if not processes:
        return "📭 Nenhum processo PM2 encontrado."

    lines = ["📊 *Status dos Processos PM2*\n"]
    for p in processes:
        status_icon = {
            "online":  "🟢",
            "stopped": "🔴",
            "errored": "💥",
            "stopping": "🟡",
        }.get(p.get("status", ""), "⚪")

        mem_mb = p.get("memory_mb", 0)
        mem_icon = "🔥" if mem_mb > 400 else "💾"

        lines.append(
            f"{status_icon} *{p['name']}*\n"
            f"  {mem_icon} Memória: `{mem_mb:.1f} MB` | CPU: `{p.get('cpu', 0):.1f}%`\n"
            f"  🔄 Restarts: `{p.get('restarts', 0)}` | ⏱ Uptime: `{p.get('uptime', 'N/A')}`\n"
        )

    return "\n".join(lines)


def format_system_status(sys_info: dict) -> str:
    """Formata informações gerais do sistema."""
    return (
        f"🖥️ *Status do VPS*\n\n"
        f"🧠 RAM: `{sys_info['ram_used_mb']:.0f} MB / {sys_info['ram_total_mb']:.0f} MB` "
        f"({sys_info['ram_percent']:.1f}%)\n"
        f"⚙️ CPU: `{sys_info['cpu_percent']:.1f}%`\n"
        f"💿 Disco: `{sys_info['disk_used_gb']:.1f} GB / {sys_info['disk_total_gb']:.1f} GB` "
        f"({sys_info['disk_percent']:.1f}%)\n"
        f"⏳ Uptime: `{sys_info['uptime']}`\n"
    )


def bytes_to_mb(b: int) -> float:
    return b / (1024 * 1024)


def format_uptime(ms: int) -> str:
    """Converte milissegundos de uptime em string legível."""
    if ms <= 0:
        return "N/A"
    seconds = ms // 1000
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
