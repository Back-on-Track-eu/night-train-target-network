"""
main.py
=======
Night Train API — Flask application entry point.

Start with:
    uv run python main.py            (development)
    uv run flask --app main run      (alternative)

Endpoints — see api/README.md for full documentation.

  GET  /api/health
  POST /api/auth/request-code        ⚠️  stub — not yet implemented
  POST /api/auth/verify              ⚠️  stub — not yet implemented
  POST /api/feedback
  GET  /api/feedback/categories
  POST /api/proposal
  GET  /api/proposals
  POST /api/proposals
  GET  /api/proposal/<id>
  GET  /api/params/StopInfrastructures
  GET  /api/params/compositions
  GET  /api/params/TrackInfrastructures
  POST /api/route/plan
  POST /api/evaluation/calc
"""

import logging

from flask import Flask, jsonify
from flask_cors import CORS

from api.helpers.dependencies import DataNotLoadedError, init
from api import health, params, route, evaluation, auth, feedback, proposals

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def create_app() -> Flask:
    init()

    app = Flask(__name__)
    CORS(app)

    # --- blueprints ---
    app.register_blueprint(health.bp, url_prefix="/api")
    app.register_blueprint(params.bp, url_prefix="/api/params")
    app.register_blueprint(route.bp, url_prefix="/api/route")
    app.register_blueprint(evaluation.bp, url_prefix="/api/evaluation")
    app.register_blueprint(auth.bp, url_prefix="/api/auth")
    app.register_blueprint(feedback.bp, url_prefix="/api")
    app.register_blueprint(proposals.bp, url_prefix="/api")

    # --- settings ---
    app.json.sort_keys = False

    # --- global error handlers ---
    @app.errorhandler(DataNotLoadedError)
    def handle_data_not_loaded(e):
        return (
            jsonify(
                {
                    "error": "data_not_loaded",
                    "message": str(e),
                }
            ),
            503,
        )

    @app.errorhandler(404)
    def handle_not_found(e):
        return jsonify({"error": "not_found", "message": str(e)}), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return jsonify({"error": "method_not_allowed", "message": str(e)}), 405

    @app.errorhandler(500)
    def handle_internal_error(e):
        logger.exception("Unhandled error: %s", e)
        return (
            jsonify(
                {"error": "internal_error", "message": "An unexpected error occurred."}
            ),
            500,
        )

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)
