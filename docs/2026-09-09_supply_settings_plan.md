# Supply & settings rework — implementation plan, 2026-09-09

The composition detail, frequency, seasonality, fares, fleet and staffing
changes David specified on 2026-09-09. Written so the next session can
execute it phase by phase; the decisions are settled, the numbers are
sourced from the code as it stands.

What shipped already (frontend, `supply-settings-phase1.zip`): the selected
row stays in sort order; revenue-by-class uses `CLASS_COLORS`; every supply
figure carries an ⓘ. Everything below is still open.

---

## 0. Decisions (David, 2026-09-09)

| | Decision |
|---|---|
| Seasonality | Frequency **per month**: `days_per_week` 0–7 for each of the twelve months |
| Trainsets | **Physical integer from a cycle-time rule** (§2) with a `min_turnaround_min` parameter, default 180. Display the integer AND the theoretical float the cost model charges (`integer / coach_avail_per`) |
| Fleet peak | Trainsets = **max over months** — the fleet covers the busiest month |
| Fares | **Per proposal**: on the request, in the family key, saved with the proposal |
| Loco | Leased by the hour; **show loco hours** per trip and per year |
| Staffing | Show **real headcount per train** (drivers, train chief, attendants), hours per trip, € per trip |
| Detail view | The overlay goes; everything it showed, plus the above, lives in the selected-composition panel |
| ⓘ | **Every number** gets an InfoHint now; the link into the documentation catalogue is a later, mechanical pass |

---

## 1. Schedule: per-month frequency

**Domain** (`models/route/route.py`): replace `Season` / `Frequency` /
`SeasonalSchedule` with

```python
@dataclass
class Schedule:
    days_per_week_by_month: dict[int, int]   # 1..12 → 0..7, 0 = not operating

    def operating_days(self, month: int) -> float:
        return calendar.monthrange(YEAR, month)[1] * self.days_per_week_by_month[month] / 7

    @property
    def operating_days_per_year(self) -> float: ...
    @property
    def peak_days_per_week(self) -> int: ...
```

`WEEKS_PER_SEASON` and `DAYS_PER_OPERATING_WEEK` in `route/model.py` are
retired; `YEAR` stays the evaluation year already used for prices.

**Request** (`api/helpers/member_compute.py`): `schedule_mode` gains
`"custom"`; a `schedule` block is required with it and rejected without it:

```json
"schedule_mode": "custom",
"schedule": { "1": 7, "2": 7, "3": 5, "4": 5, "5": 7, "6": 7,
              "7": 7, "8": 7, "9": 7, "10": 5, "11": 5, "12": 7 }
```

`"alwaysDaily"` stays the default and means 7 in every month. Validation:
twelve keys, ints 0–7, at least one month > 0.

**Strategy** (`models/route/timetable.py`): `custom_schedule(schedule)`
beside `always_daily_schedule()`; `VALID_SCHEDULE_MODES` gains `"custom"`;
one branch in `route_factory.plan_route()`.

**Wire** (`api/helpers/route_serialize.py`): `route["schedule"]` becomes
`{"days_per_week_by_month": {...}}`. `route_from_dict()` must also read the
old `seasonal_schedules` shape — stored proposals carry it until the refresh
run.

**Everything downstream that reads `operating_days_per_year`** is unchanged
in interface; `models/demand/stopgap.py` and `evaluation/summary.py` keep
calling it.

## 2. Trainsets: the cycle-time rule

`TripPair.composition_count()` today: `2 if daily else 1`, divided by
`coach_avail_per`. It becomes two figures.

**Physical** — walk one rake through the pair's own timetable:

1. Depart A at the outbound's departure minute.
2. Arrive B; the earliest return is the first scheduled B-departure at least
   `min_turnaround_min` later. If tomorrow's slot is the first that fits,
   the rake loses a day.
3. Same at A.
4. `cycle_days` = calendar days until the rake is at A in time for a
   scheduled departure.

Then, per month, `trainsets_m = ceil(cycle_days × days_per_week_m / 7)`,
and `trainsets = max_m trainsets_m`. A normal night train (arrive morning,
depart evening) has `cycle_days = 2`: daily → 2, three-a-week → 1,
four-a-week → 2. A turnaround that misses the minimum pushes the rake to
the next day's slot, so daily needs 3 — David's "each turnaround not
fulfilled needs an extra trainset" falls out without a special case.

**Stated assumption** (goes in `route/model.py` OPEN_TODOS and the model
doc): the `ceil` formula assumes departure days are spread evenly through
the week. Mon/Tue/Wed three-a-week would need 2 rakes; we do not model
which weekdays.

**Theoretical** — `trainsets / coach_avail_per`, unchanged as the cost
basis for amortisation, financing and cleaning. The cost model is
untouched in meaning; only its input changes from the 1-or-2 rule to the
physical count.

**Parameter**: `min_turnaround_min` on the request (HOW), default 180,
validated ≥ 0. In the family key.

`ROUTE_BUILDER_VERSION` bump: schedule shape + trainsets rule.

## 3. Fares per class as a request input

`STOPGAP_FARE_PER_KM_BY_CLASS` in `models/demand/model.py` stays as the
**default**. The request gains

```json
"fares_eur_per_km": { "Seat": 0.10, "Couchette": 0.13, "Sleeper": 0.18, "Capsule": 0.12 }
```

validated (known `class_main`s, positive, Catering forced 0), threaded into
`distribute_demand()`, echoed in `compute_request` so a published proposal
carries what it was priced at. Defaults published on `GET /api/models`
under `models.demand.fares_eur_per_km` so the frontend never hard-codes
them. `CALC_VERSION` bump.

## 4. The `operations` block per member

New, from calc objects that already exist (`calc.py` computes
`driver_hours`, `crew_hours`, `dwell_*_hours` per segment and stop, and
loco hours before multiplying by the lease rate — the hours are currently
discarded on the way to the wire). Per trip pair, route total summed:

```json
"operations": {
  "trainsets": { "physical": 2, "theoretical": 2.30, "coach_avail_per": 0.87,
                 "peak_month": 8, "cycle_days": 2, "min_turnaround_min": 180 },
  "loco_hours": { "per_trip": 15.5, "per_year": 10850 },
  "staffing": {
    "drivers":     { "on_board": 1, "hours_per_trip": 14.5, "roster_efficiency": 0.78, "eur_per_trip": 0 },
    "train_chief": { "on_board": 1, "hours_per_trip": 0, "roster_efficiency": 0, "eur_per_trip": 0 },
    "attendants":  { "on_board": 4, "per_coach": 0.5, "hours_per_trip": 0, "roster_efficiency": 0, "eur_per_trip": 0 },
    "total":       { "hours_per_trip": 0, "eur_per_trip": 0, "eur_per_year": 0 }
  }
}
```

Headcount from the composition's `driver_factor`, `zugchef_crew_factor`,
`crew_factor_coaches × n_coaches`. It rides on the member's **views**
response (it is per member and ~1 KB, so D9's "views on demand" applies),
not on the family document. `roster_efficiency` is exposed for the first
time — it needs its ⓘ with the calibration source before it ships.

## 5. Supply KPIs on the summary

`departures_per_year`, `trainsets_physical`, `trainsets_theoretical`,
`loco_hours_per_year` added to `build_summary_row()`; train-km and place-km
are already there. `FAMILY_DOCUMENT_FORMAT` bump.

## 6. Family key

`family_key()` folds in `schedule`, `min_turnaround_min`, `fares_eur_per_km`
(all HOW). Consequence to state in the frontend: moving any of them rebuilds
the whole family (~1.5 s warm), unlike a scenario switch.

## 7. Frontend

- **Overlay → panel**: `SupplySidebar` absorbs `CompositionDetailOverlay`'s
  formation strip, equipment list and per-km KPIs; the overlay component
  and its trigger in `SupplyTable` are deleted. Then the new sections:
  trainsets (integer bold, theoretical small beside it), loco hours, the
  staffing table (role · on board · h/trip · €/trip), the composition cost
  lines from the Breakdown (coach maintenance, amortisation, financing,
  cleaning, shunting, loco lease). All for the member on screen.
- **Frequency & months**: a 12-column mini-grid, one 0–7 stepper per month,
  with "all 7" / "weekdays" / "weekends" presets. Plus `min_turnaround_min`
  as an input beside it. HOW → `paramsStale` → Recalculate. Live client-side
  preview of departures / train-km / places / place-km before recompute
  (arithmetic on data already on screen), replaced by the backend's figures
  after.
- **Pricing panel**: four €/km inputs, defaults from `GET /api/models`,
  colour-swatched with `CLASS_COLORS`. HOW → stale → Recalculate.
- **⓵ everywhere**: `InfoHint` on every figure the panel shows, text = the
  definition, `docPath` prop added to `InfoHint` now (rendered as a link when
  set) so the catalogue linkage later is data, not code.
- **`api.ts`**: request additions (`schedule`, `min_turnaround_min`,
  `fares_eur_per_km`), `operations` on the views response, summary fields.
  This is a Bjarne coordination item — put it in `FRONTEND_HANDOVER.md` §18.

## 8. Order and gates

| Phase | Scope | Gate |
|---|---|---|
| 2 | §1 schedule + §2 trainsets + §6 key + `ROUTE_BUILDER_VERSION` | `test_20_route_content`, new trainsets table test, family-key sensitivity test, integration suite against the live stack |
| 3 | §3 fares + `CALC_VERSION` | validation tests, `test_31_evaluation_content` |
| 4 | §4 operations + §5 summary + `FAMILY_DOCUMENT_FORMAT` | views tests, `generate_model_docs.py --check` |
| 5 | §7 frontend, all of it | vue-tsc, eslint, prettier, vitest, **vite build** |
| 6 | Docs: `FRONTEND_HANDOVER` §18, `DEPLOY_HANDOVER` (refresh run rewrites stored `schedule`), `MODEL.md` regen | CI |

Phases 2–4 are backend and each ends with the integration suite on a
rebuilt api image; none of them can be verified without one. Phase 5 has
no meaning before 2–4 land. Do not collapse them.

## 9. Not decided, decide before phase 2

- Which weekdays for a non-daily month — model it, or keep the even-spread
  assumption? (Recommendation: keep it, state it.)
- Whether `min_turnaround_min` is per proposal or per composition
  (a 14-coach rake needs longer than a 6-coach one). Per proposal is what
  was decided; per composition is more honest and costs one column in the
  compositions catalog.
- The stored-proposal refresh: the schedule shape change means every stored
  route re-serialises. Coupled deploy like WP18 B2b — Giovanni.
