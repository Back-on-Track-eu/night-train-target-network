# Feedback in development, and a wording round — delivery manifest

Date: 2026-09-21 · Scope: **one devcontainer env var plus four strings.**
No backend change, no version bump.

## The 404 — the docker setup, not a bug

`POST /api/feedback` is registered and correct (`main.py`, `url_prefix="/api"`).
The 404 comes from the request never reaching Flask:

- **Deployed** (staging, production, demo, and `deploy/bot-server-app/local.sh`)
  Caddy handles `/api/*` on the app's origin, and the docs are static files
  served at `/docs/` on that same origin. A relative `/api/feedback` resolves.
  `VITE_API_BASE_URL` is baked empty there for exactly this reason.
- **Devcontainer** there is no such shared origin. The app's Vite server (5173)
  proxies `/docs` to the VitePress server (5174) but has no `/api` route, and
  neither does VitePress — so a relative POST hits a dev server that knows
  nothing about it and answers 404. The SPA never noticed because the compose
  file hands the *frontend* service `VITE_API_BASE_URL=http://localhost:5050`;
  the docs service was never given the same.

This has been true of the per-page "Found a mistake?" form since it shipped —
it was simply never submitted from a dev stack.

The fix is the one line that was missing, not a proxy: the docs service gets
the same `VITE_API_BASE_URL` the frontend service already has, which is what
`docs-site/.vitepress/theme/lib/apiBase.ts` reads. Recreate the container to
pick it up:

```powershell
docker compose -f backend/docker/docker-compose.yml -f .devcontainer/docker-compose.yml up -d docs
```

Running the docs outside Docker (`cd docs-site && npm run dev`) needs the same
variable in the environment. CORS is already configured for the dev origin —
the SPA posts cross-origin from 5173 to 5050 all day.

## What changed

| # | File | Change |
|---|---|---|
| 1 | `.devcontainer/docker-compose.yml` | `VITE_API_BASE_URL` on the `docs` service, with the reason written next to it. |
| 2 | `frontend/src/i18n/locales/de.json` | `proposal.subheading` — your new sentence (with `optimieren ihn` corrected to `optimiere ihn`, to keep the imperative series). `proposal.tripPairs.comingSoonHint` — your version, ending at "Y- oder X-förmig sein." `proposal.noStopsFound` and `proposal.missingStopLink` — see below. |
| 3 | `frontend/src/i18n/locales/en.json` | `proposal.noStopsFound` → "Not found in our data what you were looking for."; `proposal.missingStopLink` → "Suggest another stop." |
| 4 | `frontend/src/components/StopSelect.vue` | `proposal.missingStopHint` is gone: your wording carries the question in `noStopsFound` itself and makes the second sentence the link, so the empty state is two lines, not three. |

The English `subheading` and `tripPairs.comingSoonHint` are untouched — you
gave German only, and the two now differ slightly in emphasis. Say the word if
the English should follow.

## Verification (Node 22)

`vue-tsc` clean · `eslint` clean · `prettier --check` clean · `vitest run`
**337 passed** · `vite build` OK · EN and DE at 872 keys each, in parity.

## Commit split

- `fix(docs-site): give the docs dev server the API origin so feedback submits` — file 1.
- `chore(i18n): wording round — subheading, trip-pair hint, empty stop search` — files 2–4.
- `docs: manifest` — this file.
