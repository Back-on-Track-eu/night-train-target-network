"""
proposal_compare.py
====================
Per-side resolution and diff building for POST /api/proposals/compare
(PROPOSALS_DESIGN.md §7.3, WP9).

Each compare side is anchored on one stored proposal. A side without
overrides IS that proposal — reconstructed exactly like GET
/api/proposal/<id> (route from GTFS, evaluation via the scenario pin),
plus its gallery summary row, marked published: true. A side WITH
overrides (scenario_id and/or composition_id) is computed ephemerally:
the anchor's stored compute_request with the overridden fields, through
the same compute_proposal() every other compute path uses — never
persisted, marked published: false, its summary taken straight from the
calc response's own "summary" block (models/evaluation/summary.py's
build_summary_row() — the same derivation publish runs), so stored and
computed sides diff over identical summary semantics.

Both side kinds run the §4.2 on-load refresh first
(api/helpers/proposal_load.py) — for computed sides this matters just as
much as for stored ones: an override side replays the anchor's stored
compute_request, whose scenario_id only reliably means "current base"
after the refresh has run.

The diff is side B minus side A (sides[1] - sides[0]) throughout:

- "summary": the gallery-KPI columns (§5.4), each {a, b, abs, rel}
- "views": a generic recursive numeric diff over the two
  evaluation.views trees — every cost category, every view, every
  normalisation, every class key, with no per-field maintenance.
  Diffed on STRUCTURAL ids: a published side's views are keyed by its
  own P{id}_V{n}_-prefixed trip ids, so both sides are neutralised to
  the bare R1/T1 form first (_structural_views() below) — otherwise no
  trip-keyed view could ever match across two proposals. Keys still
  present on only one side after that (genuinely different countries,
  ODs, stops, or different trip counts) are collected as dotted paths
  under "views_unmatched" rather than half-diffed; those paths are
  structural too, so they read the same whichever sides produced
  them.
- route context: fingerprints, route_identical, and which resolved
  compute-request fields differ (§7.3's "identical route, different
  composition/scenario" statement).

Public interface:
  validate_compare_body(body)              -> list[str]
  resolve_side(index, side, repo, loader)  -> dict   (raises SideNotFoundError; domain ValueError propagates)
  build_diff(side_a, side_b)               -> dict
  build_route_context(side_a, side_b)      -> dict
  SideNotFoundError                        (carries .side_index, .proposal_id)
"""

from __future__ import annotations

from adapters.proposal.id_prefix import rewrite_id_prefix
from api.helpers.proposal_compute import compute_proposal, validate_calc_body
from api.helpers.proposal_load import load_current_container
from api.helpers.proposal_serialize import (
    proposal_to_response_dict,
    summary_row_to_dict,
)

_OVERRIDE_KEYS = ("scenario_id", "composition_id")
_SIDE_KEYS = frozenset({"proposal_id", *_OVERRIDE_KEYS})

# The §5.4 gallery-KPI columns the "summary" diff runs over, in gallery
# column order — deliberately an explicit list rather than "every numeric
# summary field": identity/engagement numbers (proposal_id, user_id,
# scenario_id, likes_count, comments_count, ...) are not KPIs and a delta
# over them would
# be meaningless.
SUMMARY_KPI_FIELDS = (
    "total_distance_km",
    "total_time_h",
    "avg_speed_kmh",
    "n_stops",
    "cost_eur_per_train_km",
    "revenue_eur_per_train_km",
    "margin_eur_per_train_km",
    "subsidy_eur_per_year",
    "demand_trips_per_year",
    "demand_trip_km_per_year",
    "shift_air_trips_per_year",
    "shift_air_trip_km_per_year",
    "shift_car_trips_per_year",
    "shift_car_trip_km_per_year",
    "co2_savings_t_per_year",
    "subsidy_eur_per_t_co2",
    "co2_g_per_pax_km",
)

# Deltas are rounded to absorb binary-float noise (two 2dp values can
# subtract to 0.20000000000000284) — finer than any precision the views
# actually carry, so nothing real is lost.
_DIFF_NDIGITS = 6


class SideNotFoundError(Exception):
    """A compare side's anchor proposal_id doesn't exist."""

    def __init__(self, side_index: int, proposal_id: int) -> None:
        self.side_index = side_index
        self.proposal_id = proposal_id
        super().__init__(
            f"sides[{side_index}]: no proposal with proposal_id {proposal_id}"
        )


# =============================================================================
# Request validation
# =============================================================================


def validate_compare_body(body: dict) -> list[str]:
    """Structural validation of the §7.3 compare request. Two sides for
    now (the shape allows more later); each side needs a proposal_id
    anchor and may override scenario_id/composition_id — nothing else."""
    sides = body.get("sides")
    if not isinstance(sides, list) or len(sides) != 2:
        return ["'sides' must be a list of exactly 2 side objects."]

    errors = []
    for i, side in enumerate(sides):
        if not isinstance(side, dict):
            errors.append(f"sides[{i}] must be an object.")
            continue
        if not isinstance(side.get("proposal_id"), int):
            errors.append(f"sides[{i}].proposal_id must be an integer.")
        if "scenario_id" in side and not isinstance(side["scenario_id"], int):
            errors.append(f"sides[{i}].scenario_id must be an integer.")
        if "composition_id" in side and not isinstance(side["composition_id"], str):
            errors.append(f"sides[{i}].composition_id must be a string.")
        unknown = set(side) - _SIDE_KEYS
        if unknown:
            errors.append(f"sides[{i}] has unknown keys: {sorted(unknown)}.")
    return errors


# =============================================================================
# Side resolution
# =============================================================================


def resolve_side(index: int, side: dict, repo, loader) -> dict:
    """One §7.3 side, resolved: the stored proposal as-is when no
    overrides are given, an ephemeral compute of the anchor's
    compute_request with the overridden fields otherwise. Any override
    key present routes to the compute path, even if its value equals the
    stored one — deterministic, no equality special-casing (the result
    is identical either way, only published/summary provenance differs).

    Raises SideNotFoundError for an unknown anchor; domain errors from
    an override compute (unknown scenario/composition, ...) propagate as
    ValueError for the blueprint's 422 mapping."""
    container = load_current_container(repo, side["proposal_id"])
    if container is None:
        raise SideNotFoundError(index, side["proposal_id"])

    overrides = {k: side[k] for k in _OVERRIDE_KEYS if k in side}
    if not overrides:
        return _stored_side(container, repo, loader)
    return _computed_side(container, overrides)


def _stored_side(container: dict, repo, loader) -> dict:
    """The GET /api/proposal/<id> response shape plus published: true and
    the proposal's gallery summary row (engagement counts included)."""
    route = repo.reconstruct_route(
        container["proposal_id"],
        container["proposal_version"],
        container["scenario_id"],
        loader,
    )
    evaluation = repo.reconstruct_evaluation(container, loader)
    # Summary fetched through the ordinary gallery machinery so the row
    # carries exactly the §5.4 shape incl. engagement counts. publish() writes
    # container + summary in one transaction, so the row always exists.
    rows, _ = repo.list_summaries(filters={"proposal_ids": [container["proposal_id"]]})

    side = {"published": True}
    side.update(
        proposal_to_response_dict(container, route=route, evaluation=evaluation)
    )
    side["summary"] = summary_row_to_dict(rows[0])
    return side


def _computed_side(container: dict, overrides: dict) -> dict:
    """The POST /api/proposal/calc response shape plus published: false,
    the anchor proposal_id, the applied overrides, and an on-the-fly
    summary. Nothing is persisted — the compute goes through the same
    compute_proposal() as /calc, publish, and the refresh paths, and
    therefore through the §2.3 compute cache: comparing warms the editor
    and vice versa."""
    request = dict(container["compute_request"])
    request.update(overrides)
    errors = validate_calc_body(request)
    if errors:
        raise ValueError(" ".join(errors))

    computed, cache_hit = compute_proposal(request)

    # The calc response's own §5.4 KPI block (same build_summary_row()
    # the publish projection runs — WP10 step 5), minus what only exists
    # for stored rows: geom_simplified (map columns don't diff) and the
    # DB-side identity/engagement fields. composition/scenario are echoed
    # in so both side shapes carry the variant coordinate the same way.
    summary = {
        "composition_id": computed["request"]["composition_id"],
        "scenario_id": computed["request"]["scenario_id"],
        **computed["summary"],
    }

    side = {
        "published": False,
        "proposal_id": container["proposal_id"],
        "overrides": overrides,
        "route_builder_version": computed["route_builder_version"],
        "calc_version": computed["calc_version"],
        "route_fingerprint": computed["route_fingerprint"],
        "cache_hit": cache_hit,
        "request": computed["request"],
    }
    if "suggested_stops" in computed:
        side["suggested_stops"] = computed["suggested_stops"]
    side["route"] = computed["route"]
    side["evaluation"] = computed["evaluation"]
    side["summary"] = summary
    return side


# =============================================================================
# Diff — side B minus side A
# =============================================================================


def _structural_views(side: dict) -> dict:
    """A side's evaluation.views keyed by structural ids (R1, T1, ...)
    rather than the published P{id}_V{n}_ form.

    Trip ids appear as dict KEYS in the pair-keyed views
    (per_trip_pair, ..._per_country, ..._per_od, ..._per_section,
    per_trip_per_stop), and a published side carries its own proposal's
    prefix there. Diffing two published sides verbatim therefore matched
    nothing below the route view — every pair-keyed subtree fell into
    views_unmatched, silently, however similar the two routes were.
    Neutralising both sides first makes the diff compare like with like.

    Computed sides are already structural (compute_proposal() strips the
    neutral prefix), so only published sides need rewriting. The side's
    own views are left untouched — the response still shows each side's
    real prefixed ids, per §2.2's ID convention; only the diff input is
    neutralised."""
    views = side["evaluation"]["views"]
    if not side["published"]:
        return views
    prefix = f"P{side['proposal_id']}_V{side['proposal_version']}_"
    return rewrite_id_prefix(views, prefix, "")


def build_diff(side_a: dict, side_b: dict) -> dict:
    """The §7.3 diff section: per-KPI summary deltas plus the structured
    diff over the two evaluation.views trees. B - A throughout."""
    only_a: list[str] = []
    only_b: list[str] = []
    views = _diff_tree(
        _structural_views(side_a), _structural_views(side_b), "", only_a, only_b
    )
    return {
        "summary": _diff_summary(side_a["summary"], side_b["summary"]),
        "views": views or {},
        "views_unmatched": {"a_only": only_a, "b_only": only_b},
    }


def build_route_context(side_a: dict, side_b: dict) -> dict:
    """§7.3's route context: are the two sides the same physical route
    (§3.1 fingerprints), and which resolved compute-request fields differ
    — so the frontend can state e.g. "identical route, different
    composition"."""
    req_a, req_b = side_a["request"], side_b["request"]
    differing = sorted(
        key for key in set(req_a) | set(req_b) if req_a.get(key) != req_b.get(key)
    )
    return {
        "fingerprints": [side_a["route_fingerprint"], side_b["route_fingerprint"]],
        "route_identical": side_a["route_fingerprint"] == side_b["route_fingerprint"],
        "differing_request_fields": differing,
    }


def _diff_summary(summary_a: dict, summary_b: dict) -> dict:
    """{a, b, abs, rel} per gallery-KPI column, in gallery column order.
    Fields that aren't numeric on both sides (e.g. a null
    subsidy_eur_per_t_co2 when CO2 savings are zero) are skipped — both
    raw values remain visible on the sides themselves."""
    out = {}
    for field in SUMMARY_KPI_FIELDS:
        leaf = _diff_leaf(summary_a.get(field), summary_b.get(field))
        if leaf is not None:
            out[field] = leaf
    return out


def _diff_tree(a, b, path: str, only_a: list[str], only_b: list[str]):
    """Generic recursive numeric diff. Dicts recurse over shared keys
    (side-A key order preserved) and record one-sided keys as dotted
    paths; numeric leaves become {a, b, abs, rel}; everything else —
    strings (descriptions, filter labels, normalisation metadata), lists,
    nulls, type mismatches — is skipped, and dicts left empty by the
    skipping are pruned. Returns None for anything that produced no
    numeric content."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = {}
        for key, a_val in a.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key in b:
                child = _diff_tree(a_val, b[key], child_path, only_a, only_b)
                if child is not None:
                    out[key] = child
            else:
                only_a.append(child_path)
        for key in b:
            if key not in a:
                only_b.append(f"{path}.{key}" if path else str(key))
        return out or None
    return _diff_leaf(a, b)


def _diff_leaf(a, b):
    """{a, b, abs, rel} when both values are numbers, else None. rel is
    (b - a) / |a|, null on a zero base."""
    if not (_is_number(a) and _is_number(b)):
        return None
    delta = round(b - a, _DIFF_NDIGITS)
    rel = round(delta / abs(a), _DIFF_NDIGITS) if a != 0 else None
    return {"a": a, "b": b, "abs": delta, "rel": rel}


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
