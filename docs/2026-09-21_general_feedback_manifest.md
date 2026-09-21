# General feedback form at /docs/feedback — delivery manifest

Date: 2026-09-21 · Scope: **docs-site plus one taxonomy value on the backend.**
Backend `0.5.3 → 0.5.4`. No model version bump: `feedback_serialize.py` is not
a gated model file, and no formula, schema or response shape changed.

The feedback endpoint already existed — `POST /api/feedback` with optional
auth, rate limiting, mail and storage, and `GET /api/feedback/categories` with
the ten-category taxonomy derived live from the model registries. So did a
feedback form: the per-page "Found a mistake?" box at the foot of all 44
documentation pages, which fixes `category: Documentation` and sends the page
path as `sub_category`. What was missing is the general case — the reader
choosing what the feedback is about. That is this page; nothing was rebuilt.

## What changed

### Backend

| # | File | Change |
|---|---|---|
| 1 | `backend/api/helpers/feedback_serialize.py` | `"Missing stop / suggest new stop"` added to `_ROUTE_TIMETABLE_SUB_CATEGORIES`, with the note that the app deep-links to it by alias, not by this string. |
| 2 | `backend/tests/test_60_feedback_api.py` | New `test_feedback_categories_carry_the_deep_linked_missing_stop` — the one pair the app links to must stay in the payload, or the form lands on a `sub_category` its own dropdown does not offer. |
| 3 | `backend/api/README.md` | The `Route or timetable` row of the categories table names the new value and the link that uses it. |
| 4 | `backend/pyproject.toml` | `0.5.3 → 0.5.4`. |

### Documentation site

| # | File | Change |
|---|---|---|
| 5 | **new** `docs-site/feedback.md` | The page: what it is for, when the per-page form is the quicker route, then the form. |
| 6 | **new** `docs-site/.vitepress/theme/components/GeneralFeedbackForm.vue` | Category select from `GET /api/feedback/categories`; sub-category as a select where the taxonomy has a list and a text field where it does not (Bug report, Feature request, Other and Documentation carry none by design, and the endpoint still requires a non-empty value); subject, message; reply address. A failed category load is not a dead end — both fields fall back to free text, which the endpoint accepts anyway, with a line saying so. Deep links by alias: `?topic=missing-stop` presets the pair, `?q=` fills the subject and opens the message with what was searched for. |
| 7 | **new** `docs-site/.vitepress/theme/lib/apiBase.ts` | The API origin, once, mirroring `frontend/src/lib/apiBase.ts`: empty (same origin) in production behind the app's nginx, `VITE_API_BASE_URL` for development, where the docs run as their own server behind the `/docs` proxy and have no `/api` route. |
| 8 | `docs-site/.vitepress/theme/components/FeedbackForm.vue` | Posts through `apiUrl()` instead of a hardcoded path — two forms, one origin — and its header comment now names its general counterpart. |
| 9 | `docs-site/.vitepress/theme/index.ts` | `GeneralFeedbackForm` registered globally like its sibling, with the reason: a markdown page importing from `./.vitepress/theme/components/` breaks the moment the page moves. |
| 10 | `docs-site/.vitepress/config.ts` | `Feedback` in the top nav and directly under `About` in the sidebar — it belongs to the "what this is and how to take part" half of the site, not to the model chapters. |
| 11 | `docs-site/index.md` | A short "Telling us something" section on the About page linking to it, and naming the per-page form as the alternative. |

## Identity — how "use the logged-in mail" works

The backend takes a bearer token over anything the request body claims and
resolves the account's address itself for Reply-To (`api/feedback.py`), so the
form never handles the address: it sends the token and no `email` field. Only
a **registered** account has one — a guest row is exactly a user row without an
email — so the form reads the `nt_auth` cookie (same origin, path `/`,
JS-readable by design) and offers the account route only when `is_guest` is
false. Guests and anonymous readers are asked for an address, and a signed-in
reader can untick the box and give a different one, which drops the token from
the request.

## Verification

- `ruff format --check` / `ruff check` on the whole backend — clean.
- `vitepress build` — succeeds; `/feedback` renders and `ignoreDeadLinks` is
  off, so the new About link is checked by the build.
- `prettier --check` on every file touched here — clean.
- `test_60` runs against the live stack: include it in the next integration
  run (`uv run --extra dev python -m pytest tests/test_60_feedback_api.py -v`).

## Rollout

Nothing to migrate and nothing to refresh: no schema, no stored shape and no
model version changed. The docs bundle is built into the frontend image
(`frontend/Dockerfile.demo` from the `docssrc` context), so the page ships with
the next frontend deploy; the new sub-category appears as soon as the api
container restarts.

## Commit split

- `feat(feedback): general feedback page at /docs/feedback, missing-stop sub-category` — files 1, 3–11.
- `test(feedback): pin the deep-linked missing-stop sub-category` — file 2.
- `docs: general feedback page manifest` — this file.
