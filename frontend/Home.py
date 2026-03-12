import streamlit as st
import sys
from pathlib import Path

st.set_page_config(
    page_title="Demurrage Analysis Application",
    page_icon="📊",
    layout="wide",
)

# Add frontend to path for lib
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.auth_api import (
    get_cookie_manager,
    restore_from_cookie,
    login,
    logout,
    register,
    forgot_password,
    reset_password,
    verify_email_token,
    resend_verification,
    get_current_user,
    is_authenticated,
)

ALLOWED_EMAIL_DOMAIN = "shippers.org.gh"

# Cookie-based auth so session survives reload and works on all pages
cookies = get_cookie_manager()
if not cookies.ready():
    st.stop()
# Restore session from cookie if we have a token (e.g. after reload or when opening Demurrage)
if not is_authenticated():
    restore_from_cookie(cookies)

# Handle email verification link (?verify=TOKEN) — show result in same run so it’s always visible
verify_token = st.query_params.get("verify")
if verify_token and not is_authenticated():
    ok, msg = verify_email_token(verify_token)
    if ok:
        st.success(msg)
    else:
        st.error(msg)
    if "verify" in st.query_params:
        del st.query_params["verify"]

# Handle password reset link (?reset=TOKEN) — show reset form below when not logged in
reset_token = st.query_params.get("reset")

if is_authenticated():
    # ----- Logged in: show app -----
    user = get_current_user()
    st.sidebar.title(f"Welcome, {user['full_name'] or user['username']}")
    st.sidebar.divider()
    st.sidebar.button("Logout", on_click=lambda: logout(cookies), key="logout_btn")

    col1, col2, col3 = st.columns([1.4, 1.2, 1])
    with col2:
        st.image(
            "https://shippers.org.gh/wp-content/uploads/2021/09/gsaLogo400x400.png",
            width=150,
        )
    st.markdown("<div style='text-align: center;'>", unsafe_allow_html=True)
    st.markdown(
        "<h1 style='text-align: center;'>Demurrage Analytics Dashboard</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='text-align: center; font-style: italic; font-size: 16px;'>Track and analyze container demurrage charges and port operations.</p>",
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

else:
    # ----- Not logged in: show login, register, forgot password, or reset password -----
    show_register = st.session_state.get("show_register", False)
    show_forgot = st.session_state.get("show_forgot_password", False)

    # Reset password form when ?reset=TOKEN is present
    if reset_token:
        st.markdown("## Set new password")
        st.caption("Enter your new password below. The link from your email is valid for 1 hour.")
        with st.form("reset_password_form"):
            new_pass = st.text_input("New password", type="password", help="At least 8 characters")
            confirm = st.text_input("Confirm new password", type="password")
            sub = st.form_submit_button("Update password")
        if sub:
            if not new_pass or not confirm:
                st.error("Please fill in both fields.")
            elif len(new_pass) < 8:
                st.error("Password must be at least 8 characters.")
            elif new_pass != confirm:
                st.error("Passwords do not match.")
            else:
                ok, msg = reset_password(reset_token, new_pass)
                if ok:
                    st.success(msg)
                    st.session_state.pop("show_register", None)
                    st.session_state.pop("show_forgot_password", None)
                    if "reset" in st.query_params:
                        del st.query_params["reset"]
                    st.rerun()
                else:
                    st.error(msg)
        st.divider()
        if st.button("← Back to sign in", key="back_from_reset"):
            if "reset" in st.query_params:
                del st.query_params["reset"]
            st.rerun()
    elif show_register:
        st.markdown("## Create an account")
        st.caption("Register with your @{} email.".format(ALLOWED_EMAIL_DOMAIN))
        st.button("← Back to sign in", on_click=lambda: st.session_state.update(show_register=False), key="back_to_login")
        st.divider()

        with st.form("register_form"):
            full_name = st.text_input("Full name", placeholder="Jane Doe", max_chars=100)
            email = st.text_input(
                "Email",
                placeholder="name@{}".format(ALLOWED_EMAIL_DOMAIN),
                max_chars=100,
                help="Only @{} addresses can register.".format(ALLOWED_EMAIL_DOMAIN),
            )
            username = st.text_input("Username", placeholder="jdoe", max_chars=50, help="3–50 characters: letters, numbers, . _ -")
            password = st.text_input("Password", type="password", help="At least 8 characters")
            confirm = st.text_input("Confirm password", type="password")
            submitted = st.form_submit_button("Register")

        if submitted:
            if not all([full_name, email, username, password]):
                st.error("Please fill in all fields.")
            elif password != confirm:
                st.error("Passwords do not match.")
            elif len(password) < 8:
                st.error("Password must be at least 8 characters.")
            else:
                email_clean = email.strip().lower()
                if not email_clean.endswith("@" + ALLOWED_EMAIL_DOMAIN):
                    st.error("Only @{} email addresses can register.".format(ALLOWED_EMAIL_DOMAIN))
                else:
                    ok, msg = register(username.strip(), email.strip(), full_name.strip(), password, cookies=cookies)
                    if ok:
                        st.session_state["pending_verify_email"] = email.strip().lower()
                        st.success(msg)
                        st.balloons()
                        st.session_state["show_register"] = False
                        st.rerun()
                    else:
                        st.error(msg)
    elif show_forgot:
        st.markdown("## Forgot password")
        st.caption("Enter your email and we’ll send you a link to reset your password.")
        st.button("← Back to sign in", on_click=lambda: st.session_state.update(show_forgot_password=False), key="back_from_forgot")
        st.divider()
        with st.form("forgot_password_form"):
            email = st.text_input("Email", placeholder="you@{}".format(ALLOWED_EMAIL_DOMAIN))
            sub = st.form_submit_button("Send reset link")
        if sub:
            if not email or not email.strip():
                st.error("Please enter your email.")
            else:
                ok, msg = forgot_password(email.strip())
                if ok:
                    st.info(msg)
                else:
                    st.error(msg)
    else:
        st.markdown("## Demurrage Analytics Dashboard")
        st.caption("Sign in to continue.")

        with st.form("login_form"):
            username_or_email = st.text_input(
                "Username or email",
                placeholder="Enter username or email",
            )
            password = st.text_input("Password", type="password", placeholder="Enter password")
            submitted = st.form_submit_button("Sign in")

        if submitted:
            if not username_or_email or not password:
                st.error("Please enter username/email and password.")
            else:
                ok, msg = login(username_or_email.strip(), password, cookies=cookies)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

        st.divider()
        st.button("Don't have an account? Register here", key="go_register", on_click=lambda: st.session_state.update(show_register=True))
        st.button("Forgot password?", key="go_forgot", on_click=lambda: st.session_state.update(show_forgot_password=True))

        # Post-register: show "verify your email" and resend (when we have pending_verify_email and not showing register)
        pending_email = st.session_state.get("pending_verify_email")
        if pending_email:
            st.divider()
            st.info("Check your inbox for the verification link. You can sign in after verifying.")
            if st.button("Resend verification email", key="resend_verify"):
                ok, msg = resend_verification(pending_email)
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)
