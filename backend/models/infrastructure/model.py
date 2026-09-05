"""
model.py
========
Version anchor for the infrastructure parameter model — the per-country
track and station parameters (track access charges, station charges,
energy prices, terrain, HSR permission, schedule buffer quotas, minimum
dwell times) and the stop catalog with its classification pipeline.

Its parameters live in the input_params tables (db/schema.py), versioned
as full-table snapshots pinned by scenarios; the stop classification
pipeline is documented in STOP_CLASSIFICATION.md. The formulas consuming
the parameters surface in the route builder's ROUTE_FORMULAS
(models/route/model.py) and the evaluation model's CALC_FORMULAS
(models/evaluation/model.py).

Each priced sub-domain owns a package: tac/ prices the calibrated track
access charge components for one segment (calc_tac.py), energy_pricing/
calibrates the traction energy price and the charges for supplying it. The standard
values that calculation assumes — rather than reads from a parameter
table — live here, so docs/MODEL.md can link them like any other.

Bump INFRA_MODEL_VERSION when the parameter model itself changes —
which parameters exist, how they resolve against defaults, how the
stop catalog is classified. A changed value alone is a data change and
follows the DB full-snapshot versioning rules instead.
"""

INFRA_MODEL_VERSION: str = "0.9.6"

INFRA_MODEL_DESCRIPTION: str = (
    "Infrastructure parameter model: per-country track access charges, "
    "station charges, traction energy prices, shunting and stabling, "
    "terrain, schedule supplements and minimum stopping times, with "
    "EU-average fallbacks — plus the catalog of possible night train "
    "stops. Four calibrated domains, each a package under "
    "models/infrastructure/ with its own source register, notebooks and "
    "published calibration document."
)

# =============================================================================
# STANDARD VALUES
# =============================================================================

WEEKDAY_BLEND: float = 5.0 / 7.0
"""Share of departures assumed to fall on a weekday. Austria and
Switzerland levy their congestion surcharge and peak multiplier Monday to
Friday only, but a Segment carries clock minutes and no service date, so
a weekday-only tariff window is priced at five sevenths of its overlap
rather than all or nothing — see calc_tac.py and
OPEN_TODOS['tac_weekday_blend']."""


CHANGELOG: dict = {
    "0.9.6": {
        "date": "2026-09-05",
        "author": "david",
        "changes": "VALUES CHANGE: track_buffer_quota_per is re-calibrated "
        "as a MINIMUM driving-time supplement — 0.11-0.39 by country "
        "instead of 0.35-0.71. The 2026-08-17 value was the time-weighted "
        "mean residual of real ONTD night-train legs over the router's "
        "passage time, which on the Wien-Paris corridor produced 17:21 "
        "against the real NJ 468's 15:25 and 0.71 for France against the "
        "0.22 the real train needed. The clock-time analysis of the same "
        "legs showed the mean was dominated by the one long overnight leg "
        "per trip, i.e. by the operator's arrival-hour stretching rather "
        "than by anything the network needs. The seeded value is now the "
        "lower quartile of the leg-level residual, shrunk toward the "
        "European lower-quartile prior (23.9%) by sample size and floored "
        "at 8%; France is a documented exception at 25% because every "
        "French ONTD leg is an SNCF Intercites de Nuit. Arrival-hour "
        "stretching is no longer inside the supplement; the timetable "
        "layer's fixed-night mode (slack_time_min) is where a night is "
        "stretched, and a manual per-trip override is a planned follow-up. "
        "Three resolution fixes ride along: the UK/GB key mismatch that "
        "dropped Britain's 15 legs; IT, PL, CZ, NL, RO, HU, HR and SK now "
        "carry their own route-context values instead of silently taking "
        "the EU default (money fields unchanged, still default-resolved); "
        "and the optimised-timetable benchmark re-based from 0.35 to 0.12 "
        "so the scenario still reduces something. No schema change. "
        "Calibration: models/infrastructure/route_context/calib/.",
    },
    "0.9.5": {
        "date": "2026-08-17",
        "author": "david",
        "changes": "VALUES CHANGE: route context is calibrated and seeded "
        "instead of hardcoded, completing the four-domain infrastructure "
        "calibration. Two columns move materially. track_buffer_quota_per "
        "carries ONE all-in schedule supplement per country (0.35-0.71, "
        "measured from real ONTD night-train timetables against the router's "
        "passage time and shrunk toward the European mean by sample size) "
        "instead of a flat 0.30-0.50 placeholder; an earlier draft split it "
        "into a buffer quota and a speed factor, and that split was abandoned "
        "because one measurement cannot separate two unknowns. "
        "track_terrain_score moves from 1.0-1.8 to 3-48, which is the 1-100 "
        "scale the column always documented — the old values never matched "
        "it, and any future energy calibration must fit f_terrain against "
        "the seeded scale. Utilisation and punctuality stay calibrated per "
        "country: they feed no formula now, but they are what a "
        "night-train-priority scenario would move. No schema change — every "
        "column already existed. Calibration: "
        "models/infrastructure/route_context/calib/.",
    },
    "0.9.4": {
        "date": "2026-08-17",
        "author": "david",
        "changes": "Service facility charges become a calibrated model "
        "instead of two flat rates. Shunting stays one column but now carries "
        "an all-in figure: the infrastructure manager's tariff plus the market "
        "cost of the locomotive and crew it does not supply, which is roughly "
        "nine tenths of the total in the twenty-three countries that sell only "
        "facility access. Stabling gains six columns — a basis, the rate for "
        "that basis, a free-hours allowance and a hotel-power rate — because "
        "Europe prices an occupation four different ways and Germany's is "
        "length-independent by design. The group resolves against the defaults "
        "row as a whole, keyed on the basis: a NULL basis means uncalibrated, "
        "the basis 'none' means documented as not levied. The flat "
        "track_parking_eur_day column becomes display-only, as the flat track "
        "access rate did. Calculation: facility/calc_facility.py.",
    },
    "0.9.3": {
        "date": "2026-08-17",
        "author": "david",
        "changes": "Traction energy becomes a calibrated price model "
        "instead of one flat rate per country. Both track tables gain a "
        "night-band price with its band and two catenary columns — the "
        "charge for using the traction power-supply installations, levied "
        "per train-km by nine countries and per gross-tonne-km by three, "
        "which the track access calibration excludes per country as energy. "
        "Unlike the TAC component group these terms are never resolved "
        "against the defaults row: an empty night price means one rate "
        "around the clock and an empty catenary term means the country "
        "levies none, so defaulting either would invent tariff structure. "
        "Values are seeded from "
        "models/infrastructure/energy_pricing/calib/, which is the single "
        "source of truth for them; the calculation is "
        "energy_pricing/calc_energy_price.py. Placing a country run on the "
        "clock moved out of calc_tac.py to Segment.country_windows() "
        "(models/route/trip.py), since track access and electricity need "
        "the identical placement for different bands.",
    },
    "0.9.2": {
        "date": "2026-08-13",
        "author": "david",
        "changes": "Track access charges become a calibrated component "
        "model instead of one flat rate per country. Both track tables "
        "gain the day/night train-km rates, the gross-tonne-km, seat-km, "
        "per-stop, flat per-train-km and revenue-share terms, the peak "
        "multiplier and congestion surcharge, and the night and peak "
        "band definitions; input_params.passage_charges joins them as "
        "the fifth scenario-versioned table, carrying the separately "
        "billed crossings and their polygons. Values are seeded from "
        "tac/calib in EUR at 2032 — currency and price basis are "
        "converted once, in the calibration notebook, so no code "
        "downstream sees either. RESOLUTION RULE: the component group "
        "resolves as a whole, not field by field — the EU-median default "
        "group substitutes only where a country has no distance-based "
        "rate term at all, so a lone empty component keeps its meaning "
        "of 'not levied here'. The flat track_tac_eur_train_km column "
        "survives as a display value and is no longer read by any cost "
        "path.",
    },
    "0.9.1": {
        "date": "2026-08-10",
        "author": "david",
        "changes": "Initial consolidation as its own model anchor: "
        "per-country track parameters (TAC €/train-km, parking, "
        "shunting, energy price, terrain, HSR permission, buffer quota, "
        "minimum dwell) and station charges with EU-average defaults, "
        "versioned as full-table snapshots pinned by scenarios; "
        "ONTD-derived stop catalog seeded from Drive (stop "
        "classification steps 1–3, STOP_CLASSIFICATION.md).",
    },
}


# =============================================================================
# OPEN TODOS
# =============================================================================

OPEN_TODOS: dict[str, str] = {
    "tac_weekday_blend": (
        "WEEKDAY_BLEND prices a Mon-Fri peak tariff at its expected "
        "value because a Segment carries clock minutes but no service "
        "date. Once a route knows which days it runs (Schedule already "
        "holds the frequency, just not the weekday pattern), the peak "
        "share should be evaluated against the real operating days "
        "instead of 5/7."
    ),
    "stop_classification_steps_4_7": (
        "Stop classification pipeline steps 4–7 "
        "(see STOP_CLASSIFICATION.md) — Johanna's ownership."
    ),
}
