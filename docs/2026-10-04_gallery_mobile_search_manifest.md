# Gallery search on a phone — manifest (2026-10-04)

Frontend only. Found by walking every search path (A→B, by station, by
country, between countries), both selects, both collapsible panels and the
cards at 360, 390 (iPhone), 768, 1024, 1280 and 1300 px against a mocked
API with long station names, and checking `scrollWidth` against the
viewport in every state.

## Found and fixed

- **Stop overlay wider than a phone** (the reported one). PrimeVue's
  Popover sizes shrink-to-fit, so the overlay was as wide as the longest
  station name in the catalogue and the page scrolled sideways; the gauge
  column fell off the right edge. Now `width: min(28rem, 100vw − 1rem)`,
  rows and subtitles truncate, and below `sm` the list is 13 rem tall
  instead of 20 so it stays above the on-screen keyboard. The country
  overlay gets the same rules.
- **Horizontal scrollbar on every page at 1280–1380 px.** The header's
  account badge is pushed into the outer gutter from `xl` (1280 px), but at
  that width the gutter beside the 1140 px container is 70 px and the badge
  ~110 px — 41 px of overflow on a common laptop width. The breakpoint is
  now `min-[1380px]`, where it fits.
- **"Between Countries" tab wrapped at 360 px**, leaving its icon alone on
  the first line. Tab labels no longer wrap; the cell padding is 8 px
  below `sm`.

## Checked, no change needed

Search pill in all four modes with picked values (long names truncate
with an ellipsis), country overlay, source and sort selects, range filters
panel open and closed, scenario panel open, cards, the "Suggest a new
route" button — no overflow at any width; German labels are no longer
than the English ones.

## Files

- `frontend/src/style.css` — `.search-popover`, `.search-popover-list`.
- `frontend/src/components/StopSelect.vue`, `CountrySelect.vue` — use them;
  rows truncate; the inline `max-height` moved to the class.
- `frontend/src/components/AppHeader.vue` — badge breakpoint.
- `frontend/src/components/Gallery.vue` — tab labels `whitespace-nowrap`,
  `px-2 sm:px-4`.
- `frontend/README.md` — gallery-on-a-phone paragraph.
