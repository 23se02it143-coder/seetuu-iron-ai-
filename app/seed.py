"""Reference data and first-run bootstrap.

Seeding is additive and idempotent: plans and programs are inserted only when their slug is
missing (so edits you make in the database stay), FAQs and sample testimonials only into empty tables.
All copy and prices below are placeholders - edit them here, or change rows in the database / admin panel.
"""
from __future__ import annotations

import logging
import secrets

from pydantic import TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import Settings
from .models import Faq, Plan, Program, Testimonial, User
from .schemas import Email
from .security import hash_password, validate_password_strength

log = logging.getLogger("iron.seed")

PLANS = [
    dict(
        slug="starter", name="Starter", tagline="Learn the fundamentals of safe training.",
        price_monthly_cents=0, price_annual_cents=0, highlight=False, badge="", cta_label="Start free", sort_order=1,
        features=[
            "60-second readiness assessment",
            "AI chat assistant with a daily allowance",
            "Camera form coach: squat, 3-minute sessions",
            "Diet planner for bulk, cut and maintain",
            "Strength Foundations program",
        ],
    ),
    dict(
        slug="pro", name="Pro", tagline="Adaptive training with a camera form coach on every lift.",
        price_monthly_cents=49900, price_annual_cents=499000, highlight=True, badge="Most popular", cta_label="Choose Pro", sort_order=2,
        features=[
            "Everything in Starter",
            "Camera form coach: squat, deadlift, push-up and pull-up, unlimited",
            "Voice coaching cues while you train",
            "Session history and progress tracking",
            "Full weekly schedules for every program",
            "Unlimited AI assistant, 24/7",
            "AI Training, Smart Recovery and Return to Training",
        ],
    ),
    dict(
        slug="elite", name="Elite", tagline="For serious athletes, coaches and small teams.",
        price_monthly_cents=129900, price_annual_cents=1299000, highlight=False, badge="", cta_label="Choose Elite", sort_order=3,
        features=[
            "Everything in Pro",
            "Priority support",
            "Early access to new exercises and modules",
            "Advanced strain and readiness analytics (roadmap)",
            "Team and coach workspace (roadmap)",
        ],
    ),
]

# Prices before the move to rupees. A plan still sitting on these was never edited, so it is safe to refresh.
LEGACY_PRICES = {"pro": (1900, 19000), "elite": (4900, 49000)}

PROGRAMS = [
    dict(
        slug="ai-training", code="Core-01", name="AI Training", icon="cpu", featured=True, sort_order=1,
        tagline="Dynamic load adjustment and kinetic path correction.",
        description="Every session adapts to how you recovered. Loads move up or down based on your recent training and readiness, and technique cues target the movement paths that limit your lifts.",
        level="Intermediate and up", weeks=12, sessions_per_week="3 to 5",
        highlights=[
            "Load adjusts session to session from your recovery inputs",
            "Kinetic path cues on every compound lift",
            "Weekly progress review with plateau flags",
            "Deload weeks scheduled for you",
        ],
    ),
    dict(
        slug="smart-recovery", code="Rec-02", name="Smart Recovery", icon="battery-charging-vertical", featured=True, sort_order=2,
        tagline="Bio-integrated protocols tailored to fatigue levels.",
        description="Recovery-first programming for busy, under-slept or overreaching athletes. Sessions scale with your fatigue so you keep progressing without digging a hole.",
        level="All levels", weeks=8, sessions_per_week="3",
        highlights=[
            "Fatigue-aware session volume",
            "Guided mobility and breathing protocols",
            "Sleep and stress check-ins",
            "Clear rest-day rules",
        ],
    ),
    dict(
        slug="strength-foundations", code="Fnd-03", name="Strength Foundations", icon="barbell", featured=False, sort_order=3,
        tagline="Squat, hinge, push, pull and carry, done properly.",
        description="A beginner-friendly block that teaches the five core movement patterns with clear cues, simple progressions and built-in technique checkpoints.",
        level="Beginner", weeks=8, sessions_per_week="3",
        highlights=[
            "Five movement patterns, one at a time",
            "Simple linear progression",
            "Technique checkpoints every two weeks",
        ],
    ),
    dict(
        slug="return-to-training", code="Rtn-04", name="Return to Training", icon="heartbeat", featured=False, sort_order=4,
        tagline="A staged ramp back after a layoff or niggle.",
        description="A cautious, staged return that rebuilds capacity around the area you are protecting. It supports, and never replaces, guidance from your physiotherapist or doctor.",
        level="Returning athletes", weeks=6, sessions_per_week="2 to 4",
        highlights=[
            "Staged load ramp with clear go and stop rules",
            "Focus work for your sensitive areas",
            "Designed to sit alongside clinician advice",
        ],
    ),
]

FAQS = [
    ("What is IRON-AI?", "IRON-AI is a training platform with a 60-second readiness assessment, a live camera form coach for squat, deadlift, push-up and pull-up, a diet planner for bulking, cutting and maintenance, training programs and recovery guidance."),
    ("Is IRON-AI medical advice?", "No. IRON-AI provides general training and nutrition guidance and is not a medical service. It cannot diagnose or treat injuries. If something hurts, feels wrong or worries you, stop and speak to a doctor or physiotherapist."),
    ("What do I need to get started?", "A laptop or phone with a camera and a recent browser such as Chrome. Prop the camera 2 to 3 metres away at hip height and stand side-on. Wearables are optional; data import from popular devices is on the roadmap."),
    ("Does my camera video get uploaded?", "No. The pose tracking runs inside your browser on your own device. Nothing is recorded or sent to us. If you are signed in and finish a session, we save only the rep count, form scores and the faults it noticed."),
    ("Which exercises does the form coach support?", "Squat, deadlift, push-up and pull-up, filmed from the side. Squat is free with 3-minute sessions. Pro adds the other three lifts, unlimited time, voice cues and saved history."),
    ("Can the diet planner replace a dietitian?", "No. It gives calorie and macro estimates and a sample day of Indian meals for healthy adults. If you have a medical condition, are pregnant, take medication or have a history of disordered eating, speak to a doctor or registered dietitian first."),
    ("How does the waitlist work?", "Join with your email and you'll get a queue position and a personal referral link. Every friend who joins with your link moves you 10 places closer to the front. We email you when your spot opens."),
    ("Can I cancel my subscription any time?", "Yes. Cancel from your account in one click and you keep access until the end of the period you paid for."),
    ("How is my data handled?", "We collect only what we need to run your account. Assessment answers are stored only if you choose to save them, you can download all your data at any time, and deleting your account removes it."),
    ("Do you offer team or gym plans?", "We are building them. Use the contact form and pick 'Gym or team' so we can talk through what you need."),
    ("What if the AI assistant isn't sure?", "It says so. For anything involving sharp, sudden or worsening pain, numbness, dizziness or chest symptoms it tells you to stop training and seek professional care instead of guessing."),
]

# Text that shipped before the camera coach existed. A row still holding it was never edited, so it can be refreshed.
OLD_FAQ_ANSWERS = {
    "What is IRON-AI?": "IRON-AI is a training-safety platform. It assesses your baseline mobility, checks your form in real time, gives instant cues to correct alignment, and adapts recovery to your fatigue.",
    "What do I need to get started?": "A smartphone or laptop camera for form checks. Wearables are optional; data import from popular devices is on the roadmap.",
    "Is IRON-AI medical advice?": "No. IRON-AI provides general training guidance and is not a medical service. It cannot diagnose or treat injuries. If something hurts, feels wrong or worries you, stop and speak to a doctor or physiotherapist.",
}

SAMPLE_TESTIMONIALS = [
    ("Marcus Thorne", "Powerlifter", "IRON-AI caught a rotator cuff imbalance before I even felt the pain. Form check saved my season."),
    ("Elena Vance", "Marathon runner", "Recovery protocol adjustments are insane. It knows when I'm overtraining before I even feel fatigued."),
    ("Julian Reed", "Strength coach", "Peak performance without the crash. The AI assistant is actually like having a private Olympian coach."),
    ("Priya Nair", "CrossFit athlete", "The hinge cues fixed my deadlift in two weeks. My lower back finally stopped complaining."),
    ("Diego Marín", "Returning lifter", "Coming back from a layoff, the staged ramp kept me honest. No more ego lifting on day one."),
]


def seed_reference_data(db: Session, settings: Settings) -> None:
    existing = {p.slug: p for p in db.scalars(select(Plan))}
    for row in PLANS:
        plan = existing.get(row["slug"])
        if plan is None:
            db.add(Plan(**row))
        elif (plan.price_monthly_cents, plan.price_annual_cents) == LEGACY_PRICES.get(row["slug"]):
            for key, value in row.items():
                setattr(plan, key, value)
    existing_programs = set(db.scalars(select(Program.slug)))
    for row in PROGRAMS:
        if row["slug"] not in existing_programs:
            db.add(Program(**row))
    if not db.scalar(select(func.count()).select_from(Faq)):
        for i, (q, a) in enumerate(FAQS, start=1):
            db.add(Faq(question=q, answer=a, sort_order=i))
    else:
        rows = {f.question: f for f in db.scalars(select(Faq))}
        latest = dict(FAQS)
        for question, old in OLD_FAQ_ANSWERS.items():
            row = rows.get(question)
            if row is not None and row.answer == old:
                row.answer = latest[question]
        top = max((f.sort_order for f in rows.values()), default=0)
        for question in ("Does my camera video get uploaded?", "Which exercises does the form coach support?", "Can the diet planner replace a dietitian?"):
            if question not in rows:
                top += 1
                db.add(Faq(question=question, answer=latest[question], sort_order=top))
    if settings.seed_sample_content and not db.scalar(select(func.count()).select_from(Testimonial)):
        for i, (name, role, quote) in enumerate(SAMPLE_TESTIMONIALS, start=1):
            db.add(Testimonial(name=name, role=role, quote=quote, is_sample=True, sort_order=i))
    db.commit()


def ensure_admin(db: Session, settings: Settings) -> None:
    """Create the first admin from ADMIN_EMAIL / ADMIN_PASSWORD. Never overwrites an existing account."""
    if db.scalar(select(func.count()).select_from(User).where(User.role == "admin")):
        return
    email, password = settings.admin_email.strip().lower(), settings.admin_password
    generated = False
    if not email or not password:
        if settings.is_production:
            log.warning("No admin user exists. Set ADMIN_EMAIL and ADMIN_PASSWORD, then restart, to create one.")
            return
        email, password, generated = "admin@example.com", secrets.token_urlsafe(12), True
    try:
        TypeAdapter(Email).validate_python(email)
    except ValueError:
        log.error("ADMIN_EMAIL %r is not a valid email address; admin not created.", email)
        return
    problem = None if generated else validate_password_strength(password, email=email)
    if problem and settings.is_production:
        log.error("ADMIN_PASSWORD rejected: %s. Admin not created.", problem)
        return
    existing = db.scalars(select(User).where(User.email == email)).first()
    if existing:
        existing.role = "admin"
    else:
        db.add(User(email=email, name="Admin", password_hash=hash_password(password, settings.bcrypt_rounds), role="admin"))
    db.commit()
    if generated:
        banner = "=" * 62
        print(f"\n{banner}\n  Development admin created\n  Email:    {email}\n  Password: {password}\n  (shown once; set ADMIN_EMAIL / ADMIN_PASSWORD to choose your own)\n{banner}\n", flush=True)
    else:
        log.info("Admin user ready: %s", email)
