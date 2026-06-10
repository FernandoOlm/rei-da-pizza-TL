"""Análise de memória dos processos PM2."""
from services.pm2 import get_processes
from config import MEMORY_ALERT_THRESHOLD_MB


def get_memory_report() -> dict:
    """
    Retorna relatório completo de memória dos processos PM2.
    """
    processes = get_processes()
    if not processes:
        return {"total_mb": 0, "processes": [], "alerts": []}

    total = sum(p["memory_mb"] for p in processes)
    alerts = [p for p in processes if p["memory_mb"] >= MEMORY_ALERT_THRESHOLD_MB]

    sorted_procs = sorted(processes, key=lambda x: x["memory_mb"], reverse=True)

    return {
        "total_mb": total,
        "processes": sorted_procs,
        "alerts": alerts,
        "threshold_mb": MEMORY_ALERT_THRESHOLD_MB,
    }


def format_memory_report(report: dict) -> str:
    """Formata o relatório de memória para o Telegram."""
    lines = [f"🧠 *Relatório de Memória PM2*\n"]
    lines.append(f"📦 Total consumido: `{report['total_mb']:.1f} MB`")
    lines.append(f"⚠️ Alerta acima de: `{report['threshold_mb']} MB`\n")

    for p in report["processes"]:
        bar = _memory_bar(p["memory_mb"], report["threshold_mb"])
        flag = " 🚨" if p["memory_mb"] >= report["threshold_mb"] else ""
        lines.append(
            f"{bar} *{p['name']}*{flag}\n"
            f"  `{p['memory_mb']:.1f} MB` | Status: {p['status']}\n"
        )

    if report["alerts"]:
        lines.append(f"\n🔴 *{len(report['alerts'])} processo(s) acima do threshold!*")
        lines.append("Use /limpar \\[nome\\] para liberar memória\\.")

    return "\n".join(lines)


def _memory_bar(mb: float, threshold: float) -> str:
    """Mini barra visual de memória."""
    ratio = min(mb / max(threshold, 1), 1.0)
    filled = int(ratio * 8)
    bar = "█" * filled + "░" * (8 - filled)
    return f"[{bar}]"
