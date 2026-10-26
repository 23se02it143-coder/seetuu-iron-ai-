"""Accounts: register, sign in/out, profile, password reset, data export and deletion."""
from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..database import get_db, utcnow
from ..errors import ApiError
from ..models import Assessment, WorkoutSession, Invoice, PasswordResetToken, Subscription, User, WaitlistEntry
from ..ratelimit import rate_limit
from ..schemas import (
    DeleteAccountIn,
    ForgotIn,
    LoginIn,
    PasswordChangeIn,
    ProfileIn,
    RegisterIn,
    ResetIn,
    UserOut,
)
from ..security import (
    burn_password_check,
    clear_session_cookie,
    current_user,
    hash_password,
    new_token,
    optional_user,
    session_needs_refresh,
    set_session_cookie,
    sha256,
    validate_password_strength,
    verify_password,
)
from ..services import billing, emails
from ..services.mailer import send_email
from ..services.payments import build_provider

log = logging.getLogger("iron.auth")
router = APIRouter(prefix="/api/auth", tags=["auth"])

RESET_TTL = timedelta(minutes=60)


def _user_out(user: User) -> dict:
    return UserOut.model_validate(user).model_dump(mode="json")


@router.get("/session")
def session(request: Request, response: Response, user: User | None = Depends(optional_user), settings: Settings = Depends(get_settings)):
    """Never errors: the site header uses it to decide between 'Sign in' and 'Account'.

    Every page calls this once on load, which makes it the natural place for "remember me": once a
    session is past the midpoint of its life, silently reissue the cookie with a fresh expiry, so
    anyone who visits at least once every `session_days` stays signed in indefinitely.
    """
    if user and session_needs_refresh(getattr(request.state, "session_claims", {}), settings):
        set_session_cookie(response, user, settings)
    return {"user": _user_out(user) if user else None}


@router.post("/register", status_code=201, dependencies=[Depends(rate_limit("register", 10, 3600))])
def register(
    data: RegisterIn,
    response: Response,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if db.scalars(select(User).where(User.email == data.email)).first():
        raise ApiError(409, "email_taken", "An account with this email already exists.", fields={"email": "An account with this email already exists. Try signing in."})
    user = User(email=data.email, name=data.name, password_hash=hash_password(data.password, settings.bcrypt_rounds), last_login_at=utcnow())
    db.add(user)
    db.commit()
    set_session_cookie(response, user, settings)
    subject, text, html = emails.welcome(settings, name=user.name)
    background.add_task(send_email, user.email, subject, text, html, "welcome")
    return {"user": _user_out(user)}


@router.post("/login", dependencies=[Depends(rate_limit("login", 10, 300))])
def login(data: LoginIn, response: Response, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    email = data.email.strip().lower()
    user = db.scalars(select(User).where(User.email == email)).first()
    if user is None or not user.is_active:
        burn_password_check(data.password)
        raise ApiError(401, "invalid_credentials", "Email or password is incorrect.")
    if not verify_password(data.password, user.password_hash):
        raise ApiError(401, "invalid_credentials", "Email or password is incorrect.")
    user.last_login_at = utcnow()
    db.commit()
    set_session_cookie(response, user, settings)
    return {"user": _user_out(user)}


@router.post("/logout")
def logout(response: Response):
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return {"user": _user_out(user)}


@router.patch("/me")
def update_profile(data: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.name = data.name
    db.commit()
    return {"user": _user_out(user)}


@router.post("/password", dependencies=[Depends(rate_limit("password", 10, 900))])
def change_password(
    data: PasswordChangeIn,
    response: Response,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not verify_password(data.current_password, user.password_hash):
        raise ApiError(400, "wrong_password", "Your current password is incorrect.", fields={"current_password": "Your current password is incorrect."})
    problem = validate_password_strength(data.new_password, email=user.email)
    if problem:
        raise ApiError(422, "validation_error", "Please check the highlighted fields.", fields={"new_password": problem})
    user.password_hash = hash_password(data.new_password, settings.bcrypt_rounds)
    user.token_version += 1  # signs out every other device
    db.commit()
    set_session_cookie(response, user, settings)  # keep this device signed in
    subject, text, html = emails.password_changed(settings, name=user.name)
    background.add_task(send_email, user.email, subject, text, html, "password-changed")
    return {"ok": True}


@router.post("/forgot", dependencies=[Depends(rate_limit("forgot", 5, 3600))])
def forgot_password(data: ForgotIn, background: BackgroundTasks, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    """Always answers the same way so it cannot be used to discover which emails have accounts."""
    user = db.scalars(select(User).where(User.email == data.email, User.is_active)).first()
    if user:
        raw = new_token()
        db.add(PasswordResetToken(user_id=user.id, token_hash=sha256(raw), expires_at=utcnow() + RESET_TTL))
        db.commit()
        subject, text, html = emails.password_reset(settings, name=user.name, url=f"{settings.base_url}/account?reset={raw}")
        background.add_task(send_email, user.email, subject, text, html, "password-reset")
    return {"ok": True, "message": "If an account exists for that email, a reset link is on its way."}


@router.post("/reset", dependencies=[Depends(rate_limit("reset", 10, 3600))])
def reset_password(data: ResetIn, response: Response, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    invalid = ApiError(400, "invalid_token", "This reset link is invalid or has expired. Request a new one.")
    row = db.scalars(select(PasswordResetToken).where(PasswordResetToken.token_hash == sha256(data.token))).first()
    if row is None or row.used_at is not None or row.expires_at <= utcnow():
        raise invalid
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise invalid
    problem = validate_password_strength(data.password, email=user.email)
    if problem:
        raise ApiError(422, "validation_error", "Please check the highlighted fields.", fields={"password": problem})
    user.password_hash = hash_password(data.password, settings.bcrypt_rounds)
    user.token_version += 1
    now = utcnow()
    db.execute(update(PasswordResetToken).where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None)).values(used_at=now))
    db.commit()
    set_session_cookie(response, user, settings)
    return {"user": _user_out(user)}


@router.get("/export")
def export_data(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Download everything we hold about the signed-in user (GDPR data portability)."""
    subs = db.scalars(select(Subscription).where(Subscription.user_id == user.id)).all()
    payload = {
        "exported_at": utcnow().isoformat(),
        "account": _user_out(user),
        "subscriptions": [billing.serialize_subscription(db, s) for s in subs],
        "invoices": [
            {"description": i.description, "amount_cents": i.amount_cents, "currency": i.currency, "status": i.status, "created_at": i.created_at.isoformat()}
            for i in db.scalars(select(Invoice).where(Invoice.user_id == user.id))
        ],
        "assessments": [
            {"answers": a.answers, "result": a.result, "created_at": a.created_at.isoformat()}
            for a in db.scalars(select(Assessment).where(Assessment.user_id == user.id))
        ],
        "workout_sessions": [
            {"exercise": w.exercise, "reps": w.reps, "avg_score": w.avg_score, "best_score": w.best_score, "duration_s": w.duration_s, "faults": w.faults, "created_at": w.created_at.isoformat()}
            for w in db.scalars(select(WorkoutSession).where(WorkoutSession.user_id == user.id))
        ],
        "waitlist": [
            {"email": w.email, "status": w.status, "referral_code": w.referral_code, "created_at": w.created_at.isoformat()}
            for w in db.scalars(select(WaitlistEntry).where(WaitlistEntry.email == user.email))
        ],
    }
    return JSONResponse(payload, headers={"Content-Disposition": 'attachment; filename="iron-ai-data-export.json"'})


@router.delete("/me", dependencies=[Depends(rate_limit("delete-account", 5, 3600))])
def delete_account(
    data: DeleteAccountIn,
    response: Response,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if user.role == "admin":
        raise ApiError(400, "admin_protected", "Admin accounts cannot be deleted from here.")
    if not verify_password(data.password, user.password_hash):
        raise ApiError(400, "wrong_password", "Your password is incorrect.", fields={"password": "Your password is incorrect."})

    live = billing.current_subscription(db, user)
    if live and live.provider == "stripe" and live.provider_subscription_id:
        try:
            build_provider(settings).cancel_now(live.provider_subscription_id)
        except ApiError:
            raise ApiError(502, "cancel_failed", "We could not cancel your subscription with the payment provider, so the account was not deleted. Please try again.")

    # Invoices are kept for bookkeeping but detached from the person.
    db.execute(update(Invoice).where(Invoice.user_id == user.id).values(user_id=None, subscription_id=None))
    for entry in db.scalars(select(WaitlistEntry).where(WaitlistEntry.email == user.email)):
        db.delete(entry)
    db.delete(user)
    db.commit()
    clear_session_cookie(response)
    return {"ok": True}
