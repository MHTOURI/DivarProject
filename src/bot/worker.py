"""
worker.py — سرویس مستقل اسکرپر

این پروسه کاملاً جدا از وب‌پنل (app.py) اجرا می‌شود. ارتباط بین این دو فقط از طریق
دیتابیس SQLite (جدول settings) انجام می‌شود؛ یعنی هرکدام را می‌شود جدا بالا/پایین
آورد، جدا ری‌استارت کرد، یا حتی روی دو ماشین/کانتینر متفاوت اجرا کرد (اگر DB_PATH
به یک فایل مشترک/شبکه‌ای اشاره کند).

اجرا:
    python worker.py

برای اجرای دائمی روی سرور، به‌عنوان یک سرویس systemd جدا از وب‌پنل تعریفش کن
(نمونه‌ی فایل سرویس در deploy/divar-worker.service آمده).
"""

import asyncio
import time
import traceback

from bot.database import (
    get_scraper_command,
    init_db,
    set_worker_status,
    touch_worker_heartbeat,
)
from bot.export_excel import export_links_txt, export_to_excel
from bot.logger.logger import log
from bot.scraper import DivarScraper

POLL_INTERVAL = 2  # هر چند ثانیه دستور start/stop را چک کند
HEARTBEAT_INTERVAL = 5  # هر چند ثانیه heartbeat بزند
IDLE_SLEEP_STEP = 1  # حین اسکرپینگ، هر چند ثانیه چک کند که دستور stop نیامده
EXPORT_MIN_INTERVAL = (
    300  # حداقل فاصله بین دو خروجی خودکار (ثانیه) — نه بعد از هر آگهی جدید
)

_last_export_at = 0.0


def log_error(prefix: str, exc: Exception):
    """لاگ خطا هم با پیام کوتاه هم traceback کامل، تا دقیقاً بشه فهمید ارور از کجا اومده"""
    log(f"❌ {prefix}: {exc}", "ERROR")
    for line in traceback.format_exc().strip().split("\n"):
        log(f"    {line}", "ERROR")


async def heartbeat_loop():
    tick = 0
    while True:
        try:
            await touch_worker_heartbeat()
            tick += 1
            if tick % 6 == 0:  # هر ~۳۰ ثانیه یک بار (برای این‌که لاگ شلوغ نشه)
                log(f"💓 Heartbeat OK (tick {tick})", "INFO")
        except Exception as e:
            log_error("Heartbeat failed", e)
        await asyncio.sleep(HEARTBEAT_INTERVAL)


async def maybe_export():
    """
    قبلاً بعد از هر batch آگهی جدید، کل فایل اکسل از صفر ساخته می‌شد — با بزرگ‌شدن
    دیتابیس این کار کندتر و کندتر می‌شد و چون openpyxl عملیات سنگین و synchronous
    است، در همون لحظه کل event loop (و در نتیجه fetch/heartbeat/بررسی دستور stop)
    فریز می‌شد. حالا دو کار انجام می‌شود:
      ۱) خروجی خودکار حداکثر هر EXPORT_MIN_INTERVAL ثانیه یک‌بار (نه هر چرخه)
      ۲) با asyncio.to_thread در یک ترد جدا اجرا می‌شود تا event loop اصلی بلاک نشود
    """
    global _last_export_at
    now = time.monotonic()
    remaining = EXPORT_MIN_INTERVAL - (now - _last_export_at)
    if remaining > 0:
        log(f"⏭ Auto-export skipped (throttled, {int(remaining)}s remaining)", "INFO")
        return
    _last_export_at = now

    log("📊 Auto-export starting (excel + links)...", "INFO")
    try:
        await asyncio.to_thread(_export_sync)
        log("✅ Auto-export finished successfully", "SUCCESS")
    except Exception as e:
        log_error("Auto-export failed", e)


def _export_sync():
    # این توابع async هستند ولی داخلشان فقط I/O روی aiosqlite دارند؛ برای این‌که
    # از یک ترد معمولی صدا زده شوند، هرکدام یک event loop کوچک مخصوص خودشان می‌سازند
    asyncio.run(export_to_excel())
    asyncio.run(export_links_txt())


async def scraping_session():
    """یک نشست کامل اسکرپینگ؛ تا وقتی دستور 'stop' نیاید ادامه می‌دهد."""
    await set_worker_status(True)
    log("🚀 Worker: scraping session started", "SUCCESS")

    cycle = 0
    try:
        log("🔌 Opening HTTP session...", "INFO")
        async with DivarScraper() as scraper:
            log("✅ HTTP session ready, entering monitor loop", "SUCCESS")

            while (await get_scraper_command()) == "start":
                cycle += 1
                log(f"🔄 Cycle #{cycle}: calling monitor_once()...", "INFO")
                try:
                    count = await scraper.monitor_once()
                    log(
                        f"🔄 Cycle #{cycle}: monitor_once() done → {count} آگهی جدید",
                        "INFO",
                    )
                except Exception as e:
                    log_error(f"Cycle #{cycle}: monitor_once() raised an exception", e)
                    count = 0

                if count > 0:
                    await maybe_export()

                log(
                    f"😴 Cycle #{cycle}: idling up to {30 * IDLE_SLEEP_STEP}s (checking stop command every {IDLE_SLEEP_STEP}s)",
                    "INFO",
                )
                for _ in range(30):
                    if (await get_scraper_command()) != "start":
                        log(
                            f"🛑 Stop command detected during idle wait (cycle #{cycle})",
                            "WARNING",
                        )
                        break
                    await asyncio.sleep(IDLE_SLEEP_STEP)
    except Exception as e:
        log_error("scraping_session crashed", e)
    finally:
        await set_worker_status(False)
        log("🛑 Worker: scraping session stopped", "WARNING")


async def main():
    log("🟢 Divar worker process starting (independent of web panel)", "SUCCESS")

    try:
        await init_db()
        log("✅ Database initialized/migrated OK", "SUCCESS")
    except Exception as e:
        log_error("init_db() failed — worker cannot continue", e)
        raise

    asyncio.create_task(heartbeat_loop())
    log("💓 Heartbeat task launched", "INFO")

    last_command = None
    while True:
        try:
            command = await get_scraper_command()
        except Exception as e:
            log_error("Failed to read scraper command from DB", e)
            await asyncio.sleep(POLL_INTERVAL)
            continue

        if command != last_command:
            log(f"📡 Command changed: '{last_command}' → '{command}'", "INFO")
            last_command = command

        if command == "start":
            await scraping_session()
            last_command = "stop"  # چرخه تمام شد، دوباره در حالت انتظار
        else:
            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("Worker stopped by user (Ctrl+C)", "WARNING")
    except Exception as e:
        log_error("Worker crashed at top level", e)
        raise
