from __future__ import annotations
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


def validate_email(email: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email or ""))


def strong_password(pw: str) -> Tuple[bool, str]:
    if not pw or len(pw) < 8:
        return False, "At least 8 characters."
    if not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        return False, "Passwords should include words and numbers."
    return True, ""


CM_PER_IN = 2.54
KG_PER_LB = 0.45359237


def to_metric_from_imperial(ft: int, inch: float, lb: float) -> Tuple[float, float]:
    cm = (ft * 12 + inch) * CM_PER_IN
    kg = lb * KG_PER_LB
    return cm, kg


def to_imperial_from_metric(cm: float, kg: float) -> Tuple[Tuple[int, float], float]:
    total_in = cm / CM_PER_IN
    ft = int(total_in // 12)
    inch = round(total_in - ft * 12, 1)
    lb = round(kg / KG_PER_LB, 1)
    return (ft, inch), lb


def parse_age(dob_iso: Optional[str]) -> Optional[int]:
    if not dob_iso:
        return None
    try:
        dob = datetime.strptime(dob_iso, "%Y-%m-%d").date()
        today = date.today()
        years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        return max(0, years)
    except Exception:
        return None


ACTIVITY_FACTORS = {"sedentary": 1.2, "light": 1.375, "moderate": 1.55, "active": 1.725}


def auto_goals(profile: Dict[str, Any]) -> Dict[str, Any]:
    w = float(profile.get("weight_kg") or 70)
    h = float(profile.get("height_cm") or 170)
    a = parse_age(profile.get("dob")) or 25
    sex = (profile.get("sex") or "other").lower()

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


def logs_to_df(logs: List[Dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(logs)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date")


def estimate_tdee_from_logs(df: pd.DataFrame, base_tdee_guess: int) -> Optional[int]:
    if df.empty or "kcal_in" not in df or "weight_kg" not in df:
        return None
    df = df.dropna(subset=["kcal_in", "weight_kg"]).copy()
    if len(df) < 10:
        return None

    df["kcal_in"] = df["kcal_in"].astype(float)
    df["weight_kg"] = df["weight_kg"].astype(float)

    df["kcal_in_7d"] = df["kcal_in"].rolling(7).sum()
    df["wt_7d"] = df["weight_kg"].rolling(7).mean()
    df["wt_7d_shift"] = df["wt_7d"].shift(-7)
    df = df.dropna(subset=["kcal_in_7d", "wt_7d", "wt_7d_shift"])
    if df.empty:
        return None

    delta_w = df["wt_7d_shift"].values - df["wt_7d"].values
    rhs = df["kcal_in_7d"].values - 7700.0 * delta_w  # ≈ 7*TDEE_user
    seven_tdee = float(np.mean(rhs))
    tdee_est = seven_tdee / 7.0
    tdee_est = max(base_tdee_guess * 0.7, min(base_tdee_guess * 1.3, tdee_est))
    return int(round(tdee_est))


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
    return {"protein_g": max(protein, 0), "fat_g": max(fat, 0), "carbs_g": max(carbs, 0)}


def adherence_tune(df: pd.DataFrame, goals: Dict[str, Any]) -> Optional[Dict[str, float]]:
    if df.empty or "kcal_in" not in df or "protein_g" not in df or not goals:
        return None

    df = df.tail(14).dropna(subset=["kcal_in", "protein_g"])  # recent 14 days
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
