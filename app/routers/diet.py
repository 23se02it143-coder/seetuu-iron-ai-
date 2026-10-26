"""Diet planner and camera-coach session history."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..database import get_db
from ..models import User, WorkoutSession
from ..ratelimit import rate_limit
from ..schemas import DietEmailIn, DietIn, SessionIn, WaitlistIn
from ..security import current_user
from ..services import diet as diet_service
from ..services import emails
from ..services import waitlist as waitlist_service
from ..services.mailer import send_email

router = APIRouter(prefix="/api", tags=["diet", "sessions"])


def _profile(data: DietIn) -> diet_service.Profile:
    return diet_service.Profile(
        sex=data.sex, age=data.age, height_cm=data.height_cm, weight_kg=data.weight_kg, activity=data.activity,
        goal=data.goal, pace=data.pace, preference=data.preference, meals=data.meals,
    )


@router.post("/diet/plan", dependencies=[Depends(rate_limit("diet", 60, 3600))])
def diet_plan(data: DietIn):
    """Targets plus a full day of meals. Nothing is stored."""
    return diet_service.build_plan(_profile(data), data.variants)


@router.post("/diet/email", dependencies=[Depends(rate_limit("diet-email", 5, 3600))])
def email_diet_plan(
    data: DietEmailIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Email the plan to the address the visitor typed. Only sends when they press the button."""
    plan = diet_service.build_plan(_profile(data), data.variants)
    subject, body, html = emails.diet_plan(settings, name=data.name, plan=plan, goal=data.goal)
    background.add_task(send_email, data.email, subject, body, html, "diet")
    waitlist = None
    if data.join_waitlist:
        waitlist = waitlist_service.join(db, settings, WaitlistIn(email=data.email, name=data.name, source="diet"), background)
    return {"sent": True, "waitlist": waitlist}


# ---------------------------------------------------------------- sessions
@router.post("/sessions", status_code=201, dependencies=[Depends(rate_limit("sessions", 60, 3600))])
def save_session(data: SessionIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Store a finished form-coach session (numbers only, never video)."""
    row = WorkoutSession(
        user_id=user.id, exercise=data.exercise, reps=data.reps, avg_score=data.avg_score,
        best_score=data.best_score, duration_s=data.duration_s, faults=data.faults,
    )
    db.add(row)
    db.commit()
    return {"id": row.id}


@router.get("/sessions")
def list_sessions(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(
        select(WorkoutSession).where(WorkoutSession.user_id == user.id).order_by(WorkoutSession.id.desc()).limit(30)
    ).all()
    totals = db.execute(
        select(func.count(), func.coalesce(func.sum(WorkoutSession.reps), 0), func.coalesce(func.avg(WorkoutSession.avg_score), 0))
        .where(WorkoutSession.user_id == user.id)
    ).one()
    return {
        "sessions": [
            {
                "id": r.id, "exercise": r.exercise, "reps": r.reps, "avg_score": r.avg_score, "best_score": r.best_score,
                "duration_s": r.duration_s, "faults": r.faults, "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "summary": {"sessions": int(totals[0]), "reps": int(totals[1]), "avg_score": round(float(totals[2]))},
    }
