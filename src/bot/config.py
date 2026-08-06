import os
import uuid

from dotenv import load_dotenv
from fake_useragent import UserAgent

load_dotenv()

# ======================================================
# Paths
# ======================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(BASE_DIR, "data")
EXPORT_DIR = os.path.join(BASE_DIR, "exports")
LOG_DIR = os.path.join(BASE_DIR, "logs")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(EXPORT_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "divar.db")

# ======================================================
# Security
# ======================================================

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    import secrets

    SECRET_KEY = secrets.token_hex(32)
    print(
        "\n[WARNING] SECRET_KEY تنظیم نشده؛ یک مقدار تصادفی موقت ساخته شد.\n"
        "این یعنی با هر ری‌استارت سرور همه‌ی نشست‌های کاربران باطل می‌شوند.\n"
        "برای پروداکشن، در فایل .env مقدار زیر را ثابت تنظیم کنید:\n"
        f"SECRET_KEY={secrets.token_hex(32)}\n"
    )

# آیا اپ پشت HTTPS اجرا می‌شود؟ (روی سرور واقعی حتماً True کنید)
FORCE_HTTPS = os.environ.get("FORCE_HTTPS", "false").lower() == "true"

# ======================================================
# Divar API
# ======================================================

SEARCH_URL = "https://api.divar.ir/v8/postlist/w/search"

HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://divar.ir",
    "Referer": "https://divar.ir/",
}


def get_cookies():
    return {
        "did": str(uuid.uuid4()),
        "cdid": str(uuid.uuid4()),
    }


# ======================================================
# User-Agent (با استفاده از fake_useragent)
# ======================================================

_ua = UserAgent()


def get_random_user_agent() -> str:
    """یک User-Agent تصادفی و واقعی برمی‌گرداند"""
    try:
        return _ua.random
    except Exception:
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )


# ======================================================
# Search Filter
# ======================================================

SEARCH_FILTERS = {
    "form_data": {
        "data": {
            "business-type": {"repeated_string": {"value": ["personal"]}},
            "category": {"str": {"value": "residential-rent"}},
            "districts": {
                "repeated_string": {
                    "value": [
                        "178",
                        "4148",
                        "4177",
                        "4184",
                        "4179",
                        "4178",
                        "179",
                        "175",
                        "910",
                    ]
                }
            },
        }
    },
    "server_payload": {
        "@type": "type.googleapis.com/widgets.SearchData.ServerPayload",
        "additional_form_data": {"data": {"sort": {"str": {"value": "sort_date"}}}},
    },
}

# ======================================================
# Scraper Settings
# ======================================================

MAX_CONCURRENCY = 3
REQUEST_TIMEOUT = 35
MAX_RETRY = 6

RATE_LIMIT_BASE = 10
RATE_LIMIT_MAX = 300

DEFAULT_DAILY_PAGES = 0
DEFAULT_MONITOR_INTERVAL = 30

# Proxy (مثال)
PROXIES = [
    # "http://127.0.0.1:8080",
]

# ======================================================
# Ignore Keywords
# ======================================================

IGNORE_KEYWORDS = [
    "همخانه",
    "هم خانه",
    "هم‌خانه",
    "همخونه",
    "هم خونه",
    "هم‌خونه",
    "هم اتاق",
    "هم‌اتاق",
    "هماتاق",
]

# ======================================================
# Agency Filter
# ======================================================

AGENCY_BLOCKED_WORDS = [
    "املاک",
    "مشاور املاک",
    "مشاورین املاک",
    "بنگاه",
    "دفتر املاک",
    "آژانس املاک",
    "فایل",
    "فایلینگ",
    "فایل ویژه",
    "مشاور",
    "کارشناس",
    "تماس بگیرید",
    "هماهنگی بازدید",
    "بازدید",
    "رهن و اجاره",
    "خرید و فروش",
    "مسکن",
    "همکار",
]
