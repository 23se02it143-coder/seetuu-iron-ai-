"""A reference library of exercises with correct-form cues, grouped by muscle group.

Static content (no per-user computation), same spirit as app/services/training.py. Where an exercise
is one the camera form coach can watch live, `coach` names the exercise id it opens (see
web/static/js/features/formcoach.js); everything else is guidance only.
"""
from __future__ import annotations


def ex(name: str, sets: str, cue: str, coach: str | None = None) -> dict:
    return {"name": name, "sets": sets, "cue": cue, "coach": coach}


LIBRARY: list[dict] = [
    {
        "group": "Shoulders",
        "blurb": "Train all three heads so the joint stays balanced, not just the front.",
        "exercises": [
            ex("Dumbbell front raise", "3 x 12-15", "Raise to eye height with a soft bend in the elbow. Don't use your hips to swing the weight up."),
            ex("Dumbbell lateral raise", "3 x 12-15", "Lead with the elbows, not the hands, and stop at shoulder height so your traps don't take over."),
            ex("Bent-over rear delt fly", "3 x 12-15", "Hinge at the hips with a flat back. Squeeze your shoulder blades together at the top of each rep."),
        ],
    },
    {
        "group": "Chest",
        "blurb": "Hit the chest from three angles, plus a bodyweight finisher the camera coach can watch.",
        "exercises": [
            ex("Incline dumbbell press", "3 x 8-12", "Set the bench to 30-45 degrees. Lower until your upper arm is level with your torso, no lower."),
            ex("Flat barbell bench press", "3 x 8-12", "Feet flat, shoulder blades pulled together and down, bar path travels straight to your lower chest."),
            ex("Decline dumbbell press", "3 x 8-12", "Control the descent. Don't let the dumbbells drift up toward your face as you press."),
            ex("Push-up", "3 x to near failure", "One straight line from head to heels. The camera coach above checks exactly this.", "pushup"),
        ],
    },
    {
        "group": "Back",
        "blurb": "Balance pulling with the hinge that builds it, both trackable by the camera coach.",
        "exercises": [
            ex("Pull-up", "3 x 8-12", "Full hang at the bottom, chin clears the bar at the top, no swinging.", "pullup"),
            ex("Barbell bent-over row", "3 x 8-12", "Flat back, hinge to about 45 degrees, pull the bar to your lower ribs without jerking your torso."),
            ex("Seated cable row", "3 x 10-15", "Sit tall and drive your elbows back past your ribs. Don't round your lower back at full stretch."),
            ex("Conventional deadlift", "3 x 5-8", "Bar over mid-foot, lats tight, push the floor away. The camera coach above checks the bar path.", "deadlift"),
        ],
    },
    {
        "group": "Biceps",
        "blurb": "Three angles on the same muscle: strict, neutral, and rotated.",
        "exercises": [
            ex("Barbell curl", "3 x 10-15", "Elbows pinned to your sides. No swinging your torso to finish the rep."),
            ex("Dumbbell curl", "3 x 10-15", "Rotate your palm up as you curl. Control the lowering instead of dropping the weight."),
            ex("Hammer curl", "3 x 10-15", "Keep a neutral grip throughout. Only the forearm moves, the elbow stays still."),
        ],
    },
    {
        "group": "Triceps",
        "blurb": "A pushdown, a stretch-focused extension, and a bodyweight finisher.",
        "exercises": [
            ex("Rope push-down", "3 x 10-15", "Elbows pinned at your sides. Split the rope apart at the bottom for a full squeeze."),
            ex("Overhead triceps extension", "3 x 10-15", "Keep your elbows close to your ears. Lower until you feel a stretch, not pain, behind the arm."),
            ex("Bench dip", "3 x 10-15", "Keep your hips close to the bench. Stop when your upper arm is level with the floor to protect your shoulders."),
        ],
    },
    {
        "group": "Legs",
        "blurb": "The big compound lift first, then targeted volume for the quads and calves.",
        "exercises": [
            ex("Barbell back squat", "3 x 8-12", "Same cues as the camera coach above: knees track over your toes, chest up, sit back and down.", "squat"),
            ex("Leg press", "3 x 10-15", "Feet shoulder-width on the platform. Don't let your lower back round off the pad at the bottom."),
            ex("Leg extension", "3 x 12-15", "Control the negative. Don't swing the weight up with momentum."),
            ex("Standing calf raise", "3 x 15-20", "Full stretch at the bottom, then pause and squeeze at the top."),
        ],
    },
    {
        "group": "Abs",
        "blurb": "A curl, a raise, and a hold: flexion, resistance and bracing all in one short block.",
        "exercises": [
            ex("Crunch", "3 x 15-20", "Lift your shoulder blades off the floor. Don't pull on your neck with your hands."),
            ex("Lying or hanging leg raise", "3 x 15-20", "Keep a slight bend in the knees and control the lowering. Don't let your lower back arch off the floor."),
            ex("Plank", "3 x 30-45 sec", "One straight line from head to heels, the same line the push-up coach checks above."),
        ],
    },
]
