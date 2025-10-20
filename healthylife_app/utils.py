import re # input validation for user authentication
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


def validate_email(email: str) -> bool:
    # check email format is valid or not
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email or ""))


def strong_password(pw: str) -> Tuple[bool, str]:
    if not pw or len(pw) < 8:
        return False, "At least 8 characters."
    if not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        return False, "Passwords should include words and numbers."
    return True, ""

# standard conversion from centimeter to inches & kilogram to pound
CM_PER_IN = 2.54 
KG_PER_LB = 0.45359237


# convert to centimeter and kilogram
def to_metric_from_imperial(ft: int, inch: float, lb: float) -> Tuple[float, float]:
    cm = (ft * 12 + inch) * CM_PER_IN
    kg = lb * KG_PER_LB
    return cm, kg

# the oppsite from centimeter to feet/inch and kilogram to pound
def to_imperial_from_metric(cm: float, kg: float) -> Tuple[Tuple[int, float], float]:
    total_in = cm / CM_PER_IN
    ft = int(total_in // 12)
    inch = round(total_in - ft * 12, 1)
    lb = round(kg / KG_PER_LB, 1)
    return (ft, inch), lb

# https://www.geeksforgeeks.org/python/python-program-to-calculate-age-in-year/
# set up for user dob
def parse_age(dob_iso: Optional[str]) -> Optional[int]:
    if not dob_iso:
        return None
    try:
        # calculate users' age
        dob = datetime.strptime(dob_iso, "%Y-%m-%d").date()
        today = date.today()
        years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        return max(0, years)
    except Exception:
        return None


ACTIVITY_FACTORS = {"sedentary": 1.2, "light": 1.375, "moderate": 1.55, "active": 1.725}

# provide the default value if users miss typing
def auto_goals(profile: Dict[str, Any]) -> Dict[str, Any]:
    w = float(profile.get("weight_kg") or 70)
    h = float(profile.get("height_cm") or 170)
    a = parse_age(profile.get("dob")) or 25
    sex = (profile.get("sex") or "other").lower()

    # set bmr for male and female caloeires intake from each day
    if sex == "male":
        bmr = 10 * w + 6.25 * h - 5 * a + 5
    elif sex == "female":
        bmr = 10 * w + 6.25 * h - 5 * a - 161
    else:
        bmr = 10 * w + 6.25 * h - 5 * a

    factor = ACTIVITY_FACTORS.get(profile.get("activity_level") or "light", 1.375)
    kcal = int(bmr * factor)
    return {
        "kcal": kcal,
        "protein_g": int((0.25 * kcal) / 4),
        "carbs_g": int((0.45 * kcal) / 4),
        "fat_g": int((0.30 * kcal) / 9),
        "fiber_g": 25,
        "water_ml": 2000,
    }

# convert the log to dataframe
def logs_to_df(logs: List[Dict[str, Any]]) -> pd.DataFrame:
    # convert logs to Dataframe
    df = pd.DataFrame(logs)
    if df.empty:
        return df
    # convert to date time format
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date")

# set the goal depends on your weight
def recommended_macros(profile: Dict[str, Any], kcal: int, goal: str = "fat_loss") -> Dict[str, int]:
    weight = float(profile.get("weight_kg") or 70)

    if goal == "muscle_gain":
        protein = int(round(2.0 * weight))
        fat_ratio = 0.25
    elif goal == "fat_loss":
        protein = int(round(1.8 * weight))
        fat_ratio = 0.30
    else:  # maintenance
        protein = int(round(1.6 * weight))
        fat_ratio = 0.28

    fat = int((fat_ratio * kcal) / 9)
    carbs = int((kcal - (protein * 4 + fat * 9)) / 4)
    # ensure no negative value that's why I set up max()
    return {"protein_g": max(protein, 0), "fat_g": max(fat, 0), "carbs_g": max(carbs, 0)}

# provide the recommendation based on users' record and goals
def adherence_tune(df: pd.DataFrame, goals: Dict[str, Any]) -> Optional[Dict[str, float]]:
    if df.empty or "kcal_in" not in df or "protein_g" not in df or not goals:
        return None

    # get recently 7 days record dropna is going to drop missing record
    df = df.tail(7).dropna(subset=["kcal_in", "protein_g"])  # recent 7 days
    if df.empty:
        return None

    kcal_target = goals.get("kcal")
    p_target = goals.get("protein_g")
    if not kcal_target or not p_target:
        return None

    kcal_rate = float((df["kcal_in"].between(kcal_target * 0.95, kcal_target * 1.05)).mean())
    p_rate = float((df["protein_g"] >= p_target * 0.9).mean())

    adjust = 0
    if kcal_rate < 0.4:
        adjust -= 100
    if kcal_rate > 0.8:
        adjust += 100

    return {"kcal_rate": kcal_rate, "protein_rate": p_rate, "kcal_adjust": float(adjust)}
