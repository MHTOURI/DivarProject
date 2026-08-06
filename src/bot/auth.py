import asyncio
from functools import wraps

from flask import jsonify
from flask_login import LoginManager, UserMixin, current_user
from werkzeug.security import check_password_hash, generate_password_hash

from bot.database import get_user_by_id, get_user_by_username, update_last_login

# ==========================
# Login Manager
# ==========================

login_manager = LoginManager()

login_manager.login_view = "login"

login_manager.session_protection = "strong"


# ==========================
# User Model
# ==========================


class User(UserMixin):

    def __init__(self, id, username, is_active=True):

        self.id = str(id)

        self.username = username

        self._is_active = is_active

    @property
    def is_active(self):

        return self._is_active


# ==========================
# Load User From Session
# ==========================


@login_manager.user_loader
def load_user(user_id):

    try:

        user = asyncio.run(get_user_by_id(user_id))

        if user:

            return User(
                id=user["id"], username=user["username"], is_active=user["is_active"]
            )

    except Exception as e:

        print("USER LOAD ERROR:", e)

    return None


# ==========================
# Password
# ==========================


def hash_password(password: str):

    return generate_password_hash(password, method="pbkdf2:sha256:600000")


def verify_password(password_hash, password):

    return check_password_hash(password_hash, password)


# ==========================
# Authentication
# ==========================


async def authenticate_user(username, password):

    user_data = await get_user_by_username(username)

    if not user_data:

        return None

    if not user_data["is_active"]:

        return None

    if not verify_password(user_data["password_hash"], password):

        return None

    await update_last_login(user_data["id"])

    return User(id=user_data["id"], username=user_data["username"], is_active=True)


# ==========================
# Decorator
# ==========================


def admin_required(func):

    @wraps(func)
    def wrapper(*args, **kwargs):

        if not current_user.is_authenticated:

            return jsonify({"error": "Unauthorized"}), 401

        return func(*args, **kwargs)

    return wrapper
