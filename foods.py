from __future__ import annotations
from datetime import date, datetime

import altair as alt
import streamlit as st

from auth import render_auth
from db import DB
from utils import (
    to_imperial_from_metric,
    to_metric_from_imperial,
    auto_goals,
    logs_to_df,
    recommended_macros,
    adherence_tune,
)
from foods import load_foods, suggest_meals

st.set_page_config(page_title="HealthyLife — User Pages", page_icon="👤", layout="centered")

# ---- small helper: safe int with default (handles None/str) ----
def _ival(x, default):
    try:
        return int(x) if x is not None else int(default)
    except (TypeError, ValueError):
        return int(default)

# ---- init DB ----
db = DB("healthylife.db")

# ---- session ----
if "current_user" not in st.session_state:
    st.session_state.current_user = None

# ---- router ----
if st.session_state.current_user is None:
    render_auth(db)
    st.stop()

email = st.session_state.current_user
st.sidebar.write(f"Logged in: **{email}**")
action = st.sidebar.radio("Page", ["Personal Info/Goals", "Log out"], index=0)
if action == "Log out":
    st.session_state.current_user = None
    st.rerun()

# ================= Profile / Goals =================
st.header("Personal Info / Onboarding")
prof = db.get_profile(email)
settings = db.get_settings(email)

with st.form("profile_form"):
    col1, col2 = st.columns(2)
    with col1:
        name = st.text_input(
            "Name",
            value=(db.connect().execute("SELECT name FROM users WHERE email=?", (email,)).fetchone()[0] or "")
        )
        sex_list = ["", "male", "female", "other"]
        sex = st.selectbox("Sex", sex_list, index=sex_list.index(prof.get("sex") or ""))
        dob_default = datetime.strptime(prof["dob"], "%Y-%m-%d").date() if prof.get("dob") else date(2000, 1, 1)
        dob = st.date_input("DOB", value=dob_default)
    with col2:
        unit_choice = st.selectbox(
            "輸入單位 (僅輸入時使用，內部儲存為公制)",
            ["metric", "imperial"],
            index=["metric", "imperial"].index(settings.get("unit_system", "metric")),
        )
        if unit_choice == "imperial":
            imp, lb = to_imperial_from_metric(
                float(prof.get("height_cm") or 170.0),
                float(prof.get("weight_kg") or 70.0),
            )
            ft = st.number_input("Height (ft)", min_value=0, max_value=8, value=imp[0])
            inch = st.number_input("Height (in)", min_value=0.0, max_value=11.9, value=float(imp[1]), step=0.1, format="%.1f")
            weight_lb = st.number_input("Weight (lb)", min_value=0.0, max_value=1100.0, value=float(lb), step=0.1, format="%.1f")
            height_cm, weight_kg = to_metric_from_imperial(ft, inch, weight_lb)
        else:
            height_cm = st.number_input("Height (cm)", min_value=0.0, max_value=300.0,
                                        value=float(prof.get("height_cm") or 170.0), step=0.1, format="%.1f")
            weight_kg = st.number_input("Weight (kg)", min_value=0.0, max_value=500.0,
                                        value=float(prof.get("weight_kg") or 70.0), step=0.1, format="%.1f")

        activity = st.selectbox(
            "Activity Level",
            ["sedentary", "light", "moderate", "active"],
            index=["sedentary", "light", "moderate", "active"].index(prof.get("activity_level") or "light"),
        )

    saved = st.form_submit_button("Save Personal Info")
    if saved:
        db.update_user_name(email, name)
        db.upsert_profile(
            email,
            {
                "sex": sex or None,
                "dob": dob.isoformat() if isinstance(dob, (date, datetime)) else (dob or None),
                "height_cm": round(float(height_cm), 1) if height_cm else None,
                "weight_kg": round(float(weight_kg), 1) if weight_kg else None,
                "activity_level": activity,
            },
        )
        st.success("Personal Info saved.")

st.divider()
st.subheader("Automatically Calculate Daily Goals")
if st.button("Auto-generate Goals from Data"):
    db.upsert_goals(email, auto_goals(db.get_profile(email)))
    st.success("Goals generated automatically!")

cur_goals = db.get_goals(email) or auto_goals(db.get_profile(email))

with st.form("goals_form"):
    col1, col2, col3 = st.columns(3)
    with col1:
        kcal    = st.number_input("Calories (kcal)", 0, 8000, _ival(cur_goals.get("kcal"), 2000))
        protein = st.number_input("Protein (g)", 0, 1000, _ival(cur_goals.get("protein_g"), 120))
    with col2:
        carbs   = st.number_input("Carbs (g)", 0, 1000, _ival(cur_goals.get("carbs_g"), 200))
        fat     = st.number_input("Fat (g)", 0, 1000, _ival(cur_goals.get("fat_g"), 60))
    with col3:
        fiber   = st.number_input("Fiber (g)", 0, 200, _ival(cur_goals.get("fiber_g"), 25))
        water   = st.number_input("Water (ml)", 0, 10000, _ival(cur_goals.get("water_ml"), 2000))
    if st.form_submit_button("Save Goals"):
        db.upsert_goals(
            email,
            {
                "kcal": int(kcal),
                "protein_g": int(protein),
                "carbs_g": int(carbs),
                "fat_g": int(fat),
                "fiber_g": int(fiber),
                "water_ml": int(water),
            },
        )
        st.success("Goals updated.")

st.divider()
st.subheader("Preferences")
with st.form("settings_form"):
    unit = st.selectbox("Display Unit System", ["metric", "imperial"],
                        index=["metric", "imperial"].index(settings.get("unit_system", "metric")))
    show_h2o = st.checkbox("Display Water Tracking", value=bool(settings.get("show_hydration", False)))
    nudges = st.checkbox("Receive daily reminders", value=bool(settings.get("nudge_opt_in", True)))
    if st.form_submit_button("Preferences"):
        db.upsert_settings(email, {"unit_system": unit, "show_hydration": show_h2o, "nudge_opt_in": nudges})
        st.success("Preferences updated.")

# ================= Logs & Charts =================
st.divider()
st.subheader("Daily record")
with st.form("log_form", clear_on_submit=True):
    d = st.date_input("Date", value=date.today())
    w = st.number_input("Weight (kg)", 0.0, 500.0, step=0.1, format="%.1f")
    kcal_in = st.number_input("Calories (kcal)", 0, 10000)
    p = st.number_input("Protein (g)", 0, 500)
    c = st.number_input("Carbs (g)", 0, 1000)
    f = st.number_input("Fat (g)", 0, 500)
    steps = st.number_input("Step", 0, 100000)
    if st.form_submit_button("Add record"):
        db.add_log(email, d.isoformat(), w, kcal_in, p, c, f, steps)
        st.success("Record added")

st.divider()
st.subheader("Progress Chart")
logs = db.get_logs(email)
df = logs_to_df(logs)
if df.empty:
    st.info("No log data yet, please add a few entries first!")
else:
    if "weight_kg" in df.columns and df["weight_kg"].notna().any():
        line = alt.Chart(df).mark_line(point=True).encode(
            x=alt.X("date:T", title="Date"),
            y=alt.Y("weight_kg:Q", title="Weight (kg)")
        ).properties(title="Weight Progress")
        st.altair_chart(line, use_container_width=True)

    if {"protein_g", "carbs_g", "fat_g"} <= set(df.columns):
        last7 = df.tail(7).copy()
        last7 = last7.dropna(subset=["protein_g", "carbs_g", "fat_g"])
        if not last7.empty:
            macro = last7[["protein_g", "carbs_g", "fat_g"]].mean().reset_index()
            macro.columns = ["macro", "grams"]
            pie = alt.Chart(macro).mark_arc().encode(
                theta="grams:Q", color="macro:N", tooltip=["macro", "grams"]
            ).properties(title="Macronutrient Ratio (Past 7 Days)")
            st.altair_chart(pie, use_container_width=True)

# ================= Smart Adjustments (no TDEE) =================
st.divider()
st.subheader("Smart Adjustment")

# 情境式宏量建議
st.markdown("**Scenario-Based Macro Recommendations**")
goal = st.selectbox("Target", ["fat_loss", "maintenance", "muscle_gain"], index=0, key="macro_goal")
if st.button("Generate Macro Recommendations"):
    kcal_now = int((db.get_goals(email) or auto_goals(db.get_profile(email))).get("kcal") or 2000)
    macros = recommended_macros(db.get_profile(email), kcal_now, goal)
    db.upsert_goals(email, {**(db.get_goals(email) or {}), **macros})
    st.success(f"Suggestion: Protein {macros['protein_g']} g、Fat {macros['fat_g']} g、Carbs {macros['carbs_g']} g")

# 依達標率自動微調
st.subheader("Auto-Adjust Based on Adherence Rate")
if st.button("Suggested Adjustment"):
    res = adherence_tune(df, db.get_goals(email))
    if res:
        msg = f"Calorie Adherence Rate: {res['kcal_rate']:.0%}; Protein Adherence Rate: {res['protein_rate']:.0%}"
        if int(res["kcal_adjust"]) != 0:
            g = db.get_goals(email) or {}
            new_kcal = max(1000, int(_ival(g.get("kcal"), 2000) + res["kcal_adjust"]))
            db.upsert_goals(email, {**g, "kcal": new_kcal})
            st.info(msg)
            st.success(f"Suggested daily calorie adjustment **{new_kcal} kcal**（±{int(res['kcal_adjust'])}）")
        else:
            st.success(msg + "; Current settings are reasonable, no adjustment needed for now.")
    else:
        st.warning("Insufficient data or goals not set.")

# ================= Food Suggestions =================
st.divider()
st.subheader("Meal Suggestions (Based on Goals and Food Database)")

DEFAULT_FOOD_CSV = "Food_and_Calories_Sheet1.csv"

# 預設讀檔
food_df = None
try:
    food_df = load_foods(DEFAULT_FOOD_CSV)
    st.caption(f"Default food list loaded: {DEFAULT_FOOD_CSV}")
except Exception as e:
    st.error(f"Failed to load default list: {e}")

# 提供使用者上傳自己的 CSV（可選）
uploaded = st.file_uploader("Upload your data CSV", type="csv")
if uploaded is not None:
    try:
        food_df = load_foods(uploaded)
        st.success("User-defined food list loaded!")
    except Exception as e:
        st.error(f"Failed to load user food list: {e}")

if food_df is not None and not food_df.empty:
    with st.expander("查看清單與診斷（前 20 筆）"):
        st.write({
            "rows_in": int(food_df.attrs.get("rows_in", -1)),
            "rows_after_kcal": int(food_df.attrs.get("rows_after_kcal", -1)),
            "columns_mapped": food_df.attrs.get("columns_mapped", {}),
        })
        st.dataframe(food_df.head(20), use_container_width=True)

    goals_now = db.get_goals(email) or auto_goals(db.get_profile(email))
    meal_k = st.number_input("Target Calories per Meal (kcal)", 200, 2000, int(max(200, (goals_now.get('kcal') or 1800)//3)))
    strategy = st.selectbox("Preference Strategy", ["balanced", "high_protein", "low_carb"], index=0)
    topn = st.slider("Show Top Suggestions", 3, 30, 12)

    try:
        recs = suggest_meals(food_df, goals_now, meal_kcal=meal_k, strategy=strategy, topn=topn)
        if recs.empty:
            st.warning("No suggestions generated: The CSV may be missing required fields or calorie data.")
        else:
            st.dataframe(recs, use_container_width=True)
    except Exception as ex:
        st.error(f"An error occurred while generating suggestions: {ex}")
else:
    st.info("There is currently no available food list.")
