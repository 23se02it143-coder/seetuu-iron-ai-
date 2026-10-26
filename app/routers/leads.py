"""Lead-generation endpoints: waitlist, contact form and the readiness assessment."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..database import get_db
from ..errors import ApiError
from ..models import Assessment, ContactMessage, Program, User, WaitlistEntry
from ..ratelimit import rate_limit
from ..schemas import AssessmentIn, ContactIn, ProgramOut, WaitlistIn
from ..security import optional_user
from ..services import emails, recommender
from ..services import waitlist as waitlist_service
from ..services.mailer import send_email

router = APIRouter(prefix="/api", tags=["leads"])


# ------------------------------------------------------------------ waitlist
@router.post("/waitlist", dependencies=[Depends(rate_limit("waitlist", 8, 3600))])
def join_waitlist(
    data: WaitlistIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if data.website:  # honeypot tripped: look successful, store nothing
        return {"status": "joined", "confirmation_required": False, "position": None, "total": None}
    return waitlist_service.join(db, settings, data, background)


@router.get("/waitlist/confirm", include_in_schema=False)
def confirm_waitlist(token: str = "", db: Session = Depends(get_db)):
    ok = bool(token) and waitlist_service.confirm(db, token)
    return RedirectResponse("/?waitlist=confirmed" if ok else "/?waitlist=invalid", status_code=303)


@router.get("/waitlist/unsubscribe", include_in_schema=False)
def unsubscribe_waitlist(token: str = "", db: Session = Depends(get_db)):
    ok = bool(token) and waitlist_service.unsubscribe(db, token)
    return RedirectResponse("/?waitlist=unsubscribed" if ok else "/?waitlist=invalid", status_code=303)


@router.get("/waitlist/status/{code}", dependencies=[Depends(rate_limit("waitlist-status", 60, 60))])
def waitlist_status(code: str, db: Session = Depends(get_db)):
    entry = db.scalars(select(WaitlistEntry).where(WaitlistEntry.referral_code == code.upper()[:12])).first()
    position = waitlist_service.queue_position(db, entry) if entry else None
    if entry is None or position is None:
        raise ApiError(404, "not_found", "We could not find that referral code.")
    return {
        "position": position,
        "total": waitlist_service.total_active(db),
        "referrals": waitlist_service.referral_count(db, entry),
    }


# ------------------------------------------------------------------- contact
@router.post("/contact", status_code=201, dependencies=[Depends(rate_limit("contact", 5, 3600))])
def send_contact(
    data: ContactIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if data.website:  # honeypot
        return {"ok": True}
    db.add(ContactMessage(name=data.name, email=data.email, company=data.company, topic=data.topic, message=data.message))
    db.commit()

    subject, body, html = emails.contact_receipt(settings, name=data.name)
    background.add_task(send_email, data.email, subject, body, html, "contact-receipt")
    inbox = settings.contact_inbox or settings.support_email
    if inbox:
        subject, body, html = emails.contact_notification(
            settings, name=data.name, email=data.email, company=data.company, topic=data.topic, message=data.message
        )
        background.add_task(send_email, inbox, subject, body, html, "contact-notification")
    return {"ok": True}


# --------------------------------------------------------------- assessment
@router.post("/assessments", dependencies=[Depends(rate_limit("assessment", 30, 3600))])
def create_assessment(
    data: AssessmentIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User | None = Depends(optional_user),
):
    """Score the answers. Nothing is stored unless the visitor explicitly asks to save the result."""
    if data.save and user is None:
        problems = {}
        if not data.email:
            problems["email"] = "Enter your email to save your plan"
        if not data.consent:
            problems["consent"] = "Tick the box to let us store your answers"
        if problems:
            raise ApiError(422, "validation_error", "Please check the highlighted fields.", fields=problems)

    result = recommender.assess(data)
    stored_result = dict(result)  # what we persist: no catalogue copy
    program = None
    if result["program_slug"]:
        row = db.scalars(select(Program).where(Program.slug == result["program_slug"])).first()
        program = ProgramOut.model_validate(row).model_dump() if row else None
    result["program"] = program

    saved, waitlist = False, None
    if data.save:
        address = user.email if user else data.email
        answers = data.model_dump(include={"goal", "experience", "days_per_week", "pain_areas", "recent_injury", "sleep", "red_flags"})
        db.add(Assessment(user_id=user.id if user else None, email=address, answers=answers, result=stored_result))
        db.commit()
        saved = True
        name = user.name if user else data.name
        subject, body, html = emails.assessment_plan(
            settings, name=name, headline=result["headline"], summary=result["summary"],
            insights=result["insights"], program=program["name"] if program else None,
        )
        background.add_task(send_email, address, subject, body, html, "assessment")
        if data.join_waitlist and address:
            from ..schemas import WaitlistIn

            waitlist = waitlist_service.join(
                db, settings, WaitlistIn(email=address, name=name, source="assessment"), background
            )
    return {"result": result, "saved": saved, "waitlist": waitlist}
