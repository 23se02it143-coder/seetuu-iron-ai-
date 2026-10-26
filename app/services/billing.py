"""Subscription lifecycle: activation, plan changes, cancellation, invoices, webhooks."""
from __future__ import annotations

import calendar
import hashlib
import hmac
import logging
import re
from datetime import datetime, timedelta

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..database import utcnow
from ..errors import ApiError
from ..models import CheckoutSession, Invoice, Plan, ProcessedWebhook, Subscription, User
from . import emails
from .mailer import send_email

log = logging.getLogger("iron.billing")

CHECKOUT_TTL = timedelta(hours=2)


# ------------------------------------------------------------------- helpers
def add_months(dt: datetime, months: int) -> datetime:
    index = dt.month - 1 + months
    year, month = dt.year + index // 12, index % 12 + 1
    return dt.replace(year=year, month=month, day=min(dt.day, calendar.monthrange(year, month)[1]))


def next_period_end(start: datetime, interval: str) -> datetime:
    return add_months(start, 12 if interval == "year" else 1)


def price_for(plan: Plan, interval: str) -> int:
    return plan.price_annual_cents if interval == "year" else plan.price_monthly_cents


def plans_summary(db: Session, settings: Settings) -> str:
    """One-line pricing summary handed to the assistant so it never quotes stale numbers."""
    parts = []
    for plan in db.scalars(select(Plan).where(Plan.active).order_by(Plan.sort_order)):
        if plan.is_free:
            parts.append(f"{plan.name} is free")
        else:
            parts.append(f"{plan.name} is {_fmt(plan.price_monthly_cents, settings.currency)} per month or {_fmt(plan.price_annual_cents, settings.currency)} per year")
    return ("; ".join(parts) + ".") if parts else ""


def _fmt(cents: int, currency: str) -> str:
    return emails._money(cents, currency)


# ------------------------------------------------------------- current state
def current_subscription(db: Session, user: User) -> Subscription | None:
    """The user's live subscription, after applying lazy expiry/renewal rules."""
    sub = db.scalars(
        select(Subscription)
        .where(Subscription.user_id == user.id, Subscription.status != "canceled")
        .order_by(Subscription.id.desc())
    ).first()
    if sub is None:
        return None
    now = utcnow()
    if sub.current_period_end and sub.current_period_end <= now:
        if sub.cancel_at_period_end:
            sub.status = "canceled"
            db.commit()
            return None
        if sub.provider == "mock":  # test mode: roll the renewal date forward without charging
            while sub.current_period_end <= now:
                sub.current_period_end = next_period_end(sub.current_period_end, sub.interval)
            db.commit()
        elif sub.provider in ("razorpay", "upi") and sub.status != "past_due":
            # a Razorpay Payment Link is a one-off charge, not an auto-debit mandate: nothing billed
            # automatically, so be honest that the period lapsed rather than pretending it renewed
            sub.status = "past_due"
            db.commit()
    return sub


def serialize_subscription(db: Session, sub: Subscription | None) -> dict:
    if sub is None:
        starter = db.scalars(select(Plan).where(Plan.slug == "starter")).first()
        return {
            "plan": {"slug": "starter", "name": starter.name if starter else "Starter"},
            "status": "active",
            "interval": None,
            "amount_cents": 0,
            "currency": None,
            "current_period_end": None,
            "cancel_at_period_end": False,
            "provider": None,
            "is_paid": False,
        }
    return {
        "plan": {"slug": sub.plan.slug, "name": sub.plan.name},
        "status": sub.status,
        "interval": sub.interval,
        "amount_cents": sub.amount_cents,
        "currency": sub.currency,
        "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
        "cancel_at_period_end": sub.cancel_at_period_end,
        "provider": sub.provider,
        "is_paid": True,
    }


# ------------------------------------------------------------------ checkout
def open_checkout(db: Session, settings: Settings, user: User, plan: Plan, interval: str, provider_name: str) -> CheckoutSession:
    from uuid import uuid4

    if not plan.active:
        raise ApiError(404, "plan_not_found", "That plan is not available.")
    if plan.is_free:
        raise ApiError(400, "free_plan", "The Starter plan is free, so no checkout is needed.")
    existing = current_subscription(db, user)
    if existing and existing.plan_id == plan.id and existing.interval == interval and not existing.cancel_at_period_end:
        raise ApiError(409, "already_subscribed", f"You are already on the {plan.name} plan.")
    now = utcnow()
    checkout = CheckoutSession(
        id="cs_" + uuid4().hex[:24],
        user_id=user.id,
        plan_id=plan.id,
        interval=interval,
        amount_cents=price_for(plan, interval),
        currency=settings.currency.upper(),
        provider=provider_name,
        created_at=now,
        expires_at=now + CHECKOUT_TTL,
    )
    db.add(checkout)
    db.flush()
    return checkout


def activate_subscription(
    db: Session,
    user: User,
    checkout: CheckoutSession,
    *,
    provider: str,
    provider_customer_id: str | None = None,
    provider_subscription_id: str | None = None,
    period_end: datetime | None = None,
) -> tuple[Subscription, str | None]:
    """Create the subscription, or switch the existing one to the new plan.

    Returns (subscription, superseded_provider_subscription_id). The second value is set when a
    different provider-side subscription was replaced and must be cancelled with the provider.
    """
    now = utcnow()
    sub = current_subscription(db, user)
    superseded = None
    if sub is None:
        sub = Subscription(user_id=user.id, plan_id=checkout.plan_id, interval=checkout.interval, created_at=now)
        db.add(sub)
    elif sub.provider_subscription_id and sub.provider_subscription_id != provider_subscription_id:
        superseded = sub.provider_subscription_id
    sub.plan_id = checkout.plan_id
    sub.interval = checkout.interval
    sub.status = "active"
    sub.amount_cents = checkout.amount_cents
    sub.currency = checkout.currency
    sub.provider = provider
    sub.provider_customer_id = provider_customer_id or sub.provider_customer_id
    sub.provider_subscription_id = provider_subscription_id
    sub.current_period_end = period_end or next_period_end(now, checkout.interval)
    sub.cancel_at_period_end = False
    checkout.status, checkout.completed_at = "complete", now
    db.flush()
    return sub, superseded


def add_invoice(db: Session, sub: Subscription, *, amount_cents: int, currency: str, description: str, provider: str, provider_invoice_id: str | None = None) -> Invoice:
    invoice = Invoice(
        user_id=sub.user_id,
        subscription_id=sub.id,
        description=description,
        amount_cents=amount_cents,
        currency=currency,
        provider=provider,
        provider_invoice_id=provider_invoice_id,
    )
    db.add(invoice)
    return invoice


def queue_receipt(background: BackgroundTasks, settings: Settings, user: User, sub: Subscription, plan: Plan) -> None:
    renews = sub.current_period_end.strftime("%d %B %Y") if sub.current_period_end else "n/a"
    subject, text, html = emails.subscription_receipt(
        settings, name=user.name, plan=plan.name, interval=sub.interval, amount_cents=sub.amount_cents, currency=sub.currency, renews=renews
    )
    background.add_task(send_email, user.email, subject, text, html, "receipt")


def complete_mock_checkout(db: Session, settings: Settings, background: BackgroundTasks, user: User, checkout: CheckoutSession) -> Subscription:
    if checkout.status != "open":
        raise ApiError(409, "checkout_closed", "This checkout has already been completed or cancelled.")
    if checkout.expires_at <= utcnow():
        checkout.status = "expired"
        db.commit()
        raise ApiError(410, "checkout_expired", "This checkout expired. Start again from the pricing page.")
    plan = db.get(Plan, checkout.plan_id)
    sub, _ = activate_subscription(db, user, checkout, provider="mock", period_end=None)
    add_invoice(
        db, sub, amount_cents=checkout.amount_cents, currency=checkout.currency,
        description=f"{plan.name} ({'annual' if checkout.interval == 'year' else 'monthly'}) - test mode", provider="mock",
    )
    db.commit()
    queue_receipt(background, settings, user, sub, plan)
    return sub


# ------------------------------------------------------------- stripe events
_STATUS_MAP = {
    "active": "active", "trialing": "active",
    "past_due": "past_due", "unpaid": "past_due", "incomplete": "past_due",
    "canceled": "canceled", "incomplete_expired": "canceled",
}


def _period_end(obj: dict) -> datetime | None:
    """`current_period_end` moved onto subscription items in newer Stripe API versions."""
    ts = obj.get("current_period_end")
    if ts is None:
        items = (obj.get("items") or {}).get("data") or []
        ts = items[0].get("current_period_end") if items else None
    if ts is None:
        lines = (obj.get("lines") or {}).get("data") or []
        ts = ((lines[0].get("period") or {}).get("end")) if lines else None
    return datetime.fromtimestamp(ts, tz=utcnow().tzinfo) if ts else None


def handle_stripe_event(db: Session, settings: Settings, provider, background: BackgroundTasks, event: dict) -> str:
    """Apply one verified Stripe event. Returns a short outcome string (handy for logs/tests)."""
    event_id = event.get("id", "")
    if not event_id:
        raise ApiError(400, "invalid_event", "Missing event id.")
    if db.get(ProcessedWebhook, event_id):
        return "duplicate"

    kind = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}
    outcome = "ignored"

    if kind == "checkout.session.completed":
        outcome = _on_checkout_completed(db, settings, provider, background, obj)
    elif kind == "invoice.paid":
        outcome = _on_invoice_paid(db, obj)
    elif kind == "customer.subscription.updated":
        outcome = _on_subscription_updated(db, obj)
    elif kind == "customer.subscription.deleted":
        sub = _find_sub(db, obj.get("id"))
        if sub:
            sub.status = "canceled"
            outcome = "canceled"

    db.add(ProcessedWebhook(event_id=event_id))
    db.commit()
    return outcome


def _find_sub(db: Session, provider_id: str | None) -> Subscription | None:
    if not provider_id:
        return None
    return db.scalars(select(Subscription).where(Subscription.provider_subscription_id == provider_id)).first()


def _on_checkout_completed(db, settings, provider, background, obj) -> str:
    checkout_id = (obj.get("metadata") or {}).get("checkout_id")
    checkout = db.get(CheckoutSession, checkout_id) if checkout_id else None
    if checkout is None:
        log.warning("Stripe checkout.session.completed for unknown checkout %s", checkout_id)
        return "unknown_checkout"
    if obj.get("payment_status") not in ("paid", "no_payment_required"):
        return "unpaid"
    user = db.get(User, checkout.user_id)
    plan = db.get(Plan, checkout.plan_id)
    sub, superseded = activate_subscription(
        db, user, checkout, provider="stripe",
        provider_customer_id=obj.get("customer"), provider_subscription_id=obj.get("subscription"),
    )
    db.flush()
    if superseded:
        try:
            provider.cancel_now(superseded)
        except ApiError:
            log.error("Could not cancel superseded Stripe subscription %s", superseded)
    queue_receipt(background, settings, user, sub, plan)
    return "activated"


def _on_invoice_paid(db, obj) -> str:
    provider_sub_id = obj.get("subscription")
    if not provider_sub_id and obj.get("parent"):  # newer API shape
        provider_sub_id = ((obj["parent"].get("subscription_details") or {}).get("subscription"))
    sub = _find_sub(db, provider_sub_id)
    if sub is None:
        # checkout.session.completed can arrive after invoice.paid; ask Stripe to retry later.
        raise ApiError(503, "subscription_not_ready", "Subscription not recorded yet; retry later.")
    invoice_id = obj.get("id")
    if invoice_id and db.scalars(select(Invoice).where(Invoice.provider_invoice_id == invoice_id)).first():
        return "duplicate_invoice"
    add_invoice(
        db, sub, amount_cents=int(obj.get("amount_paid") or 0), currency=str(obj.get("currency") or sub.currency).upper(),
        description=f"{sub.plan.name} subscription", provider="stripe", provider_invoice_id=invoice_id,
    )
    end = _period_end(obj)
    if end:
        sub.current_period_end = end
    sub.status = "active"
    return "invoice_recorded"


def _on_subscription_updated(db, obj) -> str:
    sub = _find_sub(db, obj.get("id"))
    if sub is None:
        return "unknown_subscription"
    sub.status = _STATUS_MAP.get(obj.get("status", ""), sub.status)
    sub.cancel_at_period_end = bool(obj.get("cancel_at_period_end"))
    end = _period_end(obj)
    if end:
        sub.current_period_end = end
    return "updated"


# ----------------------------------------------------------- razorpay events
def handle_razorpay_event(db: Session, settings: Settings, background: BackgroundTasks, event: dict) -> str:
    """Apply one verified Razorpay webhook event. Returns a short outcome string (handy for logs/tests)."""
    kind = event.get("event", "")
    payload = event.get("payload") or {}
    link = ((payload.get("payment_link") or {}).get("entity")) or {}
    payment = ((payload.get("payment") or {}).get("entity")) or {}
    dedupe_id = "rzp_" + (payment.get("id") or link.get("id") or "")
    if len(dedupe_id) <= 4:
        return "ignored"
    if db.get(ProcessedWebhook, dedupe_id):
        return "duplicate"

    outcome = "ignored"
    if kind == "payment_link.paid":
        outcome = _on_razorpay_paid(db, settings, background, link, payment)
    elif kind in ("payment_link.expired", "payment_link.cancelled"):
        checkout_id = (link.get("notes") or {}).get("checkout_id")
        checkout = db.get(CheckoutSession, checkout_id) if checkout_id else None
        if checkout and checkout.status == "open":
            checkout.status = "canceled" if kind == "payment_link.cancelled" else "expired"
            outcome = checkout.status

    db.add(ProcessedWebhook(event_id=dedupe_id))
    db.commit()
    return outcome


def _on_razorpay_paid(db, settings, background, link: dict, payment: dict) -> str:
    checkout_id = (link.get("notes") or {}).get("checkout_id")
    checkout = db.get(CheckoutSession, checkout_id) if checkout_id else None
    if checkout is None:
        log.warning("Razorpay payment_link.paid for unknown checkout %s", checkout_id)
        return "unknown_checkout"
    if checkout.status == "complete":
        return "duplicate"
    user = db.get(User, checkout.user_id)
    plan = db.get(Plan, checkout.plan_id)
    if user is None or plan is None:
        return "unknown_checkout"
    sub, _ = activate_subscription(db, user, checkout, provider="razorpay", provider_subscription_id=link.get("id"))
    add_invoice(
        db, sub, amount_cents=int(payment.get("amount") or checkout.amount_cents), currency=str(payment.get("currency") or checkout.currency).upper(),
        description=f"{plan.name} ({'annual' if checkout.interval == 'year' else 'monthly'})", provider="razorpay", provider_invoice_id=payment.get("id"),
    )
    db.flush()
    queue_receipt(background, settings, user, sub, plan)
    inbox = settings.contact_inbox or settings.support_email
    if inbox:
        subject, text, html = emails.payment_notification(
            settings, name=user.name, email=user.email, plan=plan.name, interval=checkout.interval,
            amount_cents=sub.amount_cents, currency=sub.currency, provider="Razorpay",
        )
        background.add_task(send_email, inbox, subject, text, html, "payment-notification")
    return "activated"


# ------------------------------------------------------------------ UPI QR
_UPI_REF = re.compile(r"^[A-Za-z0-9]{8,30}$")


def upi_review_token(settings: Settings, checkout_id: str) -> str:
    """Signed token for the owner's one-click review link (HMAC of the checkout id with SECRET_KEY)."""
    return hmac.new(settings.secret_key.encode(), f"upi-review:{checkout_id}".encode(), hashlib.sha256).hexdigest()[:40]


def valid_upi_review_token(settings: Settings, checkout_id: str, token: str) -> bool:
    return hmac.compare_digest(upi_review_token(settings, checkout_id), token or "")


def submit_upi_payment(db: Session, settings: Settings, background: BackgroundTasks, user: User, checkout: CheckoutSession, reference: str) -> None:
    """Customer says they paid: park the checkout as 'pending' and tell the owner to confirm it."""
    reference = (reference or "").strip().replace(" ", "")
    if checkout.status == "pending":
        raise ApiError(409, "already_submitted", "We already have your payment reference and are verifying it.")
    if checkout.status != "open":
        raise ApiError(409, "checkout_closed", "This checkout has already been completed or cancelled.")
    if checkout.expires_at <= utcnow():
        checkout.status = "expired"
        db.commit()
        raise ApiError(410, "checkout_expired", "This checkout expired. Start again from the pricing page.")
    if not _UPI_REF.match(reference):
        raise ApiError(422, "invalid_reference", "Enter the UPI transaction ID / UTR from your payment app (8-30 letters or digits).")
    tag = "utr:" + reference.upper()
    if db.scalars(select(CheckoutSession).where(CheckoutSession.provider_session_id == tag, CheckoutSession.id != checkout.id)).first():
        raise ApiError(409, "reference_used", "That transaction ID has already been submitted.")
    checkout.provider_session_id = tag
    checkout.status = "pending"
    db.commit()
    plan = db.get(Plan, checkout.plan_id)
    review_url = f"{settings.base_url}/api/billing/upi/{checkout.id}/review?t={upi_review_token(settings, checkout.id)}"
    inbox = settings.contact_inbox or settings.support_email
    if inbox:
        subject, text, html = emails.upi_review_request(
            settings, name=user.name, email=user.email, plan=plan.name, interval=checkout.interval,
            amount_cents=checkout.amount_cents, currency=checkout.currency, reference=reference.upper(), review_url=review_url,
        )
        background.add_task(send_email, inbox, subject, text, html, "payment-notification")
    subject, text, html = emails.upi_payment_received(settings, name=user.name, plan=plan.name, reference=reference.upper())
    background.add_task(send_email, user.email, subject, text, html, "payment-pending")


def approve_upi_checkout(db: Session, settings: Settings, background: BackgroundTasks, checkout: CheckoutSession) -> str:
    """Owner confirmed the money arrived: activate the plan, record the invoice, send the receipt."""
    if checkout.status == "complete":
        return "already_complete"
    if checkout.status not in ("pending", "open"):
        raise ApiError(409, "checkout_closed", "This checkout was cancelled or expired.")
    user = db.get(User, checkout.user_id)
    plan = db.get(Plan, checkout.plan_id)
    if user is None or plan is None:
        raise ApiError(404, "checkout_not_found", "The customer or plan no longer exists.")
    ref = (checkout.provider_session_id or "").removeprefix("utr:")
    sub, _ = activate_subscription(db, user, checkout, provider="upi", provider_subscription_id="upi_" + checkout.id)
    add_invoice(
        db, sub, amount_cents=checkout.amount_cents, currency=checkout.currency,
        description=f"{plan.name} ({'annual' if checkout.interval == 'year' else 'monthly'}) - UPI {ref}".strip(), provider="upi",
        provider_invoice_id="upi_" + checkout.id,
    )
    db.commit()
    queue_receipt(background, settings, user, sub, plan)
    return "activated"


def reject_upi_checkout(db: Session, settings: Settings, background: BackgroundTasks, checkout: CheckoutSession) -> str:
    if checkout.status == "complete":
        raise ApiError(409, "checkout_closed", "This payment was already approved.")
    checkout.status = "canceled"
    db.commit()
    user = db.get(User, checkout.user_id)
    if user:
        subject, text, html = emails.upi_payment_rejected(settings, name=user.name)
        background.add_task(send_email, user.email, subject, text, html, "payment-rejected")
    return "rejected"
