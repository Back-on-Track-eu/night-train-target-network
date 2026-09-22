# Gallery polish — phase 2 manifest (2026-09-20)

Second feedback round on `/gallery`, items 1–5. **Frontend only** — no API
change, no migration, no version bump. Builds on phase 1
(`docs/2026-09-20_gallery_polish_phase1_manifest.md`).

## Items and how they were solved

| #   | Feedback                                           | Solution                                                                                    |
| --- | -------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| 1   | Card column no longer ends at the map's edge       | Row is one screen tall, both columns share that height, the card list scrolls inside itself |
| 2   | Where is the all/mine switch?                      | Always-visible two-segment switch in the result column; signed out it opens the auth modal  |
| 3   | Align comments and likes, number right of the icon | Two identically built icon-then-count buttons, same box, one baseline                       |
| 4   | "Proposed by" stale after login                    | The list reloads when the identity changes (or is marked stale while cached)                |
| 5   | Comment icon should link to the discussion         | `/proposal/<id>#comments` → `focusSection` prop → scroll once the thread mounts             |

## Files touched

### `frontend/src/components/Gallery.vue`

- **One-screen row (item 1).** `measureMap` → `measureRow`: the measured budget
  now sizes the RESULTS ROW, not just the map, and both columns take that
  height. The card list moved into `cardScroller`, a `min-h-0 flex-1
overflow-y-auto` box with `.thin-scroll`, holding skeletons, cards, sentinel
  and the trailing CTA. The `IntersectionObserver` now uses `root:
cardScroller.value`. The map's `sticky top-6` is gone — the row no longer
  outgrows the screen, so there is nothing to stick to.
- **Chrome trimmed further** to buy card height: section heading and subtitle on
  one baseline row (`text-2xl`, `pt-6`), root `gap-6 → gap-4`, column
  `gap-4 → gap-3`, card gaps `gap-4 → gap-3`, skeletons `9rem → 11rem`.
  `ROW_MIN_HEIGHT_PX = 560` is the floor (≈ three cards).
- **Ownership switch (item 2).** Replaces the phase-1 pill with an "All | Mine"
  segmented control, always rendered. `selectMine()` opens the auth modal when
  there is no identity, and moves the source switch off "existing" (which has no
  owner) rather than filtering to an empty list.
- **Identity reload (item 4).** New watcher on `store.userId` /
  `store.username`: `resetAndLoad()` when the gallery is on screen, otherwise
  `store.galleryStale = true` for `onActivated` to pick up — signing in merges
  the guest session, so proposals change hands and their proposer line with
  them. `isActive` tracks activation for that decision.
- **Discussion link (item 5).** `openDiscussion()` pushes
  `{ name: 'proposal', params: { id }, hash: '#comments' }`, bound to the card's
  new `@discuss`.

### `frontend/src/components/ProposalCard.vue`

- Engagement row rebuilt (item 3): comments and likes are the same button shape
  (`h-8`, `px-2`, icon 20, count to the right of the icon, one baseline). Like
  keeps the spinner and the filled/outline state; comments emit `discuss`
  (item 5) and keep the stat popover on hover.
- Card box tightened (`p-4 → p-3`, `gap-3 → gap-2`, footer `pt-3 → pt-2.5`) so
  three fit the column.

### `frontend/src/components/ProposalWorkspace.vue`

- Reads `route.hash` into a `focusSection` prop (`'comments' | null`) — routing
  stays in the wrapper, as with `mode` and `proposalId`.

### `frontend/src/components/ProposalViewport.vue`

- New `focusSection` prop, `discussionAnchor` ref on the discussion slot
  (`id="comments"`, `scroll-mt-6`), and a one-shot watcher that scrolls there
  once `showCommentSection` opens. Waits for the gate because the discussion
  mounts only after the results do — a browser anchor would fire against
  nothing.

### `frontend/src/i18n/locales/en.json`, `de.json`

- `gallery.filter.*` is now `label` / `all` / `mine` (replaces `mineOnly`);
  `gallery.card.comments` is the comment button's label ("Read the comments").

### `frontend/README.md`

- Gallery section updated: one-screen row and internal list scrolling, the
  always-visible ownership switch and its sign-in path, the identity reload, and
  the comment-count link into the discussion.

### `docs/2026-09-20_gallery_polish_phase2_manifest.md`

- This file.

## Gates run

| Gate                   | Result                                                                          |
| ---------------------- | ------------------------------------------------------------------------------- |
| `npm run format:check` | clean                                                                           |
| `npm run lint`         | clean                                                                           |
| `npm run type-check`   | clean                                                                           |
| `npm test`             | 27 files, 325 cases green                                                       |
| `npm run build`        | green (locally with stub font files — the fonts are not in the snapshot export) |

## Rollout

1. Extract over the repository root, delete the zip.
2. `cd frontend && npm run ci && npm run build`.
3. Frontend image rebuild only; no deploy-side change, no `.env` key, no
   migration.

## Open for David

- Three cards at once is a budget, not a guarantee: on a 1920×1080 screen at
  100% zoom the row comes out around 650–700 px, which holds three cards of the
  new size. On a shorter window `ROW_MIN_HEIGHT_PX` (560) takes over and the
  page scrolls a little rather than the map collapsing. Say if you want the
  floor higher or the section heading dropped entirely (≈ 55 px more).
- The map is no longer sticky, because the row now ends with the screen. If you
  scroll past the gallery there is nothing below it anyway.
- Item 4 reloads the whole first page on sign-in. That is one request, and the
  alternative (patching proposer names client-side from the auth response) would
  guess at what the backend did during the merge.
