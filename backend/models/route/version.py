"""
version.py
==========
Version constant, standard values, open TODOs, and model description for
the Night Train Route Builder.

Bump ROUTE_BUILDER_VERSION when any change affects the Trip output:
  - Routing logic or GraphHopper configuration
  - Schedule / dwell time computation
  - Any change to Trip, TripPath, TripSegment, CountryLeg, TripStats, StopTime

This module is also the single registry for every standard value the route
model assumes (STANDARD VALUES below) and for all open TODOs on the route
model (OPEN_TODOS below) — so all standard assumptions are tracked in one
place. Modules using a value import it from here; inline TODO markers in
the code reference their OPEN_TODOS key instead of carrying the full text.

ROUTE_FORMULAS documents the key calculations in the route builder
with LaTeX and plain-English descriptions.
"""

from __future__ import annotations
from dataclasses import dataclass

# =============================================================================
# VERSION
# =============================================================================

ROUTE_BUILDER_VERSION: str = "0.9.12"

GIT_SHA: str = "unknown"  # injected by CI

# Short, plain-English summary of what this model computes — embedded as-is
# in the "models" section of POST /api/evaluation/calc's response, alongside
# ROUTE_BUILDER_VERSION and ROUTE_FORMULAS.
ROUTE_BUILDER_DESCRIPTION: str = (
    "Route/timetable builder: turns a list of stops, a composition, and "
    "routing/timetable/schedule mode selections into a full Route — trip "
    "pairs, segments with buffer time, dwell times, and a mirrored "
    "outbound/return schedule around 02:30."
)

CHANGELOG: dict = {
    "0.9.12": {
        "date": "2026-07-21",
        "author": "david",
        "changes": "Composition object reshaped with the cost calibration v2: "
        "driver/crew overhead minutes removed; material_strategy added "
        "(new/refurbished — also on CompositionType together with the "
        "seeded indicative KPI columns). Routing behaviour unchanged; "
        "composition-aware v_max routing (REF capped at 200 km/h) remains "
        "an open follow-up.",
    },
    "0.9.11": {
        "date": "2026-07-16",
        "author": "david",
        "changes": "Persist-on-calc: POST /api/route/plan now persists its own "
        "response as a proposal for any authenticated caller (guest or "
        "registered) — POST /api/proposal is gone. The response gains a "
        "trailing 'proposal' block ({persisted, action, proposal_id, "
        "proposal_version, user_id}); on a persisted plan all draft IDs in "
        "the response are already rewritten to the real "
        "P{proposal_id}_V{version} prefix, so route_id is final from the "
        "first response on. Replanning an existing proposal with an "
        "identical resolved setup (stops, composition, all modes, scenario, "
        "builder version) writes nothing and returns the stored current "
        "version's IDs (action 'unchanged'); a changed setup versions or "
        "branches per the ownership rules that POST /api/proposal used to "
        "apply. Tokenless requests compute only (action 'unauthenticated'). "
        "BREAKING for frontend: save flow removed, Authorization header now "
        "expected on plan (guest token minimum) — coordinate with Bjarne.",
    },
    "0.9.1": {
        "date": "2026-06-25",
        "author": "david",
        "changes": "Initial implementation. GTFS-aligned Route/Trip domain model. "
        "TripPath with CountryLeg-level physics. plan_route() + adjust_route() "
        "factory pattern. ID convention P{id}_V{ver}_R1_D{dir}_T{idx}. "
        "RailRouter returns TripPath directly.",
    },
    "0.9.3": {
        "date": "2026-07-12",
        "author": "david",
        "changes": "auto_stop_addition implemented end to end: finds catalog stops "
        "within AUTO_STOP_BUFFER_M (3km) of the routed path and greedily adds "
        "any that fit within a AUTO_STOP_MAX_DETOUR_PER (5%) detour-time "
        "budget, cheapest first — see models/route/timetable.py. Stop gains a "
        "new auto_added field (BREAKING for consumers of POST /api/route/plan: "
        "every from_stop/to_stop in the response now carries this field). "
        "auto_stop_addition now defaults to true (previously false/no-op), so "
        "existing callers can see additional stops without a request change "
        "unless they explicitly pass auto_stop_addition=false. "
        "timetable_mode/schedule_mode/auto_stop_addition switch logic moved "
        "out of timetable.py's internal dispatch into route_factory.py, at "
        "whichever level owns the relevant context — auto_stop_addition is "
        "decided once per TripPair (from outbound) and reused, reversed, for "
        "return, rather than re-run independently per direction; return still "
        "gets its own real routing call for its own physics, only the "
        "decision of which stops to add is shared (accepted trade-off: return "
        "no longer gets an independent detour-budget check). Candidate "
        "costing runs concurrently (ThreadPoolExecutor) rather than "
        "sequentially. Needs frontend coordination — see project notes on "
        "auditing Bjarne's frontend for POST /api/route/plan consumers.",
    },
    "0.9.4": {
        "date": "2026-07-13",
        "author": "david",
        "changes": "Each trip in route['trip_pairs'][].outbound/return_trip gains a new "
        "'general_parameters' section, placed between 'direction' and "
        "'segments' — three headline physics stats for that trip "
        "(trip_km, route_duration_min, average_speed_kmh) so consumers "
        "like the frontend don't have to derive them from segments[] "
        "themselves. Additive only (no existing fields changed/removed).",
    },
    "0.9.5": {
        "date": "2026-07-13",
        "author": "david",
        "changes": "auto_stop_addition becomes a three-value string enum "
        "(BREAKING for POST /api/route/plan callers: booleans are now "
        "rejected with 400): 'off' (old false — caller's stop list returned "
        "unmodified), 'add' (old true, still the default — candidates found "
        "and greedily added within the detour budget), and the new 'suggest' "
        "— routes exactly like 'off' but runs the same candidate search + "
        "costing as 'add' and returns every costed candidate as a new "
        "top-level 'suggested_stops' list in the response, placed between "
        "'request' and 'route', each with the added_time_min the stop would "
        "cost if implemented (no detour-budget filtering — suggestion is "
        "informational, selection is the caller's). Candidate search "
        "optimized: catalog stops are prefiltered to countries the routed "
        "legs actually touch (reusing RailRouter's country attribution — no "
        "new spatial join needed) and each leg's shapely LineString is built "
        "once per search instead of once per (stop, leg) pair. Fixes the "
        "0.9.4 key mismatch: the per-trip headline block is now actually "
        "emitted as 'general_parameters' (the code emitted 'stats' while "
        "changelog/tests said 'general_parameters'). All standard values "
        "and open TODOs of the route model consolidated here in version.py. "
        "Needs frontend coordination (Bjarne): request field type change + "
        "new suggested_stops section + general_parameters key.",
    },
    "0.9.6": {
        "date": "2026-07-14",
        "author": "david",
        "changes": "HSR avoidance fixed — it was a routing error, not the intended "
        "model. Previous behaviour: when hsr_allowed resolved to false for a "
        "country, the ENTIRE country's rail network got a blanket priority "
        "penalty (whole-country polygon, multiply_by 0.01), punishing "
        "conventional lines exactly as hard as high-speed ones; and the "
        "per-country permission was only evaluated for countries with a STOP "
        "on the route, so transited-without-stop countries were never checked "
        "against their hsr_allowed at all. Intended (now implemented) "
        "behaviour: hsr_allowed steers HIGH-SPEED LINE access only — a track "
        "segment is penalized (HSR_AVOIDANCE_PRIORITY_FACTOR) iff its "
        "permitted track speed (GraphHopper max_speed encoded value, from OSM "
        "maxspeed) exceeds HSR_TRACK_SPEED_THRESHOLD_KMH AND it lies in a "
        "country where HSR is not allowed; per-country permission = "
        "composition.hsr_allowed AND that country's track hsr_allowed, now "
        "evaluated over the FULL TrackInfraCollection (every country), not "
        "just stop countries. When every country disallows (e.g. the 2032 "
        "Base Line, or a composition-level ban) the rule is emitted globally "
        "with no area polygons at all — smaller payload, and inherently "
        "covers any country missing a border polygon. Conventional lines in "
        "HSR-forbidden countries are no longer penalized, so routed paths "
        "(distance/time) can change vs 0.9.5 wherever avoidance was active. "
        "No API contract change.",
    },
    "0.9.7": {
        "date": "2026-07-14",
        "author": "david",
        "changes": "Traction dynamics added (models/route/routing/dynamics.py): GraphHopper "
        "has no vehicle model — edge times are distance / constant edge "
        "speed and a via-point adds zero seconds — so until now every "
        "intermediate stop cost only its dwell time, making the whole "
        "timetable systematically optimistic by roughly the acceleration + "
        "braking loss per stop and biasing auto_stop_addition's detour "
        "budget toward accepting stops (surfaced by a Brno suggestion "
        "costing exactly its 2min dwell). Now every fullRouting leg's "
        "driving_time_min carries a per-leg surcharge: braking into the "
        "arrival stop (constant TRACTION_BRAKE_DECELERATION_MS2) plus "
        "accelerating out of the departure stop (two-phase traction — "
        "constant tractive effort then constant power — of an assumed "
        "standard locomotive, Siemens Vectron, hauling the composition's "
        "own coach weight; locos are leased and not composition data), "
        "each computed against that leg's own average cruise speed, i.e. "
        "the link speeds before and after the stop. Applied inside "
        "RailRouter.route() so trips, auto-stop candidate mini-reroutes, "
        "and final reroutes all get consistent physics from one call site; "
        "suggested_stops' added_time_min now automatically includes the "
        "extra accel/brake pair a new stop introduces. simpleRouting "
        "deliberately stays dynamics-free. All trip durations grow by "
        "~1-1.5min per leg vs 0.9.6; departure times shift accordingly "
        "(02:30 mirror). No API contract change.",
    },
    "0.9.8": {
        "date": "2026-07-14",
        "author": "david",
        "changes": "Traction dynamics split into its own time component so router "
        "output and dynamics stay differentiable downstream (0.9.7 folded "
        "the surcharge into driving_time_min, making the two inseparable "
        "after the fact): every segment now carries driving_time_min (raw "
        "router time, constant-cruise-speed passage), dynamics_time_min "
        "(per-stop accel/brake loss, routing/dynamics.py — also moved from "
        "models/route/ to models/route/routing/), and buffer_time_min, "
        "with total = driving + dynamics + buffer and buffer still "
        "computed on raw driving time only, by design. ADDITIVE response "
        "change for POST /api/route/plan consumers: new dynamics_time_min "
        "field on every segment, placed between driving_time_min and "
        "buffer_time_min (Bjarne: additive only, nothing renamed/removed). "
        "route_from_dict() defaults the field to 0 for stored pre-0.9.8 "
        "payloads. Evaluation counts dynamics as billable in-motion time — "
        "see CALC_VERSION 0.9.3.",
    },
    "0.9.9": {
        "date": "2026-07-14",
        "author": "david",
        "changes": "Schedule buffer now also applies to the dynamics component, at "
        "the same per-country quota as driving, with a guaranteed order of "
        "operations: the dynamics cruise speed is derived from the RAW "
        "driving time first (buffer plays no role in the physics), and only "
        "afterwards is the quota applied to both components — driving's "
        "share at parse time as before, the dynamics' share added on top of "
        "buffer_time_min by apply_traction_dynamics() (unrounded loss x the "
        "leg's time-share-weighted quota, so the two roundings don't "
        "compound). Rationale: a high buffer quota encodes a congested "
        "network, where the extra travel time around stops (braking, "
        "accelerating, queuing into stations) suffers the same operational "
        "margins as cruise running. Magnitude note: at current quotas "
        "(0.08-0.15) and ~1min dynamics per leg the buffered share is a few "
        "seconds and usually rounds to 0 at whole-minute resolution — "
        "structural guarantee, visible for heavier/faster compositions or "
        "higher quotas. No API contract change.",
    },
    "0.9.10": {
        "date": "2026-07-14",
        "author": "david",
        "changes": "Night stop classification + timetable_mode "
        "'simpleAutomaticWithFixedNight'. Stop classification is now "
        "three-way for ALL timetable modes: boarding if the stop DEPARTS "
        "strictly before NIGHT_START_MIN (00:00+1), alighting if it "
        "ARRIVES at/after NIGHT_END_MIN (05:00+1), night otherwise — "
        "replaces the old two-way split at MIRROR_MIN, and the provisional "
        "classification walk now includes the min-dwell approximation so "
        "it can judge departures and arrivals separately. StopType gains "
        "NIGHT ('night'); dwell treats it like BOTH; the stopgap demand "
        "model excludes night stops from OD pairs. New mode "
        "'simpleAutomaticWithFixedNight' (request field "
        "fixed_night_interval, two stop IDs from the stops list): the "
        "schedule is positioned so the MIDPOINT of [departure at interval "
        "start, arrival at interval end] lands on MIRROR_MIN instead of "
        "mirroring the full trip — lets a demand-strong feeder section "
        "keep evening departures while the night window sits on a chosen "
        "corridor section. The interval must depart by 23:59 and arrive "
        "at 05:00 or later (span >= 301min): a naturally shorter interval "
        "is stretched by adding slack time (proportionally to leg time "
        "across the interval's legs), pinning dep=23:59/arr=05:00 exactly "
        "in the minimal-stretch case; slack is carried as a new "
        "per-segment slack_time_min component included in total "
        "segment/trip time. If stretching drops the interval's timetable "
        "speed below FIXED_NIGHT_MIN_SPEED_RATIO of its routing speed, "
        "the trip carries a warning in "
        "general_parameters.timetable_warnings. Bjarne (BREAKING-ish for "
        "consumers of POST /api/route/plan): stop_type can now be "
        "'night'; every segment carries a new slack_time_min field (0 "
        "outside fixed-night stretching); general_parameters gains a "
        "timetable_warnings list (usually empty). route_from_dict() "
        "defaults slack_time_min to 0 for stored pre-0.9.10 payloads.",
    },
}


# =============================================================================
# STANDARD VALUES — every fixed assumption the route model makes.
# None of these is exposed as a request field; changing one is a model
# change and warrants a version bump above.
# =============================================================================

# --- API request defaults (applied once, at the API boundary — api/route.py)
DEFAULT_TIMETABLE_MODE: str = "simpleAutomatic"
DEFAULT_SCHEDULE_MODE: str = "alwaysDaily"
DEFAULT_ROUTING_MODE: str = "fullRouting"
DEFAULT_AUTO_STOP_ADDITION: str = "add"

# --- Timetable (timetable_mode="simpleAutomatic")
MIRROR_MIN: int = 26 * 60 + 30
"""02:30, expressed 'next day' (1590) on the continuous minutes-from-midnight
scale used throughout (see models.utils.hhmm_to_min). Fixed constant that
timetable_mode='simpleAutomatic' schedules are mirrored around, and that
'simpleAutomaticWithFixedNight' centers the fixed night interval on."""

NIGHT_START_MIN: int = 24 * 60
"""00:00 next day (1440) — threshold X of the night window. Boarding is
judged on DEPARTURE time: a stop departing strictly before this classifies
boarding; the fixed-night interval's start stop must depart strictly before
this (23:59 at the latest)."""

NIGHT_END_MIN: int = 29 * 60
"""05:00 next day (1740) — threshold Y of the night window. Alighting is
judged on ARRIVAL time: a stop arriving at/after this classifies alighting;
anything neither boarding nor alighting is a night stop. The fixed-night
interval's end stop must arrive no earlier than this."""

FIXED_NIGHT_MIN_SPEED_RATIO: float = 0.7
"""timetable_mode='simpleAutomaticWithFixedNight' only: minimum acceptable
ratio of the fixed interval's timetable speed (incl. slack + dwell) to its
pure routing speed (driving + dynamics + buffer). Stretching a short
interval to cover the night window can make it arbitrarily slow — below
this ratio the trip carries a 'fixed_night_stretch_slow' entry in
general_parameters.timetable_warnings (a warning, never an error)."""

# --- Schedule (seasonal model — models/route/route.py)
WEEKS_PER_SEASON: int = 26
"""SUMMER (April–Sep) and WINTER (Oct–Mar) are each a fixed 26 weeks."""

DAYS_PER_OPERATING_WEEK: dict[str, int] = {"DAILY": 7, "THREE_PER_WEEK": 3}
"""Operating days per week per Frequency name — specific days of week
aren't modelled, they don't affect cost or fleet sizing."""

# --- fullRouting HSR avoidance (models/route/routing/rail_router.py)
HSR_TRACK_SPEED_THRESHOLD_KMH: int = 230
"""A track segment counts as high-speed infrastructure when its permitted
track speed (GraphHopper's max_speed encoded value, from OSM maxspeed)
STRICTLY exceeds this. 230 deliberately targets dedicated NEW-BUILD
high-speed lines only (250+ per the UIC/EU convention, e.g. LGV, NBS,
AV): upgraded conventional lines (200-230, e.g. German ABS corridors at
230) stay fully usable for night trains regardless of hsr_allowed, and
230 also matches the fastest seeded composition's own max_speed_kmh —
track a night train could physically exploit is never treated as
forbidden high-speed infrastructure."""

HSR_TRACK_SPEED_SANITY_MAX_KMH: int = 500
"""Upper guard on the same condition — excludes segments whose maxspeed
is untagged in OSM. GraphHopper encodes a missing maxspeed as a sentinel
(0 or infinity depending on version); the two-sided range
(THRESHOLD, SANITY_MAX) excludes both conventions, so unknown-speed track
is never mistaken for high-speed infrastructure. No real European rail
line exceeds this value."""

HSR_AVOIDANCE_PRIORITY_FACTOR: float = 0.01
"""GraphHopper custom-model priority multiplier applied to high-speed
segments where HSR is not allowed — a strong penalty (100x) rather than a
hard block, so a route is still found if high-speed track is genuinely
the only physical connection."""

# --- auto_stop_addition (candidate search — models/route/timetable.py)
AUTO_STOP_BUFFER_M: int = 3_000
"""Max distance (metres) from a stop to the already-routed path for that
stop to be considered a candidate — covers both stops that sit right on
the line and ones merely 'close by'."""

AUTO_STOP_MAX_DETOUR_PER: float = 0.05
"""Max allowed increase in full (driving + dynamics + buffer + dwell) trip time, as a
fraction of the original trip's time, before mode 'add' stops adding
further candidates. Mode 'suggest' deliberately ignores this budget."""

# --- Traction dynamics (per-stop accel/brake time loss — models/route/routing/dynamics.py)
TRACTION_LOCO_WEIGHT_T: float = 90.0
"""Assumed standard locomotive weight (Siemens Vectron, ~90t). Locomotives
are full-service leased and not part of the composition data, so the loco
is a fixed standard assumption added on top of Composition.total_weight_t
(which covers coaches only)."""

TRACTION_LOCO_POWER_KW: float = 6_400.0
"""Assumed locomotive continuous power at the wheel (Siemens Vectron AC:
6.4 MW). Governs the constant-power phase of acceleration above
P / F ≈ 77 km/h."""

TRACTION_LOCO_TRACTIVE_EFFORT_KN: float = 300.0
"""Assumed locomotive starting tractive effort (Siemens Vectron: 300 kN).
Governs the constant-force phase of acceleration from standstill."""

TRACTION_BRAKE_DECELERATION_MS2: float = 0.5
"""Service braking deceleration. Rail braking is effectively
mass-independent (brake systems are dimensioned per vehicle to a standard
deceleration); 0.5 m/s² is a comfortable service value appropriate for
sleeping passengers — full emergency capability is far higher and
irrelevant for timetabling."""

# --- Stopgap demand (distribute_demand() inputs — see OPEN_TODOS)
STOPGAP_UTILIZATION_PER: float = 0.7
"""Placeholder scalar utilization applied uniformly to every class until a
real demand model lands."""

STOPGAP_FARE_PER_KM_BY_CLASS: dict[str, float] = {
    "Seat": 0.10,
    "Couchette": 0.13,
    "Sleeper": 0.18,
    "Capsule": 0.12,
    "Catering": 0.0,
}
"""Placeholder flat per-km fares by class_main — same caveat as above."""

# --- Draft proposal placeholder ids (api/route.py)
DRAFT_PROPOSAL_ID_MIN: int = 1_000_000_000
DRAFT_PROPOSAL_ID_MAX: int = 2_147_483_647
"""Random placeholder proposal_id range for a route that hasn't been saved
as a proposal yet. proposals.proposals.proposal_id is a SERIAL int4
starting at 1, so a value above one billion won't realistically collide
with a real one (upper bound = postgres int4 max). See OPEN_TODOS."""


# =============================================================================
# OPEN TODOS — every open item on the route model, consolidated. Inline
# markers in the code reference these keys instead of carrying full text.
# =============================================================================

OPEN_TODOS: dict[str, str] = {
    "trip_pair_id": (
        "(David, 2026-07-06, future — not scheduled) Consider swapping the "
        "D/T order to trip_id = P{proposal_id}_V{version}_R1_T{pair_index}_"
        "D{direction} and introducing a distinct trip-PAIR id (P{proposal_id}"
        "_V{version}_R1_T{pair_index}, no _D suffix) for anything that means "
        "'the pair', not 'one direction of the pair'. Motivation: "
        "evaluation_serialize.py's views key per_trip_pair* matrices by the "
        "outbound trip's full trip_id standing in for the whole pair — a "
        "borrowed key, not a real pair identifier. Real ID-format change: "
        "trip_id is threaded through Segment/StopCost/SegmentCost/"
        "ODPair.trip_id, route_to_dict()/route_from_dict(), and every test "
        "fixture hardcoding IDs — needs its own scoped pass across "
        "route_factory.py, route.py, route_serialize.py, and tests/."
    ),
    "demand_model": (
        "Replace distribute_demand()'s stopgap inputs (STOPGAP_UTILIZATION_"
        "PER, STOPGAP_FARE_PER_KM_BY_CLASS above) and its uniform-"
        "distribution proxy with a real demand model accounting for "
        "asymmetric directional demand, price elasticity, and competition "
        "from other modes — likely with per-scenario parameters. Target "
        "module: models/demand/."
    ),
    "auto_stop_nuts1_prefilter": (
        "Candidate search prefilters the stop catalog to countries the "
        "routed legs touch (country attribution already computed by "
        "RailRouter — effectively a free spatial join). Next refinement "
        "once the catalog grows to several thousand stops: pre-save each "
        "stop's NUTS level 1 region (one level below country) and prefilter "
        "on route-touched NUTS-1 regions instead. Known edge of the current "
        "country filter: a stop within AUTO_STOP_BUFFER_M of the path but "
        "across a border in a country the route never enters is missed — "
        "accepted at a 3km buffer; a NUTS-1 implementation should decide "
        "whether to include regions adjacent to the path, which would close "
        "this gap too."
    ),
    "return_detour_budget": (
        "auto_stop_addition's search-and-cost pass runs once per TripPair, "
        "from outbound; return reuses the decision (reversed). Accepted "
        "trade-off: return gets no independent detour-budget check against "
        "its own baseline trip time. Revisit only if asymmetric routing "
        "(e.g. one-directional HSR avoidance) is ever observed pushing "
        "return trips materially past the budget."
    ),
    "buffer_quota_time_of_day": (
        "buffer_quota_per is a flat per-country figure today. Congestion is "
        "daypart-dependent — after ~05:00 the morning rush builds while the "
        "night hours most night-train legs actually run in are far emptier "
        "— so the flat quota over-pads genuine night legs and under-pads "
        "early-morning arrival legs. Splitting it into per-country TIME "
        "BANDS needs a schema change (input_params.track_infrastructures + "
        "defaults + seed, see the TODO at db/dev/seed.py's "
        "_TRACK_INFRA_DEFAULT_2032) and route-model work: buffer would be "
        "applied per leg by the clock time the leg is driven at, which "
        "interacts with the timetable (buffer feeds departure times which "
        "feed each leg's clock time — likely needs one fixed-point "
        "iteration or an approximation from the provisional timetable)."
    ),
    "shunting_y_shape": (
        "_shuntings() creates one Shunting per trip terminal with no "
        "deduplication; Y/X-shaped routes with shared terminals may need "
        "fewer coupling/uncoupling events."
    ),
    "draft_proposal_module": (
        "The random draft proposal_id (DRAFT_PROPOSAL_ID_MIN/MAX above, "
        "minted in api/route.py) is a stand-in for a future scenarios/"
        "proposals module that will own draft-vs-saved handling properly "
        "and hand back whatever id it thinks is appropriate."
    ),
    "adjust_route_unreachable": (
        "route_factory.adjust_route() (schedule-only changes, no rerouting) "
        "exists but is not reachable from any API endpoint — kept for a "
        "future save/versioning flow."
    ),
}


# =============================================================================
# ROUTE FORMULA REGISTRY
# =============================================================================


@dataclass(frozen=True)
class RouteFormula:
    """One entry in the route builder calculation model."""

    latex: str
    description: str


ROUTE_FORMULAS: dict[str, RouteFormula] = {
    # ------------------------------------------------------------------
    # ROUTING
    # ------------------------------------------------------------------
    "buffer_time": RouteFormula(
        latex=r"t_{buffer,l} = t_{drive,l} \times q_{buffer,country(l)}",
        description="Buffer time per country leg: driving time multiplied by the "
        "country's schedule buffer quota (accounts for construction, "
        "delays, and operational margins).",
    ),
    "total_time_per_leg": RouteFormula(
        latex=r"t_{total,l} = t_{drive,l} + t_{buffer,l}",
        description="Total travel time per country leg: driving time plus buffer.",
    ),
    "total_time_per_segment": RouteFormula(
        latex=r"t_{seg} = \sum_{l \in seg} t_{total,l}",
        description="Total travel time per segment (stop pair): sum over all "
        "country legs within the segment.",
    ),
    "avg_speed": RouteFormula(
        latex=r"\bar{v}_{kmh} = \frac{d_{km}}{t_{drive,h}}",
        description="Average speed: distance divided by pure driving time "
        "(excluding buffer). Display value only — not stored.",
    ),
    # ------------------------------------------------------------------
    # DWELL TIME
    # ------------------------------------------------------------------
    "dwell_time_boarding": RouteFormula(
        latex=r"t_{dwell} = \max(t_{board,comp},\ t_{board,infra})",
        description="Dwell time at boarding stop: maximum of composition minimum "
        "boarding time and infrastructure minimum boarding time.",
    ),
    "dwell_time_alighting": RouteFormula(
        latex=r"t_{dwell} = \max(t_{alight,comp},\ t_{alight,infra})",
        description="Dwell time at alighting stop: maximum of composition minimum "
        "alighting time and infrastructure minimum alighting time.",
    ),
    "dwell_time_both": RouteFormula(
        latex=r"t_{dwell} = \max(t_{board,comp},\ t_{board,infra},\ t_{alight,comp},\ t_{alight,infra})",
        description="Dwell time at boarding+alighting stop: maximum of all four "
        "boarding and alighting time constraints.",
    ),
    # ------------------------------------------------------------------
    # AUTO STOP ADDITION
    # ------------------------------------------------------------------
    "auto_stop_added_time": RouteFormula(
        latex=r"\Delta t_{cand} = \left(\sum_{l \in reroute(a, cand, b)} t_{total,l}\right) - t_{total,(a,b)} + t_{dwell,cand}",
        description="Added time for one auto-stop candidate: total time of the "
        "3-point mini-reroute of its own leg (leg start → candidate → leg "
        "end) minus the original leg's total time, plus the candidate's "
        "dwell (conservatively StopType BOTH). Used for greedy selection "
        "in mode 'add' (budget: AUTO_STOP_MAX_DETOUR_PER of the original "
        "trip time) and reported as added_time_min in mode 'suggest'. "
        "Since 0.9.7 the mini-reroute legs carry traction dynamics (see "
        "stop_dynamics_time_loss), so the extra accel/brake pair a new "
        "stop introduces is included automatically.",
    ),
    # ------------------------------------------------------------------
    # TRACTION DYNAMICS
    # ------------------------------------------------------------------
    "stop_dynamics_time_loss": RouteFormula(
        latex=r"\Delta t_{leg} = \underbrace{\frac{v}{2\,a_{dec}}}_{braking} + \underbrace{t_{acc}(v) - \frac{d_{acc}(v)}{v}}_{acceleration},\quad t_{acc},d_{acc}\ \text{from}\ F(u)=\min\!\left(F_{loco},\ \frac{P_{loco}}{u}\right),\ m = m_{coaches} + m_{loco}",
        description="Per-leg time lost to stopping, vs the router's "
        "constant-cruise-speed passage (GraphHopper has no vehicle model): "
        "braking into the arrival stop at constant service deceleration "
        "TRACTION_BRAKE_DECELERATION_MS2 plus accelerating out of the "
        "departure stop under two-phase traction (constant tractive effort "
        "F_loco up to v1 = P/F, constant power P_loco above) of the assumed "
        "standard locomotive hauling the composition's coach weight. v is "
        "the leg's own average cruise speed, i.e. the link speed before "
        "(braking) and after (acceleration) the stop. Added to "
        "driving_time_min per fullRouting leg; damped linearly when the "
        "leg is too short to contain both phases. See "
        "models/route/routing/dynamics.py.",
    ),
    # ------------------------------------------------------------------
    # SCHEDULE
    # ------------------------------------------------------------------
    "arrival_time": RouteFormula(
        latex=r"t_{arr,i} = t_{dep,i-1} + t_{seg,i-1}",
        description="Arrival time at stop i: departure from previous stop plus "
        "total segment travel time (driving + dynamics + buffer).",
    ),
    "departure_time": RouteFormula(
        latex=r"t_{dep,i} = t_{arr,i} + t_{dwell,i}",
        description="Departure time at intermediate stop: arrival time plus dwell time.",
    ),
    # ------------------------------------------------------------------
    # TRIP STATS
    # ------------------------------------------------------------------
    "total_distance": RouteFormula(
        latex=r"d_{total} = \sum_{seg} \sum_{l \in seg} d_{m,l}",
        description="Total trip distance: sum of all country leg distances in metres.",
    ),
    "total_driving_time": RouteFormula(
        latex=r"t_{drive,total} = \sum_{seg} \sum_{l \in seg} t_{drive,l}",
        description="Total driving time: sum of pure engine time across all country legs.",
    ),
    "total_time": RouteFormula(
        latex=r"t_{total} = \sum_{seg} t_{total,seg}",
        description="Total trip time: driving time plus all buffer times.",
    ),
}
