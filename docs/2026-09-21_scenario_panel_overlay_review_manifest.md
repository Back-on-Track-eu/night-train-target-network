# Scenario panel overlays: review round — manifest

Date: 2026-09-21 · Scope: **frontend only.** No backend change, no version
bump.

## Text changes (EN / DE)

| Key | New text |
|---|---|
| `compare.scenarioHint` | *Examine your route under different scenarios. Each combines a rail network with operating conditions and, soon, price measures; the baseline is today's network and rules.* / *Prüfe Deine Strecke in verschiedenen Szenarien: Netz, Betriebsbedingungen und bald auch Preismaßnahmen. Basisszenario ist das heutige Netz mit heutigen Regeln.* |
| `compare.kpiHints.shiftAir` | *Would otherwise have flown; the share grows with journey length (none under 300 km, all from 1,200 km). Interim manual demand model — an automatic one is coming.* / *Wären sonst geflogen; der Anteil wächst mit der Reiseweite (keiner unter 300 km, alle ab 1.200 km). Vorläufiges manuelles Nachfragemodell – bald automatisch.* |
| `compare.kpiHints.shiftOther` | *The remaining passengers: half would have driven, half would not have travelled at all (induced trips). Interim manual demand model — an automatic one is coming.* / *Die übrigen Reisenden: die Hälfte wäre Auto gefahren, die andere gar nicht gereist (Neuverkehr). Vorläufiges manuelles Nachfragemodell – bald automatisch.* |

Every overlay of the panel still wraps to **four lines or fewer** at the
overlay width (checked with Liberation Sans 14 px, Arial-metric), in both
languages.

## Feedback link on every overlay

The eight KPI tiles' overlays and the two "coming soon" overlays on the
scenario switches now carry *Provide feedback*, topic `kpis`, with the KPI
label in the subject (e.g. `Shift from air · Luxembourg → Bratislava`). The
panel title already had it. In the gallery's scenario panel, which reuses
the switches, there is no route context, so the link does not render there.

## Updates by file

| File | Change |
|---|---|
| `frontend/src/components/MainKpiGrid.vue` | `feedback-topic="kpis"` + `feedback-panel` (KPI label) on every tile's ⓘ. |
| `frontend/src/components/ScenarioSwitches.vue` | Same topic on the two "coming soon" ⓘs; header comment notes the gallery case. |
| `frontend/src/i18n/locales/en.json`, `de.json` | The three keys above. 899 keys each, in parity. |

## Deployment handover

Frontend image only.

## Verification (Node 22)

`vue-tsc --noEmit` clean · `eslint .` clean · `prettier --check` clean ·
`vitest run` **376 passed** · `vite build` OK.

## Commit split

- `chore(i18n): scenario panel overlays — scenario hint, interim demand note` — locales.
- `feat(builder): feedback link on every scenario-panel overlay` — components.
- `docs: overlay review manifest` — this file.
