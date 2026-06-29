"""
scenarios.py
============
Scenario CRUD endpoints.

  POST /api/scenario        — save a new scenario
  GET  /api/scenarios       — list current scenarios
  POST /api/scenarios       — filtered list with pagination
  GET  /api/scenario/<id>   — load a scenario by ID

⚠️  NOT YET IMPLEMENTED — Phase 4.
All endpoints return 501 Not Implemented.
"""

from flask import Blueprint, jsonify

bp = Blueprint("scenarios", __name__)


@bp.post("/scenario")
def save_scenario():
    return (
        jsonify(
            {"error": "not_implemented", "message": "Scenarios not yet implemented."}
        ),
        501,
    )


@bp.get("/scenarios")
def list_scenarios():
    return (
        jsonify(
            {"error": "not_implemented", "message": "Scenarios not yet implemented."}
        ),
        501,
    )


@bp.post("/scenarios")
def filter_scenarios():
    return (
        jsonify(
            {"error": "not_implemented", "message": "Scenarios not yet implemented."}
        ),
        501,
    )


@bp.get("/scenario/<int:scenario_id>")
def get_scenario(scenario_id: int):
    return (
        jsonify(
            {"error": "not_implemented", "message": "Scenarios not yet implemented."}
        ),
        501,
    )
