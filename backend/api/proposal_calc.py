"""
proposal_calc.py
=================
POST /api/proposal/calc         — one route under one scenario × composition
POST /api/proposal/calc/matrix  — one route under every selectable scenario ×
                                  every composition, streamed cell by cell

The merged compute endpoint (adapters/proposal/README.md §2.1). One stateless
request -> route + evaluation, no side effects. The matrix (§2.5) is the
same compute repeated over a grid: every cell goes through
compute_proposal() and therefore through the §2.3 compute cache, so a
drill-down /calc on any cell afterwards is a cache hit.

The actual pipeline lives two layers down — domain orchestration in
models/pipeline.py, validation + serialization in api/helpers/
proposal_compute.py — so publish (api/helpers/publish_dispatch.py)
computes exactly the same way this endpoint does, with no risk of the two
drifting apart. This view is thin delegation + a cache_hit stamp only;
the matrix view delegates to api/helpers/proposal_matrix.py and only
chooses between the two encodings (NDJSON stream / JSON document).
"""

import json
import logging

from flask import Blueprint, Response, jsonify, request, stream_with_context

from api.helpers.dependencies import DataNotLoadedError, get_loader
from api.helpers.matrix_serialize import fold_matrix_records
from api.helpers.proposal_compute import (
    classify_compute_error,
    compute_proposal,
    validate_calc_body,
)
from api.helpers.proposal_matrix import (
    MatrixAxisError,
    iter_matrix_records,
    resolve_matrix_axes,
    validate_matrix_body,
)

NDJSON_MIMETYPE = "application/x-ndjson"

logger = logging.getLogger(__name__)
bp = Blueprint("proposal_calc", __name__)


@bp.post("/calc")
def calc():
    """
    Plan a route and evaluate it in one call — see adapters/proposal/README.md
    §2.1 for the full request/response contract. Stateless: no
    persistence, no proposal_id/proposal_version in the request, no auth.

    Request body: identical to §2.1's WHAT/HOW fields (stops,
    composition_id, scenario_id, timetable_mode, fixed_night_interval,
    schedule_mode, routing_mode, auto_stop_addition) — see
    validate_calc_body() and adapters/proposal/README.md §2.1 for field
    semantics.

    Response:
      {
        "route_builder_version": "...",
        "calc_version": "...",
        "route_fingerprint": "sha256:...",  // §3.1
        "cache_hit": false,            // true when served from the §2.3 compute cache
        "request": { ... },            // resolved: defaults applied, scenario_id concrete
        "suggested_stops": [ ... ],    // only when auto_stop_addition="suggest"
        "summary": { ... },            // §5.4 gallery KPIs (no geom_simplified)
        "route": { ... },              // route_to_dict() shape, neutral ids (R1, ...)
        "evaluation": {
          "models": { ... }, "input": { "parameters": { ... } }, "views": { ... }
        }
      }
    """
    body = request.get_json(silent=True)
    if not body:
        return (
            jsonify({"error": "bad_request", "message": "Request body must be JSON."}),
            400,
        )

    errors = validate_calc_body(body)
    if errors:
        logger.warning("proposal/calc validation failed — %s", errors)
        return jsonify({"error": "validation_error", "details": errors}), 400

    try:
        computed, cache_hit = compute_proposal(body)
    except Exception as e:
        # One mapping for every compute entry point — see
        # classify_compute_error() for what each code means.
        classified = classify_compute_error(e)
        if classified is None:
            logger.exception("proposal/calc failed (unexpected): %s", e)
            return jsonify({"error": "calc_error", "message": str(e)}), 500
        code, status, extra = classified
        log = logger.error if status == 503 else logger.warning
        log("proposal/calc failed (%s): %s", code, e)
        return jsonify({"error": code, "message": str(e), **extra}), status

    # Re-keyed (not just .update()) so cache_hit lands in its documented
    # §2.1 position between route_fingerprint and request rather than at
    # the end — app.json.sort_keys=False (main.py) means dict insertion
    # order is exactly the wire order.
    payload = {
        "route_builder_version": computed["route_builder_version"],
        "calc_version": computed["calc_version"],
        "route_fingerprint": computed["route_fingerprint"],
        "cache_hit": cache_hit,
        "request": computed["request"],
    }
    if "suggested_stops" in computed:
        payload["suggested_stops"] = computed["suggested_stops"]
    payload["summary"] = computed["summary"]
    payload["route"] = computed["route"]
    payload["evaluation"] = computed["evaluation"]

    return jsonify(payload), 200


@bp.post("/calc/matrix")
def calc_matrix():
    """
    One route under every selected scenario × every selected composition
    — adapters/proposal/README.md §2.5 for the full contract, api/README.md
    for the record shapes.

    Request body: stops + the /calc HOW fields, plus the axes
    (composition_ids / scenario_ids, null or omitted = default axis) and
    detail ("summary" default | "full").

    Two encodings of one record sequence (header, shared*, cell*, done):
      Accept: application/x-ndjson  → streamed, one JSON record per line,
                                      baseline cell first, the rest in
                                      completion order;
      anything else                 → one JSON document, cells sorted by
                                      index (fold_matrix_records).

    Request-level errors (JSON body, validation, unknown axis ids, cell
    cap, data not loaded) are ordinary 400/503 answers decided BEFORE the
    first byte. Once the stream has started, a failing cell is a cell
    record with status "error" and the HTTP status stays 200.
    """
    body = request.get_json(silent=True)
    if not body:
        return (
            jsonify({"error": "bad_request", "message": "Request body must be JSON."}),
            400,
        )
    errors = validate_matrix_body(body)
    if errors:
        logger.warning("proposal/calc/matrix validation failed — %s", errors)
        return jsonify({"error": "validation_error", "details": errors}), 400

    # Axis resolution runs once here, before the response commits, so an
    # unknown id or an oversized grid is a real 400; iter_matrix_records()
    # repeats it internally (cheap — two catalog reads) rather than
    # threading resolved objects through a second entry point.
    try:
        resolve_matrix_axes(body, get_loader())
    except MatrixAxisError as e:
        return jsonify({"error": "validation_error", "details": [str(e)]}), 400
    except DataNotLoadedError as e:
        return jsonify({"error": "data_not_loaded", "message": str(e)}), 503

    records = iter_matrix_records(body)
    # Streaming is opt-in by NAMING the mimetype, not by accepting it:
    # `NDJSON_MIMETYPE in request.accept_mimetypes` is a MATCH test, and
    # the wildcard `Accept: */*` that both `requests` and browser `fetch`
    # send by default matches it — so every default client got the stream
    # while asking for the document.
    if NDJSON_MIMETYPE in request.headers.get("Accept", ""):
        return Response(
            stream_with_context(_ndjson_lines(records)),
            mimetype=NDJSON_MIMETYPE,
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return jsonify(fold_matrix_records(records)), 200


def _ndjson_lines(records):
    # Compact separators: a "full" cell carries the views block, and the
    # stream is never gzipped (main.py leaves application/x-ndjson out of
    # Flask-Compress' mimetypes so lines reach the client as they are
    # produced).
    for record in records:
        yield json.dumps(record, separators=(",", ":")) + "\n"
