"""Payment providers.

* `mock`     - a built-in test-mode checkout page (no card data, no money moves). Default.
* `stripe`   - Stripe Checkout (hosted page) + webhooks, talking to Stripe's REST API directly
               via httpx, so there is no SDK to install.
* `razorpay` - a Razorpay Payment Link (hosted page covering UPI, cards, netbanking and wallets)
               + a webhook, via Razorpay's REST API directly. See RazorpayProvider below for why
               Payment Links rather than the Subscriptions API, and README.md for setup.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass

import httpx

from ..config import Settings
from ..errors import ApiError
from ..models import CheckoutSession, Plan, Subscription, User

log = logging.getLogger("iron.payments")


@dataclass
class CheckoutResult:
    url: str
    provider_session_id: str | None = None


class MockProvider:
    name = "mock"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def create_checkout(self, *, checkout: CheckoutSession, user: User, plan: Plan, customer_id: str | None = None) -> CheckoutResult:
        return CheckoutResult(url=f"/checkout/{checkout.id}")  # relative: stays on whichever host (localhost or 127.0.0.1) the visitor is using, so the session cookie is kept

    def set_cancel_at_period_end(self, sub: Subscription, value: bool) -> None:
        return None

    def cancel_now(self, provider_subscription_id: str) -> None:
        return None


class UpiProvider:
    """Manual UPI: the checkout page shows a QR / UPI ID for the owner's account. The customer pays in
    any UPI app and submits the transaction reference; the owner confirms it from an e-mailed link."""

    name = "upi"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def create_checkout(self, *, checkout: CheckoutSession, user: User, plan: Plan, customer_id: str | None = None) -> CheckoutResult:
        return CheckoutResult(url=f"/checkout/{checkout.id}")

    def set_cancel_at_period_end(self, sub: Subscription, value: bool) -> None:
        return None

    def cancel_now(self, provider_subscription_id: str) -> None:
        return None


def upi_uri(settings: Settings, checkout: CheckoutSession, plan: Plan) -> str:
    """The standard `upi://pay` deep link (also what the QR encodes), with the amount pre-filled."""
    from urllib.parse import quote

    amount = f"{checkout.amount_cents / 100:.2f}"
    note = f"{settings.app_name} {plan.name} {checkout.id[-6:]}"
    return (
        f"upi://pay?pa={quote(settings.upi_id, safe='@')}&pn={quote(settings.upi_name)}"
        f"&am={amount}&cu={checkout.currency}&tn={quote(note)}"
    )


class StripeProvider:
    name = "stripe"
    API = "https://api.stripe.com/v1"

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.client = client or httpx.Client(timeout=httpx.Timeout(20.0))

    def _request(self, method: str, path: str, data: dict[str, str] | None = None) -> dict:
        try:
            response = self.client.request(method, f"{self.API}{path}", data=data, auth=(self.settings.stripe_secret_key, ""))
        except httpx.HTTPError as exc:
            log.error("Stripe request failed: %s", exc)
            raise ApiError(502, "payment_provider_unreachable", "The payment provider is unreachable. Please try again shortly.") from exc
        if response.status_code >= 400:
            log.error("Stripe error %s on %s %s: %s", response.status_code, method, path, response.text[:300])
            raise ApiError(502, "payment_provider_error", "The payment provider rejected the request. Please try again or contact support.")
        return response.json()

    def create_checkout(self, *, checkout: CheckoutSession, user: User, plan: Plan, customer_id: str | None = None) -> CheckoutResult:
        base = self.settings.base_url
        data = {
            "mode": "subscription",
            "success_url": f"{base}/account?checkout=success",
            "cancel_url": f"{base}/?checkout=cancelled#pricing",
            "client_reference_id": str(user.id),
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": checkout.currency.lower(),
            "line_items[0][price_data][unit_amount]": str(checkout.amount_cents),
            "line_items[0][price_data][recurring][interval]": checkout.interval,
            "line_items[0][price_data][product_data][name]": f"{self.settings.app_name} {plan.name}",
            "metadata[checkout_id]": checkout.id,
            "subscription_data[metadata][checkout_id]": checkout.id,
            "subscription_data[metadata][user_id]": str(user.id),
        }
        if customer_id:
            data["customer"] = customer_id
        else:
            data["customer_email"] = user.email
        session = self._request("POST", "/checkout/sessions", data)
        return CheckoutResult(url=session["url"], provider_session_id=session["id"])

    def set_cancel_at_period_end(self, sub: Subscription, value: bool) -> None:
        if sub.provider_subscription_id:
            self._request("POST", f"/subscriptions/{sub.provider_subscription_id}", {"cancel_at_period_end": "true" if value else "false"})

    def cancel_now(self, provider_subscription_id: str) -> None:
        self._request("DELETE", f"/subscriptions/{provider_subscription_id}")


class RazorpayProvider:
    """Razorpay Payment Links: one hosted page per billing period, covering UPI, cards, netbanking
    and wallets. Chosen over Razorpay's Subscriptions API (recurring auto-debit mandates) because it
    maps onto this app's existing "redirect to a URL, confirm by webhook" shape with no frontend
    changes at all, and because it is the smaller, better-documented surface to get right without a
    live Razorpay account to test against. A subscription paid this way does not auto-renew with
    Razorpay; near the end of the period the account page prompts for a fresh payment link (see
    billing.current_subscription, which marks it "past_due" instead of silently rolling it forward).
    """

    name = "razorpay"
    API = "https://api.razorpay.com/v1"

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.client = client or httpx.Client(timeout=httpx.Timeout(20.0))

    def _request(self, method: str, path: str, json: dict) -> dict:
        try:
            response = self.client.request(method, f"{self.API}{path}", json=json, auth=(self.settings.razorpay_key_id, self.settings.razorpay_key_secret))
        except httpx.HTTPError as exc:
            log.error("Razorpay request failed: %s", exc)
            raise ApiError(502, "payment_provider_unreachable", "The payment provider is unreachable. Please try again shortly.") from exc
        if response.status_code >= 400:
            log.error("Razorpay error %s on %s %s: %s", response.status_code, method, path, response.text[:300])
            raise ApiError(502, "payment_provider_error", "The payment provider rejected the request. Please try again or contact support.")
        return response.json()

    def create_checkout(self, *, checkout: CheckoutSession, user: User, plan: Plan, customer_id: str | None = None) -> CheckoutResult:
        period = "year" if checkout.interval == "year" else "month"
        link = self._request(
            "POST",
            "/payment_links",
            {
                "amount": checkout.amount_cents,  # Razorpay wants the amount in paise, same as our *_cents columns for INR
                "currency": checkout.currency,
                "accept_partial": False,
                "description": f"{self.settings.app_name} {plan.name} ({period}ly)",
                "customer": {"name": user.name, "email": user.email},
                "notify": {"sms": False, "email": True},
                "reminder_enable": False,
                "reference_id": checkout.id,
                "notes": {"checkout_id": checkout.id, "user_id": str(user.id), "plan_slug": plan.slug, "interval": checkout.interval},
                "callback_url": f"{self.settings.base_url}/account?checkout=success",
                "callback_method": "get",
            },
        )
        return CheckoutResult(url=link["short_url"], provider_session_id=link["id"])

    def set_cancel_at_period_end(self, sub: Subscription, value: bool) -> None:
        return None  # nothing recurring is running at Razorpay's end to stop; see the class docstring

    def cancel_now(self, provider_subscription_id: str) -> None:
        return None


def verify_razorpay_signature(payload: bytes, header: str | None, secret: str) -> bool:
    """Razorpay's documented webhook scheme: X-Razorpay-Signature = HMAC-SHA256(webhook_secret, raw_body), hex-encoded."""
    if not header or not secret:
        return False
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def verify_stripe_signature(payload: bytes, header: str | None, secret: str, tolerance: int = 300, now: float | None = None) -> bool:
    """Verify a `Stripe-Signature` header (scheme v1: HMAC-SHA256 over "{timestamp}.{payload}")."""
    if not header or not secret:
        return False
    timestamp: str | None = None
    signatures: list[str] = []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            timestamp = value
        elif key == "v1":
            signatures.append(value)
    if not timestamp or not signatures or not timestamp.isdigit():
        return False
    if abs((now if now is not None else time.time()) - int(timestamp)) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, sig) for sig in signatures)


def build_provider(settings: Settings) -> MockProvider | StripeProvider | RazorpayProvider | UpiProvider:
    if settings.payments_provider == "upi":
        return UpiProvider(settings)
    if settings.payments_provider == "stripe":
        if not settings.stripe_secret_key:
            raise ApiError(503, "payments_not_configured", "Payments are not configured yet.")
        return StripeProvider(settings)
    if settings.payments_provider == "razorpay":
        if not settings.razorpay_key_id or not settings.razorpay_key_secret:
            raise ApiError(503, "payments_not_configured", "Payments are not configured yet.")
        return RazorpayProvider(settings)
    return MockProvider(settings)
