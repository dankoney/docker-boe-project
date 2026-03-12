"""
Send a test email to verify SMTP credentials.
Loads .env from project root. Usage:
  python scripts/test_email.py
  python scripts/test_email.py someone@example.com

Requires: SMTP_USER and SMTP_PASSWORD (or GMAIL_USER and GMAIL_APP_PASSWORD) in .env
"""
import os
import sys

# Project root = parent of scripts/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Load .env from project root
env_file = os.path.join(ROOT, ".env")
if os.path.isfile(env_file):
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)
    except ImportError:
        pass

# Run from api dir so email_sender can be imported
api_dir = os.path.join(ROOT, "api")
os.chdir(api_dir)
sys.path.insert(0, api_dir)

from email_sender import send_test_email, SMTP_USER, SMTP_PASSWORD


def main():
    to = os.environ.get("TEST_EMAIL")
    if not to and len(sys.argv) > 1:
        to = sys.argv[1].strip()
    if not to:
        print("Usage: python scripts/test_email.py <email@example.com>")
        print("   or set TEST_EMAIL in .env")
        sys.exit(1)

    if not SMTP_USER or not SMTP_PASSWORD:
        print("ERROR: SMTP credentials not set.")
        print("Set SMTP_USER and SMTP_PASSWORD (or GMAIL_USER and GMAIL_APP_PASSWORD) in .env")
        sys.exit(1)

    print(f"Sending test email to {to}...")
    ok, err = send_test_email(to)
    if ok:
        print("OK – Test email sent. Check the inbox (and spam).")
    else:
        print("FAILED –", err)
        sys.exit(1)


if __name__ == "__main__":
    main()
