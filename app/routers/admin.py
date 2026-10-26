"""Admin API: metrics, leads, content management. Every route requires an admin session."""
from __future__ import annotations

import csv
import io
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db, utcnow
from ..errors import ApiError
from ..models import (
    AnalyticsEvent,
    Assessment,
    ContactMessage,
    EmailOutbox,
    Faq,
    Subscription,
    Testimonial,
    User,
    WaitlistEntry,
)
from ..schemas import ContactUpdateIn, FaqIn, TestimonialIn
from ..security import admin_user

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(admin_user)])


# ------------------------------------------------------------------ helpers
def _page(db: Session, stmt: Select, page: int, per_page: int) -> tuple[list, int]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.limit(per_page).offset((page - 1) * per_page)).all()
    return rows, total


def csv_cell(value):
    """Neutralise spreadsheet formula injection (=, +, -, @ at the start of a cell)."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def _iso(value):
    return value.isoformat() if value else None


def _waitlist_row(w: WaitlistEntry) -> dict:
    return {
        "id": w.id, "email": w.email, "name": w.name, "interest": w.interest, "goal": w.goal, "status": w.status,
        "referral_code": w.referral_code, "referred_by_id": w.referred_by_id, "source": w.source,
        "utm_source": w.utm_source, "utm_medium": w.utm_medium, "utm_campaign": w.utm_campaign,
        "created_at": _iso(w.created_at),
    }


def _waitlist_query(q: str, status: str) -> Select:
    stmt = select(WaitlistEntry).order_by(WaitlistEntry.id.desc())
    if status:
        stmt = stmt.where(WaitlistEntry.status == status)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(WaitlistEntry.email).like(like), func.lower(WaitlistEntry.name).like(like)))
    return stmt


# ------------------------------------------------------------------ overview
@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    now = utcnow()
    week_ago, two_weeks_ago, month_ago = now - timedelta(days=7), now - timedelta(days=14), now - timedelta(days=30)

    def count(model, *conds) -> int:
        return db.scalar(select(func.count()).select_from(model).where(*conds)) or 0

    W = WaitlistEntry
    waitlist = {
        "total": count(W, W.status != "unsubscribed"),
        "confirmed": count(W, W.status == "confirmed"),
        "pending": count(W, W.status == "pending"),
        "unsubscribed": count(W, W.status == "unsubscribed"),
        "last_7d": count(W, W.created_at >= week_ago),
        "prev_7d": count(W, W.created_at >= two_weeks_ago, W.created_at < week_ago),
        "referred": count(W, W.referred_by_id.is_not(None)),
    }

    start = (now - timedelta(days=13)).replace(hour=0, minute=0, second=0, microsecond=0)
    per_day = {(start + timedelta(days=i)).date().isoformat(): 0 for i in range(14)}
    for created in db.scalars(select(W.created_at).where(W.created_at >= start)):
        key = created.date().isoformat()
        if key in per_day:
            per_day[key] += 1

    source_expr = func.coalesce(func.nullif(W.utm_source, ""), func.nullif(W.source, ""), "direct")
    sources = [
        {"source": s, "count": c}
        for s, c in db.execute(select(source_expr, func.count()).where(W.status != "unsubscribed").group_by(source_expr).order_by(func.count().desc()).limit(6))
    ]

    active = db.scalars(select(Subscription).where(Subscription.status.in_(("active", "past_due")))).all()
    mrr = sum(s.amount_cents if s.interval == "month" else round(s.amount_cents / 12) for s in active if s.status == "active")
    by_plan: dict[str, int] = {}
    for s in active:
        by_plan[s.plan.name] = by_plan.get(s.plan.name, 0) + 1

    events = {name: n for name, n in db.execute(select(AnalyticsEvent.name, func.count()).where(AnalyticsEvent.created_at >= month_ago).group_by(AnalyticsEvent.name))}

    return {
        "waitlist": waitlist,
        "signups_per_day": [{"date": d, "count": n} for d, n in per_day.items()],
        "sources": sources,
        "contacts": {"total": count(ContactMessage), "new": count(ContactMessage, ContactMessage.status == "new")},
        "users": count(User),
        "subscriptions": {"active": len(active), "mrr_cents": mrr, "by_plan": by_plan},
        "assessments_saved": count(Assessment),
        "funnel_30d": {
            "page_views": events.get("page_view", 0),
            "cta_clicks": events.get("cta_click", 0),
            "assessments_started": events.get("assessment_started", 0),
            "assessments_completed": events.get("assessment_completed", 0),
            "plans_selected": events.get("plan_selected", 0),
            "assistant_chats": events.get("assistant_used", 0),
            "coach_sessions": events.get("coach_started", 0),
            "diet_plans": events.get("diet_plan", 0),
            "waitlist_signups": count(W, W.created_at >= month_ago),
        },
    }


# ------------------------------------------------------------------ waitlist
@router.get("/waitlist")
def list_waitlist(
    q: str = Query("", max_length=100),
    status: str = Query("", pattern="^(|pending|confirmed|unsubscribed)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    rows, total = _page(db, _waitlist_query(q.strip(), status), page, per_page)
    return {"items": [_waitlist_row(w) for w in rows], "total": total, "page": page, "per_page": per_page}


@router.get("/waitlist.csv")
def export_waitlist(q: str = Query("", max_length=100), status: str = Query("", pattern="^(|pending|confirmed|unsubscribed)$"), db: Session = Depends(get_db)):
    columns = ["id", "email", "name", "interest", "goal", "status", "referral_code", "source", "utm_source", "utm_medium", "utm_campaign", "created_at"]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for entry in db.scalars(_waitlist_query(q.strip(), status)):
        row = _waitlist_row(entry)
        writer.writerow([csv_cell(row[c]) for c in columns])
    return Response(
        buffer.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="waitlist-{utcnow().date().isoformat()}.csv"'},
    )


# ------------------------------------------------------------------ contacts
@router.get("/contacts")
def list_contacts(
    status: str = Query("", pattern="^(|new|handled)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    stmt = select(ContactMessage).order_by(ContactMessage.id.desc())
    if status:
        stmt = stmt.where(ContactMessage.status == status)
    rows, total = _page(db, stmt, page, per_page)
    items = [
        {"id": c.id, "name": c.name, "email": c.email, "company": c.company, "topic": c.topic, "message": c.message, "status": c.status, "created_at": _iso(c.created_at)}
        for c in rows
    ]
    return {"items": items, "total": total, "page": page, "per_page": per_page}


@router.patch("/contacts/{contact_id}")
def update_contact(contact_id: int, data: ContactUpdateIn, db: Session = Depends(get_db)):
    contact = db.get(ContactMessage, contact_id)
    if contact is None:
        raise ApiError(404, "not_found", "Message not found.")
    contact.status = data.status
    db.commit()
    return {"id": contact.id, "status": contact.status}


# ------------------------------------------------------- subscriptions / users
@router.get("/subscriptions")
def list_subscriptions(page: int = Query(1, ge=1), per_page: int = Query(25, ge=1, le=100), db: Session = Depends(get_db)):
    rows, total = _page(db, select(Subscription).order_by(Subscription.id.desc()), page, per_page)
    items = [
        {
            "id": s.id, "email": s.user.email, "plan": s.plan.name, "interval": s.interval, "status": s.status,
            "amount_cents": s.amount_cents, "currency": s.currency, "provider": s.provider,
            "current_period_end": _iso(s.current_period_end), "cancel_at_period_end": s.cancel_at_period_end,
            "created_at": _iso(s.created_at),
        }
        for s in rows
    ]
    return {"items": items, "total": total, "page": page, "per_page": per_page}


@router.get("/users")
def list_users(q: str = Query("", max_length=100), page: int = Query(1, ge=1), per_page: int = Query(25, ge=1, le=100), db: Session = Depends(get_db)):
    stmt = select(User).order_by(User.id.desc())
    if q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(User.email).like(like), func.lower(User.name).like(like)))
    rows, total = _page(db, stmt, page, per_page)
    items = [{"id": u.id, "email": u.email, "name": u.name, "role": u.role, "created_at": _iso(u.created_at), "last_login_at": _iso(u.last_login_at)} for u in rows]
    return {"items": items, "total": total, "page": page, "per_page": per_page}


# -------------------------------------------------------------------- emails
@router.get("/emails")
def list_emails(limit: int = Query(30, ge=1, le=100), db: Session = Depends(get_db)):
    rows = db.scalars(select(EmailOutbox).order_by(EmailOutbox.id.desc()).limit(limit))
    return {
        "items": [
            {"id": e.id, "to": e.to_address, "subject": e.subject, "kind": e.kind, "status": e.status, "error": e.error, "body": e.body_text, "created_at": _iso(e.created_at)}
            for e in rows
        ]
    }


# ------------------------------------------------------------------- content
def _testimonial_row(t: Testimonial) -> dict:
    return {"id": t.id, "name": t.name, "role": t.role, "quote": t.quote, "rating": t.rating, "published": t.published, "is_sample": t.is_sample, "sort_order": t.sort_order}


@router.get("/testimonials")
def admin_testimonials(db: Session = Depends(get_db)):
    return {"items": [_testimonial_row(t) for t in db.scalars(select(Testimonial).order_by(Testimonial.sort_order, Testimonial.id))]}


@router.post("/testimonials", status_code=201)
def create_testimonial(data: TestimonialIn, db: Session = Depends(get_db)):
    row = Testimonial(**data.model_dump(), is_sample=False)
    db.add(row)
    db.commit()
    return _testimonial_row(row)


@router.put("/testimonials/{item_id}")
def update_testimonial(item_id: int, data: TestimonialIn, db: Session = Depends(get_db)):
    row = db.get(Testimonial, item_id)
    if row is None:
        raise ApiError(404, "not_found", "Testimonial not found.")
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    row.is_sample = False  # once an admin edits it, it is no longer sample copy
    db.commit()
    return _testimonial_row(row)


@router.delete("/testimonials/{item_id}", status_code=204)
def delete_testimonial(item_id: int, db: Session = Depends(get_db)):
    row = db.get(Testimonial, item_id)
    if row is None:
        raise ApiError(404, "not_found", "Testimonial not found.")
    db.delete(row)
    db.commit()
    return Response(status_code=204)


def _faq_row(f: Faq) -> dict:
    return {"id": f.id, "question": f.question, "answer": f.answer, "published": f.published, "sort_order": f.sort_order}


@router.get("/faqs")
def admin_faqs(db: Session = Depends(get_db)):
    return {"items": [_faq_row(f) for f in db.scalars(select(Faq).order_by(Faq.sort_order, Faq.id))]}


@router.post("/faqs", status_code=201)
def create_faq(data: FaqIn, db: Session = Depends(get_db)):
    row = Faq(**data.model_dump())
    db.add(row)
    db.commit()
    return _faq_row(row)


@router.put("/faqs/{item_id}")
def update_faq(item_id: int, data: FaqIn, db: Session = Depends(get_db)):
    row = db.get(Faq, item_id)
    if row is None:
        raise ApiError(404, "not_found", "FAQ not found.")
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    db.commit()
    return _faq_row(row)


@router.delete("/faqs/{item_id}", status_code=204)
def delete_faq(item_id: int, db: Session = Depends(get_db)):
    row = db.get(Faq, item_id)
    if row is None:
        raise ApiError(404, "not_found", "FAQ not found.")
    db.delete(row)
    db.commit()
    return Response(status_code=204)
