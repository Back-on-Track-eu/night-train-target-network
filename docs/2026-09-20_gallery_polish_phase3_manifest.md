# Gallery polish — phase 3 manifest (2026-09-20)

Proposal-card redesign plus the `created_at` / `updated_at` line. **Frontend
only** — no API change, no migration, no version bump. Applies on top of phases
1 and 2.

## The problem, and the rule that fixes it

Every line on the old card was set in semibold: the itinerary, all five
figures, both engagement counts. With no weight contrast left, nothing led the
eye, and the wrapping stat strip put the same figure in a different place on
every card, so the column could not be read down.

The card now has **one bold element — the route** — and three blocks with one
hairline between them:

1. route (bold, centred, intermediate stops as the quietest text on the card)
2. figures, in a fixed two-column grid
3. metadata: flags, proposer, dates, engagement — all small and dim

Below the route, hierarchy is carried by colour and size (`/85` values, `/55`
metadata, `/35` hints and icons), not by weight.

## Files touched

### `frontend/src/components/ProposalCard.vue`

- **Figures in a grid**, filled in a fixed order (distance, average speed,
  passenger trips/yr, CO₂ saved, composition) instead of a wrapping strip, so
  the same fact sits in the same corner on every card. Values `text-sm
tabular-nums text-primary-50/85` at normal weight; icons 16 px at
  `text-primary-50/35`. Composition is last and alone on its row — an
  identifier among quantities.
- **Dates (the new request).** `dateLine` renders "Created 12 Sep 2026 ·
  updated 14 Sep 2026", dropping the updated half when it would repeat the
  creation date (a proposal published once and never revised). Proposals only:
  an ONTD row has no author and no history.
- **Metadata foot**: flags + proposer + dates on the left, comments and likes on
  the right, `items-end` so both sit on one baseline. Engagement icons dropped
  to 18 px and `/55` so they stop competing with the figures.
- **Room to breathe**: `p-3 → p-4`, one hairline instead of two (the foot is
  separated by space), `leading-tight` on the itinerary, `gap-2.5` between
  blocks. Card comes out around 225 px, so the column still holds three on a
  1080p screen at 100% zoom.
- Intermediate stops and the "(N stops)" hint are now `text-xs` at `/35`–`/55`
  and normal weight (they were `text-sm font-semibold /80` — a second
  headline).
- Hover now tints the card (`hover:bg-primary-50/[0.07]`), so the row under the
  cursor is obvious while the map isolates its route.

### `frontend/src/composables/useLocaleFormat.ts`

- New `formatDate(iso)`: locale-aware short date (`12 Sep 2026` /
  `12. Sep. 2026`), empty string for an unparseable value. Day precision — the
  hour is noise on an authoring date.

### `frontend/src/components/CommentSection.vue`

- Its `'date'` age branch now calls the shared `formatDate` instead of its own
  inline `toLocaleDateString`, so card and thread print the same form. `locale`
  is no longer needed there.

### `frontend/src/i18n/locales/en.json`, `de.json`

- `gallery.card.created` ("Created {date}" / "Erstellt {date}") and
  `gallery.card.updated` ("updated {date}" / "aktualisiert {date}" — lower
  case, it is the second half of one line).

### `frontend/README.md`

- Gallery section's card paragraph rewritten for the new three-block structure,
  the fixed grid order and the date line.

### `docs/2026-09-20_gallery_polish_phase3_manifest.md`

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
3. Frontend image rebuild only.

## Open for David

- Dates are absolute and day-precise. The comment thread uses relative ages
  ("3 days ago") for anything under a week — say if you want the card to match
  that instead; `lib/commentThread.ts`'s `commentAge` is already there.
- The grid is two columns of equal width. If composition alone on the third row
  reads odd once you see it with real data, the alternative is a full-width
  third row or moving it back beside the flags.
- Sorting still does not offer demand. Now that every figure on the card is in a
  fixed slot, adding it (and dropping a sort key nothing displays) is a small
  change if you want the list orderable by what it shows.
