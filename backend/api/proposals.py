"""
proposals.py
============
Proposal listing and loading (adapters/proposal/README.md §7.1/§7.2). Gallery/map
filtering is the full WP6/WP6.1 contract.

  GET  /api/proposals       — list, no filters, summaries only
  POST /api/proposals       — gallery + map in one endpoint (§7.1): generic
                               filters, sort, pagination, sectioned response
  GET  /api/proposal/<id>   — load one proposal, reconstructed from GTFS +
                               summary; performs the on-load version-refresh
                               fallback (§4.2, WP8) before returning

There is no save endpoint here — POST /api/proposal/publish
(api/proposal_publish.py) is the only write path (§2.2). Every user can
see and load every proposal; loading is unauthenticated (GETs are open,
same policy as api/proposal_engagement.py's GETs).
"""

import logging

from flask import Blueprint, jsonify, request

from api.helpers.dependencies import get_loader, get_proposal_repository
from api.helpers.proposal_load import load_current_container
from api import config
from api.helpers.proposal_serialize import (
    DEFAULT_INCLUDE,
    map_country_counts_to_geojson,
    map_lines_to_geojson,
    map_routes_to_geojson,
    map_stop_counts_to_dict,
    proposal_to_response_dict,
    summary_row_to_dict,
    validate_list_body,
)

logger = logging.getLogger(__name__)
bp = Blueprint("proposals", __name__)


@bp.get("/proposals")
def list_proposals():
    """All proposals, most recently updated first, as summaries — same
    shape as POST /api/proposals with an empty body."""
    return _list_response({})


@bp.post("/proposals")
def filter_proposals():
    """
    Gallery + map in one endpoint (§7.1). Every numeric summary column
    accepts a {"min", "max"} range, `created_at`/`updated_at` the same
    range shape with ISO 8601 strings, every scalar categorical column
    (`user_ids`, `composition_ids`, `proposal_ids`) an OR-only value
    list, `name` a substring; `countries`/`stop_ids` accept a plain list
    (OR/"any" — the default) or {"values": [...], "mode": "any"|"all"}
    for AND/"all". `trip_windows` matches a single trip's timetable,
    `bbox` a viewport intersection. `include` picks which response
    sections to compute — only the sections asked for run their query.
    `route_builder_version`/`calc_version`/`scenario_id` are not
    filterable (internal/analytical; the system — batch refresh + the
    load endpoint's on-load fallback — keeps every stored proposal on the
    current base scenario and current code versions on its own, §4.2).

    Request body (all fields optional):
      {
        "filter":  {...},                          // see §7.1 for the full shape
        "sort":    [{"by": <column>, "dir": "asc"|"desc"}],
        "limit":   int (default 50), "offset": int,
        "include": ["summaries", "map_lines", "map_routes",
                    "map_stop_counts", "map_country_counts"]
      }

    filter.sources picks the gallery's source union (WP10 step 6b):
    ["proposal"], ["existing"] (the ONTD catalog of real night trains),
    or both — DEFAULT IS BOTH when omitted. Existing rows carry the
    reduced descriptive shape (source="existing", route_id, ontd_url,
    geometry_routed, shared metrics — no financials/likes/timestamps)
    and always sort after proposals on the default newest-first (NULLS
    LAST).

    Response sections, each present iff requested via `include`:
      "summaries":          {"total": int, "proposals": [<summary>, ...]}
                             — rows are a mix of both source shapes,
                             discriminated by "source"
      "map_lines":           GeoJSON FeatureCollection, one feature per
                              stop-pair corridor shared across sources
                              (proposal_count / existing_count /
                              total_count per feature), geometry
                              simplified for overview zoom
      "map_routes":          GeoJSON FeatureCollection, one feature per
                              LISTED row — the route behind each card on
                              this page. The ONE section that honours
                              limit/offset (it shares summaries' window
                              exactly), so its size is capped by the page
                              rather than by the result set
      "map_stop_counts":    [{"stop_id", "lat", "lon",
                              "n_proposals", "n_existing", "n"}, ...]
      "map_country_counts":  GeoJSON FeatureCollection, one feature per
                              country (border geometry + n_proposals /
                              n_existing / n)
    """
    body = request.get_json(silent=True) or {}
    errors = validate_list_body(body)
    if errors:
        return jsonify({"error": "validation_error", "details": errors}), 400

    return _list_response(body)


@bp.get("/proposal/<int:proposal_id>")
def get_proposal(proposal_id: int):
    """
    Load a proposal — reconstructed compute-response shape (§2.1) plus
    proposal metadata (§7.2). Route/evaluation are rebuilt from storage
    (GTFS + sidecars, evaluation_output + the scenario pin) rather than
    read back verbatim — see adapters/proposal/repository.py's
    reconstruct_route()/reconstruct_evaluation() and
    adapters/proposal/gtfs_store.py for what "rebuilt" means for each
    section.

    On-load version-refresh fallback (§4.2, WP8): if the stored proposal
    has fallen behind the running route_builder_version/calc_version or
    the current base scenario, it's recomputed and overwritten in place
    before the response is built — correctness for anything the batch
    script (scripts/refresh_proposals.py) hasn't reached yet, at the cost
    of one slow load. Lives in api/helpers/proposal_load.py's
    load_current_container(), shared with POST /api/proposals/compare's
    per-side resolution (WP9).

    Response: identical shape to POST /api/proposal/publish's response
    (api/helpers/proposal_serialize.py's proposal_to_response_dict()).
    """
    repo = get_proposal_repository()
    container = load_current_container(repo, proposal_id)
    if container is None:
        return (
            jsonify(
                {
                    "error": "not_found",
                    "message": f"No proposal with proposal_id {proposal_id}.",
                }
            ),
            404,
        )

    loader = get_loader()
    route = repo.reconstruct_route(
        proposal_id, container["proposal_version"], container["scenario_id"], loader
    )
    evaluation = repo.reconstruct_evaluation(container, loader)

    payload = proposal_to_response_dict(container, route=route, evaluation=evaluation)
    return jsonify(payload), 200


# =============================================================================
# List assembly — shared by GET and POST /api/proposals
# =============================================================================


def _list_response(body: dict):
    """Assembles the sectioned §7.1 response — only the sections named in
    `include` run their query (each section's repository method takes the
    same `filters` dict, so every section reflects the same filter)."""
    repo = get_proposal_repository()
    filters = body.get("filter", {})
    include = body.get("include") or DEFAULT_INCLUDE

    response = {}
    # Shared by summaries and map_routes: the two sections must describe the
    # SAME window, or the map draws routes for cards that are not on screen.
    sort = body.get("sort")
    limit = body.get("limit", config.PROPOSALS_DEFAULT_LIMIT)
    offset = body.get("offset", 0)

    if "summaries" in include:
        rows, total = repo.list_summaries(
            filters=filters,
            sort=sort,
            limit=limit,
            offset=offset,
        )
        response["summaries"] = {
            "total": total,
            "proposals": [summary_row_to_dict(row) for row in rows],
        }
    if "map_routes" in include:
        response["map_routes"] = map_routes_to_geojson(
            repo.map_routes(filters, sort=sort, limit=limit, offset=offset)
        )
    if "map_lines" in include:
        response["map_lines"] = map_lines_to_geojson(repo.map_lines(filters))
    if "map_stop_counts" in include:
        response["map_stop_counts"] = map_stop_counts_to_dict(
            repo.map_stop_counts(filters)
        )
    if "map_country_counts" in include:
        response["map_country_counts"] = map_country_counts_to_geojson(
            repo.map_country_counts(filters)
        )
    return jsonify(response), 200
