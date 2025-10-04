from __future__ import annotations
import streamlit as st
from db import DB
from utils import validate_email, strong_password


def render_auth(db: DB) -> None:
    st.title("HealthyLife — User Page")
    tab_login, tab_register = st.tabs(["Log in", "Registered"])

    with tab_login:
        with st.form("login"):
            email = st.text_input("Email")
            pw = st.text_input("Password", type="password")
            ok = st.form_submit_button("Log in")
        if ok:
            email_n = (email or "").lower().strip()
            if db.verify_user(email_n, pw):
                st.session_state.current_user = email_n
                st.success("Log in successfully!")
                st.rerun()
            else:
                st.error("Invalid username or password.")

    with tab_register:
        with st.form("register"):
            name = st.text_input("Name (can be empty)")
            email = st.text_input("Email")
            pw = st.text_input("Password (at least 8 characters, including words and numbers)", type="password")
            ok = st.form_submit_button("Create an Account")
        if ok:
            email_n = (email or "").lower().strip()
            if not validate_email(email_n):
                st.error("Please enter a valid email address.")
            else:
                ok_pw, why = strong_password(pw)
                if not ok_pw:
                    st.error(why)
                else:
                    err = db.create_user(email_n, pw, name)
                    if err:
                        st.error(err)
                    else:
                        st.success("Registration completed, please log in.")
