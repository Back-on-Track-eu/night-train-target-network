# Gallery — "Mine" asks for login, KPI grid order (2026-09-20)

Frontend only, no API change.

## "Mine" without an identity

Clicking **Mine** while signed out opens the login / registration modal
(standalone context — no "continue as guest" fork; that one belongs to the
evaluation gate) and remembers the intent: the filter applies itself the
moment an identity exists, so the click means "show mine", not "show me a
form". Dismissing the modal drops the intent. A guest session already has an
identity and its own proposals, so a guest is filtered, not prompted.

## KPI grid on the card

| Row | Left        | Right                    |
| --- | ----------- | ------------------------ |
| 1   | distance    | average speed            |
| 2   | composition | passenger trips per year |
| 3   | CO₂ saved   | subsidy per tonne of CO₂ |

The route's physics, then what runs and who rides, then climate and its
price. Proposals without an evaluation snapshot show what they have, in the
same order.

## Files touched

- `frontend/src/components/Gallery.vue` — `mineAfterAuth` intent, `applyMine()`,
  the two watchers (identity arrives → apply; modal closed without one →
  drop).
- `frontend/src/components/ProposalCard.vue` — stat order.
- `frontend/README.md` — both paragraphs updated.

## Gates

prettier, eslint, vue-tsc, 332 vitest cases, `vite build` — green.
