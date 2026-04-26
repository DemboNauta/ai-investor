"""Prueba solo el envío de email."""
import smtplib
import os
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", SMTP_USER)

print(f"SMTP: {SMTP_HOST}:{SMTP_PORT} | user={SMTP_USER}")

msg = MIMEText("Email de prueba desde AI Investor VPS. Todo OK.")
msg["Subject"] = "AI Investor — Test email"
msg["From"] = SMTP_USER
msg["To"] = NOTIFY_EMAIL

try:
    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, NOTIFY_EMAIL, msg.as_string())
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, NOTIFY_EMAIL, msg.as_string())
    print(f"OK — email enviado a {NOTIFY_EMAIL}")
except Exception as e:
    print(f"ERROR — {e}")
