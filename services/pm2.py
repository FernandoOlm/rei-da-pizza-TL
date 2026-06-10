"""Wrapper para comandos PM2 via subprocess."""
import json
import subprocess
import re
from typing import Any
from utils.formatter import bytes_to_mb, format_uptime
from utils.logger import get_logger

log = get_logger(__name__)

_ANSI_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
_PM2_PREFIX_RE = re.compile(r'^\s*\d+\|[\w_.-]+\s*\|\s*(?:\d{4}-\d{2}-\d{2} (\d{2}:\d{2}:\d{2}):?\s*)?')

def _run(cmd: list[str], timeout: int = 15) -> tuple[bool, str]:
    """Executa um comando de sistema e retorna (sucesso, output)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return False, result.stderr.strip() or "Erro desconhecido"
        return True, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "⏰ Timeout ao executar comando PM2"
    except FileNotFoundError:
        return False, "❌ PM2 não encontrado. Verifique se está instalado no PATH."
    except Exception as e:
        return False, str(e)


def get_processes() -> list[dict[str, Any]]:
    """
    Retorna lista de processos PM2 com métricas.
    Usa `pm2 jlist` que retorna JSON completo.
    """
    ok, output = _run(["pm2", "jlist"])
    if not ok:
        log.error(f"pm2 jlist falhou: {output}")
        return []

    try:
        raw: list[dict] = json.loads(output)
    except json.JSONDecodeError as e:
        log.error(f"Falha ao parsear JSON do pm2 jlist: {e}")
        return []

    processes = []
    for proc in raw:
        monit = proc.get("monit", {})
        pm2_env = proc.get("pm2_env", {})

        processes.append({
            "name":      proc.get("name", "unknown"),
            "pid":       proc.get("pid", 0),
            "status":    pm2_env.get("status", "unknown"),
            "memory_mb": bytes_to_mb(monit.get("memory", 0)),
            "cpu":       monit.get("cpu", 0.0),
            "restarts":  pm2_env.get("restart_time", 0),
            "uptime":    format_uptime(pm2_env.get("pm_uptime", 0)),
            "pm_id":     proc.get("pm_id", 0),
            "log_path":  pm2_env.get("pm_out_log_path", ""),
            "err_path":  pm2_env.get("pm_err_log_path", ""),
        })

    return processes


def get_process_by_name(name: str) -> dict | None:
    """Busca um processo específico pelo nome."""
    return next((p for p in get_processes() if p["name"] == name), None)


def get_my_process_name() -> str | None:
    """Retorna o nome do processo PM2 atual (baseado no PID do bot)."""
    import os
    pid = os.getpid()
    for p in get_processes():
        if p["pid"] == pid:
            return p["name"]
    return os.getenv("name")


def restart_process(name: str) -> tuple[bool, str]:
    """Reinicia um processo PM2."""
    ok, out = _run(["pm2", "restart", name])
    log.info(f"Restart '{name}': {'OK' if ok else 'ERRO'} — {out}")
    return ok, out


def stop_process(name: str) -> tuple[bool, str]:
    """Para um processo PM2."""
    ok, out = _run(["pm2", "stop", name])
    log.info(f"Stop '{name}': {'OK' if ok else 'ERRO'} — {out}")
    return ok, out


def delete_process(name: str) -> tuple[bool, str]:
    """Remove um processo do PM2."""
    ok, out = _run(["pm2", "delete", name])
    log.info(f"Delete '{name}': {'OK' if ok else 'ERRO'} — {out}")
    return ok, out


def flush_logs(name: str | None = None) -> tuple[bool, str]:
    """Limpa logs de um processo (ou todos se name=None)."""
    cmd = ["pm2", "flush"]
    if name:
        cmd.append(name)
    ok, out = _run(cmd)
    target = name or "todos"
    log.info(f"Flush logs '{target}': {'OK' if ok else 'ERRO'} — {out}")
    return ok, out


def get_logs(name: str, lines: int = 30) -> str:
    """Retorna as últimas N linhas de log de um processo."""
    ok, out = _run(["pm2", "logs", name, "--lines", str(lines), "--nostream"], timeout=10)
    if not ok:
        return f"❌ Erro ao buscar logs: {out}"
    if not out:
        return "📭 Sem logs disponíveis."
        
    out = _ANSI_RE.sub('', out)
    
    final_lines = []
    for line in out.splitlines():
        if "[TAILING]" in line or "pm2 logs" in line:
            continue
            
        line = line.strip()
        if not line:
            continue
            
        match = _PM2_PREFIX_RE.search(line)
        if match:
            hora = match.group(1)
            line = _PM2_PREFIX_RE.sub(f"[{hora}] " if hora else "", line)
            
        lower_line = line.lower()
        if "error" in lower_line or "exception" in lower_line or "falha" in lower_line or "fail" in lower_line or "syntaxerror" in lower_line:
            line = f"🔴 {line}"
        elif "warning" in lower_line or "warn" in lower_line:
            line = f"🟠 {line}"
        elif "success" in lower_line or "concluído" in lower_line or "ok" in lower_line:
            line = f"🟢 {line}"
        else:
            line = f"ℹ️ {line}"
            
        final_lines.append(line)

    return "\n".join(final_lines[-lines:]) if final_lines else "📭 Sem logs úteis disponíveis após filtragem."


def save_pm2() -> tuple[bool, str]:
    """Salva o estado atual do PM2 (pm2 save)."""
    return _run(["pm2", "save"])
