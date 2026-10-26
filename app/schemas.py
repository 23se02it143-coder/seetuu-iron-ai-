"""Request and response models."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
)

from .security import validate_password_strength

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean(value):
    return _CONTROL.sub("", value).strip() if isinstance(value, str) else value


def _clean_email(value):
    return _clean(value).lower() if isinstance(value, str) else value


def _email_length(value: str) -> str:
    if len(value) > 254:
        raise ValueError("Email address is too long")
    return value


def text(min_length: int = 0, max_length: int = 200):
    return Annotated[str, BeforeValidator(_clean), StringConstraints(min_length=min_length, max_length=max_length)]


Email = Annotated[EmailStr, BeforeValidator(_clean_email), AfterValidator(_email_length)]
Name = text(1, 80)
OptionalText = text(0, 160)


class Strict(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=False)


# ---------------------------------------------------------------- catalogue
class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    slug: str
    name: str
    tagline: str
    price_monthly_cents: int
    price_annual_cents: int
    features: list[str]
    highlight: bool
    badge: str
    cta_label: str


class ProgramOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    slug: str
    code: str
    name: str
    tagline: str
    description: str
    icon: str
    level: str
    weeks: int
    sessions_per_week: str
    highlights: list[str]
    featured: bool


class FaqOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    question: str
    answer: str


class TestimonialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    role: str
    quote: str
    rating: int
    is_sample: bool


# --------------------------------------------------------------------- auth
class RegisterIn(Strict):
    name: Name
    email: Email
    password: Annotated[str, StringConstraints(min_length=1, max_length=200)]

    @field_validator("password")
    @classmethod
    def _strength(cls, value: str, info: ValidationInfo) -> str:
        problem = validate_password_strength(value, email=info.data.get("email", "") or "")
        if problem:
            raise ValueError(problem)
        return value


class LoginIn(Strict):
    email: text(1, 254)
    password: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class ProfileIn(Strict):
    name: Name


class PasswordChangeIn(Strict):
    current_password: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    new_password: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class ForgotIn(Strict):
    email: Email


class ResetIn(Strict):
    token: text(10, 200)
    password: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class DeleteAccountIn(Strict):
    password: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    name: str
    role: str
    created_at: datetime


# ---------------------------------------------------------------- lead forms
Interest = Literal["athlete", "coach", "gym", "other"]


class WaitlistIn(Strict):
    email: Email
    name: text(0, 80) = ""
    interest: Interest = "athlete"
    goal: OptionalText = ""
    ref: text(0, 16) = ""
    source: text(0, 48) = ""
    utm_source: text(0, 64) = ""
    utm_medium: text(0, 64) = ""
    utm_campaign: text(0, 64) = ""
    website: text(0, 200) = ""  # honeypot: real visitors never see or fill this


class ContactIn(Strict):
    name: Name
    email: Email
    company: text(0, 120) = ""
    topic: Literal["gym-or-team", "coach", "press", "support", "other"] = "other"
    message: text(10, 3000)
    website: text(0, 200) = ""  # honeypot


# --------------------------------------------------------------- assessment
PainArea = Literal["lower_back", "knee", "shoulder", "hip", "neck", "ankle", "elbow_wrist"]


class AssessmentIn(Strict):
    goal: Literal["strength", "fitness", "performance", "recovery"]
    experience: Literal["beginner", "intermediate", "advanced"]
    days_per_week: int = Field(ge=1, le=7)
    pain_areas: list[PainArea] = Field(default_factory=list, max_length=7)
    recent_injury: bool = False
    sleep: Literal["under_5", "5_6", "6_7", "7_8", "8_plus"]
    red_flags: bool = False

    save: bool = False
    email: Email | None = None
    name: text(0, 80) = ""
    consent: bool = False
    join_waitlist: bool = False

    @field_validator("pain_areas")
    @classmethod
    def _dedupe(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


# ---------------------------------------------------------------- assistant
class ChatMessage(Strict):
    role: Literal["user", "assistant"]
    content: text(1, 1000)


class AssistantIn(Strict):
    messages: list[ChatMessage] = Field(min_length=1, max_length=12)

    @field_validator("messages")
    @classmethod
    def _last_is_user(cls, value: list[ChatMessage]) -> list[ChatMessage]:
        if value[-1].role != "user":
            raise ValueError("The last message must come from the user")
        return value


# ------------------------------------------------------------------ billing
class CheckoutIn(Strict):
    plan_slug: text(1, 32)
    interval: Literal["month", "year"] = "month"


class UpiSubmitIn(Strict):
    reference: text(6, 40)


class MockCompleteIn(Strict):
    outcome: Literal["success", "cancel"]


# ------------------------------------------------------------------- events
class EventIn(Strict):
    name: Literal[
        "page_view",
        "cta_click",
        "assessment_started",
        "assessment_completed",
        "plan_selected",
        "assistant_used",
        "coach_started",
        "coach_finished",
        "diet_plan",
    ]
    path: text(0, 120) = "/"
    referrer: text(0, 300) = ""
    utm_source: text(0, 64) = ""


# -------------------------------------------------------------------- admin
class TestimonialIn(Strict):
    name: Name
    role: text(0, 80) = ""
    quote: text(10, 600)
    rating: int = Field(default=5, ge=1, le=5)
    published: bool = True
    sort_order: int = Field(default=0, ge=0, le=9999)


class FaqIn(Strict):
    question: text(5, 240)
    answer: text(5, 3000)
    published: bool = True
    sort_order: int = Field(default=0, ge=0, le=9999)


class ContactUpdateIn(Strict):
    status: Literal["new", "handled"]


# --------------------------------------------------------------------- diet
class DietIn(Strict):
    sex: Literal["male", "female"]
    age: int = Field(ge=18, le=75)
    height_cm: float = Field(ge=120, le=230)
    weight_kg: float = Field(ge=35, le=250)
    activity: Literal["sedentary", "light", "moderate", "very_active"] = "moderate"
    goal: Literal["bulk", "cut", "recomp", "maintain"]
    pace: Literal["gentle", "standard", "fast"] = "standard"
    preference: Literal["veg", "egg", "nonveg"] = "veg"
    meals: int = Field(default=5, ge=3, le=6)
    variants: dict[str, int] = Field(default_factory=dict)

    @field_validator("variants")
    @classmethod
    def _variants_ok(cls, value: dict[str, int]) -> dict[str, int]:
        allowed = {"breakfast", "midmorning", "lunch", "evening", "dinner", "bedtime"}
        return {k: max(0, min(int(v), 9)) for k, v in value.items() if k in allowed}


class DietEmailIn(DietIn):
    email: Email
    name: text(0, 80) = ""
    join_waitlist: bool = False


class SessionIn(Strict):
    exercise: Literal["squat", "deadlift", "pushup"]
    reps: int = Field(ge=0, le=300)
    avg_score: int = Field(ge=0, le=100)
    best_score: int = Field(ge=0, le=100)
    duration_s: int = Field(ge=1, le=7200)
    faults: dict[str, int] = Field(default_factory=dict)

    @field_validator("faults")
    @classmethod
    def _faults_ok(cls, value: dict[str, int]) -> dict[str, int]:
        return {str(k)[:32]: max(0, min(int(v), 300)) for k, v in list(value.items())[:12]}
