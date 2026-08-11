# TAC Calculation — Design Decisions

What `backend/models/infrastructure/calc_tac.py` implements, and why it
implements it that way. The tariff facts themselves live in
`TAC_MODEL.md`; the numbers in `02_tac_calibration.ipynb` (both in this
same `calib/tac/` folder); this document
records the decisions made when turning both into running code
(2026-07-28, CALC_VERSION 0.9.11 / ROUTE_BUILDER_VERSION 0.9.13).

## Two night mechanisms, not three

`track_tac_night_mode` has exactly two values: `none` and `time_band`. An
earlier `segment` mode for Germany was dropped — the DE tariff is a band
tariff (Nacht 23:00–06:00, pro-rata like IT/BE/PT), and the SPFV rule is
a band *widening*, not a separate mechanism: a train carrying night
accommodation is priced Nacht over its **entire German run**. That
widening is the boolean `track_tac_night_full_if_accommodation`, and it
is evaluated **timetable-independent from the composition**
(`Composition.has_night_accommodation`: any place whose `class_main` is
not Seat or Catering — a dining car alone does not make a night train).
CH deliberately sits in `none`: its 22:00–06:00 band belongs to
electricity pricing (03), not track access.

## NULL means "not levied" — group resolution only

A NULL component is a documented tariff fact (FI charges per
gross-tonne-km *only*; its NULL `b_day` must price at zero), never
missing data. Per-field default substitution would therefore corrupt
calibrated countries. Resolution against the default row happens as a
**group**, only when `b_day`, `b_night` and `gamma` are ALL NULL
(`DBDataLoader._row_to_track`) — i.e. the country has no usable charging
term at all (in practice only CY/MT, which have no railway). The default
group is `b_day` only, set to the median of the calibrated per-country
NT-REF rates: a synthetic country charging both a train-km AND a tonne-km
term would overstate.

## The flat column is display-only

`track_tac_eur_train_km` stays in the schema as the indicative NT-REF
rate for tables and the frontend, but **the cost model never reads it**.
`tests/test_72_calc_tac_units.py` enforces this by construction: every
track stub carries an absurd flat (999 999) and every assertion still
reproduces the calibration numbers. SE keeps its flat NULL in the seed —
it is the suite's is_default fixture (test_04) and loses nothing, since
its component group is seeded normally.

## Clock placement inside a segment

A segment's country windows are placed on the clock by walking
`segment.countries` (the ordered path from routing, ROUTE_BUILDER 0.9.13)
and splitting the segment's departure→arrival span by
`country_time_shares`. Band overlaps are then computed per window with
wrap-safe minute arithmetic (`models/utils.band_overlap_min`), never by
picking the window's midpoint. `UNK` slices (ferries, open water) own
time but no tariff: they advance the cursor without being charged, so the
country after a crossing lands at the correct clock time. Pre-0.9.13
route payloads carry no `countries` list; the serializer falls back to
the share dict's keys — segment stays evaluable, path ordering (and with
it exact clock placement for multi-country segments) is approximated.

## Peak surcharges: active conservative defaults

AT's congestion surcharge (flat EUR/train-km) and CH's peak factor (×2 on
the day-rate term) apply to the peak-overlapping share of a run. Both
formally apply only on declared overloaded/high-load sections; the model
applies them blanket on the peak overlap because a night train's morning
approach into Wien Hbf or Zürich HB plausibly touches such a section, and
pricing every unconfirmed approach as free would systematically
understate cost in exactly the pattern night trains run. Weekday-only
bands are priced at their expected value, `WEEKDAY_BLEND = 5/7` — the
model has clock minutes, not service dates. The two terms are kept as
separate result fields (`congestion_eur` folded next to the multiplier's
base effect) so views can show a congestion charge as such.

## Per-stop terms

The CH Haltezuschlag is a capacity element of the path price, not a
station-usage fee — it belongs to TAC (no double-counting with the stop
charge model). Each stop is charged at **its own country's** per-stop
rate; a trip's first segment charges both of its ends (the origin stop
would otherwise never be counted).

## Passages

Storebælt, Øresund and the Channel Tunnel are separately charged
crossings — per traverse, not per km — modelled as dedicated entities in
`input_params.passage_charges` (the fifth scenario-versioned table, same
full-snapshot contract). Detection happens at ROUTING time
(`rail_router.PassageIndex`): the first trip leg intersecting a crossing
polygon owns it, recorded on the segment as `passages`. Øresund is one
polygon with two charge rows (`OERESUND_DK` / `OERESUND_SE`) — each IM
bills its half of the crossing. The Channel Tunnel's per-passenger term
is evaluated against the segment's passenger load per train run (annual
demand ÷ operating days, distributed along the OD path in the traffic
pre-pass). An unknown passage id in a payload is warned and skipped, not
fatal — a stale route must stay evaluable.

## Revenue share (CH Deckungsbeitrag)

First-class parameter, fully plumbed (`revenue_share × attributable
segment revenue`), currently NULL everywhere because the authority-set
percentage is not published. The traffic pre-pass in
`models/evaluation/calc.py` distributes route revenue distance-weighted
along each OD path, so the moment a value lands in the DB the charge
computes without code changes.

## Currency and price basis

All DB values are EUR. FX conversion happens exactly once, in
`06_seed_export.ipynb` (`FX_TO_EUR`), per component using each sourced
value's own currency. `calc_tac.py` never sees native currency.

## Locomotive weight

Tonnage terms price the full consist: coaches plus
`n_locos × loco_weight_t`. 90 t (Vectron-class) is a constant on every
catalog composition until the compositions calibration workbook carries a
per-type value (`composition_type_loco_weight_t`).

## Known understatements (accepted, documented)

- **BE day fringe**: only `b_night` is calibrated; the fraction of a
  Belgian run outside the 19:00–05:59 band prices at zero instead of the
  (higher) day/peak coefficients. Understates BE for early-evening
  departures.
- **CY/MT**: no railway, no seed row — their TAC columns are NULL and the
  loader substitutes the default group with a warning. Unreachable by
  routing, so this never prices a real leg.
