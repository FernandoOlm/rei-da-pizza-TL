"""Informações de sistema do VPS (CPU, RAM, Disco, Uptime)."""
import platform
import subprocess
from datetime import datetime, timedelta
from utils.logger import get_logger

log = get_logger(__name__)

try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False
    log.warning("psutil não disponível — usando fallback de comandos de sistema")


def get_system_info() -> dict:
    """Retorna dicionário com métricas do sistema."""
    if _PSUTIL_AVAILABLE:
        return _from_psutil()
    return _from_commands()


def _from_psutil() -> dict:
    import psutil

    ram = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    cpu = psutil.cpu_percent(interval=1)
    boot_time = datetime.fromtimestamp(psutil.boot_time())
    uptime_delta = datetime.now() - boot_time
    uptime_str = _format_timedelta(uptime_delta)

    return {
        "ram_total_mb":  ram.total / 1024 / 1024,
        "ram_used_mb":   ram.used / 1024 / 1024,
        "ram_percent":   ram.percent,
        "cpu_percent":   cpu,
        "disk_total_gb": disk.total / 1024 / 1024 / 1024,
        "disk_used_gb":  disk.used / 1024 / 1024 / 1024,
        "disk_percent":  disk.percent,
        "uptime":        uptime_str,
        "platform":      platform.system(),
    }


def _from_commands() -> dict:
    """Fallback usando comandos Linux."""
    info = {
        "ram_total_mb": 0, "ram_used_mb": 0, "ram_percent": 0,
        "cpu_percent": 0,
        "disk_total_gb": 0, "disk_used_gb": 0, "disk_percent": 0,
        "uptime": "N/A", "platform": "Linux",
    }
    try:
        result = subprocess.run(["free", "-m"], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            if line.startswith("Mem:"):
                parts = line.split()
                info["ram_total_mb"] = float(parts[1])
                info["ram_used_mb"] = float(parts[2])
                info["ram_percent"] = round(info["ram_used_mb"] / info["ram_total_mb"] * 100, 1)

        result = subprocess.run(["df", "-h", "/"], capture_output=True, text=True)
        lines = result.stdout.strip().splitlines()
        if len(lines) >= 2:
            parts = lines[1].split()
            info["disk_total_gb"] = _parse_size_gb(parts[1])
            info["disk_used_gb"] = _parse_size_gb(parts[2])
            info["disk_percent"] = float(parts[4].replace("%", ""))

        result = subprocess.run(["uptime", "-p"], capture_output=True, text=True)
        info["uptime"] = result.stdout.strip().replace("up ", "")
    except Exception as e:
        log.error(f"Erro no fallback de sistema: {e}")

    return info


def _parse_size_gb(s: str) -> float:
    s = s.upper()
    if s.endswith("G"):
        return float(s[:-1])
    if s.endswith("T"):
        return float(s[:-1]) * 1024
    if s.endswith("M"):
        return float(s[:-1]) / 1024
    return 0.0


def _format_timedelta(td: timedelta) -> str:
    days = td.days
    hours, rem = divmod(td.seconds, 3600)
    minutes = rem // 60
    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
