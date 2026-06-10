import os
from dotenv import load_dotenv

load_dotenv()

# ─── Telegram ─────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
OWNER_TELEGRAM_ID: int = int(os.getenv("OWNER_TELEGRAM_ID", "0"))

# ─── Gemini AI ──────────────────────────────────────────────────────────────────────────────
GEMINI_API_KEY: str    = os.getenv("GEMINI_API_KEY", "")
GEMINI_TEXT_MODEL: str  = "gemini-1.5-flash"

# ─── Thresholds ───────────────────────────────────────────────────────────────
MEMORY_ALERT_THRESHOLD_MB: int = int(os.getenv("MEMORY_ALERT_THRESHOLD_MB", "500"))
CPU_ALERT_THRESHOLD_PERCENT: float = float(os.getenv("CPU_ALERT_THRESHOLD_PERCENT", "85"))

# ─── Scheduler ────────────────────────────────────────────────────────────────
MONITOR_INTERVAL_SECONDS: int = int(os.getenv("MONITOR_INTERVAL_SECONDS", "600"))
CRASH_CHECK_INTERVAL_SECONDS: int = int(os.getenv("CRASH_CHECK_INTERVAL_SECONDS", "120"))
DAILY_REPORT_HOUR: int = int(os.getenv("DAILY_REPORT_HOUR", "8"))

# ─── GitHub ───────────────────────────────────────────────────────────────────
GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")

# ─── Outra VPS ────────────────────────────────────────────────────────────────
OTHER_BOT_USERNAME: str = os.getenv("OTHER_BOT_USERNAME", "")
OTHER_BOT_TOKEN: str = os.getenv("OTHER_BOT_TOKEN", "")

