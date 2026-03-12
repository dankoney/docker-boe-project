"""
Send emails via Gmail SMTP.
Set SMTP_USER (Gmail address) and SMTP_PASSWORD (App Password) in env.
"""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

SMTP_USER = os.environ.get("SMTP_USER", os.environ.get("GMAIL_USER", ""))
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", os.environ.get("GMAIL_APP_PASSWORD", ""))
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
FROM_LABEL = os.environ.get("SMTP_FROM_LABEL", "Demurrage Analytics")


def send_email(to: str, subject: str, body_html: str, body_text: str = None):
    """Send an email. Returns (True, None) on success, (False, error_message) on failure."""
    if not SMTP_USER or not SMTP_PASSWORD:
        return False, "SMTP_USER and SMTP_PASSWORD (or GMAIL_USER and GMAIL_APP_PASSWORD) are not set"
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{FROM_LABEL} <{SMTP_USER}>"
        msg["To"] = to
        if body_text:
            msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, to, msg.as_string())
        return True, None
    except Exception as e:
        return False, str(e)


def send_test_email(to: str):
    """Send a test email to verify SMTP credentials. Returns (success: bool, error: str or None)."""
    subject = "Demurrage Analytics – email test"
    body_html = "<p>If you received this, SMTP is configured correctly.</p>"
    body_text = "If you received this, SMTP is configured correctly."
    return send_email(to, subject, body_html, body_text)


def send_verification_email(to: str, full_name: str, verify_link: str):
    subject = "Verify your email - Demurrage Analytics"
    body_html = f"""
    <p>Hi {full_name},</p>
    <p>Please verify your email by clicking the link below:</p>
    <p><a href="{verify_link}">{verify_link}</a></p>
    <p>This link expires in 24 hours.</p>
    <p>If you did not create an account, you can ignore this email.</p>
    """
    body_text = f"Hi {full_name},\n\nVerify your email: {verify_link}\n\nThis link expires in 24 hours."
    return send_email(to, subject, body_html, body_text)


def send_password_reset_email(to: str, full_name: str, reset_link: str):
    subject = "Reset your password - Demurrage Analytics"
    body_html = f"""
    <p>Hi {full_name},</p>
    <p>You requested a password reset. Click the link below to set a new password:</p>
    <p><a href="{reset_link}">{reset_link}</a></p>
    <p>This link expires in 1 hour.</p>
    <p>If you did not request this, you can ignore this email.</p>
    """
    body_text = f"Hi {full_name},\n\nReset your password: {reset_link}\n\nThis link expires in 1 hour."
    return send_email(to, subject, body_html, body_text)
