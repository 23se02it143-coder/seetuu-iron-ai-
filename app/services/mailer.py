"""Email delivery. Every message is recorded in the `email_outbox` table.

* If BREVO_API_KEY or RESEND_API_KEY is set, the message is sent through that HTTPS e-mail API
  (works on hosts that block SMTP ports, such as Render's free plan).
* Else if SMTP_HOST is set, the message is sent over SMTP (STARTTLS/SSL).
* Otherwise it is only logged and stored (status "logged") - perfect for local development:
  open the admin panel > Emails to read what would have been sent.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

import httpx

from ..config import Settings, get_settings
from ..database import SessionLocal, utcnow
from ..models import EmailOutbox

log = logging.getLogger("iron.mail")


def send_email(
    to: str,
    subject: str,
    text: str,
    html: str = "",
    kind: str = "",
    settings: Settings | None = None,
) -> None:
    """Record and deliver one email. Never raises: failures are stored on the outbox row."""
    settings = settings or get_settings()
    with SessionLocal() as db:
        row = EmailOutbox(to_address=to, subject=subject[:200], body_text=text, body_html=html, kind=kind)
        db.add(row)
        db.commit()

        if not (settings.brevo_api_key or settings.resend_api_key or settings.smtp_host):
            row.status = "logged"
            db.commit()
            log.info("Email logged (no e-mail provider configured): to=%s subject=%s", to, subject)
            return

        try:
            if settings.brevo_api_key:
                _brevo_send(settings, to, subject, text, html)
            elif settings.resend_api_key:
                _resend_send(settings, to, subject, text, html)
            else:
                _smtp_send(settings, to, subject, text, html)
            row.status, row.sent_at = "sent", utcnow()
        except Exception as exc:  # noqa: BLE001 - deliberately broad; we record and move on
            row.status, row.error = "failed", str(exc)[:300]
            log.exception("Email delivery failed: to=%s subject=%s", to, subject)
        db.commit()


def _brevo_send(settings: Settings, to: str, subject: str, text: str, html: str) -> None:
    """Brevo (ex-Sendinblue) transactional API. The sender address must be verified in Brevo."""
    name, address = parseaddr(settings.email_from)
    body = {
        "sender": {"name": name or settings.app_name, "email": address},
        "to": [{"email": to}],
        "subject": subject,
        "textContent": text,
    }
    if html:
        body["htmlContent"] = html
    r = httpx.post("https://api.brevo.com/v3/smtp/email", json=body, headers={"api-key": settings.brevo_api_key, "accept": "application/json"}, timeout=15)
    if r.status_code >= 300:
        raise RuntimeError(f"Brevo {r.status_code}: {r.text[:200]}")


def _resend_send(settings: Settings, to: str, subject: str, text: str, html: str) -> None:
    """Resend API. Without a verified domain, use EMAIL_FROM='IRON-AI <onboarding@resend.dev>' (delivers only to your own Resend login e-mail)."""
    body = {"from": settings.email_from, "to": [to], "subject": subject, "text": text}
    if html:
        body["html"] = html
    r = httpx.post("https://api.resend.com/emails", json=body, headers={"Authorization": f"Bearer {settings.resend_api_key}"}, timeout=15)
    if r.status_code >= 300:
        raise RuntimeError(f"Resend {r.status_code}: {r.text[:200]}")


def _smtp_send(settings: Settings, to: str, subject: str, text: str, html: str) -> None:
    name, address = parseaddr(settings.email_from)
    msg = EmailMessage()
    msg["From"] = formataddr((name, address)) if name else address
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    context = ssl.create_default_context()
    if settings.smtp_security == "ssl":
        server: smtplib.SMTP = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15, context=context)
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
        if settings.smtp_security == "starttls":
            server.starttls(context=context)
    try:
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except smtplib.SMTPException:  # pragma: no cover
            pass
