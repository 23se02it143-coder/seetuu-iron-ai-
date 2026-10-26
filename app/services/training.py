"""Weekly session plans for each program. `coach` links an exercise to the camera form coach."""
from __future__ import annotations


def ex(name: str, sets: str, cue: str, coach: str | None = None) -> dict:
    return {"name": name, "sets": sets, "cue": cue, "coach": coach}


SCHEDULES: dict[str, dict] = {
    "strength-foundations": {
        "summary": "Three full-body sessions a week. Add a little weight only when every rep looks like your first.",
        "days": [
            {"day": "Day 1", "title": "Full body A", "focus": "Squat pattern and pressing", "exercises": [
                ex("Goblet or back squat", "3 x 8", "Brace, knees track over toes, full foot on the floor.", "squat"),
                ex("Push-up (incline if needed)", "3 x 8-12", "One straight line from head to heels.", "pushup"),
                ex("One-arm dumbbell row", "3 x 10 each", "Pull the elbow to your hip, keep your back flat."),
                ex("Glute bridge", "3 x 12", "Ribs down, squeeze at the top."),
                ex("Plank", "3 x 30 s", "Squeeze glutes, do not let the hips sag."),
            ]},
            {"day": "Day 2", "title": "Full body B", "focus": "Hinge pattern and pulling", "exercises": [
                ex("Romanian deadlift", "3 x 8", "Push hips back, bar close to legs, flat back.", "deadlift"),
                ex("Dumbbell shoulder press", "3 x 8", "Ribs down, press in a straight line."),
                ex("Lat pulldown or assisted pull-up", "3 x 10", "Chest up, pull elbows toward your ribs.", "pullup"),
                ex("Split squat", "3 x 8 each", "Front knee tracks over the middle toes."),
                ex("Farmer's carry", "3 x 30 m", "Tall posture, do not lean."),
            ]},
            {"day": "Day 3", "title": "Full body A, heavier", "focus": "Repeat Day 1 with slightly more load", "exercises": [
                ex("Goblet or back squat", "3 x 8", "Add 2.5 kg if all reps were clean last time.", "squat"),
                ex("Push-up", "3 x 10-12", "Slow 2 second lowering.", "pushup"),
                ex("One-arm dumbbell row", "3 x 10 each", "Pause for a second at the top."),
                ex("Glute bridge", "3 x 12", "Hold the top for two seconds."),
                ex("Side plank", "3 x 20 s each", "Hips high, straight line."),
            ]},
        ],
    },
    "ai-training": {
        "summary": "Four sessions a week (upper and lower). Heavier main lifts, with the form coach checking the big three.",
        "days": [
            {"day": "Day 1", "title": "Lower", "focus": "Squat strength", "exercises": [
                ex("Back squat", "4 x 5", "Depth to at least parallel, bar over mid-foot.", "squat"),
                ex("Romanian deadlift", "3 x 8", "Feel the hamstrings load, back flat.", "deadlift"),
                ex("Walking lunge", "3 x 10 each", "Long steps, stay tall."),
                ex("Standing calf raise", "3 x 12", "Full range, pause at the top."),
                ex("Hanging knee raise", "3 x 10", "No swinging."),
            ]},
            {"day": "Day 2", "title": "Upper push", "focus": "Chest, shoulders, triceps", "exercises": [
                ex("Bench press", "4 x 6", "Shoulder blades back and down, forearms vertical."),
                ex("Overhead press", "3 x 8", "Glutes tight, ribs down."),
                ex("Push-up", "3 x to 2 reps from failure", "Body in a straight line.", "pushup"),
                ex("Triceps pushdown", "3 x 12", "Elbows pinned to your sides."),
                ex("Lateral raise", "3 x 15", "Lead with the elbows, no shrugging."),
            ]},
            {"day": "Day 3", "title": "Lower and pull", "focus": "Deadlift strength", "exercises": [
                ex("Conventional deadlift", "3 x 5", "Bar over mid-foot, lats tight, push the floor away.", "deadlift"),
                ex("Pull-up or pulldown", "4 x 6", "Full hang, chest to the bar.", "pullup"),
                ex("Barbell row", "3 x 8", "Flat back, pull to the lower ribs."),
                ex("Face pull", "3 x 15", "Squeeze the shoulder blades."),
                ex("Biceps curl", "3 x 12", "Control the lowering."),
            ]},
            {"day": "Day 4", "title": "Legs and conditioning", "focus": "Volume and work capacity", "exercises": [
                ex("Front or goblet squat", "3 x 8", "Upright torso, elbows high.", "squat"),
                ex("Hip thrust", "3 x 10", "Chin tucked, full lockout."),
                ex("Leg curl", "3 x 12", "Slow lowering."),
                ex("Zone 2 cardio", "25 min", "Easy pace, you can talk in full sentences."),
            ]},
        ],
    },
    "smart-recovery": {
        "summary": "Three lighter sessions built around how you feel. Move well, keep the fatigue low, stay consistent.",
        "days": [
            {"day": "Day 1", "title": "Mobility and tempo legs", "focus": "Quality reps, low fatigue", "exercises": [
                ex("Hip and ankle mobility flow", "8 min", "Slow and controlled, no forcing."),
                ex("Tempo squat", "3 x 6", "Three seconds down, one second pause.", "squat"),
                ex("Glute bridge", "3 x 10", "Squeeze, hold for two seconds."),
                ex("Zone 2 walk or bike", "20 min", "Nose-breathing pace."),
            ]},
            {"day": "Day 2", "title": "Upper body tempo", "focus": "Control and posture", "exercises": [
                ex("Tempo push-up", "3 x 8", "Three seconds down, no sagging.", "pushup"),
                ex("Band pull-apart", "3 x 15", "Shoulders down, squeeze back."),
                ex("Half-kneeling press", "3 x 8 each", "Ribs stacked over hips."),
                ex("Dead bug", "3 x 8 each", "Low back stays flat."),
            ]},
            {"day": "Day 3", "title": "Hinge and breathe", "focus": "Posterior chain, calm nervous system", "exercises": [
                ex("Light Romanian deadlift", "3 x 8", "Feel your hamstrings, keep it light.", "deadlift"),
                ex("Bird-dog", "3 x 8 each", "Move slowly, level hips."),
                ex("Side plank", "3 x 20 s each", "Straight line from head to feet."),
                ex("Box breathing", "5 min", "Four seconds in, hold, out, hold."),
            ]},
        ],
    },
    "return-to-training": {
        "summary": "A staged ramp back after a layoff. Stop each set with two or three reps in reserve and add load gradually.",
        "days": [
            {"day": "Day 1", "title": "Reintroduction A", "focus": "Patterns, not load", "exercises": [
                ex("Bodyweight squat to box", "3 x 10", "Control the descent, sit back and up.", "squat"),
                ex("Incline push-up", "3 x 10", "Hands on a bench, straight body.", "pushup"),
                ex("Band row", "3 x 12", "Elbows close, shoulders down."),
                ex("Glute bridge", "3 x 12", "Do not arch the back."),
                ex("Dead bug", "3 x 8 each", "Slow and controlled."),
            ]},
            {"day": "Day 2", "title": "Reintroduction B", "focus": "Hinge and single-leg control", "exercises": [
                ex("Light Romanian deadlift", "3 x 10", "Light weight, perfect hinge.", "deadlift"),
                ex("Supported split squat", "2 x 8 each", "Hold a rail if you need balance."),
                ex("Dumbbell press", "3 x 10", "Light weights, full control."),
                ex("Bird-dog", "3 x 8 each", "Steady and slow."),
                ex("Easy walk", "20 min", "Finish feeling better than you started."),
            ]},
            {"day": "Day 3", "title": "Reintroduction A, progressed", "focus": "Repeat Day 1 with a little more", "exercises": [
                ex("Goblet squat", "3 x 8", "Add a light dumbbell if Day 1 felt easy.", "squat"),
                ex("Push-up (lower incline)", "3 x 8", "Lower the bench height a notch.", "pushup"),
                ex("Band row", "3 x 12", "Add a second of pause."),
                ex("Glute bridge, feet elevated", "3 x 10", "Hold the top."),
                ex("Plank", "3 x 25 s", "Stay tight."),
            ]},
        ],
    },
}
