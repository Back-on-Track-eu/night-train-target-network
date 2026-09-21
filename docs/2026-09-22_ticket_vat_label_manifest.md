# VAT labels name each country's rate; relay fix — manifest

Date: 2026-09-22 · Scope: **frontend only.** No backend change, no version
bump. Follows the 2026-09-21 ticket VAT delivery.

## Decision (David, 2026-09-22)

The effective rate uses each country's **international-leg** rate — what a
passenger is charged on a cross-border ticket today (Germany 7 % on its
kilometres, Switzerland 0 % on its own, since MWSTV Art. 42 exempts the
Swiss leg of an international rail journey) — not the domestic rates
weighted regardless of the border. Both columns stay in the table; the
choice is one line in `lib/ticketVat.ts`.

## What changed

- **The make-up is visible, not only on hover.** The example-fare headers
  read *incl. VAT 5 % · DE 7 %, CH 0 %* (countries in descending distance
  share; a country the table lacks shows a dash), and the *Ticket revenue
  incl. VAT* note reads *5 % (DE 7 %, CH 0 %) · not in the cost and revenue
  calculation*. The hover keeps the distance shares (*DE 7 % on 72 % of the
  distance · CH 0 % on 28 %*).
- **Relay fix** (already sent separately as `ticket-vat-relay-fix.zip`):
  `ProposalResults` now declares `ticketVat` and hands it to the Details
  card — the reason the first delivery showed no VAT at all.

## Updates by file

| File | Change |
|---|---|
| `frontend/src/lib/ticketVat.ts` (+ test) | `vatRatesByCountry()`; seven tests. |
| `frontend/src/components/details/PlacesPricesPanel.vue`, `WhatFollowsPanel.vue` | Labels carry the per-country rates. |
| `frontend/src/components/ProposalResults.vue` | The relay (unchanged from the fix zip). |
| `frontend/src/i18n/locales/en.json`, `de.json` | `prices.inclVat`, `follows.vatRate` gain `{countries}`. 914 keys each, in parity. |

## Verification (Node 22)

`vue-tsc --noEmit` clean · `eslint .` clean · `prettier --check` clean ·
`vitest run` **383 passed** · `vite build` OK.

## Commit split

- `fix(builder): relay ticketVat to the Details card; name each country's VAT rate on the labels` — components, lib, locales.
- `test: VAT rates-by-country label` — test file.
- `docs: manifest` — this file.
