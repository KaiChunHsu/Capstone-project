# app.py
# HealthyLife — User Pages (No-SQL, in-memory)
# Features added:
# - Daily logs (weight, intake, macros, steps)
# - Charts (weight trend, 7-day macro pie)
# - ML helpers:
#     (1) Personalized TDEE calibration from your own data
#     (2) Scenario-based macro recommendation (fat loss / maintenance / muscle gain)
#     (3) Adherence-based gentle auto-tuning

import re
import hashlib
import os
from datetime import date, datetime
from typing import Dict, Any, Optional, Tuple

import numpy as np
import pandas as pd
import altair as alt
import streamlit as st

# --------------------------------
# Streamlit App page configuration
# --------------------------------
st.set_page_config(page_title="HealthyLife — User Pages", page_icon="👤", layout="centered")

# -----------------------
# In-memory "data store"
# -----------------------
if "users" not in st.session_state:
    st.session_state.users: Dict[str, Dict[str, Any]] = {}

if "current_user" not in st.session_state:
    st.session_state.current_user: Optional[str] = None

# -----------------
# Helper functions
# -----------------
def _hash_pw(password: str, salt: bytes) -> str:
    return hashlib.sha256(salt + password.encode("utf-8")).hexdigest()

def _new_salt() -> bytes:
    return os.urandom(16)

def validate_email(email: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email or ""))

def strong_password(pw: str) -> Tuple[bool, str]:
    if not pw or len(pw) < 8:
        return False, "At least 8 digits for password"
    if not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        return False, "Password must include numbers and words."
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

# ------------------------------
# Registration / Login (Auth)
# ------------------------------
def register_user(email: str, password: str, name: str = "") -> str:
    email = (email or "").lower().strip()
    if not validate_email(email):
        return "Please enter formal Email format."
    ok, why = strong_password(password)
    if not ok:
        return why
    if email in st.session_state.users:
        return "This Email has registered."
    salt = _new_salt()
    st.session_state.users[email] = {
        "password_salt": salt.hex(),
        "password_hash": _hash_pw(password, salt),
        "profile": {
            "name": name,
            "sex": None,
            "dob": None,
            "height_cm": None,
            "weight_kg": None,
            "activity_level": "light",
        },
        "settings": {
            "unit_system": "metric",
            "show_hydration": False,
            "nudge_opt_in": True,
        },
        "goals": None,
        "logs": [],  # NEW: place to store daily logs
    }
    return "Completed register, please log in."

def login_user(email: str, password: str) -> bool:
    email = (email or "").lower().strip()
    u = st.session_state.users.get(email)
    if not u:
        return False
    salt = bytes.fromhex(u.get("password_salt", "")) if u.get("password_salt") else b""
    return u.get("password_hash") == _hash_pw(password, salt)

# ------------------------------
# Auto-goal calculator (Mifflin)
# ------------------------------
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

# ----------------------
# Logs + Data utilities
# ----------------------
def add_log(email: str, date_iso: str, weight_kg=None, kcal_in=None, protein_g=None, carbs_g=None, fat_g=None, steps=None):
    entry = {
        "date": date_iso,
        "weight_kg": float(weight_kg) if weight_kg is not None else None,
        "kcal_in": int(kcal_in) if kcal_in is not None else None,
        "protein_g": int(protein_g) if protein_g is not None else None,
        "carbs_g": int(carbs_g) if carbs_g is not None else None,
        "fat_g": int(fat_g) if fat_g is not None else None,
        "steps": int(steps) if steps is not None else None,
    }
    st.session_state.users[email]["logs"].append(entry)

def logs_df(email: str) -> pd.DataFrame:
    df = pd.DataFrame(st.session_state.users[email].get("logs", []))
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date")

# --------------------------
# TDEE tuning
# --------------------------
def estimate_tdee_from_logs(email: str, base_tdee_guess: int) -> Optional[int]:
    df = logs_df(email)
    if df.empty or "kcal_in" not in df or "weight_kg" not in df:
        return None

    df = df.dropna(subset=["kcal_in", "weight_kg"]).copy()
    if len(df) < 10:
        return None  # need enough data

    df["kcal_in"] = df["kcal_in"].astype(float)
    df["weight_kg"] = df["weight_kg"].astype(float)

    # 7-day window: energy surplus/deficit ~ weight change
    df["kcal_in_7d"] = df["kcal_in"].rolling(7).sum()
    df["wt_7d"] = df["weight_kg"].rolling(7).mean()
    df["wt_7d_shift"] = df["wt_7d"].shift(-7)  # weight 7 days later
    df = df.dropna(subset=["kcal_in_7d", "wt_7d", "wt_7d_shift"])
    if df.empty:
        return None

    # Model: ΔW(kg) ≈ (Σ(kcal_in) − 7*TDEE_user) / 7700
    delta_w = df["wt_7d_shift"].values - df["wt_7d"].values
    rhs = df["kcal_in_7d"].values - 7700.0 * delta_w  # ≈ 7*TDEE_user
    seven_tdee = np.mean(rhs)
    tdee_est = float(seven_tdee / 7.0)

    # Clamp to reasonable band around formula estimate
    tdee_est = max(base_tdee_guess * 0.7, min(base_tdee_guess * 1.3, tdee_est))
    return int(round(tdee_est))

# ----------------------------------------
# Scenario macro suggestion
# ----------------------------------------
def recommended_macros(profile: Dict[str, Any], kcal: int, goal: str = "fat_loss") -> Dict[str, int]:
    weight = float(profile.get("weight_kg") or 70)
    # protein baseline per goal
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

# --------------------------------------
# Adherence-based tuning
# --------------------------------------
def adherence_tune(email: str) -> Optional[Dict[str, float]]:
    df = logs_df(email)
    goals = st.session_state.users[email].get("goals") or {}
    if df.empty or "kcal_in" not in df or "protein_g" not in df or not goals:
        return None

    df = df.tail(14).dropna(subset=["kcal_in", "protein_g"])
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

# -------------
# Auth screens
# -------------
def render_auth():
    st.title("HealthyLife — User Page")
    tab_login, tab_register = st.tabs(["Log in", "Register"])

    with tab_login:
        with st.form("login"):
            email = st.text_input("Email")
            pw = st.text_input("Password", type="password")
            ok = st.form_submit_button("Log in")
        if ok:
            if login_user(email, pw):
                st.session_state.current_user = email.lower().strip()
                st.success("Log in successfully")
                st.rerun()
            else:
                st.error("Account or password error")

    with tab_register:
        with st.form("register"):
            name = st.text_input("Name (can leave for empty)")
            email = st.text_input("Email")
            pw = st.text_input("Password (At least 8 digits, including words and numbers)", type="password")
            ok = st.form_submit_button("Account created")
        if ok:
            msg = register_user(email, pw, name)
            if "Success" in msg:
                st.success(msg)
            else:
                st.error(msg)

# ---------------------
# Onboarding / Profile
# ---------------------
def render_profile():
    email = st.session_state.current_user
    user = st.session_state.users[email]

    st.header("Personal Info / Onboarding")
    prof = user["profile"]

    with st.form("profile_form"):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Name", value=prof.get("name") or "")
            sex_list = ["", "male", "female", "other"]
            sex = st.selectbox("Sex", sex_list, index=sex_list.index(prof.get("sex") or ""))
            dob_default = datetime.strptime(prof["dob"], "%Y-%m-%d").date() if prof.get("dob") else date(2000, 1, 1)
            dob = st.date_input("DOB", value=dob_default)
        with col2:
            unit_choice = st.selectbox("Input unit (used only for input, stored internally as metric)", ["metric", "imperial"],
                                       index=["metric", "imperial"].index(user["settings"].get("unit_system", "metric")))
            if unit_choice == "imperial":
                imp, lb = to_imperial_from_metric(float(prof.get("height_cm") or 170.0), float(prof.get("weight_kg") or 70.0))
                ft = st.number_input("Height (ft)", min_value=0, max_value=8, value=imp[0])
                inch = st.number_input("Height (in)", min_value=0.0, max_value=11.9, value=float(imp[1]), step=0.1, format="%.1f")
                weight_lb = st.number_input("Weight (lb)", min_value=0.0, max_value=1100.0, value=float(lb), step=0.1, format="%.1f")
                height_cm, weight_kg = to_metric_from_imperial(ft, inch, weight_lb)
            else:
                height_cm = st.number_input("Height (cm)", min_value=0.0, max_value=300.0, value=float(prof.get("height_cm") or 170.0), step=0.1, format="%.1f")
                weight_kg = st.number_input("Weight (kg)", min_value=0.0, max_value=500.0, value=float(prof.get("weight_kg") or 70.0), step=0.1, format="%.1f")
            activity = st.selectbox("Activity level", ["sedentary", "light", "moderate", "active"],
                                    index=["sedentary", "light", "moderate", "active"].index(prof.get("activity_level") or "light"))
        saved = st.form_submit_button("Saved personal Info")

    if saved:
        st.session_state.users[email]["profile"].update({
            "name": name,
            "sex": sex or None,
            "dob": dob.isoformat() if isinstance(dob, (date, datetime)) else (dob or None),
            "height_cm": round(float(height_cm), 1) if height_cm else None,
            "weight_kg": round(float(weight_kg), 1) if weight_kg else None,
            "activity_level": activity,
        })
        st.success("Personal Info has been saved.")

    st.divider()
    st.subheader("Automatically calculate daily goal")
    if st.button("Automatically generate goals based on data"):
        st.session_state.users[email]["goals"] = auto_goals(st.session_state.users[email]["profile"])
        st.success("Goal has been created automatically!")

    goals = user.get("goals") or auto_goals(user["profile"])

    with st.form("goals_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            kcal = st.number_input("Calories (kcal)", 0, 8000, int(goals["kcal"]))
            protein = st.number_input("Protein (g)", 0, 1000, int(goals["protein_g"]))
        with col2:
            carbs = st.number_input("Carbs (g)", 0, 1000, int(goals["carbs_g"]))
            fat = st.number_input("Fat (g)", 0, 1000, int(goals["fat_g"]))
        with col3:
            fiber = st.number_input("Fiber (g)", 0, 200, int(goals["fiber_g"]))
            water = st.number_input("Water (ml)", 0, 10000, int(goals["water_ml"]))
        saved_goals = st.form_submit_button("Save goal")
    if saved_goals:
        st.session_state.users[email]["goals"] = {
            "kcal": int(kcal),
            "protein_g": int(protein),
            "carbs_g": int(carbs),
            "fat_g": int(fat),
            "fiber_g": int(fiber),
            "water_ml": int(water),
        }
        st.success("Target updated")

    st.divider()
    st.subheader("Preferences")
    settings = user["settings"]
    with st.form("settings_form"):
        unit = st.selectbox("Show unit system", ["metric", "imperial"], index=["metric", "imperial"].index(settings.get("unit_system", "metric")))
        show_h2o = st.checkbox("Show water tracking", value=bool(settings.get("show_hydration", False)))
        nudges = st.checkbox("Receive daily reminders", value=bool(settings.get("nudge_opt_in", True)))
        saved_settings = st.form_submit_button("Preferences")
    if saved_settings:
        settings.update({
            "unit_system": unit,
            "show_hydration": show_h2o,
            "nudge_opt_in": nudges,
        })
        st.success("Preferences updated")

    # ----------------
    # Daily Log input
    # ----------------
    st.divider()
    st.subheader("Daily record")
    with st.form("log_form", clear_on_submit=True):
        d = st.date_input("Date", value=date.today())
        w = st.number_input("Weight (kg)", 0.0, 500.0, step=0.1, format="%.1f")
        kcal_in = st.number_input("Calories intake (kcal)", 0, 10000)
        p = st.number_input("Protein (g)", 0, 500)
        c = st.number_input("Carbs (g)", 0, 1000)
        f = st.number_input("Fat (g)", 0, 500)
        steps = st.number_input("Steps", 0, 100000)
        ok = st.form_submit_button("Add reocrd")
    if ok:
        add_log(email, d.isoformat(), w, kcal_in, p, c, f, steps)
        st.success("Record updated")

    # -----------
    # Charts
    # -----------
    st.divider()
    st.subheader("Chart progress")
    df = logs_df(email)
    if df.empty:
        st.info("Not receiving daily infor yet, please add some!")
    else:
        # Weight trend
        if "weight_kg" in df.columns and df["weight_kg"].notna().any():
            line = alt.Chart(df).mark_line(point=True).encode(
                x=alt.X("date:T", title="Date"),
                y=alt.Y("weight_kg:Q", title="Weight (kg)")
            ).properties(title="Trend of Weight")
            st.altair_chart(line, use_container_width=True)

        # 7-day macro pie
        if {"protein_g","carbs_g","fat_g"} <= set(df.columns):
            last7 = df.tail(7).copy()
            last7 = last7.dropna(subset=["protein_g","carbs_g","fat_g"])
            if not last7.empty:
                macro = last7[["protein_g","carbs_g","fat_g"]].mean().reset_index()
                macro.columns = ["macro","grams"]
                pie = alt.Chart(macro).mark_arc().encode(
                    theta="grams:Q",
                    color="macro:N",
                    tooltip=["macro","grams"]
                ).properties(title="Average macronutrient ratio over the past 7 days")
                st.altair_chart(pie, use_container_width=True)

    # ----------------------
    # Smart adjustments (ML)
    # ----------------------
    st.divider()
    st.subheader("Smart Tuning")
    base = (st.session_state.users[email].get("goals") or auto_goals(st.session_state.users[email]["profile"]))["kcal"]

    # Personalized TDEE calibration
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Personalized TDEE Adjustment**（Use your record）")
        if st.button("Adjust my daily energy expenditure using my records (TDEE)"):
            tdee_est = estimate_tdee_from_logs(email, base)
            if tdee_est:
                target_change = st.number_input("Target weekly weight change (kg)", -1.5, 1.5, -0.5, step=0.1, key="target_change_kgs")
                delta_kcal = int(round((target_change * 7700) / 7.0))  # daily kcal shift
                new_kcal = int(tdee_est + delta_kcal)

                st.info(f"Estimate your personalized TDEE ≈ **{tdee_est} kcal/day**")
                st.success(f"Recommend daily calories based on your goal ≈ **{new_kcal} kcal**")
                # Apply + re-calc macros proportionally
                g = st.session_state.users[email].get("goals") or {}
                g["kcal"] = new_kcal
                # keep protein tied to weight sensibly (~1.8 g/kg default)
                weight_now = st.session_state.users[email]["profile"].get("weight_kg") or 70
                g.update({
                    "protein_g": int(round(1.8 * float(weight_now))),
                    "fat_g": int((0.30 * new_kcal) / 9),
                    "carbs_g": int((new_kcal - (g["protein_g"] * 4 + int((0.30 * new_kcal)) )) / 4),
                })
                st.session_state.users[email]["goals"] = g
            else:
                st.warning("Insufficient data or missing required fields (at least 10+ days of records with both weight and calories are needed).")

    with col_b:
        st.markdown("**Scenario-based macro recommendations**")
        goal = st.selectbox("Target", ["fat_loss", "maintenance", "muscle_gain"], index=0, key="macro_goal")
        if st.button("Generate macro recommendation"):
            kcal_now = (st.session_state.users[email].get("goals") or {}).get("kcal", base)
            macros = recommended_macros(st.session_state.users[email]["profile"], kcal_now, goal)
            g = st.session_state.users[email].get("goals") or {}
            g.update(macros)
            st.session_state.users[email]["goals"] = g
            st.success(f"Suggestion：Protein {macros['protein_g']} g、Fat {macros['fat_g']} g、Carbs {macros['carbs_g']} g")

    st.subheader("Auto-adjust based on adherence rate.")
    if st.button("Recommend a slight adjustment"):
        res = adherence_tune(email)
        if res:
            msg = f"Calorie adherence rate: {res['kcal_rate']:.0%}；Protein adherence rate: {res['protein_rate']:.0%}"
            if int(res["kcal_adjust"]) != 0 and "goals" in st.session_state.users[email]:
                new_kcal = max(1000, int(st.session_state.users[email]["goals"]["kcal"] + res["kcal_adjust"]))
                st.info(msg)
                st.success(f"It is recommended to adjust daily calories to **{new_kcal} kcal**（±{int(res['kcal_adjust'])}）")
                st.session_state.users[email]["goals"]["kcal"] = new_kcal
            else:
                st.success(msg + "; The current setting is reasonable; no adjustment needed for now.")
        else:
            st.warning("Insufficient data or goal not yet set.")

# --------------
# Main router
# --------------
if st.session_state.current_user is None:
    render_auth()
    st.stop()

email = st.session_state.current_user
st.sidebar.write(f"Logged in: **{email}**")
page = st.sidebar.radio("Page", ["Personal Info/Target", "Log out"], index=0)

if page == "Log out":
    st.session_state.current_user = None
    st.rerun()
else:
    render_profile()
