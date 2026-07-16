"""
test_auth_chain.py
===================
Manual test script for the full local-plane auth chain:

  POST /api/auth/request-code  — register/login, triggers an OTP email
  POST /api/auth/verify        — verify the OTP, get a JWT
  POST /api/feedback           — submit feedback AS that authenticated user
                                  (bearer token overrides body user_id/email
                                  — see api/feedback.py)

Note this is a one-time CODE, not a clickable magic link: the endpoint
takes {email, code} in the request body (api/auth.py::verify). There is
no link to click — you read the 6-digit code out of the email and type
it in. (The original stub docstring said "OTP / magic-link JWT" as a
placeholder for two possible designs; only the OTP-code path got built.)

Usage:
    python scripts/test_auth_chain.py [command] [--email EMAIL] [--name NAME]

    command : chain | guest | request-code | verify | all
              (default: chain)

  chain          Full flow: request-code -> verify -> authenticated feedback.
                 Sends a REAL email via SMTP_* (see docker/.env.example) to
                 --email, so it exercises actual mail delivery. The script
                 pauses and asks you to paste the code you received by
                 email. If AUTH_EMAIL_DEV_MODE=true is set instead, it will
                 try to read the code from the backend-api container logs
                 automatically (no real mail sent) — otherwise it always
                 falls back to a manual prompt.
  guest          POST /api/auth/guest only — prints the guest token/identity.
                 --email/--name are ignored (guest sessions carry neither).
  request-code   POST /api/auth/request-code only (no verify/feedback).
  verify         POST /api/auth/verify only — prompts for the code
                 (uses --email, or asks if not given).
  all            Runs chain, then guest, back to back.

--email / --name (or the AUTH_EMAIL / AUTH_NAME env vars, same order of
precedence — CLI flag wins over env var wins over the built-in default):
    --email      a REAL inbox; the code is sent there for real when
                 AUTH_EMAIL_DEV_MODE is off (or unset). Check spam if it
                 doesn't arrive quickly. Default: davidj.wedekind@gmail.com
    --name       display_name for first-time registration only; ignored
                 on subsequent logins with the same email (see
                 api/auth.py::request_code). Default: david123

Examples:
    python scripts/test_auth_chain.py chain
    python scripts/test_auth_chain.py chain --email me@example.com --name railfan42
    python scripts/test_auth_chain.py request-code --email me@example.com --name railfan42
    python scripts/test_auth_chain.py verify --email me@example.com

Pre-flight:
  1. Checks Flask API is reachable.
  2. Warns if SMTP_* looks unconfigured (request-code would 502) unless
     AUTH_EMAIL_DEV_MODE is on.

Note: this actually creates an admin.users row for --email (first run) and
an admin.feedback row on every 'chain'/'all' run — not test-isolated like
tests/test_70_auth_api.py. Feedback rows are tagged with a
'MANUAL_TEST_AUTH_CHAIN_' subject prefix so they're easy to find and
remove manually afterwards if needed. Re-running 'chain' with the same
--email logs the existing user back in (request-code/verify treat an
existing email as login, not re-registration — see api/auth.py).
"""

import argparse
import json
import os
import subprocess
import sys
import time

import requests

API_BASE = "http://localhost:5000"
CONTAINER_NAME = "backend-api"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "data")

SUBJECT_PREFIX = "MANUAL_TEST_AUTH_CHAIN_"

# Fallback defaults if neither --email/--name nor AUTH_EMAIL/AUTH_NAME are
# given — see parse_args() for the full precedence order.
_FALLBACK_EMAIL = "davidj.wedekind@gmail.com"
_FALLBACK_NAME = "david123"


# =============================================================================
# PRE-FLIGHT CHECKS
# =============================================================================


def check_flask():
    print("[ ] Checking Flask API...")
    try:
        r = requests.get(f"{API_BASE}/api/health", timeout=3)
        if r.status_code == 200:
            print("[\u2713] Flask API is running.")
            return True
    except requests.ConnectionError:
        pass
    print(
        "[\u2717] Flask API not reachable at localhost:5000. "
        "Start the stack first (docker-compose up)."
    )
    return False


def check_smtp_configured(email: str):
    """
    Best-effort local hint only — the script has no way to read the API
    container's environment directly, so this can't be a hard check. Just
    reminds you what to look at if request-code comes back 502.
    """
    dev_mode = os.environ.get("AUTH_EMAIL_DEV_MODE", "").lower() == "true"
    if dev_mode:
        print(
            "[i] AUTH_EMAIL_DEV_MODE=true in THIS shell's env — but what "
            "matters is the backend-api container's own .env. If that "
            "container has dev mode on, no real email will be sent even "
            "though --email looks like a real address."
        )
    else:
        print(
            f"[i] Expecting a REAL email to {email} (SMTP_* must be "
            "configured in backend/docker/.env for this to work — see "
            "docker/.env.example). If request-code returns 502, that's the "
            "first place to check."
        )


# =============================================================================
# OTP RETRIEVAL
# =============================================================================


def _otp_from_logs(email: str) -> str | None:
    """
    Best-effort: read the most recent AUTH_EMAIL_DEV_MODE log line for this
    email out of `docker logs backend-api`. Returns None if the container
    isn't reachable via the Docker CLI or no matching line is found — the
    caller falls back to a manual prompt either way, so this is pure
    convenience, not a hard dependency.
    """
    try:
        result = subprocess.run(
            ["docker", "logs", "--tail", "200", CONTAINER_NAME],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    marker = f"OTP for {email}:"
    matches = [line for line in result.stderr.splitlines() if marker in line]
    if not matches:
        matches = [line for line in result.stdout.splitlines() if marker in line]
    if not matches:
        return None

    # Most recent match wins — request-code invalidates older codes anyway.
    last_line = matches[-1]
    # Log line shape: "...AUTH_EMAIL_DEV_MODE — OTP for <email>: <code> (not sent)"
    try:
        after_marker = last_line.split(marker, 1)[1].strip()
        code = after_marker.split()[0]
        return code if code.isdigit() else None
    except IndexError:
        return None


def get_otp(email: str) -> str:
    """
    Ask for the code the person just received by real email. Also tries
    the backend-api container logs first, purely as a convenience for the
    case AUTH_EMAIL_DEV_MODE turned out to be on after all (no real mail
    sent) — if that produces nothing, falls through to the manual prompt,
    which is the expected path when testing real SMTP delivery.
    """
    time.sleep(1)
    code = _otp_from_logs(email)
    if code:
        print(
            f"[i] Found an OTP in backend-api logs ({code}) — "
            "AUTH_EMAIL_DEV_MODE is likely on for that container, so no "
            "real email was sent. Using it, but this doesn't test mail "
            "delivery; turn dev mode off in backend/docker/.env to test "
            "the real SMTP path."
        )
        return code

    print(
        f"\n[ ] Check the inbox for {email} (and spam folder) for a "
        '"Your Night Train Tool login code" email.\n'
        "    Delivery is usually quick but can take a minute or two."
    )
    return input("    Paste the 6-digit code here: ").strip()


# =============================================================================
# AUTH STEPS
# =============================================================================


def request_code(email: str, display_name: str) -> dict:
    print(f"[ ] POST /api/auth/request-code  (email={email})")
    r = requests.post(
        f"{API_BASE}/api/auth/request-code",
        json={"email": email, "display_name": display_name},
        timeout=10,
    )
    print(f"    -> {r.status_code}")
    if r.status_code != 200:
        print(f"[\u2717] request-code failed: {r.text}")
        sys.exit(1)
    print("[\u2713] Code requested (200, empty body by design — no user enumeration).")
    return {}


def verify(email: str, code: str) -> dict:
    print(f"[ ] POST /api/auth/verify  (email={email})")
    r = requests.post(
        f"{API_BASE}/api/auth/verify",
        json={"email": email, "code": code},
        timeout=10,
    )
    print(f"    -> {r.status_code}")
    if r.status_code != 200:
        print(f"[\u2717] verify failed: {r.text}")
        sys.exit(1)
    body = r.json()
    print(
        f"[\u2713] Verified. user_id={body['user_id']} "
        f"display_name={body['display_name']} is_guest={body['is_guest']}"
    )
    return body


def guest_session() -> dict:
    print("[ ] POST /api/auth/guest")
    r = requests.post(f"{API_BASE}/api/auth/guest", timeout=10)
    print(f"    -> {r.status_code}")
    if r.status_code != 200:
        print(f"[\u2717] guest session failed: {r.text}")
        sys.exit(1)
    body = r.json()
    print(
        f"[\u2713] Guest session created. user_id={body['user_id']} "
        f"display_name={body['display_name']} is_guest={body['is_guest']}"
    )
    return body


def submit_authenticated_feedback(token: str, display_name: str) -> dict:
    """
    POST /api/feedback with a bearer token. api/feedback.py's @optional_auth
    resolves g.user_id from the token and overwrites whatever user_id/email
    is in the body — so the body below deliberately omits both to show the
    token is what actually determines authorship.
    """
    print("[ ] POST /api/feedback  (authenticated, bearer token)")
    r = requests.post(
        f"{API_BASE}/api/feedback",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "subject": f"{SUBJECT_PREFIX}from {display_name}",
            "category": "Other",
            "sub_category": "General",
            "message": (
                f"Manual auth-chain test submission from {display_name} "
                f"via scripts/test_auth_chain.py."
            ),
        },
        timeout=10,
    )
    print(f"    -> {r.status_code}")
    if r.status_code != 201:
        print(f"[\u2717] feedback submission failed: {r.text}")
        sys.exit(1)
    body = r.json()
    print(
        f"[\u2713] Feedback stored. feedback_id={body['feedback_id']} "
        f"email_sent={body['email_sent']}"
    )
    return body


# =============================================================================
# COMMANDS
# =============================================================================


def cmd_request_code(email: str, name: str):
    check_smtp_configured(email)
    request_code(email, name)


def cmd_verify(email: str, name: str):
    email = input(f"Email [{email}]: ").strip() or email
    code = input("6-digit code: ").strip()
    result = verify(email, code)
    _write_output("verify", result)


def cmd_guest(email: str, name: str):
    result = guest_session()
    _write_output("guest", result)


def cmd_chain(email: str, name: str):
    check_smtp_configured(email)
    request_code(email, name)
    code = get_otp(email)
    auth = verify(email, code)
    feedback = submit_authenticated_feedback(auth["token"], auth["display_name"])
    _write_output("chain", {"auth": auth, "feedback": feedback})


def _write_output(name: str, data: dict):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f"auth_{name}_output.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"[\u2713] Wrote {path}")


# =============================================================================
# MAIN
# =============================================================================

COMMANDS = {
    "chain": cmd_chain,
    "guest": cmd_guest,
    "request-code": cmd_request_code,
    "verify": cmd_verify,
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Manual test script for the local-plane auth chain "
        "(request-code -> verify -> authenticated feedback)."
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="chain",
        choices=[*COMMANDS, "all"],
        help="which step(s) to run (default: chain)",
    )
    parser.add_argument(
        "--email",
        default=os.environ.get("AUTH_EMAIL", _FALLBACK_EMAIL),
        help=f"email to register/log in with (default: env AUTH_EMAIL, "
        f"else {_FALLBACK_EMAIL})",
    )
    parser.add_argument(
        "--name",
        default=os.environ.get("AUTH_NAME", _FALLBACK_NAME),
        help=f"display_name for first-time registration only, ignored on "
        f"login (default: env AUTH_NAME, else {_FALLBACK_NAME})",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if not check_flask():
        sys.exit(1)

    if args.command == "all":
        cmd_chain(args.email, args.name)
        cmd_guest(args.email, args.name)
    else:
        COMMANDS[args.command](args.email, args.name)