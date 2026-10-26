"""Password hashing, session tokens and auth dependencies."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import timedelta

import bcrypt
import jwt
from fastapi import Depends, Request, Response
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .database import get_db, utcnow
from .errors import ApiError
from .models import User

SESSION_COOKIE = "iron_session"

_COMMON_PASSWORDS = {
    "password", "password1", "password12", "password123", "password1234", "1234567890", "12345678910",
    "qwertyuiop", "qwerty12345", "iloveyou123", "letmein1234", "welcome1234", "admin12345", "abc1234567",
    "ironai12345", "1q2w3e4r5t", "0123456789", "passw0rd123",
}


# ---------------------------------------------------------------- passwords
def validate_password_strength(password: str, *, email: str = "") -> str | None:
    """Return a human-readable problem, or None if the password is acceptable."""
    if len(password) < 10:
        return "Use at least 10 characters"
    if len(password.encode()) > 72:
        return "Use at most 72 bytes (bcrypt limit); shorten the password"
    if password.lower() in _COMMON_PASSWORDS or re.fullmatch(r"(.)\1+", password):
        return "That password is too common"
    local = email.split("@")[0].lower() if email else ""
    if len(local) >= 4 and local in password.lower():
        return "Do not include your email name in your password"
    return None


def hash_password(password: str, rounds: int | None = None) -> str:
    rounds = rounds or get_settings().bcrypt_rounds
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=rounds)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


_dummy_hash: str | None = None


def burn_password_check(password: str) -> None:
    """Spend the same time as a real check so login timing does not reveal valid emails."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password(secrets.token_urlsafe(12))
    verify_password(password, _dummy_hash)


# ------------------------------------------------------------ random tokens
def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def safe_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# ----------------------------------------------------------------- sessions
def create_session_token(user: User, settings: Settings) -> str:
    now = utcnow()
    payload = {
        "sub": str(user.id),
        "ver": user.token_version,
        "iat": now,
        "exp": now + timedelta(days=settings.session_days),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def set_session_cookie(response: Response, user: User, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(user, settings),
        max_age=settings.session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def _user_from_request(request: Request, db: Session, settings: Settings) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        claims = jwt.decode(token, settings.secret_key, algorithms=["HS256"], options={"require": ["exp", "sub"]})
        user = db.get(User, int(claims["sub"]))
    except (jwt.PyJWTError, ValueError, KeyError):
        return None
    if not user or not user.is_active or user.token_version != claims.get("ver"):
        return None
    request.state.session_claims = claims  # read by the "remember me" refresh in main.py's guard middleware
    return user


def session_needs_refresh(claims: dict, settings: Settings) -> bool:
    """True once a session is past the midpoint of its life, so an active visitor is kept signed in
    indefinitely (sliding window) without reissuing the cookie on every single request."""
    iat = claims.get("iat")
    if not iat:
        return False
    age = utcnow().timestamp() - iat
    return age > (settings.session_days * 86400) / 2


def optional_user(
    request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> User | None:
    return _user_from_request(request, db, settings)


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise ApiError(401, "not_authenticated", "Sign in to continue.")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise ApiError(403, "forbidden", "You do not have access to this area.")
    return user
