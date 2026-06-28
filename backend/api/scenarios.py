"""
scenarios.py
============
Scenario CRUD endpoints.

  POST /api/scenario        — save a new scenario
  GET  /api/scenarios       — list current user's scenarios
  POST /api/scenarios       — filtered list with pagination
  GET  /api/scenario/<id>   — load a scenario by ID

⚠️  NOT YET IMPLEMENTED — Phase 4.
All endpoints return 501 Not Implemented.
Auth decorators are in place so the middleware is exercised correctly.
"""

from flask import Blueprint, jsonify

from api.auth_middleware import require_auth

bp = Blueprint("scenarios", __name__)


@bp.post("/scenario")
@require_auth
def save_scenario():
    return jsonify({"error": "not_implemented", "message": "Scenarios not yet implemented."}), 501


@bp.get("/scenarios")
@require_auth
def list_scenarios():
    return jsonify({"error": "not_implemented", "message": "Scenarios not yet implemented."}), 501


@bp.post("/scenarios")
@require_auth
def filter_scenarios():
    return jsonify({"error": "not_implemented", "message": "Scenarios not yet implemented."}), 501


@bp.get("/scenario/<int:scenario_id>")
@require_auth
def get_scenario(scenario_id: int):
    return jsonify({"error": "not_implemented", "message": "Scenarios not yet implemented."}), 501