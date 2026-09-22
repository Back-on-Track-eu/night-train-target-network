# The gate opens itself at the launch moment — manifest and handover

Date: 2026-09-22 · Scope: **backend `0.5.8 → 0.5.9`.** No model bump, no
migration, no frontend change. **Must be on production before 10:00 CEST.**

## Why

Two things hang on `api/gate_page.LAUNCH` (22 September 2026, 10:00 CEST).
The page's hero already switched to "The Target Network is open" with a
button to `/` on its own — but `GET /api/gate/check`, Caddy's `forward_auth`
target for every app request, never looked at the clock: without a cookie it
kept answering `302 /gate`. A visitor at 10:01 would have seen "open",
clicked, and landed back on the gate with no code box open.

## What changed

- `gate_page.gate_is_open(now=None)` — the one switch, `now >= LAUNCH`,
  injectable for tests. The hero uses it.
- `GET /api/gate/check` answers `204` to everyone once it is true; before
  that, cookie holders only, as before.
- `GET /gate` redirects to `/` once it is true (or with a cookie), instead
  of rendering the page.
- Re-gating later is moving `LAUNCH`; the cookie and code paths stay intact.

## Updates by file

| File | Change |
|---|---|
| `backend/api/gate_page.py` | `gate_is_open()`; hero built from it. |
| `backend/api/gate.py` | Check and page consult it; module docstring says so. |
| `backend/tests/test_76_gate_page.py` | Unit: `gate_is_open` flips exactly at `LAUNCH`. |
| `backend/tests/test_75_gate_api.py` | The seven "ungated visitor is bounced" live tests carry `@before_launch` (skip once the moment has passed); new `@after_launch` test: no cookie → `204`, `/gate` → `302 /`. So the suite stays green on both sides of the clock. |
| `backend/api/README.md`, `backend/pyproject.toml` | Check row; `0.5.9`. |

## Pipeline

1. `uv run --extra dev python -m pytest tests/test_75_gate_api.py tests/test_76_gate_page.py -v` (today: the after-launch case skips, the rest run).
2. `uv run ruff format --check` / `ruff check` — clean here.
3. Ship on the `backend-dev → staging` PR, then production, **before 10:00 CEST**. The API image alone; Caddy untouched. Nothing to do on launch morning.
4. Sanity check after deploy, from any browser without the cookie:
   before 10:00 `/api/gate/check` → 302, `/gate` → the countdown; from
   10:00 → 204 and `/gate` → `/`.

## Commit split

- `feat(gate): open the gate itself at the launch moment` — api files + pyproject.
- `test(gate): time-aware gate tests` — the two test files.
- `docs: gate manifest and README` — README + this file.
