# CO₂ → CO₂e, checked against the Back-on-Track emissions study — manifest and handover

Date: 2026-09-21 · Scope: **frontend strings, documentation site, docs generator
prose.** No model change, no version bump, no stored figure changes.

## What the study says, and how the model compares

Source: Back-on-Track (2022), *The Global Warming Reduction Potential of Night
Trains*, report v1.1 and its Figure 3.

| Point | Study | Model (EMISSIONS 0.2.0) | Verdict |
|---|---|---|---|
| Factors | plane 389, car 132, night train 14 g **CO₂e** per person-km | 389 / 132 / 14 | ✔ identical |
| Unit | CO₂-equivalent, well-to-wheel, EU mix 2019 | stored as `co2_savings_t_per_year` (tonnes CO₂e) | ✔ value right, **labels said CO₂** |
| Aviation's non-CO₂ effects | radiative forcing factor 3.0 on the combustion CO₂ (GWP*, Lee et al. 2021) + 8 % distance uplift; IEA's 144 g is the figure without | included via the 389 | ✔ |
| Basis of the per-km factors | IEA 2019 GHG intensities (EEA is used for the EU totals) | model docstring says the factors "build on the EEA emissions data" | ✘ wording, see *Not done* |
| Night-train factor | IEA non-urban rail average, high load factor (report assumes 80 %) | flat 14 g/pkm whatever the train's utilisation | ⚠ known limitation, now stated |
| Mode shift | only air → night train counted; car named as additional potential | air by distance, car and induced (half/half), induced counted against | ⚠ broader than the study, now stated |
| Ratio | 1 : 28 | 389/14 = 27.8 | ✔ |

## What changed

- **Every live label now says CO₂e**: the KPI tile and the subsidy-per-tonne
  tile, their overlays, the passenger-km overlay, the gallery sort option, the
  card figures and card overlay titles, and the sign-up prompt's saving line.
  The CO₂e overlay now says it includes aviation's non-CO₂ warming — without
  that, a reader comparing with a CO₂-only figure gets a number almost three
  times larger than theirs and no reason why. (Overlays still ≤ 4 lines.)
- **Emissions page rewritten against the study**: CO₂e from the first line,
  IEA as the basis, the 144 g → 389 g step (factor 3.0, GWP*, current rather
  than 100-year warming, 8 % uplift), the 14 g as a conservative high-load
  average that ignores this train's utilisation, and a paragraph on how the
  model's mode shift differs from the report's.
- **CO₂e on the other docs pages** (scenarios, demand, known gaps, About) and
  in the generated prose under the emission-factors table — changed in the
  generator (`render_site.py`, `render_model_md.py`) and in its two outputs
  identically, so the `--check` drift gates stay green.

## Updates by file

| File | Change |
|---|---|
| `frontend/src/i18n/locales/en.json`, `de.json` | 11 keys per language as above; *CO₂* stays where it names the gas ("non-CO₂ warming", "Nicht-CO₂-Effekte"). |
| `docs-site/emissions.md` | Rewritten against the study. |
| `docs-site/scenarios.md` | *CO₂e saved*, *Subsidy per tonne of CO₂e*; anchors unchanged (explicit ids). |
| `docs-site/demand.md`, `not-modelled.md`, `index.md` | CO₂ → CO₂e. |
| `docs-site/reference/emission-factors.md`, `docs/MODEL.md` | Generated prose sentence → CO2e. |
| `backend/scripts/model_docs/render_site.py`, `render_model_md.py` | The same sentence at the source. |

## Not done — decide after the launch

- **`backend/models/emissions/model.py` wording.** Its comment and the 0.2.0
  changelog say the factors build on EEA data and that the EEA's CO₂-only
  160 g is what the non-CO₂ term separates from 389. The study's basis is the
  IEA (144 g without non-CO₂). Values are right; the provenance text is not.
  The file is version-gated: any edit forces an EMISSIONS bump, which marks
  every stored proposal outdated and recomputes it lazily. Not worth it the
  night before the launch; worth it in the next model round.
- **Gallery prose** (`gallery.welcome.pitch`: "how much CO₂ it would save") —
  left for the gallery text review; units on the cards are already CO₂e.
- **Load-dependent train emissions.** The study's 14 g assumes a well-filled
  night train; the model applies it to any utilisation. Belongs with the
  energy-based emissions model already named in the docs.

## Frontend handover

CO₂e is the unit of every emissions figure the app shows; CO₂ appears only as
the name of the gas. The API field names (`co2_savings_t_per_year`,
`subsidy_eur_per_t_co2`) are unchanged — they carry CO₂e and always did.

## Deployment handover

Frontend image only (docs are built into it). No environment variable, no
migration, no cache flush.

## Verification

Frontend: `vue-tsc`, `prettier --check` clean · `vitest run` 370 passed ·
`vite build` OK · EN/DE in parity. Docs: `vitepress build` OK. Generators:
`ruff format --check` / `ruff check` clean.
