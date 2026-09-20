# Gallery — text review applied (2026-09-20)

David's edits from `gallery-texts-review.xlsx`, plus the two comments.
Frontend only.

## Applied from the sheet

| Key                                        | Change                                                                                              |
| ------------------------------------------ | --------------------------------------------------------------------------------------------------- |
| `gallery.section.subtitle`                 | DE: "Schau Dir an, was andere vorgeschlagen haben."                                                 |
| `gallery.scenario.hint`                    | DE: "Deiner" (capitalised address)                                                                  |
| `proposal.compare.axes.infra`              | EN: "Infrastructure {network}" — also used by the builder's axis, deliberately                      |
| `proposal.compare.axes.networkPreviewHint` | EN and DE rewritten as given (one typo fixed: "infrastructure")                                     |
| `gallery.empty`                            | DE: "Für diesen Filter wurden keine Vorschläge gefunden. Sei der Erste, der einen Vorschlag macht!" |

## The two comments

- **Pitch — "rather take a shortened version from the gate page".**
  `gallery.welcome.pitch` is now a four-sentence condensation of the launch
  gate's press text (`backend/api/gate_page.py`): 150 → 300 connections and
  tripled passengers by 2032; draw routes on a real map and see cost and CO₂
  at once; the best designs feed the 2032 study for DG MOVE and national
  authorities; a closing link to the position paper. EN and DE. The template
  has always offered a `{source}` link slot that the old copy never used —
  the new copy uses it, `gallery.welcome.source` became "the position paper
  behind these numbers" / "das Positionspapier hinter diesen Zahlen", and
  `LandingIntro.vue`'s link now points at the same page the gate cites.
- **CO₂ popover — "adjust as suggested".** The sentence "Derived from
  placeholder demand figures, not yet from a full demand model" is gone from
  the CO₂ body **and** the demand body (the same sentence, the same reason:
  DEMAND 0.1.0 made it untrue), in both languages.

Unused keys (`gallery.card.distance`, `gallery.end`) left in place — no
"delete" comment.

## Files touched

- `frontend/src/i18n/locales/en.json`, `de.json`
- `frontend/src/components/LandingIntro.vue` — position-paper URL and the
  comment on the `{source}` slot.

## Gates

prettier, eslint, vue-tsc, 332 vitest cases, `vite build` — green.
