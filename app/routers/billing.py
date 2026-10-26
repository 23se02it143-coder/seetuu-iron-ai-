"""Subscriptions: checkout, test-mode payment page, cancel/resume, Stripe webhook."""
from __future__ import annotations

import json
import logging

from html import escape

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..database import get_db, utcnow
from ..errors import ApiError
from ..models import CheckoutSession, Invoice, Plan, User
from ..ratelimit import rate_limit
from ..schemas import CheckoutIn, MockCompleteIn, UpiSubmitIn
from ..security import current_user
from ..services import billing
from ..services.payments import RazorpayProvider, build_provider, upi_uri, verify_razorpay_signature, verify_stripe_signature

log = logging.getLogger("iron.billing")
router = APIRouter(prefix="/api/billing", tags=["billing"])


def get_provider(settings: Settings = Depends(get_settings)):
    """Dependency so tests can swap in a provider with a mocked HTTP transport."""
    return build_provider(settings)


@router.get("/subscription")
def get_subscription(user: User = Depends(current_user), db: Session = Depends(get_db)):
    sub = billing.current_subscription(db, user)
    invoices = db.scalars(select(Invoice).where(Invoice.user_id == user.id).order_by(Invoice.id.desc()).limit(24))
    return {
        "subscription": billing.serialize_subscription(db, sub),
        "invoices": [
            {"id": i.id, "description": i.description, "amount_cents": i.amount_cents, "currency": i.currency, "status": i.status, "created_at": i.created_at.isoformat()}
            for i in invoices
        ],
    }


@router.post("/checkout", dependencies=[Depends(rate_limit("checkout", 20, 3600))])
def start_checkout(
    data: CheckoutIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    provider=Depends(get_provider),
):
    plan = db.scalars(select(Plan).where(Plan.slug == data.plan_slug)).first()
    if plan is None:
        raise ApiError(404, "plan_not_found", "That plan does not exist.")
    checkout = billing.open_checkout(db, settings, user, plan, data.interval, provider.name)
    customer_id = None
    live = billing.current_subscription(db, user)
    if live and live.provider == provider.name:
        customer_id = live.provider_customer_id
    result = provider.create_checkout(checkout=checkout, user=user, plan=plan, customer_id=customer_id)
    checkout.provider_session_id = result.provider_session_id
    db.commit()
    return {"checkout_id": checkout.id, "url": result.url}


def _own_mock_checkout(db: Session, user: User, settings: Settings, checkout_id: str) -> CheckoutSession:
    if settings.payments_provider != "mock":
        raise ApiError(404, "not_found", "Not found.")
    checkout = db.get(CheckoutSession, checkout_id)
    if checkout is None or checkout.user_id != user.id or checkout.provider != "mock":
        raise ApiError(404, "checkout_not_found", "We could not find that checkout.")
    return checkout


@router.get("/mock/{checkout_id}")
def mock_checkout_details(checkout_id: str, user: User = Depends(current_user), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    checkout = _own_mock_checkout(db, user, settings, checkout_id)
    return {
        "id": checkout.id,
        "status": "expired" if checkout.status == "open" and checkout.expires_at <= utcnow() else checkout.status,
        "plan": {"slug": checkout.plan.slug, "name": checkout.plan.name},
        "interval": checkout.interval,
        "amount_cents": checkout.amount_cents,
        "currency": checkout.currency,
    }


@router.post("/mock/{checkout_id}/complete")
def mock_checkout_complete(
    checkout_id: str,
    data: MockCompleteIn,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    checkout = _own_mock_checkout(db, user, settings, checkout_id)
    if data.outcome == "cancel":
        if checkout.status == "open":
            checkout.status = "canceled"
            db.commit()
        return {"status": "canceled"}
    billing.complete_mock_checkout(db, settings, background, user, checkout)
    return {"status": "complete"}


# ------------------------------------------------------------------ UPI QR
def _own_upi_checkout(db: Session, user: User, settings: Settings, checkout_id: str) -> CheckoutSession:
    if settings.payments_provider != "upi":
        raise ApiError(404, "not_found", "Not found.")
    checkout = db.get(CheckoutSession, checkout_id)
    if checkout is None or checkout.user_id != user.id or checkout.provider != "upi":
        raise ApiError(404, "checkout_not_found", "We could not find that checkout.")
    return checkout


@router.get("/upi/{checkout_id}")
def upi_checkout_details(checkout_id: str, user: User = Depends(current_user), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    checkout = _own_upi_checkout(db, user, settings, checkout_id)
    status = "expired" if checkout.status == "open" and checkout.expires_at <= utcnow() else checkout.status
    return {
        "id": checkout.id,
        "status": status,
        "plan": {"slug": checkout.plan.slug, "name": checkout.plan.name},
        "interval": checkout.interval,
        "amount_cents": checkout.amount_cents,
        "currency": checkout.currency,
        "upi_id": settings.upi_id,
        "upi_name": settings.upi_name,
        "upi_uri": upi_uri(settings, checkout, checkout.plan),
        "cards_available": settings.cards_enabled,
        "reference": (checkout.provider_session_id or "").removeprefix("utr:") if status == "pending" else None,
    }


@router.get("/upi/{checkout_id}/qr.svg")
def upi_checkout_qr(checkout_id: str, user: User = Depends(current_user), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    import io

    import segno

    checkout = _own_upi_checkout(db, user, settings, checkout_id)
    buf = io.BytesIO()
    segno.make(upi_uri(settings, checkout, checkout.plan), error="m").save(buf, kind="svg", scale=8, border=3, dark="#111111", light="#ffffff", xmldecl=False, svgns=True)
    return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "private, no-store"})


@router.post("/upi/{checkout_id}/submit", dependencies=[Depends(rate_limit("upi-submit", 15, 3600))])
def upi_checkout_submit(
    checkout_id: str,
    data: UpiSubmitIn,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    checkout = _own_upi_checkout(db, user, settings, checkout_id)
    billing.submit_upi_payment(db, settings, background, user, checkout, data.reference)
    return {"status": "pending"}


@router.post("/upi/{checkout_id}/card")
def upi_checkout_card(checkout_id: str, user: User = Depends(current_user), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    """Card / netbanking / wallet instead of the QR: a Razorpay Payment Link for the same checkout."""
    checkout = _own_upi_checkout(db, user, settings, checkout_id)
    if not settings.cards_enabled:
        raise ApiError(503, "cards_not_configured", "Card payments are not available yet. Please pay with UPI.")
    if checkout.status != "open":
        raise ApiError(409, "checkout_closed", "This checkout has already been completed or cancelled.")
    result = RazorpayProvider(settings).create_checkout(checkout=checkout, user=user, plan=checkout.plan)
    checkout.provider_session_id = result.provider_session_id
    db.commit()
    return {"url": result.url}


def _review_page(title: str, body: str) -> HTMLResponse:
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)}</title>"
        '<link rel="stylesheet" href="/static/css/site.css"><link rel="stylesheet" href="/static/css/app.css">'
        '<meta name="robots" content="noindex"></head><body><main class="container review"><section class="panel">'
        f"<h1>{escape(title)}</h1>{body}</section></main></body></html>"
    )
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


def _review_checkout(db: Session, settings: Settings, checkout_id: str, token: str) -> CheckoutSession:
    checkout = db.get(CheckoutSession, checkout_id)
    if checkout is None or checkout.provider != "upi" or not billing.valid_upi_review_token(settings, checkout_id, token):
        raise ApiError(404, "not_found", "Not found.")
    return checkout


@router.get("/upi/{checkout_id}/review", response_class=HTMLResponse, include_in_schema=False, dependencies=[Depends(rate_limit("upi-review", 60, 3600))])
def upi_review_page(checkout_id: str, t: str = "", db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    checkout = _review_checkout(db, settings, checkout_id, t)
    user = db.get(User, checkout.user_id)
    ref = (checkout.provider_session_id or "").removeprefix("utr:") or "-"
    money = f"{checkout.currency} {checkout.amount_cents / 100:,.2f}"
    summary = (
        f"<p><b>{escape(user.name)}</b> ({escape(user.email)}) says they paid <b>{escape(money)}</b> "
        f"for <b>{escape(checkout.plan.name)}</b>.</p><p>UTR / reference: <b>{escape(ref)}</b></p>"
    )
    if checkout.status == "complete":
        return _review_page("Already approved", summary + "<p>This payment is already approved and the plan is active.</p>")
    if checkout.status not in ("pending", "open"):
        return _review_page("Closed", summary + f"<p>This checkout is {escape(checkout.status)}.</p>")
    form = (
        f'<form method="post" action="/api/billing/upi/{escape(checkout.id)}/review">'
        f'<input type="hidden" name="t" value="{escape(t)}">'
        "<p>Only approve after you see this amount, with this reference, in your bank / UPI app.</p>"
        '<div class="row"><button class="btn btn--primary" name="action" value="approve" type="submit">Approve and activate plan</button> '
        '<button class="btn btn--ghost" name="action" value="reject" type="submit">Reject</button></div></form>'
    )
    return _review_page("Confirm UPI payment", summary + form)


@router.post("/upi/{checkout_id}/review", response_class=HTMLResponse, include_in_schema=False, dependencies=[Depends(rate_limit("upi-review", 60, 3600))])
def upi_review_action(
    checkout_id: str,
    background: BackgroundTasks,
    t: str = Form(""),
    action: str = Form(""),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    checkout = _review_checkout(db, settings, checkout_id, t)
    if action == "approve":
        outcome = billing.approve_upi_checkout(db, settings, background, checkout)
        msg = "Plan activated. The customer has been emailed a receipt." if outcome == "activated" else "This payment was already approved."
        return _review_page("Approved", f"<p>{msg}</p>")
    if action == "reject":
        billing.reject_upi_checkout(db, settings, background, checkout)
        return _review_page("Rejected", "<p>The payment was rejected and the customer has been emailed.</p>")
    raise ApiError(400, "bad_action", "Unknown action.")


@router.post("/cancel")
def cancel_subscription(user: User = Depends(current_user), db: Session = Depends(get_db), provider=Depends(get_provider)):
    sub = billing.current_subscription(db, user)
    if sub is None:
        raise ApiError(400, "no_subscription", "You do not have a paid subscription to cancel.")
    if not sub.cancel_at_period_end:
        if sub.provider == provider.name:
            provider.set_cancel_at_period_end(sub, True)
        sub.cancel_at_period_end = True
        db.commit()
    return {"subscription": billing.serialize_subscription(db, sub)}


@router.post("/resume")
def resume_subscription(user: User = Depends(current_user), db: Session = Depends(get_db), provider=Depends(get_provider)):
    sub = billing.current_subscription(db, user)
    if sub is None:
        raise ApiError(400, "no_subscription", "There is no active subscription to resume. Choose a plan to start a new one.")
    if sub.cancel_at_period_end:
        if sub.provider == provider.name:
            provider.set_cancel_at_period_end(sub, False)
        sub.cancel_at_period_end = False
        db.commit()
    return {"subscription": billing.serialize_subscription(db, sub)}


@router.post("/webhook/stripe", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    provider=Depends(get_provider),
):
    if settings.payments_provider != "stripe" or not settings.stripe_webhook_secret:
        raise ApiError(404, "not_found", "Not found.")
    payload = await request.body()
    if not verify_stripe_signature(payload, request.headers.get("stripe-signature"), settings.stripe_webhook_secret):
        raise ApiError(400, "invalid_signature", "Signature verification failed.")
    try:
        event = json.loads(payload)
    except ValueError:
        raise ApiError(400, "invalid_payload", "The payload is not valid JSON.")
    outcome = billing.handle_stripe_event(db, settings, provider, background, event)
    log.info("Stripe webhook %s (%s): %s", event.get("id"), event.get("type"), outcome)
    return {"received": True, "outcome": outcome}


@router.post("/webhook/razorpay", include_in_schema=False)
async def razorpay_webhook(
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if settings.payments_provider not in ("razorpay", "upi") or not settings.razorpay_webhook_secret:
        raise ApiError(404, "not_found", "Not found.")
    payload = await request.body()
    if not verify_razorpay_signature(payload, request.headers.get("x-razorpay-signature"), settings.razorpay_webhook_secret):
        raise ApiError(400, "invalid_signature", "Signature verification failed.")
    try:
        event = json.loads(payload)
    except ValueError:
        raise ApiError(400, "invalid_payload", "The payload is not valid JSON.")
    outcome = billing.handle_razorpay_event(db, settings, background, event)
    log.info("Razorpay webhook %s: %s", event.get("event"), outcome)
    return {"received": True, "outcome": outcome}
