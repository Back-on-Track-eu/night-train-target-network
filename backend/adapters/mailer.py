"""
mailer.py
=========
Outbound email adapter — currently used only to notify the target-network
working group of a new feedback submission (see api/feedback.py).

Stateless by design: every call opens its own SMTP connection rather than
holding one open like ProposalRepository does for Postgres. Mail is sent
rarely (one feedback submission at a time) and a pooled connection would
add complexity without a measurable benefit.

Configuration is read from the environment on every call rather than
cached at import time, so a misconfigured deployment fails per-request
with a clear log line instead of at process startup — feedback storage
must not depend on mail being configured at all (see feedback_repository.py
and api/feedback.py: the DB insert always happens first, the mail send is
best-effort on top of it).

Required environment variables — see backend/docker/.env.example:
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM,
  FEEDBACK_NOTIFY_EMAIL
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_NOTIFY_EMAIL = "targetnetwork-wg@back-on-track.eu"


def _smtp_config() -> Optional[dict]:
    """Read SMTP_* env vars. Returns None (logging why) if any required
    value is missing, rather than raising — a missing mail config is an
    operational gap, not a request-level error; callers treat None as
    'could not send' and continue."""
    host = os.environ.get("SMTP_HOST")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    missing = [
        name
        for name, value in (
            ("SMTP_HOST", host),
            ("SMTP_USER", user),
            ("SMTP_PASSWORD", password),
        )
        if not value
    ]
    if missing:
        logger.warning(
            "Feedback mail not sent — missing SMTP env var(s): %s.", ", ".join(missing)
        )
        return None
    return {
        "host": host,
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "user": user,
        "password": password,
        "from_addr": os.environ.get("SMTP_FROM", user),
        "notify_addr": os.environ.get("FEEDBACK_NOTIFY_EMAIL", _DEFAULT_NOTIFY_EMAIL),
    }


def send_feedback_email(
    feedback_id: int,
    subject: str,
    message: str,
    category: str,
    sub_category: str,
    author_email: Optional[str],
    author_name: Optional[str],
) -> bool:
    """
    Send one feedback notification to FEEDBACK_NOTIFY_EMAIL
    (targetnetwork-wg@back-on-track.eu by default). Returns True on a
    confirmed send, False on any configuration or delivery failure —
    never raises, since a failed notification must not roll back the
    already-stored feedback row (see api/feedback.py).

    author_email, if given, is set as Reply-To so the working group can
    respond directly to the submitter.
    """
    config = _smtp_config()
    if config is None:
        return False

    author_line = author_name or author_email or "Anonymous (no email given)"
    body = (
        f"New feedback submitted on the Night Train Target Network tool.\n\n"
        f"Feedback ID:  {feedback_id}\n"
        f"From:         {author_line}\n"
        f"Category:     {category}\n"
        f"Sub-category: {sub_category}\n\n"
        f"{message}\n"
    )

    email = EmailMessage()
    email["Subject"] = f"[Feedback] {subject}"
    email["From"] = config["from_addr"]
    email["To"] = config["notify_addr"]
    if author_email:
        email["Reply-To"] = author_email
    email.set_content(body)

    try:
        with smtplib.SMTP(config["host"], config["port"], timeout=15) as smtp:
            smtp.starttls()
            smtp.login(config["user"], config["password"])
            smtp.send_message(email)
        logger.info("Feedback mail sent for feedback_id=%s.", feedback_id)
        return True
    except (smtplib.SMTPException, OSError) as e:
        logger.error("Feedback mail send failed for feedback_id=%s: %s", feedback_id, e)
        return False
