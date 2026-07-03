"""
health.py
=========
Liveness check endpoint.

  GET /api/health
  GET /api/data/status
"""

from flask import Blueprint, jsonify

bp = Blueprint("health", __name__)


@bp.get("/health")
def health():
    """Liveness check — returns 200 if the API process is running."""
    return jsonify({"status": "ok"}), 200


@bp.get("/data/status")
def data_status():
    """Returns whether the DB data loader has successfully initialised."""
    from api.helpers.dependencies import _loaded, _loaded_at, _load_error

    body = {"loaded": _loaded}
    if _loaded_at is not None:
        body["loaded_at"] = _loaded_at.isoformat()
    if _load_error is not None:
        body["error"] = _load_error
    return jsonify(body), 200
