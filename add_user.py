"""
VibePitch — Add New User Script
================================
Run this when you've verified a payment.
It generates a unique password, adds the user to users.txt,
and sends them their login details via email.

Usage:
  python add_user.py

It will ask you for their email and plan interactively.
"""

import random
import string
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

USERS_FILE = "users.txt"

# ── Your SMTP details (same as in the app) ──
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = os.getenv("SMTP_USER", "your@gmail.com")   # set in .env
SMTP_PASS = os.getenv("SMTP_PASS", "")                 # App Password
FROM_NAME = "VibePitch"
APP_URL   = "https://vibepitch-b2b-mtk.streamlit.app"


def generate_password() -> str:
    """Generate a unique password like VIBE-A3K9-XP2M"""
    chars = string.ascii_uppercase + string.digits
    part1 = ''.join(random.choices(chars, k=4))
    part2 = ''.join(random.choices(chars, k=4))
    return f"VIBE-{part1}-{part2}"


def user_exists(email: str) -> bool:
    if not os.path.exists(USERS_FILE):
        return False
    with open(USERS_FILE, "r") as f:
        for line in f:
            if line.strip().startswith("#") or not line.strip():
                continue
            if line.split(",")[0].strip().lower() == email.lower():
                return True
    return False


def add_user(email: str, password: str, plan: str):
    with open(USERS_FILE, "a") as f:
        f.write(f"{email.lower()},{password},{plan}\n")
    print(f"✅ Added {email} to users.txt")


def send_welcome_email(email: str, password: str, plan: str):
    msg = MIMEMultipart()
    msg["Subject"] = "⚡ Your VibePitch Access is Ready!"
    msg["From"]    = f"{FROM_NAME} <{SMTP_USER}>"
    msg["To"]      = email

    body = f"""Hi there,

Your payment has been verified and your VibePitch account is now active!

Here are your login details:

  App URL  : {APP_URL}
  Email    : {email}
  Password : {password}
  Plan     : {plan.title()}

Go to the app, enter your email and password, and start pitching sponsors.

If you have any issues, just reply to this email.

Welcome aboard,
Manish
VibePitch
"""
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, email, msg.as_string())
        print(f"📧 Welcome email sent to {email}")
    except Exception as e:
        print(f"❌ Email failed: {e}")
        print(f"   Send manually: Email={email}, Password={password}, Plan={plan}")


def main():
    print("\n⚡ VibePitch — Add New User")
    print("─" * 35)

    email = input("Customer Email: ").strip().lower()
    if not email:
        print("❌ Email cannot be empty.")
        return

    if user_exists(email):
        print(f"⚠️  {email} already exists in users.txt")
        return

    print("Plan options: growth / pro")
    plan = input("Plan: ").strip().lower()
    if plan not in ["growth", "pro"]:
        print("❌ Invalid plan. Enter 'growth' or 'pro'.")
        return

    password = generate_password()
    print(f"\n Generated Password: {password}")

    add_user(email, password, plan)
    send_welcome_email(email, password, plan)

    print(f"\n✅ Done! {email} can now log in with password {password}")
    print("   Remember to: git add users.txt && git commit -m 'add user' && git push --force\n")


if __name__ == "__main__":
    main()