# Gallery and landing page on a phone — manifest

Date: 2026-10-03 · Scope: **frontend only.** No backend change, no version
bump, no migration, no new i18n keys.

## What was wrong

Screenshots from an iPhone 16 Pro (393 px wide) showed `/gallery` unusable:

- The landing intro is a hard two-column grid with a 96 px gutter on each
  side, so each column was ~100 px wide and the pitch ran one word per line.
- The four mode tabs sit in one pill (~570 px for the English labels); the
  first and last were cut off on both sides.
- The search pill holds two 192 px fields plus the button side by side.
- The results row forces a 384 px card column beside a `flex-1` map — on a
  393 px screen the map got zero width and simply did not exist, and the
  fixed row height applied to the stacked column too.
- The account chip in the header is positioned past the container's right
  edge (`left-full`); below `xl` the container spans the viewport, so the
  chip was off-screen and there was no way to sign in from the header.

## What changed

Everything the gallery can do on a desktop is reachable on a phone; the
desktop layout (`lg` and up) is pixel-for-pixel what it was.

- **Landing intro** stacks below `lg`: headline and the four buttons first,
  the pitch under them. The band's own `px-24` gutter applies from `lg` up
  only; the page gutter is enough on a phone. Headline `text-3xl` below `sm`.
- **Mode tabs**: a 2×2 grid without dividers below `sm`, the pill with
  hairlines from `sm` up.
- **Search pill**: a column below `sm` — fields full-width, the hairline
  between them horizontal, the Search button a labelled full-width row (the
  existing `gallery.search.button` string, visible below `sm`, screen-reader
  only above). `SearchField` is `w-full sm:w-48`.
- **Scenario panel header** wraps (`flex-wrap`) instead of squeezing the
  summary, badge and notes into word-per-line columns; the PROPOSALS ONLY
  badge no longer breaks inside.
- **Results row** is a column below `lg`: the map first at a fixed height
  (`h-64`, `sm:h-96`; `order-first`, so the DOM keeps it after the list for
  the two-column case), then the source/sort controls, the ownership switch
  and count, then the cards running down the page. The measured row height
  moved from an inline `height` to a CSS custom property (`--row-height`)
  consumed by `lg:h-(--row-height)`, so it binds only in the two-column
  layout; the card column's inner scroll (`overflow-y-auto`, `min-h-0`,
  `flex-1`) is `lg:`-only for the same reason.
- **Infinite scroll** follows the layout: the sentinel is observed against
  the card column from `lg` up (as before) and against the viewport below
  it. `useMediaQuery(LG_MEDIA_QUERY)` — new composable, pinned to Tailwind's
  `lg` (`64rem`) so script and template cannot disagree — rebuilds the
  observer when the breakpoint is crossed and on every re-activation of the
  kept-alive page (the viewport may have changed while the gallery was
  cached).
- **Header**: the account chip is in the row after the languages below
  `xl`, and in the outer gutter past the container's edge (the
  back-on-track.eu position) from `xl` up, where that gutter exists.
- **Page gutter** `px-4` below `sm`, `px-8` above (was `px-8` everywhere).
  This reaches the builder routes too, which only gain room.

## Updates by file

| File                                               | Change                                                                                                                                                                                                                                                                                                                                                          |
| -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `frontend/src/components/Gallery.vue`              | Tabs 2×2 grid below `sm`; search pill stacks below `sm` with a labelled Search button; results row `flex-col lg:flex-row`, map `order-first` with fixed mobile height, row height via `--row-height`, column scroll `lg:`-only; `observeSentinel()` picks the observer root from `twoColumn`, rebuilt on breakpoint change and `onActivated`; comments updated. |
| `frontend/src/components/LandingIntro.vue`         | `grid-cols-1 lg:grid-cols-2`, `gap-y-10`, `lg:px-24`, headline `text-3xl sm:text-4xl`; comment updated.                                                                                                                                                                                                                                                         |
| `frontend/src/components/SearchField.vue`          | `w-full sm:w-48`; comment updated.                                                                                                                                                                                                                                                                                                                              |
| `frontend/src/components/GalleryScenarioPanel.vue` | Header button `flex-wrap gap-x-2 gap-y-1 text-left`; badge `whitespace-nowrap`.                                                                                                                                                                                                                                                                                 |
| `frontend/src/components/AppHeader.vue`            | Account chip wrapper: in-flow `ml-4` below `xl`, `xl:absolute xl:left-full …` above; comment updated.                                                                                                                                                                                                                                                           |
| `frontend/src/App.vue`                             | Page gutter `px-4 sm:px-8`; comment on why `py-12` is load-bearing.                                                                                                                                                                                                                                                                                             |
| `frontend/src/composables/useMediaQuery.ts`        | New: `useMediaQuery(query)` → readonly `Ref<boolean>` following `matchMedia` changes; `false` without a `window`. Exports `LG_MEDIA_QUERY`.                                                                                                                                                                                                                     |
| `frontend/src/composables/useMediaQuery.test.ts`   | New: no-window fallback, initial answer + change tracking, query pass-through.                                                                                                                                                                                                                                                                                  |
| `frontend/README.md`                               | Gallery section: the one-column layout below `lg` and the observer root rule; landing intro note; `composables/` in the tree.                                                                                                                                                                                                                                   |

## Frontend handover

- Nothing in the API contract changed.
- The one rule to keep: the breakpoint in `LG_MEDIA_QUERY` and the `lg:`
  classes on the results row are the same thing. Move one, move the other.
- The map on a phone is the same `GalleryMap` at a fixed height; its own
  `ResizeObserver` handles the box change. Tapping a card still isolates its
  route for the moment before navigation (`mouseenter` fires on tap).

## Deployment handover

Frontend image only. No environment variable, no migration, no cache flush.

## Not addressed here

The second screenshot's "Server request timed out" on the first proposals
load is a backend/latency symptom, not a layout one — the error box itself
rendered correctly. Worth a look at the cold-start time of `POST
/api/proposals` with `map_lines` if it recurs.

## Verification (Node 22)

`vue-tsc --noEmit` clean · `eslint .` clean · `prettier --check .` clean ·
`vitest run` **386 passed** (3 new) · `vite build` OK.

Rendered the built app against a stub `/api` with Playwright at 393×852
(iPhone 16 Pro), 820×1180 and 1440×900: no horizontal overflow at any width
(`scrollWidth === viewport`); on the phone and the tablet scrolling the page
to the end requested two further pages of proposals, on the desktop the
column scroll remains the trigger as before.

## Commit split

- `fix(gallery): one-column layout below lg, search bar and tabs that fit a phone` — components + composable + test.
- `fix(header): account chip in the row below xl` — `AppHeader.vue`, `App.vue`.
- `docs: gallery mobile layout manifest and README` — README + this file.
