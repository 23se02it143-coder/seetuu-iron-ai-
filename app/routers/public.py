"""Read-only public endpoints: health, config, catalogue, stats, anonymous funnel events."""
from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..config import APP_VERSION, Settings, get_settings
from ..database import get_db, utcnow
from ..errors import ApiError
from ..models import AnalyticsEvent, Faq, Plan, Program, Testimonial
from ..ratelimit import rate_limit
from ..schemas import EventIn, FaqOut, PlanOut, ProgramOut, TestimonialOut
from ..services import waitlist as waitlist_service

router = APIRouter(prefix="/api", tags=["public"])

CACHE = {"Cache-Control": "public, max-age=60"}


@router.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        return JSONResponse({"status": "degraded", "version": APP_VERSION}, status_code=503)
    return {"status": "ok", "version": APP_VERSION, "time": utcnow().isoformat()}


@router.get("/config")
def public_config(settings: Settings = Depends(get_settings)):
    return {
        "app_name": settings.app_name,
        "currency": settings.currency.upper(),
        "payments_mode": "test" if settings.payments_provider == "mock" else "live",
        "waitlist_double_opt_in": settings.waitlist_double_opt_in,
        "coach_open_access": settings.coach_open,
        "assistant_mode": "ai" if settings.assistant_uses_llm and settings.anthropic_api_key else "guided",
    }


@router.get("/plans")
def list_plans(response: Response, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    response.headers.update(CACHE)
    plans = db.scalars(select(Plan).where(Plan.active).order_by(Plan.sort_order))
    return {"currency": settings.currency.upper(), "plans": [PlanOut.model_validate(p) for p in plans]}


@router.get("/programs")
def list_programs(response: Response, db: Session = Depends(get_db)):
    response.headers.update(CACHE)
    rows = db.scalars(select(Program).where(Program.published).order_by(Program.sort_order))
    return {"programs": [ProgramOut.model_validate(p) for p in rows]}


@router.get("/programs/{slug}")
def get_program(slug: str, response: Response, db: Session = Depends(get_db)):
    program = db.scalars(select(Program).where(Program.slug == slug, Program.published)).first()
    if program is None:
        raise ApiError(404, "program_not_found", "That program does not exist.")
    response.headers.update(CACHE)
    return ProgramOut.model_validate(program)


@router.get("/faqs")
def list_faqs(response: Response, db: Session = Depends(get_db)):
    response.headers.update(CACHE)
    rows = db.scalars(select(Faq).where(Faq.published).order_by(Faq.sort_order, Faq.id))
    return {"faqs": [FaqOut.model_validate(f) for f in rows]}


@router.get("/testimonials")
def list_testimonials(response: Response, db: Session = Depends(get_db)):
    response.headers.update(CACHE)
    rows = db.scalars(select(Testimonial).where(Testimonial.published).order_by(Testimonial.sort_order, Testimonial.id))
    return {"testimonials": [TestimonialOut.model_validate(t) for t in rows]}


@router.get("/stats")
def public_stats(response: Response, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    response.headers.update(CACHE)
    return {"waitlist_count": waitlist_service.public_count(db, settings)}


@router.post("/events", status_code=204, dependencies=[Depends(rate_limit("events", 120, 60))])
def track_event(data: EventIn, db: Session = Depends(get_db)):
    """Anonymous funnel counter. Stores no IP, cookie or user id; referrer is reduced to its hostname."""
    host = ""
    if data.referrer:
        try:
            host = (urlparse(data.referrer).hostname or "")[:120]
        except ValueError:
            host = ""
    path = data.path if data.path.startswith("/") else "/"
    db.add(AnalyticsEvent(name=data.name, path=path.split("?")[0][:120], referrer_host=host, utm_source=data.utm_source))
    db.commit()
    return Response(status_code=204)


@router.get("/programs/{slug}/schedule")
def program_schedule(slug: str, response: Response):
    from ..services.training import SCHEDULES

    data = SCHEDULES.get(slug)
    if not data:
        raise ApiError(404, "not_found", "No schedule for that program.")
    response.headers["Cache-Control"] = "public, max-age=300"
    return data


@router.get("/exercise-library")
def exercise_library(response: Response):
    from ..services.exercise_library import LIBRARY

    response.headers["Cache-Control"] = "public, max-age=300"
    return {"groups": LIBRARY}
