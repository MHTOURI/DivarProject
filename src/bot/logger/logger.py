import os
from collections import deque
from datetime import datetime
from typing import Dict, List, Optional

from rich.console import Console
from rich.text import Text

# ======================================================
# Setup
# ======================================================

console = Console()

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "crawler.log")

# برای نگهداری لاگ‌های اخیر (برای API و SocketIO)
_recent_logs = deque(maxlen=300)


# ======================================================
# SocketIO (اختیاری)
# ======================================================

_socketio = None


def init_logger(socketio=None):
    """این تابع را از app.py صدا بزن تا لاگ‌ها به مرورگر هم بروند"""
    global _socketio
    _socketio = socketio


# ======================================================
# Main Log Function
# ======================================================


def log(message: str, level: str = "INFO"):
    """
    لاگ اصلی برنامه
    level می‌تواند: INFO, SUCCESS, WARNING, ERROR باشد
    """
    now = datetime.now()
    time_str = now.strftime("%Y-%m-%d %H:%M:%S")
    short_time = now.strftime("%H:%M:%S")

    line = f"[{time_str}] [{level}] {message}"

    # ---------- Console (Rich) ----------
    if level == "ERROR":
        style = "bold red"
    elif level == "WARNING":
        style = "yellow"
    elif level == "SUCCESS":
        style = "bold green"
    else:
        style = "cyan"

    console.print(Text(line, style=style))

    # ---------- File ----------
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

    # ---------- Memory (برای API) ----------
    log_entry = {
        "time": short_time,
        "level": level,
        "message": message,
    }
    _recent_logs.appendleft(log_entry)

    # ---------- SocketIO (ارسال به فرانت) ----------
    if _socketio:
        try:
            _socketio.emit("log", log_entry)
        except Exception:
            pass


# ======================================================
# Helper Functions
# ======================================================


def get_logs(limit: int = 100) -> List[Dict]:
    """آخرین لاگ‌ها را برمی‌گرداند (برای API)"""
    return list(_recent_logs)[:limit]


def clear_logs():
    """پاک کردن لاگ‌های حافظه"""
    _recent_logs.clear()
