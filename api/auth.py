"""
Authentication: register, login, logout, session (me), email verification, password reset.
Uses PostgreSQL users, user_sessions, email_verification_tokens, password_reset_tokens.
"""
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
import bcrypt
import psycopg2.extras
from fastapi import APIRouter, HTTPException, Header, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from db_connect import get_api_connection
from email_sender import send_verification_email, send_password_reset_email, send_test_email

router = APIRouter(prefix="/auth", tags=["auth"])

SESSION_DAYS = int(os.environ.get("AUTH_SESSION_DAYS", "30"))
VERIFY_TOKEN_HOURS = 24
RESET_TOKEN_HOURS = 1
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8501").rstrip("/")
# Only allow registration with this email domain (case-insensitive)
ALLOWED_EMAIL_DOMAIN = os.environ.get("ALLOWED_EMAIL_DOMAIN", "shippers.org.gh").strip().lower()
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,50}$")


# --- Pydantic models ---
class RegisterRequest(BaseModel):
    username: str
    email: str
    full_name: str
    password: str

    @field_validator("username")
    @classmethod
    def username_alphanumeric(cls, v: str) -> str:
        if not USERNAME_RE.match(v):
            raise ValueError("Username must be 3–50 chars: letters, numbers, . _ -")
        return v.strip().lower()

    @field_validator("password")
    @classmethod
    def password_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("full_name")
    @classmethod
    def strip_full_name(cls, v: str) -> str:
        return v.strip() if v else v

    @field_validator("email")
    @classmethod
    def email_domain(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if not v:
            raise ValueError("Email is required")
        if not v.count("@") == 1:
            raise ValueError("Invalid email format")
        local, domain = v.rsplit("@", 1)
        if domain != ALLOWED_EMAIL_DOMAIN:
            raise ValueError(f"Only @{ALLOWED_EMAIL_DOMAIN} email addresses can register")
        return v


class LoginRequest(BaseModel):
    username_or_email: str
    password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class ResendVerificationRequest(BaseModel):
    email: str


class TestEmailRequest(BaseModel):
    to: str


class AuthResponse(BaseModel):
    token: str
    user_id: int
    username: str
    email: str
    full_name: str
    role: str


class MeResponse(BaseModel):
    user_id: int
    username: str
    email: str
    full_name: str
    role: str


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def _check_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def _create_session(conn, user_id: int) -> str:
    token_jti = str(uuid.uuid4())
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO user_sessions (user_id, token_jti, expires_at)
            VALUES (%s, %s, %s)
            """,
            (user_id, token_jti, expires),
        )
    conn.commit()
    return token_jti


@router.post("/register", response_model=AuthResponse)
def register(body: RegisterRequest):
    """Register a new user. Returns session token and user info."""
    conn = None
    try:
        conn = get_api_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                "SELECT id FROM users WHERE username = %s OR email = %s",
                (body.username, body.email.strip().lower()),
            )
            if cur.fetchone():
                raise HTTPException(status_code=400, detail="Username or email already registered")

            password_hash = _hash_password(body.password)
            email_lower = body.email.strip().lower()
            full_name = body.full_name.strip()
            cur.execute(
                """
                INSERT INTO users (username, email, password_hash, full_name, role, is_active, is_verified)
                VALUES (%s, %s, %s, %s, 'user', true, false)
                RETURNING id, username, email, full_name, role
                """,
                (body.username, email_lower, password_hash, full_name),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=500, detail="Insert failed")
            user_id = row["id"]
            # Create verification token and send email
            verify_token = str(uuid.uuid4())
            expires = datetime.now(timezone.utc) + timedelta(hours=VERIFY_TOKEN_HOURS)
            cur.execute(
                "INSERT INTO email_verification_tokens (user_id, token, expires_at) VALUES (%s, %s, %s)",
                (user_id, verify_token, expires),
            )
        verify_link = f"{APP_BASE_URL}/?verify={verify_token}"
        ok, err = send_verification_email(email_lower, full_name, verify_link)
        if not ok:
            import logging
            logging.warning("Failed to send verification email to %s: %s", email_lower, err)
        conn.commit()
        # Do not create session until email is verified
        return JSONResponse(
            status_code=200,
            content={
                "message": "Account created. Check your email to verify before signing in.",
                "require_verification": True,
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()


@router.post("/login", response_model=AuthResponse)
def login(body: LoginRequest):
    """Login with username or email and password. Returns session token and user info."""
    conn = None
    try:
        conn = get_api_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            key = body.username_or_email.strip().lower()
            cur.execute(
                """
                SELECT id, username, email, full_name, role, password_hash, is_active,
                       is_verified, locked_until
                FROM users
                WHERE LOWER(username) = %s OR LOWER(email) = %s
                """,
                (key, key),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=401, detail="Invalid username or password")

            if not row["is_active"]:
                raise HTTPException(status_code=403, detail="Account is deactivated")
            if not row.get("is_verified", True):
                raise HTTPException(
                    status_code=403,
                    detail="Email not verified. Check your inbox for the verification link or request a new one.",
                )

            locked = row.get("locked_until")
            if locked and locked > datetime.now(locked.tzinfo or timezone.utc):
                raise HTTPException(status_code=403, detail="Account temporarily locked")

            if not _check_password(body.password, row["password_hash"]):
                raise HTTPException(status_code=401, detail="Invalid username or password")

            user_id = row["id"]
            cur.execute(
                "UPDATE users SET last_login = %s, failed_login_attempts = 0 WHERE id = %s",
                (datetime.now(timezone.utc), user_id),
            )
        conn.commit()
        token_jti = _create_session(conn, user_id)
        return AuthResponse(
            token=token_jti,
            user_id=user_id,
            username=row["username"],
            email=row["email"],
            full_name=row["full_name"],
            role=row["role"] or "user",
        )
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()


@router.post("/forgot-password")
def forgot_password(body: ForgotPasswordRequest):
    """Send password reset email if the address is registered. Always return 200 to avoid email enumeration."""
    conn = None
    try:
        conn = get_api_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            email = body.email.strip().lower()
            cur.execute("SELECT id, full_name FROM users WHERE LOWER(email) = %s AND is_active = true", (email,))
            row = cur.fetchone()
            if not row:
                return {"message": "If that email is registered, you will receive a reset link."}
            user_id, full_name = row["id"], row["full_name"] or "User"
            token = str(uuid.uuid4())
            expires = datetime.now(timezone.utc) + timedelta(hours=RESET_TOKEN_HOURS)
            cur.execute(
                "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (%s, %s, %s)",
                (user_id, token, expires),
            )
        conn.commit()
        reset_link = f"{APP_BASE_URL}/?reset={token}"
        ok, err = send_password_reset_email(email, full_name, reset_link)
        if not ok:
            import logging
            logging.warning("Failed to send password reset email to %s: %s", email, err)
        return {"message": "If that email is registered, you will receive a reset link."}
    except Exception:
        if conn:
            conn.rollback()
        return {"message": "If that email is registered, you will receive a reset link."}
    finally:
        if conn:
            conn.close()


@router.post("/reset-password")
def reset_password(body: ResetPasswordRequest):
    """Set new password using a valid reset token."""
    conn = None
    try:
        conn = get_api_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """
                SELECT prt.user_id FROM password_reset_tokens prt
                WHERE prt.token = %s AND prt.expires_at > %s AND prt.used_at IS NULL
                """,
                (body.token, datetime.now(timezone.utc)),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=400, detail="Invalid or expired reset link. Request a new one.")
            user_id = row["user_id"]
            password_hash = _hash_password(body.new_password)
            cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (password_hash, user_id))
            cur.execute(
                "UPDATE password_reset_tokens SET used_at = %s WHERE token = %s",
                (datetime.now(timezone.utc), body.token),
            )
        conn.commit()
        return {"message": "Password updated. You can sign in now."}
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()


@router.get("/verify-email")
def verify_email(token: str = Query(..., description="Verification token from email")):
    """Mark user as verified when they click the link in the verification email."""
    conn = None
    try:
        conn = get_api_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """
                SELECT evt.user_id FROM email_verification_tokens evt
                WHERE evt.token = %s AND evt.expires_at > %s AND evt.used_at IS NULL
                """,
                (token, datetime.now(timezone.utc)),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=400, detail="Invalid or expired verification link. Request a new one.")
            user_id = row["user_id"]
            cur.execute("UPDATE users SET is_verified = true WHERE id = %s", (user_id,))
            cur.execute(
                "UPDATE email_verification_tokens SET used_at = %s WHERE token = %s",
                (datetime.now(timezone.utc), token),
            )
        conn.commit()
        return {"message": "Email verified. You can sign in now."}
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()


@router.post("/resend-verification")
def resend_verification(body: ResendVerificationRequest):
    """Send a new verification email."""
    conn = None
    try:
        conn = get_api_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            email_lower = body.email.strip().lower()
            cur.execute(
                "SELECT id, full_name, is_verified FROM users WHERE LOWER(email) = %s AND is_active = true",
                (email_lower,),
            )
            row = cur.fetchone()
            if not row:
                return {"message": "If that email is registered, you will receive a verification link."}
            if row["is_verified"]:
                return {"message": "This email is already verified. You can sign in."}
            user_id, full_name = row["id"], row["full_name"] or "User"
            token = str(uuid.uuid4())
            expires = datetime.now(timezone.utc) + timedelta(hours=VERIFY_TOKEN_HOURS)
            cur.execute(
                "INSERT INTO email_verification_tokens (user_id, token, expires_at) VALUES (%s, %s, %s)",
                (user_id, token, expires),
            )
        conn.commit()
        verify_link = f"{APP_BASE_URL}/?verify={token}"
        ok, err = send_verification_email(email_lower, full_name, verify_link)
        if not ok:
            import logging
            logging.warning("Failed to resend verification email to %s: %s", email_lower, err)
        return {"message": "Verification email sent. Check your inbox."}
    except Exception:
        if conn:
            conn.rollback()
        return {"message": "If that email is registered, you will receive a verification link."}
    finally:
        if conn:
            conn.close()


# Hidden from users; uncomment to re-enable SMTP test from API (e.g. POST /auth/test-email)
# @router.post("/test-email")
# def test_email(body: TestEmailRequest):
#     """Send a test email to verify SMTP credentials."""
#     to = body.to.strip()
#     if not to:
#         raise HTTPException(status_code=400, detail="Email address required")
#     ok, err = send_test_email(to)
#     if ok:
#         return {"ok": True, "message": "Test email sent. Check the inbox (and spam)."}
#     return {"ok": False, "error": err or "Failed to send"}


@router.post("/logout")
def logout(
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    """Invalidate the current session (token)."""
    jti = token or (authorization.replace("Bearer ", "").strip() if authorization else None)
    if not jti:
        return {"message": "No token provided"}
    conn = None
    try:
        conn = get_api_connection()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_sessions WHERE token_jti = %s", (jti,))
        conn.commit()
        return {"message": "Logged out"}
    finally:
        if conn:
            conn.close()


@router.get("/me", response_model=MeResponse)
def me(
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    """Return current user info if the session token is valid."""
    jti = token or (authorization.replace("Bearer ", "").strip() if authorization else None)
    if not jti:
        raise HTTPException(status_code=401, detail="Not authenticated")
    conn = None
    try:
        conn = get_api_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """
                SELECT u.id, u.username, u.email, u.full_name, u.role
                FROM users u
                JOIN user_sessions s ON s.user_id = u.id
                WHERE s.token_jti = %s AND s.expires_at > %s AND u.is_active = true
                """,
                (jti, datetime.now(timezone.utc)),
            )
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Invalid or expired session")
        return MeResponse(
            user_id=row["id"],
            username=row["username"],
            email=row["email"],
            full_name=row["full_name"],
            role=row["role"] or "user",
        )
    finally:
        if conn:
            conn.close()
