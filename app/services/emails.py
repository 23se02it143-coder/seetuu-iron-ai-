"""Email content. Each builder returns (subject, plain_text, html)."""
from __future__ import annotations

from html import escape

from ..config import Settings

_BRAND = "#4d061c"


def _money(cents: int, currency: str) -> str:
    symbol = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹"}.get(currency.upper(), currency.upper() + " ")
    value = cents / 100
    return f"{symbol}{value:,.0f}" if cents % 100 == 0 else f"{symbol}{value:,.2f}"


def _wrap(settings: Settings, heading: str, paragraphs: list[str], cta: tuple[str, str] | None = None, footer: str = "") -> str:
    body = "".join(f'<p style="margin:0 0 16px;line-height:1.6;color:#d4d4d4">{escape(p)}</p>' for p in paragraphs)
    button = (
        f'<p style="margin:28px 0"><a href="{escape(cta[1], quote=True)}" style="background:{_BRAND};color:#fff;'
        f'text-decoration:none;padding:14px 28px;border-radius:999px;font-weight:600;display:inline-block">{escape(cta[0])}</a></p>'
        if cta
        else ""
    )
    foot = f'<p style="margin:32px 0 0;font-size:12px;color:#8a8a8a;line-height:1.5">{escape(footer)}</p>' if footer else ""
    return (
        '<!doctype html><html><body style="margin:0;background:#171717;padding:32px 16px;'
        'font-family:Inter,Helvetica,Arial,sans-serif">'
        '<div style="max-width:560px;margin:0 auto;background:#212121;border:1px solid #333;border-radius:20px;padding:40px">'
        f'<p style="margin:0 0 28px;font-family:Georgia,serif;font-size:22px;color:#fff;font-weight:bold">'
        f'<span style="color:#e5758f">IRON</span>-AI</p>'
        f'<h1 style="margin:0 0 20px;font-family:Georgia,serif;font-size:28px;line-height:1.2;color:#fff;font-weight:500">{escape(heading)}</h1>'
        f"{body}{button}{foot}</div></body></html>"
    )


# ------------------------------------------------------------------- waitlist
def waitlist_welcome(settings: Settings, *, name: str, position: int, referral_url: str, confirm_url: str | None, unsubscribe_url: str):
    hello = f"Hi {name}," if name else "Hi,"
    if confirm_url:
        subject = f"Confirm your place on the {settings.app_name} waitlist"
        paras = [hello, "Please confirm your email address to secure your place on the waitlist."]
        cta = ("Confirm my place", confirm_url)
        text = f"{hello}\n\nConfirm your place on the {settings.app_name} waitlist:\n{confirm_url}\n"
    else:
        subject = f"You're on the {settings.app_name} waitlist (#{position})"
        paras = [
            hello,
            f"You're number {position} on the waitlist. We'll email you as soon as your spot opens.",
            "Want to move up? Every friend who joins with your link moves you 10 places closer to the front.",
        ]
        cta = ("Share your link", referral_url)
        text = (
            f"{hello}\n\nYou're number {position} on the {settings.app_name} waitlist.\n"
            f"Every friend who joins with your link moves you 10 places up:\n{referral_url}\n"
        )
    footer = "You received this because you joined the waitlist. Unsubscribe: " + unsubscribe_url
    text += f"\n--\nUnsubscribe: {unsubscribe_url}\n"
    return subject, text, _wrap(settings, "You're on the list" if not confirm_url else "One more step", paras, cta, footer)


def waitlist_existing(settings: Settings, *, name: str, referral_url: str, unsubscribe_url: str):
    hello = f"Hi {name}," if name else "Hi,"
    subject = f"You're already on the {settings.app_name} waitlist"
    paras = [hello, "Good news: you're already on the waitlist. Here's your personal referral link."]
    text = f"{hello}\n\nYou're already on the {settings.app_name} waitlist.\nYour referral link: {referral_url}\n\n--\nUnsubscribe: {unsubscribe_url}\n"
    return subject, text, _wrap(settings, "You're already in", paras, ("Share your link", referral_url), "Unsubscribe: " + unsubscribe_url)


# -------------------------------------------------------------------- contact
def contact_receipt(settings: Settings, *, name: str):
    subject = f"We received your message - {settings.app_name}"
    paras = [f"Hi {name},", "Thanks for getting in touch. A member of the team will reply within two business days."]
    text = f"Hi {name},\n\nThanks for getting in touch. A member of the team will reply within two business days.\n\n{settings.company_name}\n"
    return subject, text, _wrap(settings, "Message received", paras)


def contact_notification(settings: Settings, *, name: str, email: str, company: str, topic: str, message: str):
    subject = f"[{settings.app_name}] New {topic} enquiry from {name}"
    text = f"From: {name} <{email}>\nCompany: {company or '-'}\nTopic: {topic}\n\n{message}\n"
    return subject, text, _wrap(settings, f"New {topic} enquiry", [f"{name} <{email}>" + (f" ({company})" if company else ""), message])


# ----------------------------------------------------------------------- auth
def welcome(settings: Settings, *, name: str):
    subject = f"Welcome to {settings.app_name}"
    paras = [f"Hi {name},", "Your account is ready. Take the 60-second readiness assessment to get a starting program."]
    text = f"Hi {name},\n\nYour account is ready. Take the 60-second readiness assessment: {settings.base_url}/#assessment\n"
    return subject, text, _wrap(settings, "Welcome aboard", paras, ("Take the assessment", f"{settings.base_url}/#assessment"))


def password_reset(settings: Settings, *, name: str, url: str):
    subject = f"Reset your {settings.app_name} password"
    paras = [f"Hi {name},", "Use the button below to choose a new password. The link works once and expires in 60 minutes.", "If you didn't ask for this, you can ignore this email; your password won't change."]
    text = f"Hi {name},\n\nChoose a new password (link expires in 60 minutes):\n{url}\n\nIf you didn't ask for this, ignore this email.\n"
    return subject, text, _wrap(settings, "Reset your password", paras, ("Choose a new password", url))


def password_changed(settings: Settings, *, name: str):
    subject = f"Your {settings.app_name} password was changed"
    paras = [f"Hi {name},", "Your password was just changed and all other sessions were signed out.", "If this wasn't you, reset your password immediately and contact us."]
    text = f"Hi {name},\n\nYour password was just changed and all other sessions were signed out.\nIf this wasn't you, reset your password immediately and contact us.\n"
    return subject, text, _wrap(settings, "Password changed", paras)


# -------------------------------------------------------------------- billing
def payment_notification(settings: Settings, *, name: str, email: str, plan: str, interval: str, amount_cents: int, currency: str, provider: str):
    """Sent to the site owner (settings.contact_inbox / support_email), not the customer, so a
    payment shows up as a notification without anyone needing to check the admin panel."""
    price = f"{_money(amount_cents, currency)} per {'year' if interval == 'year' else 'month'}"
    subject = f"Payment received: {plan} ({price}) via {provider}"
    paras = [
        f"{name} <{email}> just paid for {plan}, {price}, via {provider}.",
        "This is an automatic notification. Open the admin panel for the full invoice and subscriber list.",
    ]
    text = f"{paras[0]}\n\n{settings.base_url}/admin\n"
    return subject, text, _wrap(settings, "New payment", paras, ("Open admin panel", f"{settings.base_url}/admin"))


def upi_review_request(settings: Settings, *, name: str, email: str, plan: str, interval: str, amount_cents: int, currency: str, reference: str, review_url: str):
    """To the owner: a customer says they paid by UPI. Check your bank/UPI app for the amount and reference, then approve."""
    price = f"{_money(amount_cents, currency)} per {'year' if interval == 'year' else 'month'}"
    subject = f"UPI payment to confirm: {plan} ({price}) from {name}"
    paras = [
        f"{name} <{email}> says they paid {price} for {plan} by UPI.",
        f"Transaction reference (UTR): {reference}",
        "Check that the money is in your account with this reference, then open the link and tap Approve. The plan is only activated after you approve.",
    ]
    text = f"{paras[0]}\nUTR: {reference}\n\nReview and approve (or reject): {review_url}\n"
    return subject, text, _wrap(settings, "Confirm a UPI payment", paras, ("Review and approve", review_url))


def upi_payment_received(settings: Settings, *, name: str, plan: str, reference: str):
    subject = f"We received your payment details - {settings.app_name}"
    paras = [f"Hi {name},", f"Thanks! We have your UPI reference {reference} for the {plan} plan and are checking it now.", "You will get a confirmation email as soon as your plan is active (usually within a few hours)."]
    text = f"Hi {name},\n\nWe have your UPI reference {reference} for the {plan} plan and are checking it now.\nYou will get a confirmation email once your plan is active.\n"
    return subject, text, _wrap(settings, "Payment received - verifying", paras)


def upi_payment_rejected(settings: Settings, *, name: str):
    subject = f"We could not verify your payment - {settings.app_name}"
    paras = [f"Hi {name},", "We could not find a matching payment, so your plan was not activated.", f"If you did pay, reply to {settings.support_email} with a screenshot of the payment and we will sort it out."]
    text = f"Hi {name},\n\nWe could not find a matching payment, so your plan was not activated.\nIf you did pay, email {settings.support_email} with a screenshot.\n"
    return subject, text, _wrap(settings, "Payment not verified", paras)


def subscription_receipt(settings: Settings, *, name: str, plan: str, interval: str, amount_cents: int, currency: str, renews: str):
    price = f"{_money(amount_cents, currency)} per {'year' if interval == 'year' else 'month'}"
    subject = f"Your {settings.app_name} {plan} subscription"
    paras = [f"Hi {name},", f"Thanks for subscribing to {plan} ({price}).", f"Your next renewal date is {renews}. You can cancel any time from your account."]
    text = f"Hi {name},\n\nThanks for subscribing to {plan} ({price}).\nNext renewal: {renews}. Cancel any time from your account: {settings.base_url}/account\n"
    return subject, text, _wrap(settings, "Subscription confirmed", paras, ("Manage subscription", f"{settings.base_url}/account"))


# ----------------------------------------------------------------- assessment
def assessment_plan(settings: Settings, *, name: str, headline: str, summary: str, insights: list[str], program: str | None):
    subject = f"Your {settings.app_name} readiness plan"
    hello = f"Hi {name}," if name else "Hi,"
    paras = [hello, headline, summary, *insights]
    text = f"{hello}\n\n{headline}\n{summary}\n\n" + "\n".join(f"- {i}" for i in insights)
    if program:
        text += f"\n\nRecommended program: {program}"
    text += "\n\nThis is general guidance, not medical advice.\n"
    return subject, text, _wrap(settings, "Your readiness plan", paras, ("Explore programs", f"{settings.base_url}/#programs"), "General guidance only, not medical advice.")


def diet_plan(settings: Settings, *, name: str, plan: dict, goal: str):
    label = {"bulk": "bulking", "cut": "cutting", "recomp": "recomposition", "maintain": "maintenance"}[goal]
    t = plan["targets"]
    subject = f"Your {label} diet plan from {settings.app_name}"
    hello = f"Hi {name}," if name else "Hi,"
    head = f"Daily target: {t['calories']} kcal, {t['protein_g']} g protein, {t['carbs_g']} g carbs, {t['fat_g']} g fat, about {t['water_l']} L of water."
    lines = []
    for m in plan["meals"]:
        foods = "; ".join(f"{i['name']} ({i['serving']})" for i in m["items"])
        lines.append(f"{m['label']} ({m['time']}): {foods} (about {m['kcal']} kcal, {round(m['p'])} g protein)")
    text = f"{hello}\n\n{head}\n\n" + "\n".join(lines) + "\n\n" + plan["disclaimer"] + "\n"
    paras = [hello, head, *lines, plan["disclaimer"]]
    return subject, text, _wrap(settings, f"Your {label} plan", paras, ("Adjust my plan", f"{settings.base_url}/#diet"), "General guidance only, not medical or dietetic advice.")
