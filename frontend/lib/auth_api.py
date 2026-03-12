"""
Auth helpers: call auth API, manage session in st.session_state, and persist token in cookie.
Cookie survives page reload and is available on all pages (Demurrage etc.).
Set API_BASE_URL in env (e.g. http://api:8000 in Docker).
"""
import os
import requests

API_BASE = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
API_BASE_FALLBACK = "http://127.0.0.1:8000"
SESSION_TOKEN_KEY = "auth_token"
SESSION_USER_KEY = "auth_user"
COOKIE_AUTH_KEY = "auth_token"
COOKIES_PASSWORD = os.environ.get("COOKIES_PASSWORD", "boe-auth-cookie-secret-change-in-production")
COOKIES_PREFIX = "boe/"


def get_cookie_manager():
    """Return the shared cookie manager (same prefix/password everywhere)."""
    from streamlit_cookies_manager import EncryptedCookieManager
    return EncryptedCookieManager(prefix=COOKIES_PREFIX, password=COOKIES_PASSWORD)


def _auth_bases():
    """Primary and fallback auth base URLs (without trailing slash)."""
    return (f"{API_BASE}/auth", f"{API_BASE_FALLBACK}/auth")


def _post_with_fallback(path_suffix: str, json_data: dict, timeout: int = 10):
    """POST to auth API; if primary fails with connection error, try fallback (e.g. localhost)."""
    primary, fallback = _auth_bases()
    last_err = None
    for base in (primary, fallback):
        try:
            return requests.post(f"{base}{path_suffix}", json=json_data, timeout=timeout)
        except requests.exceptions.RequestException as e:
            last_err = e
            continue
    if last_err:
        raise last_err
    return None


def _get_with_fallback(path_suffix: str, headers: dict, timeout: int = 5):
    """GET from auth API; if primary fails, try fallback."""
    primary, fallback = _auth_bases()
    last_err = None
    for base in (primary, fallback):
        try:
            return requests.get(f"{base}{path_suffix}", headers=headers, timeout=timeout)
        except requests.exceptions.RequestException as e:
            last_err = e
            continue
    if last_err:
        raise last_err
    return None


def _headers():
    token = _get_token()
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def _get_token():
    import streamlit as st
    return st.session_state.get(SESSION_TOKEN_KEY)


def set_session(token: str, user: dict, cookies=None):
    import streamlit as st
    st.session_state[SESSION_TOKEN_KEY] = token
    st.session_state[SESSION_USER_KEY] = user
    if cookies is not None:
        try:
            cookies[COOKIE_AUTH_KEY] = token
            cookies.save()
        except Exception:
            pass


def clear_session(cookies=None):
    import streamlit as st
    token = st.session_state.get(SESSION_TOKEN_KEY)
    if token:
        try:
            primary, fallback = _auth_bases()
            for base in (primary, fallback):
                try:
                    requests.post(f"{base}/logout", headers={"Authorization": f"Bearer {token}"}, timeout=5)
                    break
                except Exception:
                    continue
        except Exception:
            pass
    st.session_state.pop(SESSION_TOKEN_KEY, None)
    st.session_state.pop(SESSION_USER_KEY, None)
    if cookies is not None:
        try:
            if COOKIE_AUTH_KEY in cookies:
                del cookies[COOKIE_AUTH_KEY]
            cookies.save()
        except Exception:
            pass


def restore_from_cookie(cookies):
    """If not logged in but cookie has token, validate with API and set session. Returns True if restored."""
    import streamlit as st
    if is_authenticated():
        return True
    token = cookies.get(COOKIE_AUTH_KEY) if cookies else None
    if not token:
        return False
    try:
        r = _get_with_fallback("/me", headers={"Authorization": f"Bearer {token}"}, timeout=5)
        if r and r.status_code == 200:
            data = r.json()
            st.session_state[SESSION_TOKEN_KEY] = token
            st.session_state[SESSION_USER_KEY] = {
                "user_id": data["user_id"],
                "username": data["username"],
                "email": data["email"],
                "full_name": data["full_name"],
                "role": data.get("role", "user"),
            }
            return True
        if r and r.status_code == 401:
            try:
                if COOKIE_AUTH_KEY in cookies:
                    del cookies[COOKIE_AUTH_KEY]
                cookies.save()
            except Exception:
                pass
            return False
    except Exception:
        pass
    return False


def get_current_user():
    import streamlit as st
    return st.session_state.get(SESSION_USER_KEY)


def is_authenticated():
    return get_current_user() is not None


def register(username: str, email: str, full_name: str, password: str, cookies=None):
    """Register. Returns (success, message). Pass cookies to persist token across reloads."""
    try:
        r = _post_with_fallback(
            "/register",
            json_data={
                "username": username,
                "email": email,
                "full_name": full_name,
                "password": password,
            },
            timeout=10,
        )
        if r and r.status_code == 200:
            data = r.json()
            if data.get("require_verification"):
                return True, data.get("message", "Account created. Check your email to verify before signing in.")
            set_session(data["token"], {
                "user_id": data["user_id"],
                "username": data["username"],
                "email": data["email"],
                "full_name": data["full_name"],
                "role": data.get("role", "user"),
            }, cookies=cookies)
            return True, "Account created. You are now logged in."
        err = r.json().get("detail", r.text)
        if isinstance(err, list):
            err = err[0].get("msg", str(err))
        return False, str(err)
    except requests.exceptions.RequestException as e:
        return False, f"Connection error: {e}"


def _error_detail(r, fallback: str = "Something went wrong. Please try again."):
    """Extract user-facing error from API response. Handles detail as string or list (validation)."""
    if not r:
        return fallback
    try:
        data = r.json()
    except Exception:
        return fallback
    detail = data.get("detail")
    if detail is None:
        return fallback
    if isinstance(detail, list):
        for item in detail:
            if isinstance(item, dict) and "msg" in item:
                return str(item["msg"])
        return fallback
    return str(detail)


def login(username_or_email: str, password: str, cookies=None):
    """Login. Returns (success, message). Pass cookies to persist token across reloads."""
    try:
        r = _post_with_fallback(
            "/login",
            json_data={"username_or_email": username_or_email, "password": password},
            timeout=10,
        )
        if r is None:
            return False, "Could not reach the server. Please try again."
        if r.status_code == 200:
            data = r.json()
            set_session(data["token"], {
                "user_id": data["user_id"],
                "username": data["username"],
                "email": data["email"],
                "full_name": data["full_name"],
                "role": data.get("role", "user"),
            }, cookies=cookies)
            return True, "Welcome back."
        if r.status_code == 401:
            return False, "Invalid username or password."
        if r.status_code == 403:
            return False, _error_detail(r, "Access denied.")
        return False, _error_detail(r)
    except requests.exceptions.RequestException:
        return False, "Connection error. Please try again."




def logout(cookies=None):
    clear_session(cookies=cookies)


def forgot_password(email: str):
    """Request password reset. Returns (success, message). Always shows generic message for privacy."""
    try:
        r = _post_with_fallback("/forgot-password", json_data={"email": email}, timeout=10)
        if r and r.status_code == 200:
            data = r.json()
            return True, data.get("message", "If that email is registered, you will receive a reset link.")
        return False, (r.json().get("detail", r.text) if r else "Request failed")
    except requests.exceptions.RequestException as e:
        return False, f"Connection error: {e}"


def reset_password(token: str, new_password: str):
    """Set new password with reset token. Returns (success, message)."""
    try:
        r = _post_with_fallback(
            "/reset-password",
            json_data={"token": token, "new_password": new_password},
            timeout=10,
        )
        if r is None:
            return False, "Could not reach the server. Please try again."
        if r.status_code == 200:
            data = r.json()
            return True, data.get("message", "Password updated. You can sign in now.")
        if r.status_code == 400:
            return False, "This reset link is invalid or has already been used. Request a new link from Forgot password."
        return False, _error_detail(r)
    except requests.exceptions.RequestException:
        return False, "Connection error. Please try again."


def verify_email_token(token: str):
    """Verify email via token from link. Returns (success, message)."""
    try:
        primary, fallback = _auth_bases()
        last_err = None
        for base in (primary, fallback):
            try:
                r = requests.get(f"{base}/verify-email", params={"token": token}, timeout=10)
                if r and r.status_code == 200:
                    data = r.json()
                    return True, data.get("message", "Email verified. You can sign in now.")
                if r and r.status_code == 400:
                    return False, _error_detail(r, "This verification link is invalid or has already been used. Request a new one after signing in or from the resend option.")
                return False, _error_detail(r, "Verification failed. Please try again.")
            except requests.exceptions.RequestException as e:
                last_err = e
                continue
        return False, str(last_err) if last_err else "Connection error. Please try again."
    except Exception as e:
        return False, str(e)


def resend_verification(email: str):
    """Resend verification email. Returns (success, message)."""
    try:
        r = _post_with_fallback("/resend-verification", json_data={"email": email}, timeout=10)
        if r and r.status_code == 200:
            data = r.json()
            return True, data.get("message", "Verification email sent. Check your inbox.")
        return False, (r.json().get("detail", r.text) if r else "Request failed")
    except requests.exceptions.RequestException as e:
        return False, f"Connection error: {e}"


def test_email(to: str):
    """Send a test email to verify SMTP. Returns (success, message or error)."""
    try:
        r = _post_with_fallback("/test-email", json_data={"to": to}, timeout=15)
        if r and r.status_code == 200:
            data = r.json()
            if data.get("ok"):
                return True, data.get("message", "Test email sent.")
            return False, data.get("error", "Send failed")
        return False, (r.json().get("detail", r.text) if r else "Request failed")
    except requests.exceptions.RequestException as e:
        return False, f"Connection error: {e}"


def verify_session() -> bool:
    """If we have a token, validate it with API and refresh user. Returns True if valid.
    Only clears session on 401 (invalid/expired token); connection errors leave session intact.
    """
    import streamlit as st
    token = st.session_state.get(SESSION_TOKEN_KEY)
    if not token:
        return False
    try:
        r = _get_with_fallback("/me", headers={"Authorization": f"Bearer {token}"}, timeout=5)
        if r and r.status_code == 200:
            data = r.json()
            st.session_state[SESSION_USER_KEY] = {
                "user_id": data["user_id"],
                "username": data["username"],
                "email": data["email"],
                "full_name": data["full_name"],
                "role": data.get("role", "user"),
            }
            return True
        if r and r.status_code == 401:
            clear_session()
            return False
        # 5xx, no response, etc.: don't clear session, just return False
        return False
    except Exception:
        # Connection error etc.: keep existing session (user may still be logged in)
        return get_current_user() is not None
