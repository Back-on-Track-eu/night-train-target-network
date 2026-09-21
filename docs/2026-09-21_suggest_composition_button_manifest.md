# "Suggest a new composition" on the landing intro — manifest and handover

Date: 2026-09-21 · Scope: **frontend + docs-site + one taxonomy value on the
backend.** Backend `0.5.6 → 0.5.7`. No model version bump.

## What changed

- **A fourth button on the gallery's opening band**, beside *See other
  people's suggestions* and *About*: **Suggest a new composition** (DE *Neue
  Zugbildung vorschlagen*). It opens `/docs/feedback?topic=composition` in a
  new tab.
- **The feedback form opens as a form to fill**: category *Compositions*,
  sub-category *Suggest a new composition*, subject *New composition*, and a
  message that starts with one sentence and then one line per parameter
  the catalogue needs, in the calibration's order — name / example
  operator, locomotive, coaches in order with type and count, places per
  class, length and mass, max speed and high-speed permission, new build or
  refurbished and the year, catering on board, purchase or lease price with
  its source, why it belongs in the target network, sources. The reader
  fills in what they know and sends.
- **Taxonomy**: the *Compositions* category, whose sub-categories are the
  live composition fields, gets one static value first — *Suggest a new
  composition* (group `Suggestion`) — so the form's dropdown offers what the
  link preselects (the same rule as the missing-stop entry).

## Updates by file

| File | Change |
|---|---|
| `frontend/src/components/LandingIntro.vue` | The button; comments updated. |
| `frontend/src/lib/feedbackLink.ts` | `FEEDBACK_TOPIC_COMPOSITION`. |
| `frontend/src/i18n/locales/en.json`, `de.json` | `gallery.welcome.suggestComposition`. 911 keys each, in parity. |
| `frontend/README.md` | Landing copy section names the button. |
| `docs-site/.vitepress/theme/components/GeneralFeedbackForm.vue` | `composition` topic with the parameter template as its lead. |
| `backend/api/helpers/feedback_serialize.py` | `COMPOSITION_SUGGEST_SUB_CATEGORY`, listed first in the Compositions category. |
| `backend/tests/test_60_feedback_api.py` | Compositions test allows the `Suggestion` group; new test pins the entry. |
| `backend/api/README.md`, `backend/pyproject.toml` | Categories table; `0.5.7`. |

## Pipeline

1. Rebuild the API image; `uv run --extra dev python -m pytest tests/test_60_feedback_api.py -v`.
2. `uv run ruff format --check` / `ruff check` on `backend/` — clean here.
3. Frontend gates: `vue-tsc --noEmit` clean · `eslint .` clean · `prettier --check` clean · `vitest run` **376 passed** · `vite build` OK.
4. Docs site: `prettier --check` clean.

## Deployment handover

API image and frontend image (docs bundle included). No environment
variable, no migration, no cache flush. Order does not matter: with an
older backend the form falls back to free text for the sub-category.

## Commit split

- `feat(feedback): "Suggest a new composition" — taxonomy entry` — backend files.
- `feat(gallery): suggest-a-composition button opening the prefilled feedback form` — frontend + docs-site files.
- `docs: manifest` — this file.
