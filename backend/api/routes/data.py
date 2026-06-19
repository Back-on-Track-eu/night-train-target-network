"""
routes/data.py
==============
Data loading endpoints.

  POST /api/data/load    — load from Google Sheets (blocking); 409 if already loaded
  POST /api/data/reload  — force reload regardless of current state (blocking)
  GET  /api/data/status  — returns loaded flag, loaded_at, last error
"""

from flask import Blueprint, jsonify
import logging

from api import dependencies

logger = logging.getLogger(__name__)
bp = Blueprint("data", __name__)


@bp.post("/load")
def load():
    """
    Load all parameter sheets from Google Sheets.
    Blocking — returns when complete.
    Returns 409 if data is already loaded; use /reload to force a refresh.
    """
    if dependencies._loaded:
        return jsonify({
            "message": "Data already loaded. Use POST /api/data/reload to refresh.",
            **dependencies.status(),
        }), 409

    try:
        result = dependencies.load()
        return jsonify({"message": "Data loaded successfully.", **result}), 200
    except Exception as e:
        return jsonify({
            "error": "load_failed",
            "message": str(e),
            **dependencies.status(),
        }), 500


@bp.post("/reload")
def reload():
    """
    Force reload of all parameter sheets from Google Sheets.
    Blocking — replaces the current cached data on success.
    """
    try:
        result = dependencies.load()
        return jsonify({"message": "Data reloaded successfully.", **result}), 200
    except Exception as e:
        return jsonify({
            "error": "reload_failed",
            "message": str(e),
            **dependencies.status(),
        }), 500


@bp.get("/status")
def data_status():
    """Return the current data loading state."""
    return jsonify(dependencies.status()), 200