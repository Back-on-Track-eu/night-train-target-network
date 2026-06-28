"""
email_sender.py
===============
Sends OTP emails via the Resend API.

Dev mode
--------
If RESEND_API_KEY is set to "dev", no real email is sent. The OTP is
printed to the application log at INFO level instead. This lets the full
auth flow run locally without a Resend account or real email address.

Usage
-----
    from api.email_sender import send_otp_email

    send_otp_email("user@example.com", "482917")

Raises
------
    EmailError  — on any delivery failure (Resend API error, network issue,
                  missing config). The auth route handler catches this and
                  returns a 502 to the client.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_DEV_KEY = "dev"


class EmailError(Exception):
    """Raised when OTP email delivery fails."""
    pass


def send_otp_email(to_address: str, otp: str) -> None:
    """
    Send a one-time login code to the given email address.

    In dev mode (RESEND_API_KEY=dev), logs the OTP instead of sending.
    In production, calls the Resend API.

    Parameters
    ----------
    to_address : str   Recipient email address.
    otp        : str   6-digit OTP code to include in the email.

    Raises
    ------
    EmailError on any failure.
    """
    api_key      = os.environ.get("RESEND_API_KEY", "")
    from_address = os.environ.get("RESEND_FROM_ADDRESS", "")

    if not api_key:
        raise EmailError(
            "RESEND_API_KEY is not set. Check your .env file."
        )

    # ── Dev mode ─────────────────────────────────────────────────────────────
    if api_key == _DEV_KEY:
        logger.info(
            "DEV MODE — OTP for %s: %s  (not sent, RESEND_API_KEY=dev)",
            to_address,
            otp,
        )
        return

    # ── Production ───────────────────────────────────────────────────────────
    if not from_address:
        raise EmailError(
            "RESEND_FROM_ADDRESS is not set. Check your .env file."
        )

    try:
        import resend
    except ImportError:
        raise EmailError(
            "resend package is not installed. Run: uv add resend"
        )

    resend.api_key = api_key

    subject  = "Your Night Train Tool login code"
    html_body = _render_email_html(otp)
    text_body = _render_email_text(otp)

    try:
        response = resend.Emails.send({
            "from":    from_address,
            "to":      [to_address],
            "subject": subject,
            "html":    html_body,
            "text":    text_body,
        })
        logger.info("OTP email sent to %s (id: %s)", to_address, response.get("id"))
    except Exception as e:
        logger.error("Failed to send OTP email to %s: %s", to_address, e)
        raise EmailError(f"Email delivery failed: {e}") from e


# ---------------------------------------------------------------------------
# Email templates
# ---------------------------------------------------------------------------

def _render_email_text(otp: str) -> str:
    return f"""\
Your Night Train Tool login code

{otp}

This code expires in 15 minutes and can only be used once.

If you did not request this code, you can safely ignore this email.

— Your Back-on-Track Target Network Team
"""


def _render_email_html(otp: str) -> str:
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

          <!-- Header -->
          <tr>
            <td style="background:#1c3d2e;padding:28px 36px;">
              <p style="margin:0;color:#f5f0e8;font-size:18px;font-weight:600;
                        letter-spacing:0.02em;">
                Night Train Tool
              </p>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:36px 36px 28px;">
              <p style="margin:0 0 16px;color:#1c3d2e;font-size:15px;line-height:1.5;">
                Here is your login code:
              </p>

              <!-- OTP box -->
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

          <!-- Footer -->
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