"""
test_feedback_api.py
=====================
Manual test script for the feedback endpoints:

  GET  /api/feedback/categories
  POST /api/feedback

Usage:
    python scripts/test_feedback_api.py [command] [args]

    command : categories | submit-anonymous | submit-user | validation | all
              (default: all)

  categories        GET /api/feedback/categories [scenario_id]
  submit-anonymous  POST /api/feedback identified by email
                     [email] (default: manual-test@example.com)
  submit-user       POST /api/feedback identified by user_id
                     [user_id] (default: 1 — David, see db/dev/seed.py:USERS)
  validation        Fires the four expected-to-fail requests (no identity,
                     bad email, missing fields, unknown user_id) and checks
                     each gets the right error status — no output file.

Examples:
    python scripts/test_feedback_api.py
    python scripts/test_feedback_api.py categories
    python scripts/test_feedback_api.py submit-anonymous someone@example.com
    python scripts/test_feedback_api.py submit-user 2

Writes pretty-printed responses to scripts/data/feedback_<command>_output.json
(categories and submit-* only — validation has nothing worth persisting).

Pre-flight:
  1. Checks Flask API is reachable
  2. Loads data if not already loaded

Note: every submission here actually inserts an admin.feedback row and, if
SMTP_* is configured (see docker/.env.example), sends a real notification
mail to FEEDBACK_NOTIFY_EMAIL — this script is not test-isolated the way
tests/test_60_feedback_api.py is. Rows are tagged with a
'MANUAL_TEST_FEEDBACK_' subject prefix so they're easy to find and remove
manually afterwards if needed.
"""

import json
import os
import sys
import requests

API_BASE = "http://localhost:5000"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "data")

SUBJECT_PREFIX = "MANUAL_TEST_FEEDBACK_"

DEFAULT_EMAIL = "manual-test@example.com"
DEFAULT_USER_ID = 1  # David — see db/dev/seed.py:USERS


# =============================================================================
# PRE-FLIGHT CHECKS
# =============================================================================


def check_flask():
    print("[ ] Checking Flask API...")
    try:
        r = requests.get(f"{API_BASE}/api/health", timeout=3)
        if r.status_code == 200:
            print("[✓] Flask API is running.")
            return True
    except requests.ConnectionError:
        pass
    print(
        "[✗] Flask API not reachable at localhost:5000. Start it with: uv run python main.py"
    )
    return False


def ensure_data_loaded():
    print("[ ] Checking data status...")
    r = requests.get(f"{API_BASE}/api/data/status")
    status = r.json()

    if status.get("loaded"):
        print(f"[✓] Data already loaded at {status.get('loaded_at')}.")
        return True

    print("[ ] Data not loaded — loading now...")
    r = requests.post(f"{API_BASE}/api/data/load")
    result = r.json()

    if r.status_code == 200:
        print(f"[✓] Data loaded at {result.get('loaded_at')}.")
        return True
    else:
        print(f"[✗] Data load failed: {result.get('message')}")
        return False


# =============================================================================
# SHARED
# =============================================================================


def _write_output(command: str, response_body: dict) -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, f"feedback_{command}_output.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(response_body, f, indent=2, ensure_ascii=False)
    print(f"\nResponse written to {output_path}")


def _print_error_or(response: requests.Response, on_success) -> dict | None:
    """Print status + body; on non-2xx print the error and return None,
    otherwise hand the parsed body to on_success and return it."""
    print(f"Status: {response.status_code}")
    try:
        body = response.json()
    except requests.exceptions.JSONDecodeError:
        print("\nNon-JSON response body (raw Flask error page?) — check the Flask")
        print("server's terminal for the actual traceback. Raw response body:\n")
        print(response.text)
        return None

    if response.status_code // 100 == 2:
        on_success(body)
    else:
        print("\nError response:")
        print(json.dumps(body, indent=2))
    return body


# =============================================================================
# TEST — GET /api/feedback/categories
# =============================================================================


def test_categories(scenario_id: int | None):
    params = {"scenario_id": scenario_id} if scenario_id is not None else {}

    print("\nGET /api/feedback/categories")
    if scenario_id is not None:
        print(f"scenario_id: {scenario_id}")
    print("-" * 60)

    response = requests.get(f"{API_BASE}/api/feedback/categories", params=params)

    def on_success(body):
        categories = body["categories"]
        print(f"\n--- CATEGORIES ({len(categories)}) ---")
        for c in categories:
            print(f"  {c['category']}: {len(c['sub_categories'])} sub-categories")
        infra_entry = next(
            (c for c in categories if c["category"] == "Infrastructure"), None
        )
        if infra_entry and infra_entry["sub_categories"]:
            first = infra_entry["sub_categories"][0]
            print(f"  first Infrastructure sub-category: {first}")

    body = _print_error_or(response, on_success)
    if body is not None:
        _write_output("categories", body)


# =============================================================================
# TEST — POST /api/feedback
# =============================================================================


def _submit(command: str, body: dict):
    print(f"\nPOST /api/feedback ({command})")
    print(json.dumps(body, indent=2))
    print("-" * 60)

    response = requests.post(f"{API_BASE}/api/feedback", json=body)

    def on_success(response_body):
        print("\n--- FEEDBACK SUBMITTED ---")
        print(f"  feedback_id: {response_body['feedback_id']}")
        print(f"  created_at:  {response_body['created_at']}")
        print(f"  email_sent:  {response_body['email_sent']}")
        if not response_body["email_sent"]:
            print(
                "  (email_sent=False is expected if SMTP_* isn't configured — "
                "the row is still stored either way, see adapters/mailer.py)"
            )

    response_body = _print_error_or(response, on_success)
    if response_body is not None:
        _write_output(command, response_body)


def test_submit_anonymous(email: str):
    _submit(
        "submit-anonymous",
        {
            "email": email,
            "subject": f"{SUBJECT_PREFIX}anonymous",
            "category": "Infrastructure",
            "sub_category": "tac_eur_train_km",
            "message": "Manual test submission — anonymous, identified by email.",
        },
    )


def test_submit_user(user_id: int):
    _submit(
        "submit-user",
        {
            "user_id": user_id,
            "subject": f"{SUBJECT_PREFIX}logged_in",
            "category": "Bug report",
            "sub_category": "General",
            "message": "Manual test submission — logged in, identified by user_id.",
        },
    )


# =============================================================================
# TEST — validation errors
# =============================================================================


def _check_validation_case(name: str, body: dict, expected_status: int):
    response = requests.post(f"{API_BASE}/api/feedback", json=body)
    ok = response.status_code == expected_status
    mark = "✓" if ok else "✗"
    print(f"[{mark}] {name}: expected {expected_status}, got {response.status_code}")
    if not ok:
        print(f"    body: {response.text[:300]}")


def test_validation():
    print("\nPOST /api/feedback — validation error cases")
    print("-" * 60)

    _check_validation_case(
        "no identity (no user_id/email)",
        {
            "subject": f"{SUBJECT_PREFIX}no_identity",
            "category": "Bug report",
            "sub_category": "General",
            "message": "Missing identity.",
        },
        400,
    )
    _check_validation_case(
        "invalid email format",
        {
            "email": "not-an-email",
            "subject": f"{SUBJECT_PREFIX}bad_email",
            "category": "Bug report",
            "sub_category": "General",
            "message": "Invalid email format.",
        },
        400,
    )
    _check_validation_case(
        "missing subject/category/sub_category/message",
        {"email": "someone@example.com"},
        400,
    )
    _check_validation_case(
        "unknown user_id",
        {
            "user_id": 999_999_999,
            "subject": f"{SUBJECT_PREFIX}unknown_user",
            "category": "Bug report",
            "sub_category": "General",
            "message": "This user_id should not exist.",
        },
        422,
    )


# =============================================================================
# MAIN
# =============================================================================

COMMANDS = ("categories", "submit-anonymous", "submit-user", "validation")

if __name__ == "__main__":
    if len(sys.argv) > 3:
        print(__doc__)
        sys.exit(1)

    command_arg = sys.argv[1] if len(sys.argv) >= 2 else "all"
    extra_arg = sys.argv[2] if len(sys.argv) == 3 else None

    if command_arg != "all" and command_arg not in COMMANDS:
        print(
            f"Unknown command '{command_arg}'. Choose from: {', '.join(COMMANDS)}, all"
        )
        sys.exit(1)

    print("=" * 60)
    print("  Night Train — feedback endpoints test")
    print("=" * 60)

    if not check_flask():
        sys.exit(1)
    if not ensure_data_loaded():
        sys.exit(1)

    if command_arg in ("categories", "all"):
        scenario_id_arg = (
            int(extra_arg) if extra_arg and command_arg == "categories" else None
        )
        test_categories(scenario_id_arg)

    if command_arg in ("submit-anonymous", "all"):
        email_arg = (
            extra_arg
            if extra_arg and command_arg == "submit-anonymous"
            else DEFAULT_EMAIL
        )
        test_submit_anonymous(email_arg)

    if command_arg in ("submit-user", "all"):
        user_id_arg = (
            int(extra_arg)
            if extra_arg and command_arg == "submit-user"
            else DEFAULT_USER_ID
        )
        test_submit_user(user_id_arg)

    if command_arg in ("validation", "all"):
        test_validation()
