#!/usr/bin/env python3
import asyncio

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from bot.auth import hash_password, verify_password
from bot.config import DEFAULT_DAILY_PAGES, DEFAULT_MONITOR_INTERVAL
from bot.database import (
    change_password,
    create_admin_user,
    get_setting,
    get_user_by_username,
    init_db,
    set_setting,
)

app = typer.Typer(help="Divar Crawler Admin CLI")
console = Console()


def ok(msg):
    console.print(f"[green]✓[/green] {msg}")


def err(msg):
    console.print(f"[red]✗[/red] {msg}")


@app.command()
def create_admin(username: str = "admin"):
    """ساخت ادمین"""

    async def run():
        await init_db()
        if await get_user_by_username(username):
            err("کاربر از قبل وجود دارد")
            raise typer.Exit(1)
        password = Prompt.ask("رمز عبور", password=True)
        await create_admin_user(username, hash_password(password))
        ok(f"ادمین {username} ساخته شد")

    asyncio.run(run())


@app.command("change-password")
def change_password_cmd(username: str = typer.Option("admin", help="نام کاربری")):
    """تغییر رمز عبور ادمین"""

    async def _run():
        await init_db()

        user = await get_user_by_username(username)
        if not user:
            err(f"کاربر «{username}» یافت نشد")
            raise typer.Exit(1)

        current = Prompt.ask("رمز فعلی", password=True)
        if not verify_password(user["password_hash"], current):
            err("رمز فعلی اشتباه است")
            raise typer.Exit(1)

        new_pass = Prompt.ask("رمز جدید", password=True)
        confirm = Prompt.ask("تکرار رمز جدید", password=True)

        if new_pass != confirm:
            err("رمزها با هم مطابقت ندارند")
            raise typer.Exit(1)

        if len(new_pass) < 8:
            err("رمز باید حداقل ۸ کاراکتر باشد")
            raise typer.Exit(1)

        # اینجا از تابع دیتابیس استفاده می‌کنیم
        from bot.database import change_password as db_change_password

        new_hash = hash_password(new_pass)
        await db_change_password(user["id"], new_hash)

        ok("رمز عبور با موفقیت تغییر کرد")

    asyncio.run(_run())


@app.command()
def settings():
    """نمایش تنظیمات"""

    async def run():
        await init_db()
        table = Table(title="تنظیمات")
        table.add_column("کلید")
        table.add_column("مقدار")
        table.add_row("monitor", await get_setting("monitor", "1"))
        table.add_row(
            "monitor_interval",
            await get_setting("monitor_interval", str(DEFAULT_MONITOR_INTERVAL)),
        )
        table.add_row(
            "daily_pages", await get_setting("daily_pages", str(DEFAULT_DAILY_PAGES))
        )
        console.print(table)

    asyncio.run(run())


@app.command()
def set(key: str, value: str):
    """تغییر تنظیم (monitor / monitor_interval / daily_pages)"""
    if key not in {"monitor", "monitor_interval", "daily_pages"}:
        err("کلید نامعتبر")
        raise typer.Exit(1)

    async def run():
        await init_db()
        await set_setting(key, value)
        ok(f"{key} → {value}")

    asyncio.run(run())


@app.command()
def status():
    """وضعیت سیستم"""

    async def run():
        await init_db()
        monitor = await get_setting("monitor", "1")
        interval = await get_setting("monitor_interval", str(DEFAULT_MONITOR_INTERVAL))
        console.print(
            Panel(
                f"مانیتور: {'[green]فعال[/green]' if monitor=='1' else '[red]غیرفعال[/red]'}\n"
                f"فاصله: {interval} ثانیه",
                title="Status",
            )
        )

    asyncio.run(run())


if __name__ == "__main__":
    app()
