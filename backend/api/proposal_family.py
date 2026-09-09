"""
proposal_family.py
==================
The proposal family (adapters/family/README.md): one compute for every
scenario variant × composition of a stop list + HOW.

  POST /api/proposal/family
      stops + HOW (+ optional scenario_variant_ids, composition_ids,
      presented) → the §2.5 document. Synchronous; built once per family
      key and served from family.documents afterwards.
  GET  /api/proposal/family/<key>
      the document again, or 404 once its TTL has passed (the client
      POSTs again — the key is the same).
  GET  /api/proposal/family/<key>/members/<scenario_variant_id>/<composition_id>/views
      {views} for one member, computed on demand and member-cached (D9).

Thin delegation: every decision is in api/helpers/family_compute.py, every
dict in api/helpers/family_serialize.py. This view only maps the helper
layer's exceptions to status codes (classify_compute_error — the one
mapping from pipeline exceptions to wire codes).
"""

import logging

from flask import Blueprint, jsonify, request

from api.helpers.dependencies import DataNotLoadedError, get_family_document_cache
from api.helpers.family_compute import (
    FamilyBodyError,
    FamilyTooLargeError,
    UnknownMemberError,
    build_or_load_family,
    member_views,
    validate_family_body,
)
from api.helpers.member_compute import classify_compute_error

logger = logging.getLogger(__name__)
bp = Blueprint("proposal_family", __name__)


def _not_found(message: str):
    return jsonify({"error": "not_found", "message": message}), 404


@bp.post("/family")
def post_family():
    body = request.get_json(silent=True)
    if not body:
        return (
            jsonify({"error": "bad_request", "message": "Request body must be JSON."}),
            400,
        )
    errors = validate_family_body(body)
    if errors:
        logger.warning("proposal/family validation failed — %s", errors)
        return jsonify({"error": "validation_error", "details": errors}), 400

    try:
        document = build_or_load_family(body)
    except FamilyTooLargeError as e:
        return jsonify({"error": "family_too_large", "message": str(e)}), 400
    except FamilyBodyError as e:
        return jsonify({"error": "validation_error", "details": e.errors}), 400
    except DataNotLoadedError as e:
        return jsonify({"error": "data_not_loaded", "message": str(e)}), 503
    return jsonify(document), 200


@bp.get("/family/<key>")
def get_family(key: str):
    document = get_family_document_cache().get(key)
    if document is None:
        return _not_found(f"No family document for key {key} — post the family again.")
    return jsonify(document), 200


@bp.get("/family/<key>/members/<int:scenario_variant_id>/<composition_id>/views")
def get_member_views(key: str, scenario_variant_id: int, composition_id: str):
    document = get_family_document_cache().get(key)
    if document is None:
        return _not_found(f"No family document for key {key} — post the family again.")
    try:
        views = member_views(document["request"], scenario_variant_id, composition_id)
    except UnknownMemberError as e:
        return _not_found(str(e))
    except DataNotLoadedError as e:
        return jsonify({"error": "data_not_loaded", "message": str(e)}), 503
    except Exception as e:  # noqa: BLE001 — classified below, re-raised if ours
        classified = classify_compute_error(e)
        if classified is None:
            raise
        code, status, extra = classified
        return jsonify({"error": code, "message": str(e), **extra}), status
    return jsonify(views), 200
