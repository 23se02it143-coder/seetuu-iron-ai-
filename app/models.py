"""Database models."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base, UTCDateTime, utcnow


# --------------------------------------------------------------------------- users
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16), default="user")  # user | admin
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    assessments: Mapped[list["Assessment"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    workout_sessions: Mapped[list["WorkoutSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    reset_tokens: Mapped[list["PasswordResetToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    checkout_sessions: Mapped[list["CheckoutSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    user: Mapped[User] = relationship(back_populates="reset_tokens")


# ------------------------------------------------------------------ catalogue
class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(48))
    tagline: Mapped[str] = mapped_column(String(160))
    price_monthly_cents: Mapped[int] = mapped_column(Integer, default=0)
    price_annual_cents: Mapped[int] = mapped_column(Integer, default=0)
    features: Mapped[list] = mapped_column(JSON, default=list)
    highlight: Mapped[bool] = mapped_column(Boolean, default=False)
    badge: Mapped[str] = mapped_column(String(32), default="")
    cta_label: Mapped[str] = mapped_column(String(48), default="Get started")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    @property
    def is_free(self) -> bool:
        return self.price_monthly_cents == 0 and self.price_annual_cents == 0


class Program(Base):
    __tablename__ = "programs"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(48), unique=True)
    code: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(64))
    tagline: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    icon: Mapped[str] = mapped_column(String(32), default="cpu")
    level: Mapped[str] = mapped_column(String(32), default="All levels")
    weeks: Mapped[int] = mapped_column(Integer, default=8)
    sessions_per_week: Mapped[str] = mapped_column(String(16), default="3")
    highlights: Mapped[list] = mapped_column(JSON, default=list)
    featured: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    published: Mapped[bool] = mapped_column(Boolean, default=True)


class Faq(Base):
    __tablename__ = "faqs"

    id: Mapped[int] = mapped_column(primary_key=True)
    question: Mapped[str] = mapped_column(String(240))
    answer: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    published: Mapped[bool] = mapped_column(Boolean, default=True)


class Testimonial(Base):
    __tablename__ = "testimonials"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(80), default="")
    quote: Mapped[str] = mapped_column(String(600))
    rating: Mapped[int] = mapped_column(Integer, default=5)
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    published: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


# -------------------------------------------------------------------- billing
class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    interval: Mapped[str] = mapped_column(String(8))  # month | year
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | past_due | canceled
    amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    provider: Mapped[str] = mapped_column(String(16), default="mock")
    provider_customer_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider_subscription_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    current_period_end: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="subscriptions")
    plan: Mapped[Plan] = relationship()


class CheckoutSession(Base):
    __tablename__ = "checkout_sessions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    interval: Mapped[str] = mapped_column(String(8))
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    provider: Mapped[str] = mapped_column(String(16))
    provider_session_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="open")  # open | complete | canceled | expired
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    user: Mapped[User] = relationship(back_populates="checkout_sessions")
    plan: Mapped[Plan] = relationship()


class Invoice(Base):
    """Kept after account deletion (user_id/subscription_id are nulled) for bookkeeping."""

    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True
    )
    description: Mapped[str] = mapped_column(String(160))
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(12), default="paid")
    provider: Mapped[str] = mapped_column(String(16), default="mock")
    provider_invoice_id: Mapped[str | None] = mapped_column(String(80), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ProcessedWebhook(Base):
    """Idempotency ledger for payment-provider webhooks."""

    __tablename__ = "processed_webhooks"

    event_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# ---------------------------------------------------------------------- leads
class WaitlistEntry(Base):
    __tablename__ = "waitlist_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80), default="")
    interest: Mapped[str] = mapped_column(String(24), default="athlete")
    goal: Mapped[str] = mapped_column(String(160), default="")
    referral_code: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    referred_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("waitlist_entries.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="confirmed")  # pending | confirmed | unsubscribed
    confirm_token: Mapped[str] = mapped_column(String(64), unique=True)
    unsubscribe_token: Mapped[str] = mapped_column(String(64), unique=True)
    source: Mapped[str] = mapped_column(String(48), default="")
    utm_source: Mapped[str] = mapped_column(String(64), default="")
    utm_medium: Mapped[str] = mapped_column(String(64), default="")
    utm_campaign: Mapped[str] = mapped_column(String(64), default="")
    last_emailed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class ContactMessage(Base):
    __tablename__ = "contact_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(254))
    company: Mapped[str] = mapped_column(String(120), default="")
    topic: Mapped[str] = mapped_column(String(24), default="other")
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="new")  # new | handled
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Assessment(Base):
    """Saved only when the visitor explicitly asks us to (health-adjacent data)."""

    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    answers: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    user: Mapped[User | None] = relationship(back_populates="assessments")


class AnalyticsEvent(Base):
    """Privacy-friendly, anonymous funnel events (no IP, no cookies, no user id)."""

    __tablename__ = "analytics_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32), index=True)
    path: Mapped[str] = mapped_column(String(120), default="/")
    referrer_host: Mapped[str] = mapped_column(String(120), default="")
    utm_source: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class EmailOutbox(Base):
    """Every outgoing email is recorded here (audit trail and local-dev mailbox)."""

    __tablename__ = "email_outbox"

    id: Mapped[int] = mapped_column(primary_key=True)
    to_address: Mapped[str] = mapped_column(String(254))
    subject: Mapped[str] = mapped_column(String(200))
    body_text: Mapped[str] = mapped_column(Text)
    body_html: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(12), default="queued")  # queued | sent | logged | failed
    error: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


Index("ix_waitlist_status", WaitlistEntry.status)


class WorkoutSession(Base):
    """A finished camera form-coach session. Numbers only: the video never leaves the device."""

    __tablename__ = "workout_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    exercise: Mapped[str] = mapped_column(String(24))
    reps: Mapped[int] = mapped_column(Integer, default=0)
    avg_score: Mapped[int] = mapped_column(Integer, default=0)
    best_score: Mapped[int] = mapped_column(Integer, default=0)
    duration_s: Mapped[int] = mapped_column(Integer, default=0)
    faults: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    user: Mapped[User] = relationship(back_populates="workout_sessions")
