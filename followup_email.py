from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from typing import Tuple


def is_followup_email_enabled() -> bool:
    return os.environ.get("FOLLOWUP_EMAIL_ENABLED", "").strip() == "1"


def _smtp_port() -> int:
    raw = os.environ.get("SMTP_PORT", "587").strip()
    try:
        return int(raw)
    except ValueError:
        return 587


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return raw == "1"


def send_followup_email(*, to_email: str, to_name: str, subject: str, body: str) -> Tuple[bool, str]:
    if not is_followup_email_enabled():
        return False, "FOLLOWUP_EMAIL_ENABLED is not enabled"

    host = os.environ.get("SMTP_HOST", "").strip()
    from_email = os.environ.get("SMTP_FROM_EMAIL", "").strip()
    if not host or not from_email:
        return False, "SMTP_HOST or SMTP_FROM_EMAIL is missing"

    from_name = os.environ.get("SMTP_FROM_NAME", "").strip() or "魂のナビ診断"
    smtp_user = os.environ.get("SMTP_USER", "").strip()
    smtp_pass = os.environ.get("SMTP_PASS", "").strip()
    reply_to = os.environ.get("SMTP_REPLY_TO", "").strip()
    timeout_sec = float(os.environ.get("SMTP_TIMEOUT_SEC", "15").strip() or "15")
    port = _smtp_port()
    use_ssl = _bool_env("SMTP_USE_SSL", False)
    use_starttls = _bool_env("SMTP_USE_STARTTLS", True)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to_email.strip()
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=timeout_sec) as server:
                if smtp_user:
                    server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=timeout_sec) as server:
                server.ehlo()
                if use_starttls:
                    server.starttls()
                    server.ehlo()
                if smtp_user:
                    server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        return True, "sent"
    except Exception as exc:  # pragma: no cover
        name = to_name.strip() if to_name else ""
        suffix = f" ({name})" if name else ""
        return False, f"send failed for {to_email}{suffix}: {type(exc).__name__}: {exc}"
