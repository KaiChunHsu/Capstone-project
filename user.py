import re 
import hashlib
import os
from datetime import date, datetime
from typing import Dict, Any, Optional, Tuple
import streamlit as st

# set entire Streamlit App interface title, icon, and layouts
st.set_page_config(page_title="HealthyLife — User Pages", page_icon="👤", layout="centered")

# -----------------------
# In-memory "data store"
# -----------------------
if "users" not in st.session_state:
    st.session_state.users = {}
    #st.session_state["users"] = dict()
    #st.session_state.users: Dict[str, Dict[str, Any]] = {}

if "current_user" not in st.session_state:
    st.session_state.current_user: Optional[str] = None

# -----------------
# Helper functions
# -----------------
def hash_pw(password: str, salt: bytes) -> str:
    return hashlib.sha256(salt + password.encode("utf-8")).hexdigest()

def new_salt() -> bytes:
    return os.urandom(16)

def validate_email(email: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email or ""))

def strong_password(pw: str) -> Tuple[bool, str]:
    if not pw or len(pw) < 8:
        return False, "Password at least 8 digits"
    if not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        return False, "Password should include words and numerical"
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

# ----------------------
# Registration / Login
# ----------------------
def register_user(email: str, password: str, name: str = "") -> str:
    email = (email or "").lower().strip()
    if not validate_email(email):
        return "Please enter formal Email format."
    ok, why = strong_password(password)
    if not ok:
        return why
    if email in st.session_state.users:
        return "This Email has been registered."
    salt = new_salt()
    st.session_state.users[email] = {
        "password_salt": salt.hex(),
        "password_hash": hash_pw(password, salt),
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
    }
    return "Completed registration, please log in."

def login_user(email: str, password: str) -> bool:
    email = (email or "").lower().strip()
    u = st.session_state.users.get(email)
    if not u:
        return False
    salt = bytes.fromhex(u.get("password_salt", "")) if u.get("password_salt") else b""
    return u.get("password_hash") == hash_pw(password, salt)
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
            pw = st.text_input("Password (At least 8 digits, including words and numerical)", type="password")
            ok = st.form_submit_button("Create account")
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
            sex = st.selectbox("Sex", ["", "male", "female", "other"], index=["", "male", "female", "other"].index(prof.get("sex") or ""))
            dob = st.date_input("DOB", value=(datetime.strptime(prof["dob"], "%Y-%m-%d").date() if prof.get("dob") else date(2000, 1, 1)))
        with col2:
            unit_choice = st.selectbox("Input unit (used only for input, stored internally as metric)", ["metric", "imperial"], index=["metric", "imperial"].index(user["settings"].get("unit_system", "metric")))
            if unit_choice == "imperial":
                imp, lb = to_imperial_from_metric(float(prof.get("height_cm") or 170.0), float(prof.get("weight_kg") or 70.0))
                ft = st.number_input("Height (ft)", min_value=0, max_value=8, value=imp[0])
                inch = st.number_input("Height (in)", min_value=0.0, max_value=11.9, value=float(imp[1]))
                weight_lb = st.number_input("Weight (lb)", min_value=0.0, max_value=1100.0, value=float(lb))
                height_cm, weight_kg = to_metric_from_imperial(ft, inch, weight_lb)
            else:
                height_cm = st.number_input("Height (cm)", min_value=0.0, max_value=300.0, value=float(prof.get("height_cm") or 170.0))
                weight_kg = st.number_input("Weight (kg)", min_value=0.0, max_value=500.0, value=float(prof.get("weight_kg") or 70.0))
            activity = st.selectbox("Activity level", ["sedentary", "light", "moderate", "active"], index=["sedentary", "light", "moderate", "active"].index(prof.get("activity_level") or "light"))
        saved = st.form_submit_button("Personal Info save")

    if saved:
        st.session_state.users[email]["profile"].update({
            "name": name,
            "sex": sex or None,
            "dob": dob.isoformat() if isinstance(dob, (date, datetime)) else (dob or None),
            "height_cm": round(float(height_cm), 1) if height_cm else None,
            "weight_kg": round(float(weight_kg), 1) if weight_kg else None,
            "activity_level": activity,
        })
        st.success("Personal Info has been saved")

    st.divider()
    st.subheader("Automatically calculate daily goal")
    if st.button("Automatically generate goals based on data"):
        st.session_state.users[email]["goals"] = auto_goals(st.session_state.users[email]["profile"])
        st.success("Goal has been created automatically!")

    goals = user.get("goals") or auto_goals(user["profile"])

    with st.form("goals_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            kcal = st.number_input("calories (kcal)", 0, 8000, int(goals["kcal"]))
            protein = st.number_input("protein (g)", 0, 1000, int(goals["protein_g"]))
        with col2:
            carbs = st.number_input("carbs (g)", 0, 1000, int(goals["carbs_g"]))
            fat = st.number_input("fat (g)", 0, 1000, int(goals["fat_g"]))
        with col3:
            fiber = st.number_input("fiber (g)", 0, 200, int(goals["fiber_g"]))
            water = st.number_input("water (ml)", 0, 10000, int(goals["water_ml"]))
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
        st.success("Goal updated")

    st.divider()
    st.subheader("Preferences")
    settings = user["settings"]
    with st.form("settings_form"):
        unit = st.selectbox("Show unit system", ["metric", "imperial"], index=["metric", "imperial"].index(settings.get("unit_system", "metric")))
        show_h2o = st.checkbox("Show water tracking", value=bool(settings.get("show_hydration", False)))
        nudges = st.checkbox("Receive daily reminders", value=bool(settings.get("nudge_opt_in", True)))
        saved_settings = st.form_submit_button("Save preferences")
    if saved_settings:
        settings.update({
            "unit_system": unit,
            "show_hydration": show_h2o,
            "nudge_opt_in": nudges,
        })
        st.success("Preferences updated.")

# --------------
# Main router
# --------------
if st.session_state.current_user is None:
    render_auth()
    st.stop()

email = st.session_state.current_user
st.sidebar.write(f"Logged in：**{email}**")
page = st.sidebar.radio("Page", ["Personal Info/Target", "Log out"], index=0)

if page == "Log out":
    st.session_state.current_user = None
    st.rerun()
else:
    render_profile()
