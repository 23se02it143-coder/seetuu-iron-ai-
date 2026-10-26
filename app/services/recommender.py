"""Readiness assessment: a transparent, deterministic rules engine.

Nothing here is a medical assessment. It turns six self-reported answers into a
starting-point recommendation, and steers anyone reporting warning symptoms to a clinician.
"""
from __future__ import annotations

from typing import Any

from ..schemas import AssessmentIn

DISCLAIMER = (
    "This is general guidance based on your answers, not medical advice. "
    "If something hurts or worries you, speak to a qualified clinician."
)

_SLEEP_PENALTY = {"under_5": 25, "5_6": 15, "6_7": 7, "7_8": 0, "8_plus": 0}

_FOCUS = {
    "lower_back": ("Lower back", "Hip hinge pattern and bracing before every rep."),
    "knee": ("Knees", "Knee tracking and single-leg control."),
    "shoulder": ("Shoulders", "Scapular control and overhead mobility."),
    "hip": ("Hips", "Hip mobility and glute activation."),
    "neck": ("Neck", "Upper-back posture and neck-friendly set-ups."),
    "ankle": ("Ankles", "Ankle mobility and balance work."),
    "elbow_wrist": ("Elbows and wrists", "Grip, wrist position and gradual elbow loading."),
}

_PROGRAM_PLAN = {
    "strength-foundations": "starter",
    "ai-training": "pro",
    "smart-recovery": "pro",
    "return-to-training": "pro",
}


def _label(score: int) -> str:
    if score >= 80:
        return "High"
    if score >= 60:
        return "Moderate"
    return "Low"


def assess(data: AssessmentIn) -> dict[str, Any]:
    """Return the assessment result as a JSON-serialisable dict."""
    if data.red_flags:
        return {
            "status": "medical_review",
            "readiness": None,
            "program_slug": None,
            "plan_slug": None,
            "headline": "Check in with a clinician before you train",
            "summary": (
                "You reported symptoms that deserve an in-person assessment first, such as chest pain, "
                "dizziness, numbness or sudden severe pain. Please stop training and get checked; "
                "if symptoms are severe or sudden, contact emergency services."
            ),
            "insights": ["Once you have been cleared, retake this assessment for a starting program."],
            "focus": [],
            "disclaimer": DISCLAIMER,
        }

    score = 100
    insights: list[str] = []

    sleep_cost = _SLEEP_PENALTY[data.sleep]
    score -= sleep_cost
    if sleep_cost >= 15:
        insights.append("Short sleep is your biggest limiter: recovery quality drives strength gains and injury resilience.")
    elif sleep_cost > 0:
        insights.append("A little more sleep would lift your recovery; aim for seven hours or more.")
    else:
        insights.append("Your sleep supports solid recovery, which is a strong foundation.")

    pain_cost = min(len(data.pain_areas) * 8, 24)
    score -= pain_cost
    if data.pain_areas:
        insights.append("Ongoing discomfort in " + _join([_FOCUS[a][0].lower() for a in data.pain_areas]) + " calls for cautious loading and technique work.")

    if data.recent_injury:
        score -= 15
        insights.append("A recent injury means load should ramp back up gradually rather than jumping to your old numbers.")

    if data.days_per_week >= 6:
        score -= 10
        insights.append("Training six or more days a week leaves little room to recover; plan at least one true rest day.")
    elif data.days_per_week == 5:
        score -= 4
    if data.experience == "beginner" and data.days_per_week >= 5:
        score -= 8
        insights.append("As a beginner, three to four sessions a week will build skill faster than five or more.")

    score = max(20, min(100, score))

    program = _choose_program(data, score)
    plan = _PROGRAM_PLAN[program]
    if data.experience == "advanced" and data.goal == "performance" and program == "ai-training":
        plan = "elite"

    focus = [{"area": a, "label": _FOCUS[a][0], "tip": _FOCUS[a][1]} for a in data.pain_areas]
    label = _label(score)
    return {
        "status": "ok",
        "readiness": {"score": score, "label": label},
        "program_slug": program,
        "plan_slug": plan,
        "headline": f"Your readiness is {label.lower()}: {score} out of 100",
        "summary": _summary(program),
        "insights": insights[:4],
        "focus": focus,
        "disclaimer": DISCLAIMER,
    }


def _choose_program(data: AssessmentIn, score: int) -> str:
    if data.recent_injury or len(data.pain_areas) >= 2 or (data.pain_areas and score < 75):
        return "return-to-training"
    if data.sleep in ("under_5", "5_6") or data.days_per_week >= 6 or data.goal == "recovery":
        return "smart-recovery"
    if data.experience == "beginner":
        return "strength-foundations"
    return "ai-training"


def _summary(program: str) -> str:
    return {
        "return-to-training": "A cautious, staged ramp back into training that respects what your body is telling you.",
        "smart-recovery": "Recovery-first programming that adapts to your fatigue so you can keep progressing.",
        "strength-foundations": "Master the core movement patterns first; strength follows quickly from good technique.",
        "ai-training": "Adaptive loading with real-time form feedback to push past plateaus safely.",
    }[program]


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]
