"""Waitlist logic: signup, referrals, queue position, double opt-in, unsubscribe."""
from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from fastapi import BackgroundTasks
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..config import Settings
from ..database import utcnow
from ..models import WaitlistEntry
from ..schemas import WaitlistIn
from . import emails
from .mailer import send_email

log = logging.getLogger("iron.waitlist")

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L
REFERRAL_BONUS = 10  # places gained per referred friend
EMAIL_COOLDOWN = timedelta(minutes=10)

_POSITION_SQL = text(
    """
    WITH refs AS (
        SELECT referred_by_id AS rid, COUNT(*) AS c
        FROM waitlist_entries
        WHERE referred_by_id IS NOT NULL AND status != 'unsubscribed'
        GROUP BY referred_by_id
    ), scored AS (
        SELECT w.id AS id, w.id - :bonus * COALESCE(r.c, 0) AS score
        FROM waitlist_entries w LEFT JOIN refs r ON r.rid = w.id
        WHERE w.status != 'unsubscribed'
    )
    SELECT 1 + COUNT(*) FROM scored
    WHERE score < (SELECT score FROM scored WHERE id = :id)
       OR (score = (SELECT score FROM scored WHERE id = :id) AND id < :id)
    """
)


def referral_url(settings: Settings, code: str) -> str:
    return f"{settings.base_url}/?ref={code}"


def new_code(db: Session) -> str:
    while True:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        if not db.scalar(select(WaitlistEntry.id).where(WaitlistEntry.referral_code == code)):
            return code


def queue_position(db: Session, entry: WaitlistEntry) -> int | None:
    if entry.status == "unsubscribed":
        return None
    return int(db.execute(_POSITION_SQL, {"id": entry.id, "bonus": REFERRAL_BONUS}).scalar_one())


def total_active(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(WaitlistEntry).where(WaitlistEntry.status != "unsubscribed")) or 0


def public_count(db: Session, settings: Settings) -> int | None:
    """Count shown on the landing page; hidden until it is large enough to be persuasive."""
    confirmed = db.scalar(select(func.count()).select_from(WaitlistEntry).where(WaitlistEntry.status == "confirmed")) or 0
    return confirmed if confirmed >= settings.waitlist_public_count_min else None


def referral_count(db: Session, entry: WaitlistEntry) -> int:
    return db.scalar(
        select(func.count()).select_from(WaitlistEntry).where(
            WaitlistEntry.referred_by_id == entry.id, WaitlistEntry.status != "unsubscribed"
        )
    ) or 0


def _queue_welcome(background: BackgroundTasks, settings: Settings, entry: WaitlistEntry, position: int) -> None:
    confirm_url = None
    if entry.status == "pending":
        confirm_url = f"{settings.base_url}/api/waitlist/confirm?token={entry.confirm_token}"
    unsub = f"{settings.base_url}/api/waitlist/unsubscribe?token={entry.unsubscribe_token}"
    subject, body, html = emails.waitlist_welcome(
        settings, name=entry.name, position=position, referral_url=referral_url(settings, entry.referral_code),
        confirm_url=confirm_url, unsubscribe_url=unsub,
    )
    background.add_task(send_email, entry.email, subject, body, html, "waitlist")
    entry.last_emailed_at = utcnow()


def join(db: Session, settings: Settings, data: WaitlistIn, background: BackgroundTasks) -> dict:
    entry = db.scalars(select(WaitlistEntry).where(WaitlistEntry.email == data.email)).first()
    status_after_join = "pending" if settings.waitlist_double_opt_in else "confirmed"

    if entry and entry.status != "unsubscribed":
        # Already on the list: resend the relevant email (rate-limited per entry), reveal nothing else.
        recently = entry.last_emailed_at and utcnow() - entry.last_emailed_at < EMAIL_COOLDOWN
        if not recently:
            if entry.status == "pending":
                _queue_welcome(background, settings, entry, queue_position(db, entry) or 0)
            else:
                unsub = f"{settings.base_url}/api/waitlist/unsubscribe?token={entry.unsubscribe_token}"
                subject, body, html = emails.waitlist_existing(
                    settings, name=entry.name, referral_url=referral_url(settings, entry.referral_code), unsubscribe_url=unsub
                )
                background.add_task(send_email, entry.email, subject, body, html, "waitlist")
                entry.last_emailed_at = utcnow()
            db.commit()
        return {"status": "exists", "confirmation_required": entry.status == "pending"}

    if entry:  # previously unsubscribed and now explicitly re-joining
        entry.status = status_after_join
        entry.name = data.name or entry.name
        entry.interest = data.interest
        entry.confirmed_at = utcnow() if status_after_join == "confirmed" else None
        created = False
    else:
        referrer = None
        if data.ref:
            referrer = db.scalars(select(WaitlistEntry).where(WaitlistEntry.referral_code == data.ref.upper())).first()
        entry = WaitlistEntry(
            email=data.email, name=data.name, interest=data.interest, goal=data.goal,
            referral_code=new_code(db), referred_by_id=referrer.id if referrer else None,
            status=status_after_join, confirm_token=secrets.token_urlsafe(32), unsubscribe_token=secrets.token_urlsafe(32),
            source=data.source, utm_source=data.utm_source, utm_medium=data.utm_medium, utm_campaign=data.utm_campaign,
            confirmed_at=utcnow() if status_after_join == "confirmed" else None,
        )
        db.add(entry)
        created = True
    db.flush()
    position = queue_position(db, entry) or 0
    _queue_welcome(background, settings, entry, position)
    db.commit()
    log.info("Waitlist %s: id=%s status=%s", "signup" if created else "re-join", entry.id, entry.status)
    return {
        "status": "joined",
        "confirmation_required": entry.status == "pending",
        "position": position,
        "total": total_active(db),
        "referral_code": entry.referral_code,
        "referral_url": referral_url(settings, entry.referral_code),
    }


def confirm(db: Session, token: str) -> bool:
    entry = db.scalars(select(WaitlistEntry).where(WaitlistEntry.confirm_token == token)).first()
    if entry is None:
        return False
    if entry.status == "pending":
        entry.status, entry.confirmed_at = "confirmed", utcnow()
        db.commit()
    return entry.status != "unsubscribed"


def unsubscribe(db: Session, token: str) -> bool:
    entry = db.scalars(select(WaitlistEntry).where(WaitlistEntry.unsubscribe_token == token)).first()
    if entry is None:
        return False
    entry.status = "unsubscribed"
    db.commit()
    return True
