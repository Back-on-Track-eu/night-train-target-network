"""
family_compute.py
=================
Validation + resolution + orchestration for POST /api/proposal/family and
its two GETs (api/proposal_family.py) — the family-level counterpart of
member_compute.py, and Flask-free apart from dependencies.py.

Flow of a POST:
  validate_family_body()   stops, HOW fields (shared with /calc), the two
                           optional axis lists, the optional `presented`
  resolve_family_request() the resolved echo — stops + the HOW fields as
                           member_compute resolves them, no composition
                           or scenario (those are the axes)
  resolve_family_axes()    ids → domain: variants (default: every variant
                           of a current scenario, base first), compositions
                           (default: the non-indicative catalog); the
                           FAMILY_MAX_MEMBERS cap
  family_key()             models/family/key.py — the pins AND the
                           document's shape (FAMILY_DOCUMENT_FORMAT), so a
                           reshaped document invalidates the cache
  build_or_load_family()   document cache hit → the stored document;
                           miss → run_family() on a fresh FamilyContext,
                           serialise, store, return

member_views() serves GET …/members/<sv>/<comp>/views: compute_member()
for that one member — member-cache hit or ≈350 ms — so the family never
writes 72 members into the member cache it does not need (D9).

Public interface:
  FamilyBodyError(errors)           400 validation
  FamilyTooLargeError(n, cap)       400 family_too_large
  UnknownMemberError(sv, comp)      404 on the views endpoint
  validate_family_body(body) -> list[str]
  resolve_family_request(body) -> dict
  resolve_family_axes(body, loader) -> FamilyAxes
  build_or_load_family(body) -> dict            # the document
  member_views(document_request, sv, comp) -> dict
"""

from __future__ import annotations

from api.config import FAMILY_MAX_MEMBERS, FAMILY_WORKERS
from api.helpers.dependencies import (
    get_family_document_cache,
    get_loader,
    get_rail_router,
)
from api.helpers.family_serialize import (
    FAMILY_DOCUMENT_FORMAT,
    error_member,
    family_document,
)
from api.helpers.member_compute import (
    classify_compute_error,
    compute_member,
    resolve_how_fields,
    validate_how_fields,
    validate_stops,
)
from api.helpers.route_serialize import expert_timetable_from_dict
from models.family.builder import FamilyAxes, FamilyRequest, run_family
from models.family.context import FamilyContext
from models.family.key import family_key
from models.route.model import DEFAULT_COMPOSITION_ID


class FamilyBodyError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


class FamilyTooLargeError(ValueError):
    def __init__(self, n_members: int) -> None:
        super().__init__(
            f"{n_members} members exceeds FAMILY_MAX_MEMBERS ({FAMILY_MAX_MEMBERS}); "
            "narrow scenario_variant_ids or composition_ids."
        )


class UnknownMemberError(LookupError):
    def __init__(self, scenario_variant_id: int, composition_id: str) -> None:
        super().__init__(
            f"No member for scenario_variant_id {scenario_variant_id} and "
            f"composition_id '{composition_id}' in this family's axes."
        )


# =============================================================================
# Validation
# =============================================================================


def _validate_id_list(body: dict, key: str, item_type: type) -> list[str]:
    value = body.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or not value:
        return [f"'{key}' must be a non-empty list if provided."]
    if not all(isinstance(v, item_type) and not isinstance(v, bool) for v in value):
        return [f"'{key}' must be a list of {item_type.__name__} values."]
    if len(set(value)) != len(value):
        return [f"'{key}' must not repeat an id."]
    return []


def validate_family_body(body: dict) -> list[str]:
    """Stops and HOW fields exactly as /calc validates them, plus the two
    optional axis lists and the optional presented member."""
    errors = validate_stops(body)
    errors.extend(validate_how_fields(body, body.get("stops")))
    errors.extend(_validate_id_list(body, "scenario_variant_ids", int))
    errors.extend(_validate_id_list(body, "composition_ids", str))

    presented = body.get("presented")
    if presented is not None:
        if not isinstance(presented, dict) or set(presented) - {
            "scenario_variant_id",
            "composition_id",
        }:
            errors.append(
                "'presented' must be an object with scenario_variant_id and/or "
                "composition_id."
            )
        else:
            sv = presented.get("scenario_variant_id")
            if sv is not None and (not isinstance(sv, int) or isinstance(sv, bool)):
                errors.append("'presented.scenario_variant_id' must be an integer.")
            cid = presented.get("composition_id")
            if cid is not None and not isinstance(cid, str):
                errors.append("'presented.composition_id' must be a string.")
    return errors


# =============================================================================
# Resolution
# =============================================================================


def resolve_family_request(body: dict) -> dict:
    """The document's request echo: stops + the HOW fields with defaults
    applied. Hashed into the family key, and what publish posts back as
    the compute_request together with the presented composition."""
    return {"stops": list(body["stops"]), **resolve_how_fields(body)}


def resolve_family_axes(body: dict, loader) -> FamilyAxes:
    """Axis lists (or their absence) → domain objects in presentation
    order. Variants default to every variant whose scenario is a current
    lineage head — the base scenario's first, then by scenario key — which
    is GET /api/scenarios' order; compositions default to the catalog
    without indicative KPIs, in catalog order. An explicit list keeps the
    caller's order."""
    scenarios = {s.scenario_id: s for s in loader.list_all_scenarios()}
    measure_sets = loader.build_all_measure_sets().all()
    all_variants = loader.list_scenario_variants()

    variant_ids = body.get("scenario_variant_ids")
    if variant_ids is None:
        variants = [
            v for v in all_variants if scenarios[v.scenario_id].is_current_scenario
        ]
        variants.sort(
            key=lambda v: (
                not scenarios[v.scenario_id].is_current_base,
                scenarios[v.scenario_id].scenario_key,
                v.measure_set_id,
            )
        )
    else:
        by_id = {v.scenario_variant_id: v for v in all_variants}
        unknown = [i for i in variant_ids if i not in by_id]
        if unknown:
            raise FamilyBodyError([f"Unknown scenario_variant_ids: {unknown}."])
        variants = [by_id[i] for i in variant_ids]

    catalog = loader.build_all_compositions(include_indicative=False).all()
    composition_ids = body.get("composition_ids")
    if composition_ids is None:
        compositions = list(catalog.values())
    else:
        unknown = [c for c in composition_ids if c not in catalog]
        if unknown:
            raise FamilyBodyError([f"Unknown composition_ids: {unknown}."])
        compositions = [catalog[c] for c in composition_ids]

    axes = FamilyAxes(
        variants=variants,
        scenarios=scenarios,
        measure_sets=measure_sets,
        compositions=compositions,
    )
    if axes.n_members > FAMILY_MAX_MEMBERS:
        raise FamilyTooLargeError(axes.n_members)
    return axes


def resolve_presented(body: dict, axes: FamilyAxes, loader) -> tuple[int, str]:
    """(scenario_variant_id, composition_id) the client shows first.
    Defaults: the base scenario's variant with the empty measure set, and
    DEFAULT_COMPOSITION_ID; either half may be posted. Must be on the
    axes — a presented member outside the family would never be built."""
    presented = body.get("presented") or {}
    variant_id = presented.get("scenario_variant_id")
    if variant_id is None:
        base_id = loader.resolve_scenario_id(None)
        base = [v for v in axes.variants if v.scenario_id == base_id]
        # The base variant is only absent from an explicit axis list.
        variant_id = (
            min(base, key=lambda v: v.measure_set_id).scenario_variant_id
            if base
            else axes.variants[0].scenario_variant_id
        )
    composition_id = presented.get("composition_id")
    if composition_id is None:
        ids = [c.comp_id for c in axes.compositions]
        composition_id = (
            DEFAULT_COMPOSITION_ID if DEFAULT_COMPOSITION_ID in ids else ids[0]
        )

    if variant_id not in {v.scenario_variant_id for v in axes.variants}:
        raise FamilyBodyError(
            [f"'presented.scenario_variant_id' {variant_id} is not on the axes."]
        )
    if composition_id not in {c.comp_id for c in axes.compositions}:
        raise FamilyBodyError(
            [f"'presented.composition_id' '{composition_id}' is not on the axes."]
        )
    return variant_id, composition_id


# =============================================================================
# Build or load
# =============================================================================


def build_or_load_family(body: dict) -> dict:
    """The document for a validated body: cache hit or a full build.
    `presented` is not part of the key, so a cached document is served
    with its own presented member replaced by the caller's — the members
    are the same either way."""
    loader = get_loader()
    request = resolve_family_request(body)
    axes = resolve_family_axes(body, loader)
    presented = resolve_presented(body, axes, loader)
    key = family_key(
        request,
        [v.scenario_variant_id for v in axes.variants],
        [c.comp_id for c in axes.compositions],
        FAMILY_DOCUMENT_FORMAT,
    )

    cache = get_family_document_cache()
    document = cache.get(key)
    if document is not None:
        document["presented"] = {
            "scenario_variant_id": presented[0],
            "composition_id": presented[1],
        }
        document["stats"]["cache_hit"] = True
        return document

    result = run_family(
        FamilyRequest(
            stops=request["stops"],
            timetable_mode=request["timetable_mode"],
            fixed_night_interval=request["fixed_night_interval"],
            schedule_mode=request["schedule_mode"],
            routing_mode=request["routing_mode"],
            auto_stop_addition=request["auto_stop_addition"],
            expert_timetable=expert_timetable_from_dict(request["expert_timetable"]),
        ),
        axes,
        FamilyContext(loader, get_rail_router),
        presented,
        FAMILY_WORKERS,
    )

    error_records = {}
    for member in result.members:
        if member.status == "error":
            classified = classify_compute_error(member.error)
            code, _, extra = classified or ("calc_error", 500, {})
            error_records[(member.scenario_variant_id, member.composition_id)] = (
                error_member(member, code, str(member.error), extra)
            )

    document = family_document(
        result, key, request, cache_hit=False, error_records=error_records
    )
    cache.put(key, document)
    return document


def member_views(
    document_request: dict, scenario_variant_id: int, composition_id: str
) -> dict:
    """{views} for one member — the full six views via compute_member()
    on the member's request, served from the member cache when it is
    there and computed once (≈350 ms) when it is not.

    document_request is the family's request echo; the member's scenario
    comes from its variant, its measure set with it (bypassing the member
    cache while it is not the empty one — see compute_member)."""
    loader = get_loader()
    try:
        scenario, measure_set = loader.resolve_scenario_variant(scenario_variant_id)
    except ValueError as exc:
        raise UnknownMemberError(scenario_variant_id, composition_id) from exc
    catalog = loader.build_all_compositions(include_indicative=False).all()
    if composition_id not in catalog:
        raise UnknownMemberError(scenario_variant_id, composition_id)

    body = {
        **document_request,
        "scenario_id": scenario.scenario_id,
        "composition_id": composition_id,
        # A member's route never carries suggestions; the family's did.
        "auto_stop_addition": "off",
    }
    payload, _ = compute_member(body, measures=measure_set)
    return {"views": payload["evaluation"]["views"]}
