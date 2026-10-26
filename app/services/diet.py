"""Diet planner: calorie and macro targets plus a day of Indian meals, tuned to the goal.

Deterministic and rules-based (no ML, no network). Numbers are estimates: standard Mifflin-St Jeor energy needs,
protein and fat set per kg of body weight, carbohydrate as the remainder, and food values rounded from typical
Indian home-cooking servings. It is general guidance for healthy adults, not medical or dietetic advice.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..errors import ApiError

DISCLAIMER = (
    "These are estimates for healthy adults, not medical or dietetic advice. Food values vary with recipe and portion. "
    "If you have a medical condition, are pregnant, take medication, or have a history of disordered eating, "
    "speak to a doctor or registered dietitian before changing your diet."
)

ACTIVITY = {"sedentary": 1.2, "light": 1.375, "moderate": 1.55, "very_active": 1.725}
BULK_PCT = {"gentle": 0.07, "standard": 0.12, "fast": 0.18}
CUT_PCT = {"gentle": 0.10, "standard": 0.16, "fast": 0.22}
KCAL_PER_KG = 7700  # energy in a kilogram of body-weight change (rough)

# name, serving description, kcal, protein, carbs, fat, step (smallest sensible portion change)
FOODS: dict[str, tuple[str, str, float, float, float, float, float]] = {
    "roti": ("Roti / chapati", "medium roti (40 g)", 120, 3.5, 22, 2, 1),
    "rice": ("Cooked rice", "cup (150 g)", 200, 4, 44, 0.5, 0.5),
    "dal": ("Dal", "katori (150 g cooked)", 150, 9, 20, 3, 0.5),
    "rajma": ("Rajma", "katori (150 g cooked)", 190, 13, 34, 0.8, 0.5),
    "chana": ("Boiled chana", "katori (100 g)", 165, 9, 27, 2.6, 0.5),
    "sprouts": ("Moong sprouts", "bowl (100 g cooked)", 100, 7, 17, 0.6, 0.5),
    "soya": ("Soya chunks", "serving (30 g dry)", 104, 15.6, 10, 0.2, 0.5),
    "paneer": ("Paneer", "serving (100 g)", 265, 18, 3, 20, 0.5),
    "egg": ("Whole egg", "egg", 70, 6, 0.5, 5, 1),
    "eggwhite": ("Egg whites", "3 whites", 51, 11, 0.7, 0.2, 1),
    "chicken": ("Chicken breast (cooked)", "serving (100 g)", 165, 31, 0, 3.6, 0.5),
    "fish": ("Fish (rohu / similar, cooked)", "serving (100 g)", 130, 20, 0, 5, 0.5),
    "curd": ("Curd (dahi)", "katori (150 g)", 98, 5, 7, 5, 0.5),
    "milk": ("Toned milk", "glass (250 ml)", 155, 8, 12, 7.5, 0.5),
    "oats": ("Oats", "serving (40 g dry)", 150, 5, 26, 3, 0.5),
    "poha": ("Poha with veg", "plate", 230, 5, 42, 4, 0.5),
    "chilla": ("Besan chilla", "2 chillas", 220, 12, 25, 7, 0.5),
    "banana": ("Banana", "medium banana", 105, 1.3, 27, 0.4, 1),
    "fruit": ("Seasonal fruit", "bowl (150 g)", 80, 1, 20, 0.3, 0.5),
    "peanuts": ("Roasted peanuts", "handful (30 g)", 170, 8, 5, 14, 0.5),
    "pbutter": ("Peanut butter", "tbsp (16 g)", 95, 4, 3, 8, 1),
    "almonds": ("Almonds", "10 almonds (12 g)", 70, 2.5, 2.6, 6, 1),
    "makhana": ("Roasted makhana", "bowl (30 g)", 105, 3, 22, 0.1, 0.5),
    "sabzi": ("Mixed vegetable sabzi", "katori (150 g)", 90, 3, 10, 4, 0.5),
    "salad": ("Salad (cucumber, tomato, onion)", "bowl", 40, 2, 8, 0.3, 1),
    "potato": ("Boiled potato / sweet potato", "medium potato (150 g)", 130, 2.5, 30, 0.2, 0.5),
    "whey": ("Whey protein (optional)", "scoop (30 g)", 120, 24, 3, 2, 1),
    "ghee": ("Ghee", "tsp (5 g)", 45, 0, 0, 5, 1),
}

SLOT_ORDER = ["breakfast", "midmorning", "lunch", "evening", "dinner", "bedtime"]
SLOT_LABEL = {
    "breakfast": "Breakfast", "midmorning": "Mid-morning", "lunch": "Lunch",
    "evening": "Evening / pre-workout", "dinner": "Dinner", "bedtime": "Before bed",
}
SLOT_TIME = {"breakfast": "8:00", "midmorning": "11:00", "lunch": "13:30", "evening": "17:00", "dinner": "20:30", "bedtime": "22:30"}
SLOT_SHARE = {"breakfast": 0.24, "midmorning": 0.10, "lunch": 0.28, "evening": 0.13, "dinner": 0.20, "bedtime": 0.05}
SLOTS_BY_MEALS = {
    3: ["breakfast", "lunch", "dinner"],
    4: ["breakfast", "lunch", "evening", "dinner"],
    5: ["breakfast", "midmorning", "lunch", "evening", "dinner"],
    6: SLOT_ORDER,
}

# variants[preference][slot] = list of [(food, servings)]
_VEG_B = [
    [("oats", 1), ("milk", 1), ("banana", 1), ("almonds", 1)],
    [("chilla", 1), ("curd", 1), ("fruit", 1)],
    [("poha", 1), ("sprouts", 1), ("milk", 1)],
]
_EGG_B = [
    [("egg", 3), ("roti", 2), ("fruit", 1)],
    [("oats", 1), ("egg", 2), ("banana", 1)],
    [("egg", 2), ("eggwhite", 1), ("roti", 2), ("curd", 1)],
]
_VEG_M = [[("curd", 1), ("fruit", 1), ("almonds", 1)], [("sprouts", 1), ("banana", 1)], [("milk", 1), ("peanuts", 1)]]
_EGG_M = [[("egg", 2), ("fruit", 1)], [("curd", 1), ("almonds", 2)], [("sprouts", 1), ("egg", 1)]]
_VEG_L = [
    [("roti", 3), ("dal", 1), ("paneer", 1), ("sabzi", 1), ("salad", 1)],
    [("rice", 1.5), ("rajma", 1), ("curd", 1), ("salad", 1)],
    [("roti", 3), ("chana", 1), ("soya", 1), ("sabzi", 1), ("salad", 1)],
]
_EGG_L = [
    [("rice", 1.5), ("dal", 1), ("egg", 2), ("sabzi", 1), ("salad", 1)],
    [("roti", 3), ("dal", 1), ("paneer", 1), ("sabzi", 1)],
    [("rice", 1.5), ("rajma", 1), ("egg", 2), ("salad", 1)],
]
_NV_L = [
    [("rice", 1.5), ("chicken", 1.5), ("dal", 1), ("salad", 1)],
    [("roti", 3), ("fish", 1.5), ("sabzi", 1), ("salad", 1)],
    [("roti", 3), ("chicken", 1.5), ("dal", 1), ("sabzi", 1)],
]
_VEG_E = [
    [("makhana", 1), ("milk", 1)],
    [("banana", 1), ("pbutter", 2), ("milk", 1)],
    [("sprouts", 1), ("chana", 1), ("fruit", 1)],
]
_EGG_E = [[("egg", 2), ("banana", 1), ("almonds", 1)], [("egg", 2), ("roti", 1), ("curd", 1)], [("makhana", 1), ("milk", 1)]]
_VEG_D = [
    [("roti", 2), ("paneer", 1.5), ("sabzi", 1), ("dal", 1)],
    [("rice", 1), ("dal", 1), ("soya", 1), ("sabzi", 1), ("curd", 1)],
    [("roti", 2), ("rajma", 1), ("sabzi", 1), ("curd", 1)],
]
_EGG_D = [
    [("egg", 3), ("roti", 2), ("sabzi", 1), ("dal", 1)],
    [("rice", 1), ("dal", 1), ("egg", 2), ("sabzi", 1)],
    [("roti", 2), ("paneer", 1), ("egg", 2), ("sabzi", 1)],
]
_NV_D = [
    [("roti", 2), ("chicken", 1.5), ("sabzi", 1), ("salad", 1)],
    [("rice", 1), ("fish", 1.5), ("dal", 1), ("sabzi", 1)],
    [("roti", 2), ("chicken", 1.5), ("dal", 1)],
]
_BED = [[("milk", 1), ("almonds", 1)], [("curd", 1), ("makhana", 0.5)], [("milk", 1), ("banana", 1)]]

VARIANTS: dict[str, dict[str, list[list[tuple[str, float]]]]] = {
    "veg": {"breakfast": _VEG_B, "midmorning": _VEG_M, "lunch": _VEG_L, "evening": _VEG_E, "dinner": _VEG_D, "bedtime": _BED},
    "egg": {"breakfast": _EGG_B, "midmorning": _EGG_M, "lunch": _EGG_L, "evening": _EGG_E, "dinner": _EGG_D, "bedtime": _BED},
    "nonveg": {"breakfast": _EGG_B, "midmorning": _EGG_M, "lunch": _NV_L, "evening": _EGG_E, "dinner": _NV_D, "bedtime": _BED},
}


@dataclass
class Profile:
    sex: str
    age: int
    height_cm: float
    weight_kg: float
    activity: str
    goal: str  # bulk | cut | recomp | maintain
    pace: str = "standard"
    preference: str = "veg"
    meals: int = 5


def bmr(p: Profile) -> float:
    base = 10 * p.weight_kg + 6.25 * p.height_cm - 5 * p.age
    return base + (5 if p.sex == "male" else -161)


def targets(p: Profile) -> dict:
    bmi = p.weight_kg / ((p.height_cm / 100) ** 2)
    if p.goal == "cut" and bmi < 18.5:
        raise ApiError(
            422, "unsafe_goal",
            "At your height and weight, cutting isn't recommended. Choose maintain or bulk, and speak to a doctor or dietitian if you'd like to change your weight.",
            fields={"goal": "Not recommended at this body weight"},
        )
    base = bmr(p)
    tdee = base * ACTIVITY[p.activity]
    notes: list[str] = []

    if p.goal == "bulk":
        delta = tdee * BULK_PCT[p.pace]
    elif p.goal == "cut":
        delta = -tdee * CUT_PCT[p.pace]
        max_loss = 0.0075 * p.weight_kg * KCAL_PER_KG / 7  # keep loss under 0.75% of body weight per week
        if -delta > max_loss:
            delta = -max_loss
            notes.append("Your deficit was capped so weight loss stays under about 0.75% of body weight per week.")
    elif p.goal == "recomp":
        delta = -tdee * 0.05
    else:
        delta = 0.0

    floor = max(1500 if p.sex == "male" else 1200, base)
    calories = tdee + delta
    if calories < floor:
        calories = floor
        delta = calories - tdee
        notes.append("Calories were raised to a safe minimum for your body.")
    calories = round(calories / 10) * 10

    protein_per_kg = {"bulk": 1.8, "cut": 2.1, "recomp": 2.0, "maintain": 1.6}[p.goal]
    protein = min(protein_per_kg * p.weight_kg, 0.35 * calories / 4)
    fat_per_kg = {"bulk": 1.0, "cut": 0.8, "recomp": 0.9, "maintain": 0.9}[p.goal]
    fat = max(fat_per_kg * p.weight_kg, 0.2 * calories / 9)
    carbs = max(0.0, (calories - protein * 4 - fat * 9) / 4)

    weekly = (calories - tdee) * 7 / KCAL_PER_KG
    return {
        "bmr": round(base), "tdee": round(tdee), "calories": int(calories),
        "protein_g": round(protein), "carbs_g": round(carbs), "fat_g": round(fat),
        "water_l": round(p.weight_kg * 0.035, 1),
        "daily_change_kcal": round(calories - tdee),
        "weekly_change_kg": round(weekly, 2),
        "bmi": round(bmi, 1),
        "notes": notes,
    }


# ------------------------------------------------------------------ meals
def _nutrients(items: list[dict]) -> dict:
    return {k: round(sum(i[k] for i in items), 1) for k in ("kcal", "p", "c", "f")}


_FRACTION = {0.0: "", 0.5: "\u00bd"}
# largest sensible amount of a food in one meal (keeps top-ups from producing 100 g of soya chunks in a sitting)
_CAP = {"soya": 2, "whey": 2, "paneer": 2.5, "chicken": 3, "fish": 2.5, "eggwhite": 3, "egg": 4}


def _qty_text(qty: float) -> str:
    whole, frac = int(qty), round(qty - int(qty), 2)
    mark = _FRACTION.get(frac, f"{frac:g}")
    return f"{whole or ''}{mark}" or "0"


_SPECIAL = {
    "egg": lambda q: f"{q:g} egg{'s' if q != 1 else ''}",
    "eggwhite": lambda q: f"{round(q * 3)} egg whites",
    "almonds": lambda q: f"{round(q * 10)} almonds",
    "chilla": lambda q: f"{round(q * 2)} chillas",
}
_GRAMS = re.compile(r"\((\d+(?:\.\d+)?) g( [a-z ]+)?\)$")


def serving_text(food: str, qty: float) -> str:
    """'1 medium roti (40 g)', '150 g' of paneer, '1\u00bd katori (225 g cooked)': quantities people can actually measure."""
    if food in _SPECIAL:
        return _SPECIAL[food](qty)
    unit = FOODS[food][1]
    m = _GRAMS.search(unit)
    if not m:
        return f"{_qty_text(qty)} {unit}"
    grams, suffix, label = qty * float(m.group(1)), m.group(2) or "", unit[: m.start()].strip()
    if label == "serving":
        return f"{grams:g} g{suffix}"
    return f"{_qty_text(qty)} {label} ({grams:g} g{suffix})"


def _item(food: str, qty: float) -> dict:
    name, unit, kcal, p, c, f, _step = FOODS[food]
    return {
        "food": food, "name": name, "qty": qty,
        "serving": serving_text(food, qty),
        "kcal": round(kcal * qty), "p": round(p * qty, 1), "c": round(c * qty, 1), "f": round(f * qty, 1),
    }


def _round_step(food: str, qty: float) -> float:
    step = FOODS[food][6]
    return max(step, round(qty / step) * step)


def _build_meal(slot: str, preference: str, variant: int, kcal_target: float) -> dict:
    options = VARIANTS[preference][slot]
    index = variant % len(options)
    base = options[index]
    base_kcal = sum(FOODS[f][2] * q for f, q in base)
    factor = kcal_target / base_kcal
    items = [_item(f, _round_step(f, q * factor)) for f, q in base]
    return {
        "slot": slot, "label": SLOT_LABEL[slot], "time": SLOT_TIME[slot],
        "variant": index, "variants_count": len(options), "items": items, **_nutrients(items),
    }


def _totals(meals: list[dict]) -> dict:
    return {k: round(sum(m[k] for m in meals)) for k in ("kcal", "p", "c", "f")}


def _bump(meal: dict, food: str, delta: float) -> bool:
    for item in meal["items"]:
        if item["food"] == food:
            new = item["qty"] + delta
            if new < FOODS[food][6] or (delta > 0 and new > _CAP.get(food, 99)):
                return False
            item.update(_item(food, new))
            meal.update(_nutrients(meal["items"]))
            return True
    return False


_UP = ("rice", "roti", "potato", "banana", "almonds", "peanuts")
_DOWN = ("rice", "roti", "potato", "banana", "peanuts", "pbutter", "almonds", "ghee", "makhana", "poha", "oats")


_DROP = ("ghee", "almonds", "peanuts", "pbutter", "makhana", "banana", "fruit", "potato", "poha", "oats")


def _close_gap(meals: list[dict], target: int, tolerance: float = 0.03) -> None:
    """Nudge staple foods (rice, roti, ...) in the biggest meals until calories are within tolerance of the target."""
    for _ in range(24):
        gap = target - _totals(meals)["kcal"]
        if abs(gap) <= target * tolerance:
            return
        sign = 1 if gap > 0 else -1
        changed = False
        for meal in sorted(meals, key=lambda m: -m["kcal"]):
            order = _UP if sign > 0 else _DOWN
            for food in order:
                if _bump(meal, food, sign * FOODS[food][6]):
                    changed = True
                    break
            if changed:
                break
        if not changed and sign < 0:
            # portions are already at their smallest: drop optional extras from the fullest meals
            for food in _DROP:
                for meal in sorted(meals, key=lambda m: -m["kcal"]):
                    item = next((i for i in meal["items"] if i["food"] == food), None)
                    if item is not None and len(meal["items"]) > 2:
                        meal["items"].remove(item)
                        meal.update(_nutrients(meal["items"]))
                        changed = True
                        break
                if changed:
                    break
        if not changed:
            return


def _protein_top_up(meals: list[dict], preference: str, target_protein: int) -> None:
    """Add lean protein (best protein per calorie first) until the day is close to the protein target."""
    boosters = {
        "nonveg": ("chicken", "eggwhite", "egg", "whey"),
        "egg": ("eggwhite", "egg", "soya", "whey"),
        "veg": ("soya", "whey", "paneer"),
    }[preference]
    homes = ("dinner", "lunch", "evening", "breakfast", "bedtime", "midmorning")
    for _ in range(12):
        if _totals(meals)["p"] >= target_protein * 0.97:
            return
        done = False
        for food in boosters:
            for slot in homes:
                meal = next((m for m in meals if m["slot"] == slot), None)
                if meal is None:
                    continue
                if any(i["food"] == food for i in meal["items"]):
                    done = _bump(meal, food, FOODS[food][6])
                elif slot in ("dinner", "lunch", "evening", "breakfast"):
                    meal["items"].append(_item(food, FOODS[food][6]))
                    meal.update(_nutrients(meal["items"]))
                    done = True
                if done:
                    break
            if done:
                break
        if not done:
            return


def build_plan(p: Profile, variants: dict[str, int] | None = None) -> dict:
    t = targets(p)
    variants = variants or {}
    n_meals = p.meals
    if t["calories"] < 1700 and n_meals > 4:
        n_meals = 4
        t["notes"].append("Your calorie target is small, so it is split across 4 meals instead of more, to keep portions sensible.")
    slots = SLOTS_BY_MEALS[n_meals]
    share_sum = sum(SLOT_SHARE[s] for s in slots)
    meals = [
        _build_meal(s, p.preference, int(variants.get(s, 0)), t["calories"] * SLOT_SHARE[s] / share_sum) for s in slots
    ]
    _close_gap(meals, t["calories"])
    _protein_top_up(meals, p.preference, t["protein_g"])
    _close_gap(meals, t["calories"])  # protein additions add calories; trim the staples back
    totals = _totals(meals)
    off = totals["kcal"] - t["calories"]
    if abs(off) > t["calories"] * 0.08:
        t["notes"].append(
            f"Portions are rounded to practical servings, so this sample day lands about {abs(off)} kcal {'above' if off > 0 else 'below'} your target. "
            "Trim or add rice, roti or fruit to match."
        )
    if totals["p"] < t["protein_g"] * 0.9:
        t["notes"].append("This sample day is a little short on protein. A scoop of whey, extra egg whites or more soya chunks closes the gap.")
    return {
        "targets": t,
        "meals": meals,
        "totals": totals,
        "tips": tips(p, t),
        "supplements": supplements(p),
        "disclaimer": DISCLAIMER,
    }


# ------------------------------------------------------------------- tips
def tips(p: Profile, t: dict) -> list[str]:
    out: list[str] = []
    if p.goal == "bulk":
        out += [
            f"Aim for about {abs(t['daily_change_kcal'])} kcal above maintenance and a gain of roughly {max(t['weekly_change_kg'], 0):.2f} kg a week. If the scale moves faster than 0.5 kg a week, trim the extra rice or roti.",
            "Eat every 3 to 4 hours. If you struggle to finish meals, add calorie-dense extras: ghee on roti, peanut butter, a banana milkshake.",
            "Train hard on compound lifts (squat, deadlift, press, pull). Food only builds muscle when the training asks for it.",
        ]
    elif p.goal == "cut":
        out += [
            f"You're about {abs(t['daily_change_kcal'])} kcal below maintenance, which should drop roughly {abs(t['weekly_change_kg']):.2f} kg a week. Slower and steady keeps your muscle.",
            "Keep protein high and keep lifting heavy so the weight you lose is fat. Fill up on dal, sprouts, salad, curd and vegetables.",
            "Pause the cut for a week (eat at maintenance) if your energy, sleep or mood suffers, and don't stay in a deficit longer than 8 to 12 weeks at a stretch.",
        ]
    elif p.goal == "recomp":
        out += [
            "A recomposition is slow: hold strength, keep protein high and be patient for 8 to 12 weeks. Judge it by photos, waist measurements and lifts, not just the scale.",
        ]
    else:
        out += ["At maintenance, your weight should stay steady. Use it as a rest phase between a bulk and a cut."]
    if p.preference == "veg":
        out.append("Vegetarian protein is easier with combinations: dal with rice or roti, paneer, curd, soya chunks, sprouts and milk. A whey scoop is optional and fills gaps.")
    elif p.preference == "egg":
        out.append("Eggs are your most efficient protein. Three to four a day is fine for most healthy adults; vary the rest with dal, paneer and curd.")
    else:
        out.append("Grill, bake or curry with little oil, and rotate chicken and fish. Keep dal and vegetables in every meal for fibre.")
    out += [
        f"Drink about {t['water_l']} litres of water a day, more in hot weather or on training days.",
        "Have most of your carbohydrates in the meals before and after training. Sleep seven to nine hours; recovery decides how much of your diet turns into progress.",
        "Weigh yourself first thing in the morning, two or three times a week, and adjust portions by about 100 to 150 kcal if nothing changes for two weeks.",
    ]
    return out


def supplements(p: Profile) -> list[str]:
    return [
        "Supplements are optional. Whole food comes first.",
        "Whey protein is convenient if you struggle to reach your protein target; check the label for third-party testing.",
        "Creatine monohydrate (3 to 5 g a day) has good evidence for strength; check with a doctor first if you have any kidney condition.",
    ]


def quick_macros(weight_kg: float, goal: str) -> dict:
    """Rough per-kg guidance for the chat assistant (no personal calorie maths)."""
    protein = {"bulk": (1.8, 2.2), "cut": (2.0, 2.4), "recomp": (1.8, 2.2), "maintain": (1.4, 1.8)}[goal]
    return {"protein_g": (round(weight_kg * protein[0]), round(weight_kg * protein[1])), "water_l": round(weight_kg * 0.035, 1)}
