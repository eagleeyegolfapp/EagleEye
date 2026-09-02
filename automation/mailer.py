#!/usr/bin/env python3
"""Email a post summary to eagleeyegolfapp@gmail.com. Always writes a local report too."""
from __future__ import annotations

import os
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
TZ = ZoneInfo("America/New_York")


def write_report(subject: str, body: str) -> Path:
    folder = HERE / "logs" / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(TZ).strftime("%Y-%m-%d-%H%M%S")
    path = folder / f"{stamp}.txt"
    path.write_text(f"{subject}\n\n{body}\n")
    return path


def send_report(to_addr: str, subject: str, body: str) -> str:
    path = write_report(subject, body)
    user = (os.environ.get("GMAIL_USER") or os.environ.get("REPORT_EMAIL") or to_addr).strip()
    password = (os.environ.get("GMAIL_APP_PASSWORD") or "").strip()
    if not password:
        print("  email   skipped (no GMAIL_APP_PASSWORD) — report at", path)
        return "saved-local"
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(user, password)
        smtp.sendmail(user, [to_addr], msg.as_string())
    print("  email   sent to", to_addr)
    return "sent"
