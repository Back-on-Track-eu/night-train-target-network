# Gallery — "Mine" for accounts only, loading state at the top (2026-09-20)

Frontend only, no API change.

1. **Mine asks guests to log in.** A guest session carries a user id, so the
   switch used to filter silently to the anonymous user — which reads as
   "Mine does nothing" to someone who never logged in. `canFilterMine` is now
   `authChoice === 'user'`: signed out **or a guest**, clicking Mine opens the
   login / registration modal and the filter applies itself once the account
   exists (registering merges the guest's proposals into it, so nothing is
   lost by asking). Dismissing the modal drops the intent.
2. **Loading state at the head of the column.** While any page is in flight
   the count line shows a spinner and "Loading routes…" (`role="status"`);
   the count returns when it lands. The "Loading more…" text at the foot of
   the list is gone — the sentinel is now a silent 2 rem gap.

## Files touched

- `frontend/src/components/Gallery.vue` — `canFilterMine` on `authChoice`;
  `AppSpinner` in the count row; silent sentinel.
- `frontend/src/i18n/locales/en.json`, `de.json` — `gallery.loading`
  ("Loading routes…" / "Strecken werden geladen…"); `gallery.loadingMore`
  removed.
- `frontend/README.md` — ownership-switch paragraph.

## Gates

prettier, eslint, vue-tsc, 332 vitest cases, `vite build` — green.
