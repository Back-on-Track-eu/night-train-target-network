# Landing intro: pitch in three paragraphs, buttons under the headline — manifest

Date: 2026-09-21 · Scope: **frontend only.** No backend change, no version bump,
no migration.

## What changed

- **Pitch split into three paragraphs**, wording untouched in both languages:
  1. `network` — the Target Network 2032 (300 connections, 2× / 3×).
  2. `contribute` — "This is where you come in" … free and open source.
  3. `study` — what happens to the best suggestions, credit, and the
     `{source}` link.
- **Buttons moved to the left**, under the headline. The call to action sits
  on its own line and the two quiet buttons share the line beneath, so the
  layout no longer depends on how the labels happen to wrap. The columns are
  now equal (were 2 : 3) so that line fits in EN and DE.

## Updates by file

| File | Change |
|---|---|
| `frontend/src/components/LandingIntro.vue` | Left column = headline + button stack, right column = pitch rendered from `PITCH_PARAGRAPHS` via `i18n-t` (one `{source}` slot, used by the last paragraph only); grid `grid-cols-2`, `items-center`; comments updated. |
| `frontend/src/i18n/locales/en.json`, `de.json` | `gallery.welcome.pitch` is now an object `{ network, contribute, study }`. EN/DE in parity at 897 keys. |
| `frontend/README.md` | *Landing Page Copy* rewritten: it still described three headed blocks and a collapsible second band that no longer exist. |

## Frontend handover

- **Key rename for the text review.** `gallery-texts-review.xlsx` has one row
  for `gallery.welcome.pitch`; its reviewed text now goes into the three
  `gallery.welcome.pitch.*` keys. A fourth paragraph = new key + entry in
  `PITCH_PARAGRAPHS`.
- The pitch still mirrors the gate page's press facts
  (`backend/api/gate_page.py`) — unchanged here.

## Deployment handover

Frontend image only. No environment variable, no migration, no cache flush.

## Verification (Node 22)

`vue-tsc --noEmit` clean · `eslint .` clean · `prettier --check` clean ·
`vitest run` **370 passed** · `vite build` OK.

## Commit split

- `feat(gallery): pitch in three paragraphs, calls to action under the headline` — component + locales.
- `docs: landing intro manifest and README` — README + this file.
