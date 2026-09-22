# Report menu (route / timetable) and German review of the builder — manifest and handover

Date: 2026-09-21 · Scope: **frontend + documentation site.** No backend change,
no version bump — both topics use existing `Route or timetable` sub-categories.

## Report menu

The report button in the map pill opens a two-item menu:

| Item | Topic alias | Sub-category | Lead sentence asks about |
|---|---|---|---|
| Problem with the route | `routing` | Routing / track geometry | detours, lines avoided, borders, distance |
| Problem with the timetable | `timetable` | Schedule / timetable / frequency | unrealistic hours, legs too fast or slow, the night on the wrong section |

Both carry the same parameter block, which now also lists each direction's
first departure and last arrival (`Outbound: 19:30 Budapest-Déli → 09:31 (+1)
Bruxelles-Midi`). One block for both on purpose: a timetable problem is often a
routing one in disguise.

## German review

Every German string of the builder (`proposal.*`, 737 keys) and of `errors.*`
was read against its English source. What changed, by kind:

- **Baseline → Basisszenario** in the KPI tiles (`isBaseline`, `noBaselineYet`,
  `vsBaseline`) and in the scenario overlay; `errors.scenariosUnavailable` no
  longer says "Live-Basis".
- **Wrong meaning.** `compare.change` was the noun *Veränderung* for the verb
  link "change ↓" → *ändern ↓*. `compare.breakEven` called the colour
  *Bernstein* → *Orange*. `groupsPanel.info`/`rule` said *erste Klasse* for "the
  first listed class" — read as first class → *erstgelistete Klasse*.
  `overhead.fixed.info` opened with *Der Betreiber im Betrieb seiner selbst*.
- **Rail and regulatory terms.** Composition is *Zugbildung* throughout (it was
  *Wagenreihung* in eight places; *Wagenreihung* stays only for the coach-order
  view). High-speed line is *Schnellfahrstrecke* throughout. OD pair is
  *Relation*. Induced traffic is *Neuverkehr*. Track access "at direct costs" is
  *zu unmittelbaren Kosten* (the regulatory term), not *Grenzkosten*. Night
  trains as *eigenes Marktsegment*, the term of the track-access system.
- **Anglicisms and odd constructions.** *pinnen/gepinnt* → *fixieren/fixiert*;
  *Panels* → *Bereiche*; *Eintrittspreis* → *Sockelpreis*; *Jahresblätter* →
  *Einzelposten*; *Zeilen steigen ein* → *Zeilen: Einstieg*; *€ / Reisendem* →
  *€ / Person*; *Automatik* → *automatischer Fahrplan*.
- **A grammar bug in a template.** The stale-inputs line joined capitalised
  scope names mid-sentence ("Der Fahrplan und Die Preise wurden geändert"). It
  now reads *Geändert: Fahrplan und Preise. Bereiche, die davon abhängen, …* —
  no capitalisation and no singular/plural agreement to get wrong.
- **One address form.** *Du* capitalised, as in the heading and the gallery:
  *Dein Vorschlag*, *Deine eigene Kopie*, *Bleib dran!* (was *Bleibt dran!*).
- **Typography.** Spaced em dashes → spaced en dashes, the German convention.
- **Your own line.** *Nicht das in unseren Daten gefunden, was Du suchst?* →
  *Nicht in unseren Daten gefunden, was Du suchst?* — word order only.

Every overlay text still wraps to four lines or fewer at the overlay width
(checked with Arial metrics, wider than Mark Pro), in both languages.

**Not touched:** the gallery strings (under your own review in
`gallery-texts-review.xlsx`; one inconsistency there — *deine* lowercase in
`gallery.filter.disabledHint`), and a handful of builder keys no component
uses any more (`supply.sidebar.*`, `settings.demand.*`,
`evaluation.demand.estimate*`) — stale in both languages, candidates for
removal rather than translation.

## Updates by file

| File | Change |
|---|---|
| `frontend/src/components/MapShareBar.vue` | `feedbackHrefs` (route + timetable) replaces `feedbackHref`; the report button opens a two-item menu styled like the share menu. |
| `frontend/src/components/ProposalViewport.vue` | `reportHrefs` builds both links; `tripSpanText()` / `reportTimes` add each direction's span to the parameter block. |
| `frontend/src/lib/feedbackLink.ts` (+ test) | `FEEDBACK_TOPIC_TIMETABLE`; `RoutingReport.times`; two new context lines. |
| `frontend/src/i18n/locales/en.json` | `share.report`, `share.reportRoute` (reworded for the menu), `share.reportTimetable`. |
| `frontend/src/i18n/locales/de.json` | The same three, and the review above. |
| `docs-site/.vitepress/theme/components/GeneralFeedbackForm.vue` | `timetable` topic; the routing lead now asks about distance rather than travel time, which is the timetable's topic. |

## Frontend handover

- A new report topic needs the alias in `lib/feedbackLink.ts`, an entry in the
  form's `TOPICS`, and a sub-category that exists in
  `api/helpers/feedback_serialize.py`.
- German terminology is now consistent; keep it so: *Zugbildung*,
  *Schnellfahrstrecke*, *Relation*, *Neuverkehr*, *Basisszenario*, *fixieren*,
  *Du* capitalised, spaced en dash.

## Deployment handover

Frontend image only. No environment variable, no migration, no cache flush.

## Verification (Node 22)

`vue-tsc`, `eslint`, `prettier --check` clean · `vitest run` **370 passed** ·
`vite build` OK · `vitepress build` OK · EN/DE at 887 keys each, in parity.
