from datetime import date, datetime, timedelta
import pandas as pd

import altair as alt # generate visualization 
import streamlit as st # main construction of UI interaction

from auth import render_auth # display interface of log in/register 
from db import DB # categorical of database operation
from utils import (
    to_imperial_from_metric,
    to_metric_from_imperial,
    auto_goals,
    logs_to_df,
    recommended_macros,
    adherence_tune,
)
from foods import load_foods, suggest_meals

# set the default value of page_icon
st.set_page_config(page_title="HealthyLife — User Pages", page_icon="👤", layout="centered")

# safe int with default (handles None/str)
def _ival(x, default):
    try:
        return int(x) if x is not None else int(default)
    except (TypeError, ValueError):
        return int(default)

# init DB 
# establish database object in order to connect SQLite file 
db = DB("healthylife.db")

# session
# https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state
if "current_user" not in st.session_state:
    st.session_state.current_user = None

# router
if st.session_state.current_user is None:
    render_auth(db)
    st.stop() # display log in page but not the following content

email = st.session_state.current_user
st.sidebar.write(f"Logged in: **{email}**")

# https://docs.streamlit.io/develop/api-reference/widgets/st.radio
action = st.sidebar.radio("Page", ["Personal Info/Goals", "Log out"], index=0)
if action == "Log out":
    st.session_state.current_user = None # clean out the infor and rerun the page 
    st.rerun()

# Profile / Goals
# display title 
st.header("Personal Info / Onboarding")
# get personal file from current user / preference settings
prof = db.get_profile(email) 
settings = db.get_settings(email) 

with st.form("profile_form"):
    # divide two columns
    col1, col2 = st.columns(2)
    with col1:
        # use default value or the name that user create the account for register
        name = st.text_input(
            "Name",
            value=(db.connect().execute("SELECT name FROM users WHERE email=?", (email,)).fetchone()[0] or "")
        )

        # select gender in the box
        sex_list = ["", "male", "female", "other"]
        sex = st.selectbox("Sex", sex_list, index=sex_list.index(prof.get("sex") or ""))

        # setting the DOB by user to store in prof['dob'] or default value as 2000/1/1
        dob_default = datetime.strptime(prof["dob"], "%Y-%m-%d").date() if prof.get("dob") else date(2000, 1, 1)
        dob = st.date_input("DOB", value=dob_default)
        
    with col2:
        # choose metric or imperial
        unit_choice = st.selectbox(
            "Unit choice",
            ["metric", "imperial"],
            index=["metric", "imperial"].index(settings.get("unit_system", "metric")),
        )
        # Usually I set the default as metric, but here is the conversion from metric to imperial
        # As using the function that I created from utils.py
        if unit_choice == "imperial":
            imp, lb = to_imperial_from_metric(
                float(prof.get("height_cm") or 170.0),
                float(prof.get("weight_kg") or 70.0),
            )
            # step = 0.1 as streamlit is going to adjust users' Height and Weight with 0.1 value 
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
    # name and profile will be separated 
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

# After entering PI, I divide the format
st.divider()
st.subheader("Automatically Calculate Daily Goals")
if st.button("Auto-generate Goals from Data"):
    db.upsert_goals(email, auto_goals(db.get_profile(email)))
    st.success("Goals generated automatically!")

# generate the basic goals based on user profile
cur_goals = db.get_goals(email) or auto_goals(db.get_profile(email))

# use _ival to check the value is integer 
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
        # update if info has been created, insert if nothing in dict
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


# Water Tracking
# convert water unit from oz to ml
OZ_TO_ML = 29.5735
st.divider()
st.subheader("Preferences")

# create select box that user choose the unit (metric or imperial)
with st.form("settings_form"):
    unit = st.selectbox(
        "Display Unit System",
        ["metric", "imperial"],
        index=["metric", "imperial"].index(settings.get("unit_system", "metric"))
    )

    # check the box if they want the preference
    show_h2o = st.checkbox("Display Water Tracking", value=bool(settings.get("show_hydration", False)))

    # Hydration goal input (liters)
    # it will convert it for next one
    hydration_goal_liters = None
    if show_h2o:
        hydration_goal_liters = st.number_input(
            "Daily Hydration Goal (liters)",
            min_value=0.5, max_value=10.0, step=0.1,
            value=float(settings.get("hydration_goal", 2.0))
        )

    if st.form_submit_button("Save Preferences"):
        update_data = {
            "unit_system": unit,
            "show_hydration": show_h2o,
        }
        if hydration_goal_liters is not None:
            # update the goal that user set up
            update_data["hydration_goal"] = float(hydration_goal_liters)
        db.upsert_settings(email, update_data)
        st.success("Preferences updated.")


# Hydration UI 
# get the data from users' setting
# set default as metric with 2000 liter
if (db.get_settings(email) or {}).get("show_hydration"):
    s = db.get_settings(email) or {}
    unit_system = s.get("unit_system", "metric")
    goal_l = float(s.get("hydration_goal", 2.0))
    goal_ml = int(round(goal_l * 1000))

    # Initialize local water log if missing
    # record daily water intake
    if "h2o_log" not in st.session_state:
        st.session_state.h2o_log = {}  # {"YYYY-MM-DD": total_ml}

    # get the current day string and how much water user dirnks
    today_str = date.today().isoformat()
    today_ml = int(st.session_state.h2o_log.get(today_str, 0))

    st.divider()
    st.subheader("Hydration Tracker 💧")

    # add the buttons that user can click for how much water they drink or modify it
    col1, col2, col3, col4, col5 = st.columns(5)
    # set the liter for metric and oz
    if unit_system == "metric":
        add_sizes = [250, 350, 500, 750, 1000]
        labels = [f"{x} ml" for x in add_sizes]
    else:
        oz_sizes = [8, 12, 16, 24, 32]
        add_sizes = [int(round(o * OZ_TO_ML)) for o in oz_sizes]
        labels = [f"{o} oz" for o in oz_sizes]

    # using for loop and zip to calculate the total that users' accumulate
    for col, lbl, ml in zip([col1, col2, col3, col4, col5], labels, add_sizes):
        if col.button(f"+ {lbl}"):
            today_ml = int(st.session_state.h2o_log.get(today_str, 0)) + ml
            st.session_state.h2o_log[today_str] = today_ml

    # Manual add
    # established the expander that can save the sapce
    with st.expander("Manual add"):
        # add the water intake with metric or imperial and save each to daily water intake
        if unit_system == "metric":
            add_custom = st.number_input("Add amount (ml)", min_value=0, max_value=4000, step=50, value=0)
            if st.button("Add water"):
                today_ml = int(st.session_state.h2o_log.get(today_str, 0)) + int(add_custom)
                st.session_state.h2o_log[today_str] = today_ml
        else:
            # here is the else statement for oz 
            add_custom_oz = st.number_input("Add amount (oz)", min_value=0, max_value=150, step=1, value=0)
            if st.button("Add water"):
                today_ml = int(st.session_state.h2o_log.get(today_str, 0)) + int(round(add_custom_oz * OZ_TO_ML))
                st.session_state.h2o_log[today_str] = today_ml

    # Delete Record Section
    st.subheader("Delete Record")
    if st.button("Delete Today’s Record ❌"):
        # check if user record the daily water intake 
        if today_str in st.session_state.h2o_log:
            del st.session_state.h2o_log[today_str]
            st.success("Today's record deleted.")
        else:
            st.warning("No record found for today.")

    with st.expander("Delete Past Record"):
        # set the expander
        # delete past record if needed
        # sort all the past 7 days and reverse it
        all_dates = sorted(st.session_state.h2o_log.keys(), reverse=True)
        if all_dates:
            # delete all the date
            date_to_delete = st.selectbox("Select a date to delete", all_dates)
            if st.button("Delete Selected Date"):
                # select the date you would like to delete if show up in the expander
                if date_to_delete in st.session_state.h2o_log:
                    del st.session_state.h2o_log[date_to_delete]
                    st.success(f"Record for {date_to_delete} deleted.")
        else:
            st.info("No past records to delete.")

    # show the progress on how much water user intake
    today_ml = int(st.session_state.h2o_log.get(today_str, 0))
    pct = min(1.0, today_ml / goal_ml if goal_ml > 0 else 0.0)
    if unit_system == "metric":
        disp_taken = f"{today_ml} ml"
        disp_goal = f"{goal_ml} ml"
        disp_left = f"{max(0, goal_ml - today_ml)} ml left"
    else:
        # transfer unit to oz
        taken_oz = today_ml / OZ_TO_ML
        goal_oz = goal_ml / OZ_TO_ML
        left_oz = max(0, goal_ml - today_ml) / OZ_TO_ML
        disp_taken = f"{taken_oz:.1f} oz"
        disp_goal = f"{goal_oz:.1f} oz"
        disp_left = f"{left_oz:.1f} oz left"

    # show the progress with bar chart
    st.markdown(f"**Today:** {disp_taken} / {disp_goal}  —  {disp_left}")
    st.progress(pct)

    # 7-day chart
    def days_back(n: int):
        # substract today's date 
        result = []
        for i in range(n):
            # trace back reversely
            d = date.today() - timedelta(days=n - 1 - i)
            result.append(d.isoformat())
        return result

    # recently 7 days
    # https://docs.streamlit.io/develop/api-reference/charts/st.altair_chart
    last7 = days_back(7)
    data = []
    for d in last7:
        # get the water intake from users' data
        ml = int(st.session_state.h2o_log.get(d, 0))
        data.append({"date": d, "intake_ml": ml, "goal_ml": goal_ml})

    df = pd.DataFrame(data)

    if unit_system == "metric":
        df["intake_disp"] = df["intake_ml"]
        df["goal_disp"] = df["goal_ml"]
        y_title = "Intake (ml)"
    else:
        df["intake_disp"] = df["intake_ml"] / OZ_TO_ML
        df["goal_disp"] = df["goal_ml"] / OZ_TO_ML
        y_title = "Intake (oz)"

    st.subheader("Last 7 Days")
    # create bar chart with alt
    bars = alt.Chart(df).mark_bar().encode(
        x=alt.X("date:N", title="Date"),
        y=alt.Y("intake_disp:Q", title=y_title),
        # set up when users' mouse stick on the chart and it will represent the value 
        tooltip=[
            alt.Tooltip("date:N", title="Date"),
            alt.Tooltip("intake_disp:Q", title="Intake", format=".1f"),
            alt.Tooltip("goal_disp:Q", title="Goal", format=".1f"),
        ],
    )

    # transfer to dotted line 
    goal_rule = alt.Chart(df).mark_rule(strokeDash=[4,4]).encode(
        # draw the vertical line from each date
        x="date:N",
        # draw the horizontal line from each ml/oz
        y="goal_disp:Q"
    )

    # adjust streamlit width 
    st.altair_chart(bars + goal_rule, use_container_width=True)





        



# Logs & Charts
# save the daily record and pop up for the chart
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

# visualization after adding the record
st.divider()
st.subheader("Progress Chart")
logs = db.get_logs(email)
df = logs_to_df(logs)
if df.empty:
    st.info("No log data yet, please add a few entries first!")
else:
    # weight progress
    if "weight_kg" in df.columns and df["weight_kg"].notna().any():
        line = alt.Chart(df).mark_line(point=True).encode(
            x=alt.X("date:T", title="Date"),
            y=alt.Y("weight_kg:Q", title="Weight (kg)")
        ).properties(title="Weight Progress")
        st.altair_chart(line, use_container_width=True)
    # the ratio between protein, carb and fat
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

# Smart Adjustments
st.divider()
st.subheader("Smart Adjustment")

# Scenario-Based Macro Recommendations (情境式宏量建議)
st.markdown("**Scenario-Based Macro Recommendations**")
# check which target you pursue
goal = st.selectbox("Target", ["fat_loss", "maintenance", "muscle_gain"], index=0, key="macro_goal")
if st.button("Generate Macro Recommendations"):
    # try to get the kcal from users' account, if not the default is 2000
    kcal_now = int((db.get_goals(email) or auto_goals(db.get_profile(email))).get("kcal") or 2000)
    macros = recommended_macros(db.get_profile(email), kcal_now, goal)
    db.upsert_goals(email, {**(db.get_goals(email) or {}), **macros})
    #st.success(f"Suggestion: Protein {macros['protein_g']} g、Fat {macros['fat_g']} g、Carbs {macros['carbs_g']} g")
    st.success(f"Suggestion: Total {kcal_now} kcal — Protein {macros['protein_g']} g、Fat {macros['fat_g']} g、Carbs {macros['carbs_g']} g")


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

# Food Suggestions
st.divider()
st.subheader("Meal Suggestions (Based on Goals and Food Database)")

# I have an sheet for food calories and if I put into the main file it will pop up with it
DEFAULT_FOOD_CSV = "Food_and_Calories_Sheet1.csv"

# This is a default value
food_df = None
try:
    food_df = load_foods(DEFAULT_FOOD_CSV)
    st.caption(f"Default food list loaded: {DEFAULT_FOOD_CSV}")
except Exception as e:
    st.error(f"Failed to load default list: {e}")

# Here is the let user to upload their file to check what recommendations they want
uploaded = st.file_uploader("Upload your data CSV", type="csv")
if uploaded is not None:
    try:
        food_df = load_foods(uploaded)
        st.success("User-defined food list loaded!")
    except Exception as e:
        st.error(f"Failed to load user food list: {e}")

# check the file is not empty 
if food_df is not None and not food_df.empty:
    with st.expander("Review the list/dignosis (top 20)"):
        st.write({
            "rows_in": int(food_df.attrs.get("rows_in", -1)),
            "rows_after_kcal": int(food_df.attrs.get("rows_after_kcal", -1)),
            "columns_mapped": food_df.attrs.get("columns_mapped", {}),
        })
        st.dataframe(food_df.head(20), use_container_width=True)

    # check daily target from get_goals, if not setting up it will use auto_goals 
    goals_now = db.get_goals(email) or auto_goals(db.get_profile(email))
    meal_k = st.number_input("Target Calories per Meal (kcal)", 200, 2000, int(max(200, (goals_now.get('kcal') or 1800)//3)))
    strategy = st.selectbox("Preference Strategy", ["balanced", "high_protein", "low_carb"], index=0)
    # display the recommendation from setting
    # here I set was 3 - 30
    topn = st.slider("Show Top Suggestions", 3, 30, 12)

    try:
        # recommendation 
        recs = suggest_meals(food_df, goals_now, meal_kcal=meal_k, strategy=strategy, topn=topn)
        if recs.empty:
            st.warning("No suggestions generated: The CSV may be missing required fields or calorie data.")
        else:
            st.dataframe(recs, use_container_width=True)
    except Exception as ex:
        st.error(f"An error occurred while generating suggestions: {ex}")
else:
    st.info("There is currently no available food list.")
