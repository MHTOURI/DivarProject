import asyncio
import os
import secrets
import threading
import time
from datetime import timedelta
from pathlib import Path

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_socketio import SocketIO, disconnect
from werkzeug.middleware.proxy_fix import ProxyFix

from bot.auth import User, authenticate_user, hash_password, login_manager
from bot.config import EXPORT_DIR, FORCE_HTTPS, LOG_DIR, SECRET_KEY
from bot.database import (
    count_active_users,
    create_admin_user,
    delete_user_db,
    get_all_ads,
    get_districts,
    get_scraper_command,
    get_stats,
    get_user_by_username,
    get_worker_status,
    init_db,
    list_users,
    set_scraper_command,
    set_user_active,
)
from bot.export_excel import export_links_txt, export_to_excel
from bot.logger.logger import log

# ====================== App ======================
app = Flask(__name__)
app.config.update(
    SECRET_KEY=SECRET_KEY,
    SESSION_COOKIE_NAME="divar_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=FORCE_HTTPS,
    SESSION_COOKIE_SAMESITE="Lax",
    REMEMBER_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_SECURE=FORCE_HTTPS,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

limiter = Limiter(
    get_remote_address, app=app, default_limits=["300 per day", "60 per hour"]
)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading", logger=False)

login_manager.init_app(app)
login_manager.login_view = "login"
# توجه: init_logger(socketio) عمداً صدا زده نمی‌شود — چون لاگ‌ها همیشه در فایل
# نوشته می‌شوند و ترد پایین (_tail_log_file) همان فایل را دنبال می‌کند و به مرورگر
# می‌فرستد. این باعث می‌شود لاگ‌های app.py و worker.py هر دو از یک مسیر واحد به
# فرانت برسند، بدون دوبار ارسال شدن.


# ====================== Log Tailing (برای لاگ‌های worker مستقل) ======================
# worker.py یک پروسه‌ی جداست و به این SocketIO دسترسی ندارد؛ پس لاگ‌های خودش را فقط
# در logs/crawler.log می‌نویسد. این تِرد فایل را دنبال (tail) می‌کند و خط‌های جدید را
# هم برای مرورگرهای متصل ارسال می‌کند تا لاگ زنده از هر دو پروسه دیده شود.
def _tail_log_file():
    log_path = os.path.join(LOG_DIR, "crawler.log")
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        open(log_path, "a", encoding="utf-8").close()
        with open(log_path, "r", encoding="utf-8") as f:
            f.seek(0, os.SEEK_END)
            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.5)
                    continue
                line = line.strip()
                if not line:
                    continue
                # فرمت: [YYYY-mm-dd HH:MM:SS] [LEVEL] message
                try:
                    ts_part, rest = line.split("] [", 1)
                    level_part, message = rest.split("] ", 1)
                    short_time = ts_part.strip("[").split(" ")[1]
                    socketio.emit(
                        "log",
                        {"time": short_time, "level": level_part, "message": message},
                    )
                except Exception:
                    socketio.emit("log", {"time": "", "level": "INFO", "message": line})
    except Exception:
        pass


threading.Thread(target=_tail_log_file, daemon=True).start()


# ====================== Security Headers ======================
@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    # CSP: فقط منابع خودمان + سی‌دی‌ان‌های شناخته‌شده‌ای که در قالب‌ها استفاده شده‌اند
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.socket.io; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
        "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
        "img-src 'self' data:; "
        "connect-src 'self' ws: wss:; "
        "frame-ancestors 'none'"
    )
    if FORCE_HTTPS:
        response.headers["Strict-Transport-Security"] = (
            "max-age=63072000; includeSubDomains"
        )
    return response


# ====================== CSRF Protection (login form) ======================
def _get_csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return session["_csrf_token"]


app.jinja_env.globals["csrf_token"] = _get_csrf_token


@app.before_request
def _check_csrf():
    if request.method == "POST" and request.endpoint == "login":
        form_token = request.form.get("csrf_token", "")
        session_token = session.get("_csrf_token", "")
        if not form_token or not secrets.compare_digest(form_token, session_token):
            flash("نشست شما منقضی شده، دوباره تلاش کنید", "error")
            return redirect(url_for("login"))


# ====================== State ======================
# دیگر وضعیت اسکرپر در حافظه‌ی پروسه‌ی Flask نگه‌داری نمی‌شود.
# اسکرپر یک پروسه‌ی مستقل است (worker.py) و از طریق جدول settings در دیتابیس
# کنترل می‌شود؛ این یعنی وب‌پنل می‌تواند بدون توقف اسکرپر ری‌استارت شود.


# ====================== Auth ======================
@app.route("/login", methods=["GET", "POST"])
@limiter.limit("8 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = asyncio.run(authenticate_user(username, password))
        if user:
            login_user(user, remember=True)
            session.permanent = True
            log(f"Admin logged in: {username}", "SUCCESS")
            return redirect(url_for("index"))

        flash("نام کاربری یا رمز عبور اشتباه است", "error")
        log(f"Failed login attempt: {username}", "WARNING")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    log(f"Admin logged out: {current_user.username}", "INFO")
    logout_user()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    return render_template("index.html")


# ====================== APIs ======================
@app.route("/api/stats")
@login_required
def api_stats():
    return jsonify(asyncio.run(get_stats()))


@app.route("/api/ads")
@login_required
def api_ads():
    search = request.args.get("search")
    return jsonify(asyncio.run(get_all_ads(search=search)))


@app.route("/api/district/<path:name>")
@login_required
def api_district(name):
    return jsonify(asyncio.run(get_all_ads(district=name)))


@app.route("/api/districts")
@login_required
def api_districts():
    return jsonify(asyncio.run(get_districts()))


@app.route("/api/status")
@login_required
def api_status():
    return jsonify(asyncio.run(get_worker_status()))


# ====================== Export & Download ======================
@app.route("/api/export/excel", methods=["POST"])
@login_required
def api_export_excel():
    try:
        filename = asyncio.run(export_to_excel())
        log(f"Excel exported by {current_user.username}: {filename}", "SUCCESS")
        return jsonify({"status": "ok", "filename": os.path.basename(filename)})
    except Exception as e:
        log(f"Excel export error: {e}", "ERROR")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/export/links", methods=["POST"])
@login_required
def api_export_links():
    try:
        filename = asyncio.run(export_links_txt())
        log(f"Links TXT exported by {current_user.username}: {filename}", "SUCCESS")
        return jsonify({"status": "ok", "filename": os.path.basename(filename)})
    except Exception as e:
        log(f"Links export error: {e}", "ERROR")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/download/<path:filename>")
@login_required
def download_file(filename):
    """دانلود امن فایل‌های خروجی"""
    file_path = os.path.join(EXPORT_DIR, filename)

    # امنیت: فقط فایل‌های داخل پوشه exports
    if not os.path.abspath(file_path).startswith(os.path.abspath(EXPORT_DIR)):
        return "Forbidden", 403

    if not os.path.exists(file_path):
        return "File not found", 404

    return send_file(file_path, as_attachment=True)


# ====================== Scraper Control ======================
# app.py دیگر خودش اسکرپینگ اجرا نمی‌کند — فقط یک دستور در دیتابیس می‌گذارد
# که پروسه‌ی مستقل worker.py آن را می‌خواند و اجرا می‌کند.


@app.route("/api/start", methods=["POST"])
@login_required
@limiter.limit("10 per minute")
def api_start():
    status = asyncio.run(get_worker_status())
    if status["running"]:
        return jsonify({"status": "already_running"})

    if not status["worker_alive"]:
        log("Start requested but worker.py process seems offline", "WARNING")
        return (
            jsonify(
                {
                    "status": "worker_offline",
                    "message": "پروسه‌ی worker.py در حال اجرا نیست. آن را جداگانه اجرا کن: python worker.py",
                }
            ),
            503,
        )

    asyncio.run(set_scraper_command("start"))
    log(f"Scraper start requested by {current_user.username}", "INFO")
    return jsonify({"status": "started"})


@app.route("/api/stop", methods=["POST"])
@login_required
def api_stop():
    asyncio.run(set_scraper_command("stop"))
    log(f"Scraper stop requested by {current_user.username}", "WARNING")
    return jsonify({"status": "stopping"})


# ====================== User Management ======================
@app.route("/api/users")
@login_required
def api_users():
    return jsonify(asyncio.run(list_users()))


@app.route("/api/users", methods=["POST"])
@login_required
@limiter.limit("15 per minute")
def api_users_create():
    username = (
        (request.json or {}).get("username", "").strip()
        if request.is_json
        else request.form.get("username", "").strip()
    )
    password = (
        (request.json or {}).get("password", "")
        if request.is_json
        else request.form.get("password", "")
    )

    if not username or len(username) < 3:
        return (
            jsonify(
                {"status": "error", "message": "نام کاربری باید حداقل ۳ کاراکتر باشد"}
            ),
            400,
        )
    if not password or len(password) < 8:
        return (
            jsonify(
                {"status": "error", "message": "رمز عبور باید حداقل ۸ کاراکتر باشد"}
            ),
            400,
        )

    existing = asyncio.run(get_user_by_username(username))
    if existing:
        return (
            jsonify({"status": "error", "message": "این نام کاربری قبلاً ثبت شده"}),
            409,
        )

    ok = asyncio.run(create_admin_user(username, hash_password(password)))
    if not ok:
        return jsonify({"status": "error", "message": "ساخت کاربر ناموفق بود"}), 500

    log(f"User created by {current_user.username}: {username}", "SUCCESS")
    return jsonify({"status": "ok"})


@app.route("/api/users/<int:user_id>/toggle", methods=["POST"])
@login_required
def api_users_toggle(user_id):
    if str(user_id) == current_user.id:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "نمی‌توانید دسترسی خودتان را غیرفعال کنید",
                }
            ),
            400,
        )

    users = asyncio.run(list_users())
    target = next((u for u in users if u["id"] == user_id), None)
    if not target:
        return jsonify({"status": "error", "message": "کاربر پیدا نشد"}), 404

    new_active = not bool(target["is_active"])
    if not new_active:
        active_count = asyncio.run(count_active_users())
        if active_count <= 1:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "باید حداقل یک ادمین فعال باقی بماند",
                    }
                ),
                400,
            )

    asyncio.run(set_user_active(user_id, new_active))
    log(
        f"User {'activated' if new_active else 'deactivated'} by {current_user.username}: {target['username']}",
        "WARNING",
    )
    return jsonify({"status": "ok", "is_active": new_active})


@app.route("/api/users/<int:user_id>", methods=["DELETE"])
@login_required
def api_users_delete(user_id):
    if str(user_id) == current_user.id:
        return (
            jsonify(
                {"status": "error", "message": "نمی‌توانید حساب خودتان را حذف کنید"}
            ),
            400,
        )

    users = asyncio.run(list_users())
    target = next((u for u in users if u["id"] == user_id), None)
    if not target:
        return jsonify({"status": "error", "message": "کاربر پیدا نشد"}), 404

    if target["is_active"]:
        active_count = asyncio.run(count_active_users())
        if active_count <= 1:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "باید حداقل یک ادمین فعال باقی بماند",
                    }
                ),
                400,
            )

    asyncio.run(delete_user_db(user_id))
    log(f"User deleted by {current_user.username}: {target['username']}", "ERROR")
    return jsonify({"status": "ok"})


# ====================== SocketIO ======================
@socketio.on("connect")
def on_connect():
    if not current_user.is_authenticated:
        disconnect()
        return False
    log(f"Browser connected: {current_user.username}", "INFO")


@socketio.on("disconnect")
def on_disconnect():
    if current_user.is_authenticated:
        log(f"Browser disconnected: {current_user.username}", "INFO")


# ====================== First Admin ======================
async def ensure_admin():
    admin = await get_user_by_username("admin")
    if not admin:
        pw_hash = hash_password("admin123")
        await create_admin_user("admin", pw_hash)
        print("\n" + "=" * 55)
        print("Admin created → username: admin | password: admin123")
        print("لطفاً فوری رمز را عوض کنید با دستور:")
        print("python cli.py change-password")
        print("=" * 55 + "\n")


if __name__ == "__main__":
    asyncio.run(init_db())
    asyncio.run(ensure_admin())
    log("🟢 Secure server starting...", "SUCCESS")
    socketio.run(
        app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True
    )
