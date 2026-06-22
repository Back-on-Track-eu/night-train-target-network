"""
routes/data.py
==============
Data status endpoint.

  GET  /api/data/status  — returns loaded flag, loaded_at, last error
"""

from flask import Blueprint, jsonify

from api import dependencies

bp = Blueprint("data", __name__)


@bp.get("/status")
def data_status():
    """Return the current database connection state."""
    return jsonify(dependencies.status()), 200