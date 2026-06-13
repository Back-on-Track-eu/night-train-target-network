"""
main.py
=======
Night Train API — Flask application entry point.

Start with:
    uv run python main.py            (development)
    uv run flask --app main run      (alternative)

Endpoints
---------
  GET  /api/health              — liveness check
  GET  /api/data/status         — data loading state
  POST /api/data/load           — load from Google Sheets (blocking)
  POST /api/data/reload         — force reload (blocking)
  GET  /api/compositions        — list available compositions
  GET  /api/stops               — list available stops with coordinates
  POST /api/evaluate            — run full pipeline, return ModelResult
"""

import logging
import os

from flask import Flask, jsonify
from flask_cors import CORS

from api.dependencies import DataNotLoadedError
from api.routes import data, params, evaluate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app)  # allow requests from the frontend (localhost:5173 in dev)

    # --- blueprints ---
    app.register_blueprint(data.bp,     url_prefix="/api/data")
    app.register_blueprint(params.bp,   url_prefix="/api")
    app.register_blueprint(evaluate.bp, url_prefix="/api/evaluate")

    # --- health check ---
    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok"}), 200

    # --- global error handlers ---
    @app.errorhandler(DataNotLoadedError)
    def handle_data_not_loaded(e):
        return jsonify({
            "error":   "data_not_loaded",
            "message": str(e),
        }), 503

    @app.errorhandler(404)
    def handle_not_found(e):
        return jsonify({"error": "not_found", "message": str(e)}), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return jsonify({"error": "method_not_allowed", "message": str(e)}), 405

    @app.errorhandler(500)
    def handle_internal_error(e):
        logger.exception("Unhandled error: %s", e)
        return jsonify({"error": "internal_error", "message": "An unexpected error occurred."}), 500

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)
