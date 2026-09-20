# Gallery polish — phase 4 manifest (2026-09-20)

Card follow-ups from the screenshots: no wrapped values, one vocabulary across
legend and filters, a hairline above the metadata foot, flags moved up to the
stop list, and the subsidy-per-tonne KPI. **Frontend only** — no API change, no
migration, no version bump.

## Items

| Feedback                                       | Solution                                                                     |
| ---------------------------------------------- | ---------------------------------------------------------------------------- |
| "13,013 t CO₂/yr saved" wrapped onto two lines | Label shortened to "{value} t CO₂/yr" and every cell set `whitespace-nowrap` |
| Legend and filter used different words         | "Proposals" / "Existing" everywhere, both locales                            |
| Missing rule between the figures and the foot  | Second hairline restored on the foot                                         |
| Flags belong with the stops                    | `CountryFlags` moved to the head of the itinerary block                      |
| Subsidy per tonne of CO₂ missing               | New KPI from `subsidy_eur_per_t_co2`, straight after CO₂ saved               |

## Files touched

### `frontend/src/components/ProposalCard.vue`

- **No wrapping.** The CO₂ label lost the trailing "saved" (the hover
  explanation already says it), and the value span is `whitespace-nowrap`. The
  grid only works if every cell is one line.
- **Subsidy per tonne** (`subsidy_eur_per_t_co2`, `mdiCashMultiple`), rendered
  through `lib/money.ts`'s `formatEur` so it prints like every other euro figure
  in the app. Placed directly after CO₂ saved: the saving and its price are one
  argument. Null until the proposal has an evaluation snapshot, as with the
  other KPIs. Grid order is now distance, speed, trips/yr, CO₂/yr, €/t CO₂,
  composition.
- **Flags to the top**, centred above the origin — they describe what the route
  crosses, not who proposed it.
- **Hairline above the foot** restored, so the card is three fenced blocks
  rather than two plus a trailing line.

### `frontend/src/i18n/locales/en.json`, `de.json`

- `gallery.map.legend.proposed/existing` → "Proposals" / "Existing"
  ("Vorschläge" / "Bestehend"), matching `gallery.source.*`.
- `gallery.card.existing` badge → "Existing" / "Bestehend".
- `gallery.card.co2PerYear` → "{value} t CO₂/yr" / "{value} t CO₂/Jahr".
- New `gallery.card.subsidyPerTCo2` ("{value}/t CO₂") and its
  `gallery.card.stat.subsidyPerTCo2` explanation in both locales.

### `frontend/README.md`

- Card paragraph updated (flags at the head, the six-slot grid, the one-line
  rule, money via `lib/money.ts`), plus a short "one vocabulary" note naming the
  three keys that have to stay in step.

### `docs/2026-09-20_gallery_polish_phase4_manifest.md`

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

- The card grew: a flag row at the top, a sixth figure and a second hairline add
  roughly 50 px, so an evaluated proposal now stands at about 265 px and a
  1080p screen shows two and a half of them rather than three. Dropping the
  "Gallery / Browse what people have suggested so far." heading buys ~55 px back
  — say the word and it goes.
- Subsidy per tonne can be negative (a route that earns more than it costs) and
  prints as such. If a negative figure should read as "no subsidy needed"
  instead, that is a label change, not a model one.
- The euro format is the app-wide rule from `lib/money.ts` ("142.00 €/t CO₂").
  On a card, two decimals may be more precision than the eye needs — a
  card-local rounding would be the exception to that rule, so I left it alone.
