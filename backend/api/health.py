"""
health.py
=========
Liveness check endpoint.

  GET /api/health
"""

from flask import Blueprint, jsonify

bp = Blueprint("health", __name__)


@bp.get("/health")
def health():
    """Liveness check — returns 200 if the API process is running."""
    return jsonify({"status": "ok"}), 200