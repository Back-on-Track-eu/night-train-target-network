"""
member_compute.py
=================
Validation + serialization wrapper around models/pipeline.py's
run_compute() — the L1–L4 primitive with the member cache: one member
(one scenario, one composition, one measure set) of one stop list + HOW,
as a wire-shaped dict. Every path that turns a request into a stored or
served result goes through here so they can never drift: the family's
views endpoint (api/helpers/family_compute.py), publish
(api/helpers/publish_dispatch.py), the on-load refresh fallback
(api/helpers/proposal_load.py), compare's override sides
(api/helpers/proposal_compare.py) and scripts/refresh_proposals.py. The
family itself (models/family/builder.py) runs the same run_compute() on a
shared context and serialises its own document; it does not write here.

Until WP18 B2b this was proposal_compute.py behind POST /api/proposal/calc.
The endpoint is gone; the function is what remains of it, and its payload
lost the two blocks that have their own endpoints since then:
evaluation.models (GET /api/models) and evaluation.input.parameters
(GET /api/params/*). What is left is what a member IS:

  {route_builder_version, calc_version, route_fingerprint, request,
   suggested_stops?, summary, route, evaluation: {views}}

validate_calc_body() keeps its name: it validates a member request (stops,
composition, scenario, HOW), which is what publish's compute_request and
compare's override sides still post.

Public interface:
  validate_calc_body(body: dict) -> list[str]
  validate_stops(body: dict) -> list[str]
  validate_how_fields(body: dict, stops) -> list[str]
  classify_compute_error(exc) -> (error_code, http_status, extra) | None
  normalize_expert_timetable(block: dict | None) -> dict | None
  canonical_sha256(obj) -> str            # re-exported from models/utils.py
  canonical_request_hash(resolved_request, measure_set_id) -> str
  resolve_how_fields(body: dict) -> dict  # the HOW subset of the echo
  compute_member(body, loader=None, router=None, use_cache=True,
                 measures=NO_MEASURES)
      -> tuple[dict, bool]   # (member payload, cache_hit)
"""

from __future__ import annotations

from adapters.proposal.id_prefix import rewrite_id_prefix
from adapters.proposal.projection import route_fingerprint
from models.evaluation.operations import build_operations
from models.evaluation.summary import build_summary_row
from models.route.routing.gauge import GaugeMismatchError
from models.route.routing.rail_router import RailRoutingError
from api.helpers.dependencies import (
    RoutingGraphNotConfiguredError,
    get_loader,
    get_member_cache,
    get_rail_router,
)
from api.helpers.evaluation_serialize import views_to_dict
from api.config import (
    EXPERT_DEPARTURE_MAX_TIME,
    EXPERT_DEPARTURE_MIN_TIME,
    EXPERT_MAX_ADDON_MIN,
    EXPERT_MAX_ADDONS,
    EXPERT_MAX_DEPARTURE_SHIFT_MIN,
)
from api.helpers.route_serialize import (
    expert_timetable_from_dict,
    route_to_dict,
    suggested_stops_to_dicts,
)
from models.evaluation.model import CALC_VERSION
from models.params import NO_MEASURES, MeasureSet
from models.pipeline import run_compute
from models.utils import canonical_sha256
from models.route.timetable import (
    VALID_AUTO_STOP_ADDITION_MODES,
    VALID_DEPARTURE_MODES,
    VALID_TIMETABLE_MODES,
)
from models.route.routing.rail_router import VALID_ROUTING_MODES
from models.demand.model import (
    FARE_CLASS_MAINS,
    resolve_catering,
    resolve_fares,
    resolve_fares_per_pax,
    resolve_services,
)
from models.route.model import (
    DEFAULT_AUTO_STOP_ADDITION,
    DEFAULT_COMPOSITION_ID,
    DEFAULT_DAYS_PER_WEEK,
    DEFAULT_ROUTING_MODE,
    DEFAULT_MIN_TURNAROUND_MIN,
    DEFAULT_TIMETABLE_MODE,
    NEUTRAL_PROPOSAL_ID,
    NEUTRAL_PROPOSAL_VERSION,
    ROUTE_BUILDER_VERSION,
)

_NEUTRAL_PREFIX = f"P{NEUTRAL_PROPOSAL_ID}_V{NEUTRAL_PROPOSAL_VERSION}_"


def validate_calc_body(body: dict) -> list[str]:
    """Request validation for one member request — stops, composition,
    scenario and the HOW fields, minus proposal_id/proposal_version
    (publish-only, not a compute concern). Shared by publish
    (api/helpers/publish_dispatch.py) and compare's override sides
    (api/helpers/proposal_compare.py) so both reject the same malformed
    compute_request the same way."""
    errors = []

    if body.get("scenario_id") is not None and not isinstance(body["scenario_id"], int):
        errors.append("'scenario_id' must be an integer if provided.")

    errors.extend(validate_stops(body))
    stops = body.get("stops")

    # Optional: an omitted composition is computed with DEFAULT_COMPOSITION_ID
    # (resolved in _resolve_request below, before the request is hashed).
    if "composition_id" in body and not isinstance(body["composition_id"], str):
        errors.append("'composition_id' must be a string if provided.")

    errors.extend(validate_how_fields(body, stops))
    return errors


def validate_stops(body: dict) -> list[str]:
    """The stop list every compute request carries — shared by the calc
    request and the family request (api/helpers/family_compute.py)."""
    stops = body.get("stops")
    if not isinstance(stops, list):
        return ["'stops' must be a list of stop_id strings."]
    if len(stops) < 2:
        return ["'stops' must contain at least 2 entries."]
    if not all(isinstance(s, str) for s in stops):
        return ["'stops' must be a list of stop_id strings."]
    return []


def validate_how_fields(body: dict, stops) -> list[str]:
    """The HOW fields every compute request carries — timetable_mode,
    fixed_night_interval, schedule, routing_mode, auto_stop_addition,
    expert_timetable — checked the same way for a member request (via
    validate_calc_body) and a family request (api/helpers/
    family_compute.py), whose WHAT fields are axes instead of one
    composition/scenario.
    `stops` is passed separately because the fixed-night and add-on
    checks refer to it and the caller has already validated it."""
    errors = []

    timetable_mode = body.get("timetable_mode", DEFAULT_TIMETABLE_MODE)
    if timetable_mode not in VALID_TIMETABLE_MODES:
        errors.append(
            f"'timetable_mode' = '{timetable_mode}' is invalid. Must be one of: {sorted(VALID_TIMETABLE_MODES)}."
        )

    fixed_night_interval = body.get("fixed_night_interval")
    if timetable_mode == "simpleAutomaticWithFixedNight":
        if (
            not isinstance(fixed_night_interval, list)
            or len(fixed_night_interval) != 2
            or not all(isinstance(s, str) for s in fixed_night_interval)
            or fixed_night_interval[0] == fixed_night_interval[1]
        ):
            errors.append(
                "'fixed_night_interval' must be a list of exactly 2 distinct "
                "stop_id strings when timetable_mode is "
                "'simpleAutomaticWithFixedNight'."
            )
        elif isinstance(stops, list) and all(isinstance(s, str) for s in stops):
            missing = [s for s in fixed_night_interval if s not in stops]
            if missing:
                errors.append(
                    f"'fixed_night_interval' stops {missing} are not in 'stops'."
                )
            elif stops.index(fixed_night_interval[0]) >= stops.index(
                fixed_night_interval[1]
            ):
                errors.append(
                    "'fixed_night_interval' start must come before its end in "
                    "'stops' order."
                )
    elif fixed_night_interval is not None:
        errors.append(
            "'fixed_night_interval' is only allowed with timetable_mode "
            "'simpleAutomaticWithFixedNight'."
        )

    if "schedule_mode" in body:
        # Gone with ROUTE_BUILDER 0.9.40; a stored request still carrying
        # it is one the 2026-09-19 migration did not reach.
        errors.append(
            "'schedule_mode' no longer exists: post 'schedule' as "
            "{'days_per_week': 1..7} or a month map, or omit it for the default."
        )
    errors.extend(validate_schedule(body.get("schedule")))
    turnaround = body.get("min_turnaround_min", DEFAULT_MIN_TURNAROUND_MIN)
    if (
        not isinstance(turnaround, int)
        or isinstance(turnaround, bool)
        or turnaround < 0
    ):
        errors.append("'min_turnaround_min' must be a non-negative integer (minutes).")
    errors.extend(validate_fares(body.get("fares_eur_per_km")))
    errors.extend(validate_fares_per_pax(body.get("fares_eur_per_pax")))
    errors.extend(validate_services(body.get("services_eur_per_pax")))
    errors.extend(validate_catering(body.get("catering_eur_per_pax")))

    routing_mode = body.get("routing_mode", DEFAULT_ROUTING_MODE)
    if routing_mode not in VALID_ROUTING_MODES:
        errors.append(
            f"'routing_mode' = '{routing_mode}' is invalid. Must be one of: {sorted(VALID_ROUTING_MODES)}."
        )

    auto_stop_addition = body.get("auto_stop_addition", DEFAULT_AUTO_STOP_ADDITION)
    if auto_stop_addition not in VALID_AUTO_STOP_ADDITION_MODES:
        errors.append(
            f"'auto_stop_addition' = '{auto_stop_addition}' is invalid. Must be one "
            f"of: {sorted(VALID_AUTO_STOP_ADDITION_MODES)}."
        )

    errors.extend(_validate_expert_timetable(body.get("expert_timetable"), stops))
    return errors


def classify_compute_error(exc: BaseException) -> tuple[str, int, dict] | None:
    """Map a compute_member() failure to (error_code, http_status,
    extra_fields), or None for anything that is our own fault (the caller
    logs it with a traceback and answers calc_error/500). One mapping for
    the views endpoint's HTTP arms and the family's per-member error
    records, so a member reports exactly the code the views endpoint
    would answer for the same request:

      gauge_mismatch / 422 (+ conflicting_stops, which the frontend marks
        on the map) — checked before the generic ValueError arm because
        GaugeMismatchError subclasses it;
      routing_graph_not_configured / 503 — the scenario pins a graph this
        deployment runs no instance for: a configuration gap, not a bad
        request, and not a crash for monitoring;
      routing_error / 422 — the router cannot serve the pair (no path on
        this gauge's network, a stop that does not snap);
      domain_error / 422 — models/pipeline.py's ValueError.
    """
    if isinstance(exc, GaugeMismatchError):
        return "gauge_mismatch", 422, {"conflicting_stops": exc.conflicting_stops}
    if isinstance(exc, RoutingGraphNotConfiguredError):
        return "routing_graph_not_configured", 503, {}
    if isinstance(exc, RailRoutingError):
        return "routing_error", 422, {}
    if isinstance(exc, ValueError):
        return "domain_error", 422, {}
    return None


# =============================================================================
# expert_timetable — validation + normalisation (0.9.32)
# =============================================================================

_EXPERT_KEYS = frozenset({"outbound", "return"})
_DIRECTION_KEYS = frozenset({"departure", "segment_addons"})


def _validate_departure(departure, where: str) -> list[str]:
    """One direction's departure override. An absent/None block is valid —
    it means "let the timetable_mode decide", which is the default."""
    if departure is None:
        return []
    if not isinstance(departure, dict):
        return [f"'{where}.departure' must be an object or null."]
    mode = departure.get("mode")
    if mode not in VALID_DEPARTURE_MODES:
        return [
            f"'{where}.departure.mode' = '{mode}' is invalid. Must be one of: "
            f"{sorted(VALID_DEPARTURE_MODES)}."
        ]
    field = "time_min" if mode == "absolute" else "shift_min"
    value = departure.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        return [f"'{where}.departure.{field}' must be an integer."]
    if mode == "absolute" and not (
        EXPERT_DEPARTURE_MIN_TIME <= value <= EXPERT_DEPARTURE_MAX_TIME
    ):
        return [
            f"'{where}.departure.time_min' must be between "
            f"{EXPERT_DEPARTURE_MIN_TIME} and {EXPERT_DEPARTURE_MAX_TIME} "
            f"(minutes on the service-day scale)."
        ]
    if mode == "shift" and abs(value) > EXPERT_MAX_DEPARTURE_SHIFT_MIN:
        return [
            f"'{where}.departure.shift_min' must be within "
            f"±{EXPERT_MAX_DEPARTURE_SHIFT_MIN} minutes."
        ]
    return []


def _validate_addons(addons, stops, where: str) -> list[str]:
    """One direction's per-leg add-ons.

    Every add-on names an ORDERED stop pair that must be adjacent in the
    posted 'stops' — the caller can always know that, so a pair that isn't
    is a request error rather than something to silently drop. Since route
    builder 0.9.34 nothing on the server can split a pair either (mode
    "add" is gone), so an add-on accepted here always reaches the leg it
    names; timetable.resolve_addons' drop path is a safety net rather than
    an expected case.

    'stops' is validated separately above; when it is malformed the
    adjacency check is skipped rather than reported twice."""
    if addons is None:
        return []
    if not isinstance(addons, list):
        return [f"'{where}.segment_addons' must be a list."]
    if len(addons) > EXPERT_MAX_ADDONS:
        return [
            f"'{where}.segment_addons' may hold at most {EXPERT_MAX_ADDONS} entries."
        ]

    errors: list[str] = []
    stops_usable = isinstance(stops, list) and all(isinstance(s, str) for s in stops)
    adjacent = (
        {(stops[i], stops[i + 1]) for i in range(len(stops) - 1)}
        if stops_usable
        else set()
    )
    seen: set[tuple[str, str]] = set()
    for i, addon in enumerate(addons):
        at = f"'{where}.segment_addons[{i}]'"
        if not isinstance(addon, dict):
            errors.append(f"{at} must be an object.")
            continue
        from_id, to_id = addon.get("from_stop_id"), addon.get("to_stop_id")
        if not isinstance(from_id, str) or not isinstance(to_id, str):
            errors.append(f"{at} needs string 'from_stop_id' and 'to_stop_id'.")
            continue
        add_min = addon.get("add_min")
        if isinstance(add_min, bool) or not isinstance(add_min, int):
            errors.append(f"{at}.add_min must be an integer.")
        elif not (1 <= add_min <= EXPERT_MAX_ADDON_MIN):
            # The lower bound is what makes this an ADD-on: a leg can only
            # ever be padded, never shortened below its routed physics.
            errors.append(
                f"{at}.add_min must be between 1 and {EXPERT_MAX_ADDON_MIN} minutes."
            )
        if (from_id, to_id) in seen:
            errors.append(f"{at} repeats the stop pair '{from_id}' → '{to_id}'.")
        seen.add((from_id, to_id))
        if stops_usable and (from_id, to_id) not in adjacent:
            errors.append(
                f"{at} names '{from_id}' → '{to_id}', which is not a leg of "
                f"'stops' — an add-on belongs to two consecutive stops, in "
                f"travel order."
            )
    return errors


def _validate_expert_timetable(block, stops) -> list[str]:
    """The whole expert_timetable block (§ the compute request contract).
    Absent is valid and means a fully automatic timetable."""
    if block is None:
        return []
    if not isinstance(block, dict):
        return ["'expert_timetable' must be an object."]

    errors: list[str] = []
    unknown = set(block) - _EXPERT_KEYS
    if unknown:
        errors.append(f"'expert_timetable' has unknown keys: {sorted(unknown)}.")

    for name in ("outbound", "return"):
        direction = block.get(name)
        if direction is None:
            continue
        where = f"expert_timetable.{name}"
        if not isinstance(direction, dict):
            errors.append(f"'{where}' must be an object.")
            continue
        if name == "return" and "mirror_outbound" in direction:
            # The default, spelled out. Mutually exclusive with the rest:
            # a block that both mirrors and overrides is a contradiction,
            # not something to resolve by precedence.
            if direction.get("mirror_outbound") is not True:
                errors.append(f"'{where}.mirror_outbound' must be true if present.")
            if set(direction) - {"mirror_outbound"}:
                errors.append(
                    f"'{where}' cannot carry 'mirror_outbound' together with "
                    f"its own overrides."
                )
            continue
        unknown = set(direction) - _DIRECTION_KEYS
        if unknown:
            errors.append(f"'{where}' has unknown keys: {sorted(unknown)}.")
        errors.extend(_validate_departure(direction.get("departure"), where))
        # The return direction runs the reversed stop list.
        direction_stops = (
            list(reversed(stops))
            if name == "return" and isinstance(stops, list)
            else stops
        )
        errors.extend(
            _validate_addons(direction.get("segment_addons"), direction_stops, where)
        )
    return errors


def _normalize_direction(direction: dict | None) -> dict | None:
    """One direction, in canonical form — or None when it overrides
    nothing, so an empty block and an absent one hash the same."""
    if not direction:
        return None
    departure = direction.get("departure") or None
    if departure is not None:
        mode = departure["mode"]
        field = "time_min" if mode == "absolute" else "shift_min"
        departure = {"mode": mode, field: int(departure[field])}
    addons = sorted(
        (
            {
                "from_stop_id": a["from_stop_id"],
                "to_stop_id": a["to_stop_id"],
                "add_min": int(a["add_min"]),
            }
            for a in direction.get("segment_addons") or []
        ),
        key=lambda a: (a["from_stop_id"], a["to_stop_id"]),
    )
    if departure is None and not addons:
        return None
    return {"departure": departure, "segment_addons": addons}


def normalize_expert_timetable(block) -> dict | None:
    """Canonical form of the expert_timetable block, for the resolved
    request echo — which is also the compute cache key, so two bodies that
    mean the same thing have to hash the same. Add-on order is irrelevant
    (sorted), an empty direction is None, and a return that mirrors is
    always spelled {"mirror_outbound": true} whether it was written out or
    left implicit.

    Assumes the block already passed validation above."""
    if not block:
        return None
    outbound = _normalize_direction(block.get("outbound"))
    raw_return = block.get("return")
    if raw_return and not raw_return.get("mirror_outbound"):
        return_block = _normalize_direction(raw_return) or {"mirror_outbound": True}
    else:
        return_block = {"mirror_outbound": True}
    if outbound is None and return_block == {"mirror_outbound": True}:
        return None  # overrides nothing — indistinguishable from no block at all
    return {"outbound": outbound, "return": return_block}


def canonical_request_hash(resolved_request: dict, measure_set_id: int) -> str:
    """The member cache key: canonical_sha256() over the RESOLVED request
    and the measure set. Hashing the resolved form — not the posted body —
    is what makes an omitted field and an explicitly-posted default
    converge on the same cache entry. The measure set is part of the key
    and not of the echo: the echo names a scenario and a composition, the
    variant names the measures, and two members of one scenario under
    different measures must not share a row."""
    return canonical_sha256(
        {"request": resolved_request, "measure_set_id": measure_set_id}
    )


MONTHS = tuple(str(m) for m in range(1, 13))


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_schedule(schedule) -> list[str]:
    """The optional `schedule` block, in either of its two shapes:

      {"days_per_week": n}     one frequency, an integer 1..7 — what the
                               Details card posts (ROUTE_BUILDER 0.9.40)
      {"1": d, ..., "12": d}   days per week for each month, each 0..7,
                               at least one month running — the seasonal
                               shape a later UI will post

    Absent means DEFAULT_DAYS_PER_WEEK in every month. A train that never
    runs has no evaluation, hence the floor on both shapes."""
    if schedule is None:
        return []
    if not isinstance(schedule, dict):
        return [
            "'schedule' must be an object: {'days_per_week': 1..7} or a month map "
            "'1'..'12' → days per week."
        ]
    if set(schedule) == {"days_per_week"}:
        d = schedule["days_per_week"]
        if not _is_int(d) or not 1 <= d <= 7:
            return ["'schedule.days_per_week' must be an integer 1..7."]
        return []
    errors = []
    if {str(k) for k in schedule} != set(MONTHS):
        errors.append(
            "'schedule' must carry either 'days_per_week' or exactly the months "
            "'1'..'12'."
        )
    for k, v in schedule.items():
        if not _is_int(v) or not 0 <= v <= 7:
            errors.append(f"'schedule[{k}]' must be an integer 0..7 (days per week).")
    if not errors and not any(int(v) > 0 for v in schedule.values()):
        errors.append("'schedule' must have at least one month with days > 0.")
    return errors


def normalize_schedule(schedule) -> dict[str, int]:
    """The month map every resolved request carries, string month keys in
    calendar order — one frequency expanded onto the twelve months, a
    posted map canonicalised, an absent block the default — so the echo,
    and therefore the family key, is the same however the plan was
    spelled. Assumes the block passed validate_schedule()."""
    if not isinstance(schedule, dict):
        return {m: DEFAULT_DAYS_PER_WEEK for m in MONTHS}
    if set(schedule) == {"days_per_week"}:
        return {m: int(schedule["days_per_week"]) for m in MONTHS}
    return {m: int(schedule[m] if m in schedule else schedule[int(m)]) for m in MONTHS}


def validate_fares(fares) -> list[str]:
    """`fares_eur_per_km`: an object of class_main → €/km, only the four
    fare classes, each a non-negative number. Partial is fine — the rest
    take the defaults."""
    if fares is None:
        return []
    if not isinstance(fares, dict):
        return ["'fares_eur_per_km' must be an object of class_main → EUR per km."]
    errors = []
    unknown = sorted(set(fares) - set(FARE_CLASS_MAINS))
    if unknown:
        errors.append(
            f"'fares_eur_per_km' has unknown classes {unknown}; "
            f"allowed: {list(FARE_CLASS_MAINS)}."
        )
    for k, v in fares.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
            errors.append(f"'fares_eur_per_km[{k}]' must be a non-negative number.")
    return errors


def _validate_per_class(value, field: str, *, signed: bool) -> list[str]:
    """The shape the three per-passenger tariff parts share: an object of
    class_main → EUR, only the four fare classes, partial allowed.

    `signed` is the one difference between them, and it is a modelling
    statement rather than a nicety: catering may be negative because a
    restaurant can be carried by the tickets it helps sell; a base fare and
    a bicycle charge cannot, because nobody is paid to travel."""
    if value is None:
        return []
    if not isinstance(value, dict):
        # Until CALC 0.9.30 catering_eur_per_pax was a single number for the
        # whole train. Say so, rather than letting a stored request fail as a
        # bare type error.
        if field == "catering_eur_per_pax" and isinstance(value, (int, float)):
            return [
                "'catering_eur_per_pax' is now an object of class_main → EUR "
                "per passenger (CALC 0.9.30), not a single number: the classes "
                "differ in what their base fare already includes."
            ]
        return [f"'{field}' must be an object of class_main → EUR per passenger."]
    errors = []
    unknown = sorted(set(value) - set(FARE_CLASS_MAINS))
    if unknown:
        errors.append(
            f"'{field}' has unknown classes {unknown}; "
            f"allowed: {list(FARE_CLASS_MAINS)}."
        )
    for k, v in value.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            errors.append(f"'{field}[{k}]' must be a number.")
        elif not signed and v < 0:
            errors.append(f"'{field}[{k}]' must be a non-negative number.")
    return errors


def validate_catering(catering) -> list[str]:
    """`catering_eur_per_pax`: class_main → EUR per passenger, either sign."""
    return _validate_per_class(catering, "catering_eur_per_pax", signed=True)


def validate_services(services) -> list[str]:
    """`services_eur_per_pax`: class_main → EUR per passenger, non-negative.
    It is the fare for carrying a bike, not a net figure."""
    return _validate_per_class(services, "services_eur_per_pax", signed=False)


def validate_fares_per_pax(fares) -> list[str]:
    """`fares_eur_per_pax`: the fixed part of the base fare, non-negative."""
    return _validate_per_class(fares, "fares_eur_per_pax", signed=False)


def _normalize_per_class(value, resolver) -> dict[str, float]:
    """The complete resolved map in FARE_CLASS_MAINS order, rounded to the
    cent — what the echo carries and the family key hashes. Ordering and
    rounding together keep an omitted field, a partial override and an
    explicit full default hashing alike."""
    resolved = resolver(value if isinstance(value, dict) else None)
    return {k: round(float(resolved[k]), 2) for k in FARE_CLASS_MAINS}


def normalize_catering(catering) -> dict[str, float]:
    return _normalize_per_class(catering, resolve_catering)


def normalize_services(services) -> dict[str, float]:
    return _normalize_per_class(services, resolve_services)


def normalize_fares_per_pax(fares) -> dict[str, float]:
    return _normalize_per_class(fares, resolve_fares_per_pax)


def normalize_fares(fares) -> dict[str, float]:
    """The complete resolved fare dict in FARE_CLASS_MAINS order — what the
    echo carries and the family key hashes."""
    resolved = resolve_fares(fares if isinstance(fares, dict) else None)
    return {k: round(float(resolved[k]), 4) for k in FARE_CLASS_MAINS}


def resolve_how_fields(body: dict) -> dict:
    """The HOW fields with defaults applied, in echo order — the part of
    the resolved request that does not name a scenario or composition,
    which is why the family request (api/helpers/family_compute.py) is
    exactly this plus the stops. An omitted field and an explicitly-posted
    default must compare (and hash) equal, so this is built explicitly
    rather than echoing the posted body verbatim."""
    return {
        "timetable_mode": body.get("timetable_mode", DEFAULT_TIMETABLE_MODE),
        "fixed_night_interval": body.get("fixed_night_interval"),
        # Always the twelve-month map with string keys: one posted
        # frequency, a posted map and an omitted block all land on the same
        # shape, so the same plan hashes the same however it was spelled.
        "schedule": normalize_schedule(body.get("schedule")),
        "min_turnaround_min": int(
            body.get("min_turnaround_min", DEFAULT_MIN_TURNAROUND_MIN)
        ),
        # Always the complete, resolved dict — defaults filled in and keys
        # in a fixed order — so a request naming one class and a request
        # spelling out all four with the same values hash the same.
        "fares_eur_per_km": normalize_fares(body.get("fares_eur_per_km")),
        # The three per-passenger tariff parts, each per class and each
        # resolved here like the per-km fares, so the key cannot tell an
        # omitted field from a posted default (models/demand/model.py).
        "fares_eur_per_pax": normalize_fares_per_pax(body.get("fares_eur_per_pax")),
        "services_eur_per_pax": normalize_services(body.get("services_eur_per_pax")),
        "catering_eur_per_pax": normalize_catering(body.get("catering_eur_per_pax")),
        "routing_mode": body.get("routing_mode", DEFAULT_ROUTING_MODE),
        "auto_stop_addition": body.get(
            "auto_stop_addition", DEFAULT_AUTO_STOP_ADDITION
        ),
        # Canonicalised (see normalize_expert_timetable) so an add-on list
        # in a different order, or a spelled-out mirroring return block,
        # converges on the same cache entry. None for every request that
        # doesn't override the timetable — which is the reason the key is
        # always present: an absent and an explicitly-empty block have to
        # be the same request.
        "expert_timetable": normalize_expert_timetable(body.get("expert_timetable")),
    }


def _resolve_request(body: dict, loader) -> dict:
    """The §2.1 resolved-request echo — defaults applied, scenario_id
    concrete — built BEFORE the compute so it can double as the cache key
    input."""
    return {
        "stops": list(body["stops"]),
        "composition_id": body.get("composition_id", DEFAULT_COMPOSITION_ID),
        "scenario_id": loader.resolve_scenario_id(body.get("scenario_id")),
        **resolve_how_fields(body),
    }


def _response_from_cache(entry: dict) -> dict:
    """Reassemble the member payload from a cache hit, in the exact key
    order the miss path produces."""
    payload = entry["payload"]
    response = {
        "route_builder_version": payload["route_builder_version"],
        "calc_version": payload["calc_version"],
        "route_fingerprint": entry["route_fingerprint"],
        "request": entry["resolved_request"],
    }
    if entry["suggested_stops"] is not None:
        response["suggested_stops"] = entry["suggested_stops"]
    for key in ("summary", "route", "evaluation"):
        response[key] = payload[key]
    return response


def compute_member(
    body: dict,
    loader=None,
    router=None,
    use_cache: bool = True,
    measures: MeasureSet = NO_MEASURES,
) -> tuple[dict, bool]:
    """Resolve + serve-from-cache-or-compute one member request (stops,
    composition_id, scenario_id, the HOW fields). Callers validate the body
    first (validate_calc_body() above) — this function assumes it has been
    checked and lets models/pipeline.py's ValueError (domain errors)
    propagate uncaught; the API layer maps them with
    classify_compute_error().

    loader defaults to the process-wide singleton (get_loader()); router
    defaults to the registry router for the scenario's routing_graph_key
    pin, resolved AFTER the request is (see below) — every Flask caller
    relies on these defaults and passes neither. The overrides exist for
    tests and scripts that bring their own instance; a caller passing a
    router takes over graph selection entirely. use_cache=False is what
    scripts/refresh_proposals.py uses: it flushes the cache first and
    computes each proposal exactly once.

    measures: the variant's measure set — only the evaluate half reads it
    (models/pipeline.py). Part of the cache key, not of the echo.

    Cache flow: resolved request + measure set -> canonical hash ->
    family.members lookup (adapters/family/member_cache.py). A hit whose
    stored payload matches the running ROUTE_BUILDER_VERSION/CALC_VERSION
    is served with zero routing and zero evaluation; a version mismatch is
    a miss (defence in depth for a forgotten flush — the recompute below
    overwrites the stale row). On a miss the fresh payload is stored under
    the same key.

    Returns (payload, cache_hit):
      {route_builder_version, calc_version, route_fingerprint, request,
       suggested_stops?, summary, route, evaluation: {views}}
    cache_hit's placement on the wire stays the caller's concern (compare
    exposes it; publish and the refresh paths ignore it).
    """
    loader = loader if loader is not None else get_loader()

    resolved_request = _resolve_request(body, loader)
    scenario_id = resolved_request["scenario_id"]
    # Router selection is a scenario pin (scenario.scenarios
    # .routing_graph_key), so it can only happen after the scenario is
    # resolved — an explicit router argument still wins, exactly like an
    # explicit loader. Not part of the cache hash: scenario rows are
    # immutable, so scenario_id already pins the graph.
    if router is None:
        router = get_rail_router(loader.resolve_routing_graph_key(scenario_id))

    cache = get_member_cache() if use_cache else None
    request_hash = (
        canonical_request_hash(resolved_request, measures.measure_set_id)
        if cache
        else None
    )
    if cache is not None:
        entry = cache.lookup(request_hash)
        if (
            entry is not None
            and entry["payload"]["route_builder_version"] == ROUTE_BUILDER_VERSION
            and entry["payload"]["calc_version"] == CALC_VERSION
        ):
            return _response_from_cache(entry), True

    result = run_compute(
        proposal_id=NEUTRAL_PROPOSAL_ID,
        proposal_version=NEUTRAL_PROPOSAL_VERSION,
        stops=body["stops"],
        composition_id=resolved_request["composition_id"],
        scenario_id=scenario_id,
        timetable_mode=resolved_request["timetable_mode"],
        fixed_night_interval=resolved_request["fixed_night_interval"],
        schedule=resolved_request["schedule"],
        min_turnaround_min=resolved_request["min_turnaround_min"],
        fares_eur_per_km=resolved_request["fares_eur_per_km"],
        fares_eur_per_pax=resolved_request["fares_eur_per_pax"],
        services_eur_per_pax=resolved_request["services_eur_per_pax"],
        catering_eur_per_pax=resolved_request["catering_eur_per_pax"],
        routing_mode=resolved_request["routing_mode"],
        auto_stop_addition=resolved_request["auto_stop_addition"],
        expert_timetable=expert_timetable_from_dict(
            resolved_request["expert_timetable"]
        ),
        loader=loader,
        router=router,
        measures=measures,
    )

    # route_dict carries the neutral-prefixed ids (P0_V0_R1...) exactly
    # like route_to_dict() always has; the evaluation views key some of
    # their data by trip_id too (per_trip_pair* matrices) —
    # rewrite_id_prefix() below strips the prefix from both in one
    # recursive pass, values AND dict keys, so the merged response is
    # prefix-free throughout.
    route_dict = route_to_dict(
        result.route, result.provenance.scenario_id, result.provenance.tracks
    )

    # §3.1 — computed from route_dict before the prefix strip below, but
    # prefix-independent by construction: the canonical extract only ever
    # uses stop_id (never route_id/trip_id/geometry_id), so the fingerprint
    # is identical whichever side of rewrite_id_prefix() it's taken from.
    fingerprint = route_fingerprint(route_dict)

    payload = {
        "route_builder_version": ROUTE_BUILDER_VERSION,
        "calc_version": CALC_VERSION,
        "route_fingerprint": fingerprint,
        "request": resolved_request,
    }
    if resolved_request["auto_stop_addition"] == "suggest":
        payload["suggested_stops"] = suggested_stops_to_dicts(result.suggestions)
    # Views only: the models registry is GET /api/models and the
    # parameters a member was priced from are GET /api/params/* for its
    # scenario — neither belongs in every member (D11).
    evaluation = {
        "views": views_to_dict(result.views, result.route),
        # CALC 0.9.28: the physical side of the same evaluation — rakes,
        # loco hours, people on board — read from the records the cost
        # model priced, so it cannot disagree with the breakdown.
        "operations": build_operations(
            result.route,
            result.evaluation_result,
            result.provenance.tracks,
            result.provenance.stop_infra,
        ),
    }
    # §5.4 gallery KPIs, derived from the exact route/evaluation dicts
    # this response carries — the same build_summary_row() the publish
    # projection uses, so the calc "summary" and a published gallery row
    # cannot drift. No geom_simplified here: the response already has the
    # full per-segment geometry (the gallery row needs the simplified
    # copy precisely because it has no segments).
    payload["summary"] = build_summary_row(route_dict, evaluation)
    payload["route"] = route_dict
    payload["evaluation"] = evaluation

    response = rewrite_id_prefix(payload, _NEUTRAL_PREFIX, "")

    if cache is not None:
        cache.store(
            request_hash=request_hash,
            route_fingerprint=fingerprint,
            scenario_id=scenario_id,
            measure_set_id=measures.measure_set_id,
            composition_id=resolved_request["composition_id"],
            resolved_request=response["request"],
            suggested_stops=response.get("suggested_stops"),
            payload={
                key: response[key]
                for key in (
                    "route_builder_version",
                    "calc_version",
                    "summary",
                    "route",
                    "evaluation",
                )
            },
        )

    return response, False
