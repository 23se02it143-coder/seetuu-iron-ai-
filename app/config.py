"""Application settings, loaded from environment variables / a local .env file."""
from __future__ import annotations

import logging
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
DATA_DIR = BASE_DIR / "data"

log = logging.getLogger("iron.config")

APP_VERSION = "1.0.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- Application -------------------------------------------------------
    app_name: str = "IRON-AI"
    company_name: str = "Divya Solanki"
    environment: Literal["development", "production", "test"] = "development"
    base_url: str = "http://localhost:8000"
    secret_key: str = ""
    session_days: int = 45  # "remember me": sliding renewal keeps an active visitor signed in indefinitely
    bcrypt_rounds: int = 12
    database_url: str = ""
    seed_sample_content: bool = True
    support_email: str = "divyasolanki10125@gmail.com"

    # ---- Bootstrap admin ---------------------------------------------------
    admin_email: str = ""
    admin_password: str = ""

    # ---- Waitlist ----------------------------------------------------------
    waitlist_double_opt_in: bool = False
    waitlist_public_count_min: int = 25

    # ---- Commerce ----------------------------------------------------------
    currency: str = "INR"
    coach_all_free: bool | None = None  # None = unlocked when not in production
    require_login: bool = False  # if true, "/" redirects anonymous visitors to /welcome to sign in first
    open_browser: bool = False  # run.bat sets this so the site opens itself
    payments_provider: Literal["mock", "stripe", "razorpay", "upi"] = "mock"
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    # UPI QR checkout (PAYMENTS_PROVIDER=upi): customer scans a QR / pays to this UPI ID, enters the
    # transaction reference (UTR), and the owner confirms it from an e-mailed link.
    upi_id: str = "divyasolanki10125@okhdfcbank"
    upi_name: str = "Divya Solanki"

    # ---- Email -------------------------------------------------------------
    email_from: str = "IRON-AI <no-reply@localhost>"
    contact_inbox: str = "divyasolanki10125@gmail.com"  # also where "someone paid" notifications go (see payment_notification)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    # HTTP e-mail APIs (use one of these on hosts that block SMTP ports, e.g. Render's free plan).
    brevo_api_key: str = ""
    resend_api_key: str = ""

    # ---- AI assistant ------------------------------------------------------
    assistant_provider: Literal["auto", "rules", "anthropic"] = "auto"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"

    # ---- Misc --------------------------------------------------------------
    rate_limit_enabled: bool = True
    social_instagram: str = ""
    social_x: str = ""
    social_linkedin: str = ""
    social_youtube: str = ""

    # ------------------------------------------------------------------ derived
    @model_validator(mode="after")
    def _finalise(self) -> "Settings":
        self.base_url = self.base_url.rstrip("/")

        if not self.database_url:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            self.database_url = f"sqlite:///{DATA_DIR / 'iron_ai.db'}"
        elif self.database_url.startswith("postgres://"):
            # Railway/Heroku-style platforms hand out a bare "postgres://..." URL; SQLAlchemy 2.0 needs
            # the driver named explicitly, or it can't find a Postgres driver at all and refuses to start.
            self.database_url = "postgresql+psycopg://" + self.database_url[len("postgres://"):]
        elif self.database_url.startswith("postgresql://"):
            self.database_url = "postgresql+psycopg://" + self.database_url[len("postgresql://"):]

        if not self.secret_key:
            if self.environment == "production":
                raise ValueError(
                    "SECRET_KEY must be set in production (use: python -c \"import secrets; print(secrets.token_urlsafe(48))\")"
                )
            self.secret_key = _dev_secret()
        elif self.environment == "production" and len(self.secret_key) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters in production")

        if self.environment == "production" and self.payments_provider == "stripe":
            if not (self.stripe_secret_key and self.stripe_webhook_secret):
                raise ValueError(
                    "PAYMENTS_PROVIDER=stripe requires STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET"
                )
        if self.payments_provider == "upi" and not self.upi_id:
            raise ValueError("PAYMENTS_PROVIDER=upi requires UPI_ID")
        if self.environment == "production" and self.payments_provider == "razorpay":
            if not (self.razorpay_key_id and self.razorpay_key_secret and self.razorpay_webhook_secret):
                raise ValueError(
                    "PAYMENTS_PROVIDER=razorpay requires RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET and RAZORPAY_WEBHOOK_SECRET "
                    "(without the webhook secret, paid checkouts can never be confirmed)"
                )
        return self

    @property
    def cards_enabled(self) -> bool:
        """Card / netbanking payments need Razorpay (we never touch card data ourselves)."""
        return bool(self.razorpay_key_id and self.razorpay_key_secret and self.razorpay_webhook_secret)

    @property
    def coach_open(self) -> bool:
        """Everything in the camera coach is unlocked on a local test install; the plan limits apply in production."""
        return self.coach_all_free if self.coach_all_free is not None else not self.is_production

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cookie_secure(self) -> bool:
        return self.base_url.startswith("https://")

    @property
    def assistant_uses_llm(self) -> bool:
        if self.assistant_provider == "rules":
            return False
        if self.assistant_provider == "anthropic":
            return True
        return bool(self.anthropic_api_key)

    @property
    def social_links(self) -> dict[str, str]:
        links = {
            "Instagram": self.social_instagram,
            "X": self.social_x,
            "LinkedIn": self.social_linkedin,
            "YouTube": self.social_youtube,
        }
        return {k: v for k, v in links.items() if v}


def _dev_secret() -> str:
    """Persist a random secret for local development so sessions survive reloads."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / ".dev_secret"
    if path.exists():
        value = path.read_text().strip()
        if len(value) >= 32:
            return value
    value = secrets.token_urlsafe(48)
    path.write_text(value)
    try:
        path.chmod(0o600)
    except OSError:  # pragma: no cover - non-POSIX filesystems
        pass
    log.warning("Generated a development SECRET_KEY at %s", path)
    return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
