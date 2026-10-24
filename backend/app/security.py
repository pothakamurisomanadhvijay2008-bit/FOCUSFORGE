"""Password hashing and opaque cookie-session helpers."""

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Request

from .database import connect

COOKIE_NAME = "focusforge_session"
SESSION_DAYS = 7


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def encode_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return "scrypt$" + base64.urlsafe_b64encode(salt + derived).decode("ascii")


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, encoded = stored.split("$", 1)
        raw = base64.urlsafe_b64decode(encoded.encode("ascii"))
        salt, expected = raw[:16], raw[16:]
        if algorithm != "scrypt" or len(salt) != 16 or not expected:
            return False
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_login(request: Request, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with connect(request.app.state.db_path) as db:
        db.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (encode_time(utc_now()),))
        db.execute(
            "INSERT INTO auth_sessions(token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (token_digest(token), user_id, encode_time(utc_now() + timedelta(days=SESSION_DAYS))),
        )
    return token


def current_user(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    with connect(request.app.state.db_path) as db:
        row = db.execute(
            """SELECT users.id, users.email, auth_sessions.token_hash
               FROM auth_sessions JOIN users ON users.id = auth_sessions.user_id
               WHERE auth_sessions.token_hash = ? AND auth_sessions.expires_at > ?""",
            (token_digest(token), encode_time(utc_now())),
        ).fetchone()
    if not row:
        return None
    request.state.auth_token_hash = row["token_hash"]
    return {"id": row["id"], "email": row["email"]}
