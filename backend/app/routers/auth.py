"""Account registration, login, and logout endpoints."""

import re

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator

from ..database import connect
from ..security import (
    COOKIE_NAME,
    SESSION_DAYS,
    create_login,
    current_user,
    password_hash,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,63}$")
DUMMY_PASSWORD_HASH = password_hash("focusforge-dummy-password-for-login-timing")


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not EMAIL_RE.fullmatch(normalized):
            raise ValueError("Enter a valid email address")
        return normalized


def _set_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=request.app.state.cookie_secure,
        samesite="strict",
        path="/",
    )


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: Credentials, request: Request, response: Response) -> dict:
    with connect(request.app.state.db_path) as db:
        try:
            cursor = db.execute(
                "INSERT INTO users(email, password_hash, created_at) VALUES (?, ?, ?)",
                (payload.email, password_hash(payload.password), request.app.state.now()),
            )
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise HTTPException(status_code=409, detail="An account with that email already exists") from exc
            raise
        user_id = cursor.lastrowid
    token = create_login(request, user_id)
    _set_cookie(request, response, token)
    return {"id": user_id, "email": payload.email}


@router.post("/login")
def login(payload: Credentials, request: Request, response: Response) -> dict:
    with connect(request.app.state.db_path) as db:
        user = db.execute(
            "SELECT id, email, password_hash FROM users WHERE email = ? COLLATE NOCASE",
            (payload.email,),
        ).fetchone()
    stored_hash = user["password_hash"] if user else DUMMY_PASSWORD_HASH
    valid_password = verify_password(payload.password, stored_hash)
    if not user or not valid_password:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_login(request, user["id"])
    _set_cookie(request, response, token)
    return {"id": user["id"], "email": user["email"]}


@router.get("/me")
def me(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response) -> Response:
    current_user(request)
    token_hash = getattr(request.state, "auth_token_hash", None)
    if token_hash:
        with connect(request.app.state.db_path) as db:
            db.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (token_hash,))
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="strict")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
