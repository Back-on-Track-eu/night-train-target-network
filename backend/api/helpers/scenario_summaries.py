"""
scenario_summaries.py
=====================
The §5.4 projection of one proposal on EVERY current scenario variant
(adapters/proposal/README.md §5.4a) — the rows
proposals.proposal_scenario_summaries holds, computed for every publish
and refresh so the gallery can be read on the scenario a viewer picks.

Two paths to the same rows, cheap one first:

  DOCUMENT — the family the builder just ran for these stops and HOW
  fields is in family.documents (its default axes: every current variant
  x the whole catalog). Every member there already carries the §5.4
  summary this projection would rebuild, and one compact route per
  (scenario, composition) with a shared geometry pool. So when the key
  hits, the rows are a lookup plus the geometry work — no routing, no
  catalog loads, no evaluation. This is the publish-after-Evaluate case,
  which is nearly every publish.

  BUILD — no document (a stored request replayed by the refresh script, a
  document swept by TTL, a version bump): run_family() for the proposal's
  composition across the current variants on a shared FamilyContext, the
  same call POST /api/proposal/family makes, and project each member.

Both produce identical rows by construction: the document's summary IS
build_summary_row()'s output, and the geometry helpers in
adapters/proposal/projection.py share their simplification between the
full and compact route shapes.

Before either path, variants whose routing graph this deployment does not
serve are resolved to error rows WITHOUT a build: the router registry
answers per graph key, so the four Infra 2032 variants on a stack that
runs only infra-2026 cost a dict lookup instead of a full catalog load
each.

A member the family cannot compute — its variant's routing graph not
served by this deployment, an unroutable pair on that network, a gauge
clash — is returned as an error row (status "error", the member's code,
no figures) rather than dropped: the gallery then says why the proposal
is missing on that scenario instead of silently omitting it.

Flask-free apart from dependencies.py, like family_compute.py: the
publish view, the on-load refresh and scripts/refresh_proposals.py all
call compute_scenario_rows() the same way.

Public interface:
  compute_scenario_rows(compute_request) -> list[dict]
  SCENARIO_ROW_SOURCE  (module-level counter, for the tests and the log)
"""

from __future__ import annotations

import logging

from adapters.proposal.projection import (
    build_summary_db_row,
    compact_route_geometry,
    corridor_segments,
)
from api.config import FAMILY_WORKERS
from api.helpers.dependencies import (
    RoutingGraphNotConfiguredError,
    get_family_document_cache,
    get_loader,
    get_rail_router,
)
from api.helpers.evaluation_serialize import route_view_to_dict
from api.helpers.family_compute import (
    family_request_from_echo,
    resolve_family_axes,
    resolve_family_request,
)
from api.helpers.family_serialize import FAMILY_DOCUMENT_FORMAT, route_ref
from api.helpers.member_compute import classify_compute_error
from api.helpers.route_serialize import route_to_dict
from models.family.builder import FamilyAxes, run_family
from models.family.context import FamilyContext
from models.family.key import family_key

logger = logging.getLogger(__name__)

# Which path the last call took — "document", "build", or "unavailable"
# when every variant short-circuited. Diagnostics only (the log line below
# and the tests); nothing branches on it.
SCENARIO_ROW_SOURCE: str | None = None


def compute_scenario_rows(compute_request: dict, loader=None) -> list[dict]:
    """One row per current scenario variant for the proposal described
    by `compute_request` (a resolved member request: stops, HOW fields,
    composition_id). Returns dicts the repository writes as they are:

      {scenario_variant_id, scenario_id, measure_set_id, composition_id,
       status: "ok" | "error", error_code: str | None,
       summary: build_summary_db_row() output | None,
       segments: corridor_segments() output | None}

    The variants are the family's default axis — every variant of a
    current scenario, base first — so the rows cover exactly what
    GET /api/scenarios offers.
    """
    global SCENARIO_ROW_SOURCE
    loader = loader if loader is not None else get_loader()
    composition_id = compute_request["composition_id"]
    # Re-resolved rather than taken verbatim: a stored compute_request from
    # before a HOW field existed lacks that key, and the backfill replays
    # exactly such rows. Defaults apply the way they do on every compute.
    echo = resolve_family_request(compute_request)

    axes = resolve_family_axes({}, loader)
    catalog = loader.build_all_compositions(include_indicative=True).all()
    if composition_id not in catalog:
        raise ValueError(f"Unknown composition_id '{composition_id}'.")

    # Variants this deployment cannot compute at all, answered before any
    # catalog is touched: the router registry is a dict keyed by the
    # scenario's routing_graph_key pin, so one lookup per distinct graph
    # settles every variant on it.
    servable, unavailable = _split_by_routing_graph(axes)
    rows = [
        _row(variant, composition_id, status="error", error_code=code)
        for variant, code in unavailable
    ]
    if not servable:
        SCENARIO_ROW_SOURCE = "unavailable"
        return rows

    document_rows = _rows_from_document(echo, axes, servable, composition_id)
    if document_rows is not None:
        SCENARIO_ROW_SOURCE = "document"
        return rows + document_rows

    SCENARIO_ROW_SOURCE = "build"
    return rows + _rows_from_build(
        echo, axes, servable, composition_id, catalog, loader
    )


def _row(
    variant,
    composition_id: str,
    *,
    status: str,
    error_code: str | None = None,
    summary: dict | None = None,
    segments: dict | None = None,
) -> dict:
    """One repository-shaped row. Kept in one place so the three paths
    below cannot drift in what they emit."""
    return {
        "scenario_variant_id": variant.scenario_variant_id,
        "scenario_id": variant.scenario_id,
        "measure_set_id": variant.measure_set_id,
        "composition_id": composition_id,
        "status": status,
        "error_code": error_code,
        "summary": summary,
        "segments": segments,
    }


def _split_by_routing_graph(axes: FamilyAxes):
    """(servable variants, [(variant, error code), ...]) — a variant whose
    scenario pins a routing graph this deployment serves no instance for
    can only ever be an error member, and finding that out through a full
    build costs a catalog load per scenario (FamilyContext.prewarm() loads
    before it asks for the router). This asks the registry first."""
    servable = []
    unavailable = []
    graph_ok: dict[str, bool] = {}
    for variant in axes.variants:
        graph_key = axes.scenarios[variant.scenario_id].routing_graph_key
        if graph_key not in graph_ok:
            try:
                get_rail_router(graph_key)
                graph_ok[graph_key] = True
            except RoutingGraphNotConfiguredError:
                graph_ok[graph_key] = False
        if graph_ok[graph_key]:
            servable.append(variant)
        else:
            unavailable.append((variant, "routing_graph_not_configured"))
    return servable, unavailable


def _rows_from_document(
    echo: dict, axes: FamilyAxes, servable: list, composition_id: str
) -> list[dict] | None:
    """The rows read out of the family document the builder just wrote, or
    None when there is no usable document (a miss, or one missing a member
    this projection needs — a partial document is not worth stitching to a
    build, so the caller rebuilds the lot).

    The key is the DEFAULT family: every current variant x the whole
    catalog, which is what the builder posts, so a publish that follows an
    Evaluate or a Recalculate hits. The document is server-written
    (adapters/family/README.md), so reading it satisfies §2.2's "never
    persist a client-supplied result" exactly as a member-cache hit does.
    """
    key = family_key(
        echo,
        [v.scenario_variant_id for v in axes.variants],
        [c.comp_id for c in axes.compositions],
        FAMILY_DOCUMENT_FORMAT,
    )
    document = get_family_document_cache().get(key)
    if document is None:
        return None

    members = {
        (m["scenario_variant_id"], m["composition_id"]): m
        for m in document.get("members", [])
    }
    pool = document.get("geometries", {})
    routes = document.get("routes", {})
    rows = []
    for variant in servable:
        member = members.get((variant.scenario_variant_id, composition_id))
        if member is None:
            return None
        if member["status"] != "ok":
            rows.append(
                _row(
                    variant,
                    composition_id,
                    status="error",
                    error_code=member.get("error", "calc_error"),
                )
            )
            continue
        route = routes.get(
            member.get("route_ref") or route_ref(variant.scenario_id, composition_id)
        )
        if route is None:
            return None
        geom_simplified, segments = compact_route_geometry(route, pool)
        rows.append(
            _row(
                variant,
                composition_id,
                status="ok",
                summary={**member["summary"], "geom_simplified": geom_simplified},
                segments=segments,
            )
        )
    logger.info("scenario rows from family document (%d variant(s))", len(rows))
    return rows


def _rows_from_build(
    echo: dict,
    axes: FamilyAxes,
    servable: list,
    composition_id: str,
    catalog: dict,
    loader,
) -> list[dict]:
    """The fallback: one family for this proposal's composition across the
    servable variants, on a shared FamilyContext — the same run_family()
    POST /api/proposal/family makes, so a row built here cannot disagree
    with what the builder shows for that member. Suggestions are off: the
    stops are the proposal's, and a suggestion run would cost time and
    change nothing stored."""
    build_axes = FamilyAxes(
        variants=servable,
        scenarios=axes.scenarios,
        measure_sets=axes.measure_sets,
        compositions=[catalog[composition_id]],
    )
    # Base variant with the empty measure set first — the same member the
    # container row holds, and the one whose route the others share on the
    # same network.
    base_id = loader.resolve_scenario_id(None)
    base = [v for v in servable if v.scenario_id == base_id]
    presented_variant = (
        min(base, key=lambda v: v.measure_set_id).scenario_variant_id
        if base
        else servable[0].scenario_variant_id
    )

    result = run_family(
        family_request_from_echo({**echo, "auto_stop_addition": "off"}),
        build_axes,
        FamilyContext(loader, get_rail_router),
        (presented_variant, composition_id),
        FAMILY_WORKERS,
    )

    by_id = {v.scenario_variant_id: v for v in servable}
    rows = []
    for member in result.members:
        variant = by_id[member.scenario_variant_id]
        if member.status != "ok":
            classified = classify_compute_error(member.error)
            rows.append(
                _row(
                    variant,
                    composition_id,
                    status="error",
                    error_code=classified[0] if classified else "calc_error",
                )
            )
            continue
        # The same two dicts family_serialize builds the document's member
        # summary from — route first, because the summary reads od_pairs
        # and the composition block off it.
        route_dict = route_to_dict(
            member.route, member.scenario_id, member.provenance.tracks
        )
        evaluation = {
            "views": {"route": route_view_to_dict(member.views.bd_all, member.route)}
        }
        rows.append(
            _row(
                variant,
                composition_id,
                status="ok",
                summary=build_summary_db_row(route_dict, evaluation),
                segments=corridor_segments(route_dict),
            )
        )
    logger.info("scenario rows built (%d variant(s))", len(rows))
    return rows
