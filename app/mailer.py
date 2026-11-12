"""Send a reviewed preparedness brief only to the configured test inbox."""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage


def send_test_brief(subject: str, body: str) -> dict:
    inbox = os.environ.get("BRIEF_TEST_INBOX", "").strip()
    host = os.environ.get("SMTP_HOST", "").strip()
    if not inbox or not host:
        return {
            "sent": False,
            "status": "not_configured",
            "message": "Set BRIEF_TEST_INBOX and SMTP_HOST in .env, then restart Vela. The draft stays here.",
        }
    sender = os.environ.get("SMTP_FROM", "").strip() or inbox
    port = int(os.environ.get("SMTP_PORT", "587") or "587")
    username = os.environ.get("SMTP_USERNAME", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = inbox
    message.set_content(body)
    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls()
            if username:
                smtp.login(username, password)
            smtp.send_message(message)
    except Exception:
        return {
            "sent": False,
            "status": "request_failed",
            "message": "The test inbox could not be reached. The draft was not sent.",
        }
    return {"sent": True, "status": "sent", "inbox": inbox, "message": f"Sent to the test inbox {inbox}."}
