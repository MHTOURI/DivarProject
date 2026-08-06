import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import aiosqlite

from bot.config import DB_PATH


@asynccontextmanager
async def get_db():
    db = await aiosqlite.connect(DB_PATH, timeout=15)
    db.row_factory = aiosqlite.Row
    # WAL: اجازه می‌دهد دو پروسه (وب‌پنل و worker اسکرپر) هم‌زمان
    # به یک فایل SQLite بنویسند/بخوانند بدون قفل شدن روی هم
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=15000")
    try:
        yield db
    finally:
        await db.close()


async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with get_db() as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS ads (
                token TEXT PRIMARY KEY,
                title TEXT,
                seo_title TEXT,
                url TEXT,
                district TEXT,
                text TEXT,
                special INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_ads_created ON ads(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_ads_district ON ads(district);
            CREATE INDEX IF NOT EXISTS idx_ads_special ON ads(special);
        """)
        # migration for older DBs missing seo_title
        try:
            await db.execute("ALTER TABLE ads ADD COLUMN seo_title TEXT")
        except Exception:
            pass
        await db.commit()


# ---------- Settings ----------
async def get_setting(key: str, default: Any = None) -> Any:
    async with get_db() as db:
        async with db.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
            return row["value"] if row else default


async def set_setting(key: str, value: Any):
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
            (key, str(value)),
        )
        await db.commit()


# ---------- Ads ----------
async def is_seen(token: str) -> bool:
    async with get_db() as db:
        async with db.execute("SELECT 1 FROM ads WHERE token = ?", (token,)) as cur:
            return await cur.fetchone() is not None


async def mark_seen(
    token: str,
    title: str,
    url: str,
    district: str,
    text: str,
    special: int,
    seo_title: str = "",
):
    async with get_db() as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO ads (token, title, seo_title, url, district, text, special)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (token, title, seo_title, url, district, text, special),
        )
        await db.commit()


async def get_stats() -> Dict:
    async with get_db() as db:
        async with db.execute("SELECT COUNT(*) as total FROM ads") as cur:
            total = (await cur.fetchone())["total"]
        async with db.execute(
            "SELECT COUNT(*) as special FROM ads WHERE special = 1"
        ) as cur:
            special = (await cur.fetchone())["special"]
        return {"total": total, "special": special, "filtered": 0, "runtime": "—"}


async def get_all_ads(
    search: str = None, district: str = None, limit: int = 100
) -> List[Dict]:
    query = "SELECT token, title, seo_title, url, district, text, special, created_at FROM ads WHERE 1=1"
    params = []

    if search:
        query += " AND (title LIKE ? OR district LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    if district:
        query += " AND district = ?"
        params.append(district)

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    async with get_db() as db:
        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()
            return [dict(row) for row in rows]


async def get_districts() -> List[Dict]:
    async with get_db() as db:
        async with db.execute("""
            SELECT district, COUNT(*) as count
            FROM ads
            WHERE district IS NOT NULL AND district != ''
            GROUP BY district
            ORDER BY count DESC
        """) as cur:
            rows = await cur.fetchall()
            return [dict(row) for row in rows]


async def get_user_by_id(user_id):

    async with get_db() as db:

        async with db.execute(
            """
            SELECT
                id,
                username,
                is_active
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ) as cur:

            row = await cur.fetchone()

            return dict(row) if row else None


# ---------- Users ----------
async def create_admin_user(username: str, password_hash: str) -> bool:
    async with get_db() as db:
        try:
            await db.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, password_hash),
            )
            await db.commit()
            return True
        except Exception:
            return False


async def get_user_by_username(username: str) -> Optional[Dict]:
    async with get_db() as db:
        async with db.execute(
            "SELECT id, username, password_hash, is_active FROM users WHERE username = ?",
            (username,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def update_last_login(user_id: int):
    async with get_db() as db:
        await db.execute(
            "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?", (user_id,)
        )
        await db.commit()


async def change_password(user_id: int, new_hash: str):
    """تغییر رمز عبور کاربر"""
    async with get_db() as db:
        await db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id)
        )
        await db.commit()


# ======================================================
# Scraper control (اشتراکی بین وب‌پنل و worker مستقل)
# دیگر state داخل حافظه‌ی پروسه‌ی Flask نگه‌داری نمی‌شود؛
# از جدول settings به‌عنوان یک کانال ارتباطی ساده استفاده می‌شود.
# ======================================================


async def get_scraper_command() -> str:
    """'start' یا 'stop' — دستوری که پنل به worker می‌دهد"""
    return await get_setting("scraper_command", "stop")


async def set_scraper_command(command: str):
    await set_setting("scraper_command", command)


async def set_worker_status(running: bool):
    await set_setting("scraper_running", "1" if running else "0")


async def touch_worker_heartbeat():
    import datetime

    await set_setting("worker_heartbeat", datetime.datetime.utcnow().isoformat())


async def get_worker_status() -> Dict[str, Any]:
    """وضعیت واقعی worker: در حال اجرا و آخرین ضربان (heartbeat)"""
    import datetime

    running = (await get_setting("scraper_running", "0")) == "1"
    heartbeat_raw = await get_setting("worker_heartbeat")
    alive = False
    if heartbeat_raw:
        try:
            last = datetime.datetime.fromisoformat(heartbeat_raw)
            alive = (datetime.datetime.utcnow() - last).total_seconds() < 20
        except Exception:
            alive = False
    return {"running": running and alive, "worker_alive": alive}


# ======================================================
# مدیریت کاربران (پنل ادمین)
# ======================================================


async def list_users() -> List[Dict]:
    async with get_db() as db:
        async with db.execute(
            "SELECT id, username, is_active, created_at, last_login FROM users ORDER BY created_at ASC"
        ) as cur:
            rows = await cur.fetchall()
            return [dict(row) for row in rows]


async def count_active_users() -> int:
    async with get_db() as db:
        async with db.execute(
            "SELECT COUNT(*) as c FROM users WHERE is_active = 1"
        ) as cur:
            row = await cur.fetchone()
            return row["c"]


async def set_user_active(user_id: int, active: bool):
    async with get_db() as db:
        await db.execute(
            "UPDATE users SET is_active = ? WHERE id = ?", (1 if active else 0, user_id)
        )
        await db.commit()


async def delete_user_db(user_id: int):
    async with get_db() as db:
        await db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        await db.commit()
