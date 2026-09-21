# Gallery — hero rewrite, headline, subsidy price-level note (2026-09-20)

Frontend only.

- **Headline**: "Bring the night trains back on track!" /
  "Bringen wir die Nachtzüge zurück aufs Gleis!"
- **Pitch**: rewritten in the lighter voice of the original landing copy,
  roughly half again as long, carrying the press facts (300 connections,
  twice today's, three times the passengers; real map, cost, public money,
  CO₂, realistic timetables, twelve compositions, free and open source; the
  best suggestions become the backbone of the 2032 study for the Commission
  and national authorities; contributors credited) and closing on a link to
  Back-on-Track's reports and studies (`https://back-on-track.eu/reports-and-studies/`)
  instead of one paper. EN and DE.
- **Layout**: the headline is vertically centred on the paragraph
  (`items-center` on the hero row; it used to share the paragraph's top line).
- **Subsidy per tonne popover**: "All prices are scaled to 2032 price levels
  (inflation-adjusted)." / "Alle Preise sind auf das Preisniveau 2032
  hochgerechnet (inflationsbereinigt)."

## Files touched

- `frontend/src/i18n/locales/en.json`, `de.json` — `gallery.heading`,
  `gallery.welcome.pitch`, `gallery.welcome.source`,
  `gallery.card.stat.subsidyPerTCo2.body`.
- `frontend/src/components/LandingIntro.vue` — `STUDIES_URL` replaces
  `POSITION_PAPER_URL`; `items-center` on the hero row; comments.

## Gates

prettier, eslint, vue-tsc, 332 vitest cases, `vite build` — green.
