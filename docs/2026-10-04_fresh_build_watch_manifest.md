# Open tabs follow a deploy — `useFreshBuild` (2026-10-04)

Frontend only; no backend change, no version bump, no migration. Closes
the second way people end up on an old build: the nginx cache headers
(2026-10-04 manifest) settle what a browser does on its next page load,
this settles tabs that never make one — and a browser that served a stale
`index.html` anyway now corrects itself within seconds.

## Files

- `frontend/src/lib/freshBuild.ts` — **new**: `entryBundleOf(html)`,
  `runningEntryBundle(document)`, `liveEntryBundle()` (fetches
  `/index.html` with `cache: 'no-store'`).
- `frontend/src/lib/freshBuild.test.ts` — **new** (2 tests).
- `frontend/src/composables/useFreshBuild.ts` — **new**:
  `startFreshBuildWatch(router)` — checks after boot (3 s), on
  `visibilitychange` to visible, every 10 min, at most once a minute;
  stale on the gallery → `location.reload()` unless the reader is typing;
  stale elsewhere → reload in `router.afterEach` once the next navigation
  lands on the gallery. Off on the dev server (no hashed entry).
- `frontend/src/main.ts` — starts the watch after mount.
- `frontend/README.md` — "Staying on the current build" under Production
  image; `docs/FRONTEND_HANDOVER.md` §27.

## Verified

Production build served locally, API mocked, Playwright with a faked
clock:

- startup check makes exactly one `GET /index.html`; same bundle → no
  reload;
- "deploy" (index.html renamed to a new entry hash) + the 10-minute tick
  on the gallery → the tab reloads onto the new bundle;
- the same in the builder → no reload; going back to the gallery → full
  load onto the new bundle at `/gallery?mode=…` (an earlier version that
  cancelled the navigation in `beforeEach` failed this on back/forward —
  the router reverts the URL — hence `afterEach`).

vitest 396, eslint and prettier clean, vue-tsc unchanged.
