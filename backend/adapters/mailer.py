"""
mailer.py
=========
Outbound email adapter — feedback notifications to the working group
(see api/feedback.py) and OTP login codes (see api/auth.py).

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
            "Mail not sent — missing SMTP env var(s): %s.", ", ".join(missing)
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


# ---------------------------------------------------------------------------
# OTP login codes (api/auth.py)
# ---------------------------------------------------------------------------


def send_otp_email(to_address: str, otp: str) -> bool:
    """
    Send a one-time login code. Returns True on a confirmed send, False on
    any configuration or delivery failure — never raises, same contract as
    send_feedback_email(). Unlike feedback, the CALLER treats False as a
    request-level failure (502): an OTP that never arrives is a dead login,
    not a best-effort extra.

    Dev mode: AUTH_EMAIL_DEV_MODE=true logs the code at WARNING level
    instead of sending, so the full auth flow runs locally without SMTP.
    Never enable it on a public deployment.
    """
    if os.environ.get("AUTH_EMAIL_DEV_MODE", "").lower() == "true":
        logger.warning(
            "AUTH_EMAIL_DEV_MODE — OTP for %s: %s (not sent)", to_address, otp
        )
        return True

    config = _smtp_config()
    if config is None:
        return False

    email = EmailMessage()
    email["Subject"] = "Your Night Train Tool login code"
    email["From"] = config["from_addr"]
    email["To"] = to_address
    email.set_content(
        f"Your Night Train Tool login code\n\n"
        f"{otp}\n\n"
        f"This code expires in 15 minutes and can only be used once.\n\n"
        f"If you did not request this code, you can safely ignore this "
        f"email.\n\n"
        f"— Your Back-on-Track Target Network Team\n"
    )
    email.add_alternative(_render_otp_html(otp), subtype="html")

    try:
        with smtplib.SMTP(config["host"], config["port"], timeout=15) as smtp:
            smtp.starttls()
            smtp.login(config["user"], config["password"])
            smtp.send_message(email)
        logger.info("OTP mail sent to %s.", to_address)
        return True
    except (smtplib.SMTPException, OSError) as e:
        logger.error("OTP mail send failed for %s: %s", to_address, e)
        return False


def _render_otp_html(otp: str) -> str:
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Your login code</title>
</head>
<body style="margin:0;padding:0;background:#f5f0e8;font-family:'DM Sans',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f0e8;padding:40px 0;">
    <tr>
      <td align="center">
        <table width="480" cellpadding="0" cellspacing="0"
               style="background:#ffffff;border-radius:8px;overflow:hidden;">
          <tr>
            <td style="background:#1c3d2e;padding:28px 36px;">
              <p style="margin:0;color:#f5f0e8;font-size:18px;font-weight:600;
                        letter-spacing:0.02em;">
                Night Train Tool
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:36px 36px 28px;">
              <p style="margin:0 0 16px;color:#1c3d2e;font-size:15px;line-height:1.5;">
                Here is your login code:
              </p>
              <div style="margin:24px 0;text-align:center;">
                <span style="display:inline-block;padding:16px 40px;
                             background:#f5f0e8;border-radius:6px;
                             font-size:36px;font-weight:700;letter-spacing:0.18em;
                             color:#1c3d2e;font-family:'DM Mono',monospace;">
                  {otp}
                </span>
              </div>
              <p style="margin:24px 0 0;color:#555;font-size:13px;line-height:1.6;">
                This code expires in <strong>15 minutes</strong> and can only
                be used once.<br>
                If you did not request this code, you can safely ignore this email.
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 36px;border-top:1px solid #e8e2d9;">
              <p style="margin:0;color:#999;font-size:12px;">
                The Back-on-Track Team &nbsp;·&nbsp;
                <a href="https://back-on-track.eu"
                   style="color:#c8522a;text-decoration:none;">
                  back-on-track.eu
                </a>
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""
