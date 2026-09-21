# "2032 prices" sticker, overlay and docs page — manifest and handover

Date: 2026-09-21 · Scope: **frontend + documentation site.** No backend
change, no version bump.

## What changed

- **Sticker.** An amber *2032 prices* chip on the two headlines that put
  euros on screen: *Details* (the card's summary) and *Costs and revenue*.
  Same treatment as the other "mind this" chips (stale results, coming
  soon), so it reads as a caveat. On hover, focus or click it opens the
  standard overlay: the rule in four lines (*All costs and fares are 2032
  money, escalated from each source's price year at a documented rate. One
  exception: rolling stock is bought now, its price stays at 2026.*), *Read
  more in the documentation* and *Provide feedback* (breakdown topic,
  subject `2032 prices · A → B`). Inside the breakdown's `<summary>` its
  clicks are stopped so the section does not toggle.
- **Docs page** _Price basis: 2032 prices_ (`/docs/price-basis`), in the
  sidebar under _The model_: why 2032, the once-only conversion in the
  calibrations, the rolling-stock exception and why escalating it would
  double-count, the per-domain rate table (labour/lease, track access 3 %,
  energy 2 %, shunting 2.5 %, stabling 2 %, fares at 2032), what is
  deliberately not escalated (purchase price; maintenance, cleaning and
  stockings at 2026 as the optimistic side; station charges at their
  published year, escalation planned) and what the price year means for
  ratios versus single lines.
- **A wrong sentence on the rolling-stock page corrected.**
  `methodology/compositions.md` said purchase prices are "stated at the 2032
  evaluation year, escalated from their source year". They are not — the
  calibration's own price-basis policy (CALIBRATION.md rule 2) keeps them at
  the 2026 contract basis. The paragraph now says so and links the new page.

## Updates by file

| File | Change |
|---|---|
| **new** `frontend/src/components/PriceBasisBadge.vue` | The chip with its overlay (`InfoPopover` + `DocsReadMore` + `FeedbackLink`). |
| `frontend/src/components/DetailsSection.vue`, `CostRevenueBreakdown.vue` | Chip on the headline. Both contain today's earlier changes — extract after those zips. |
| `frontend/src/lib/docsLinks.ts` | `DOCS_PRICE_BASIS`. |
| `frontend/src/i18n/locales/en.json`, `de.json` | `proposal.priceBasis.badge` / `.hint`. 910 keys each, in parity. |
| **new** `docs-site/price-basis.md` | The page. |
| `docs-site/methodology/compositions.md` | Purchase-price paragraph corrected. |
| `docs-site/.vitepress/config.ts` | Sidebar entry after _Views of costs and revenue_. |

## Worth deciding

- The page states station charges are **not yet escalated** (the charges
  notebook carries `price_basis_year` per reading and applies no factor —
  HANDOVER.md: "escalation to 2032 happens once, later"). If that is to be
  fixed rather than documented, it is a notebook change plus reseed and an
  `INFRA_MODEL_VERSION` bump; the page's sentence would then go.
- Placement: the sticker sits on the Details and breakdown headlines as
  asked. It would fit the scenario panel's *Necessary subsidy* tile too; not
  done, so the panel keeps one message.

## Deployment handover

Frontend image only (docs bundle included). No environment variable, no
migration, no cache flush.

## Verification (Node 22)

Frontend: `vue-tsc --noEmit` clean · `eslint .` clean · `prettier --check`
clean · `vitest run` **376 passed** · `vite build` OK.
Docs site: `prettier --check` clean · `vitepress build` OK.

## Commit split

- `docs(site): price basis — 2032 prices, the rolling-stock exception, rates per domain` — docs-site files.
- `feat(builder): "2032 prices" sticker with overlay on the Details and breakdown headlines` — frontend files.
- `docs: price basis manifest` — this file.
