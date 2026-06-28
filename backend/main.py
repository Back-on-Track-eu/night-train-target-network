"""
main.py
=======
Night Train API — Flask application entry point.

Start with:
    uv run python main.py            (development, via entrypoint.sh in Docker)
    gunicorn "main:create_app()"     (production, called by entrypoint.sh)

Endpoints — see api/README.md for full documentation.

  GET  /api/health
  POST /api/auth/request-code
  POST /api/auth/verify
  POST /api/auth/guest
  POST /api/feedback                 ⚠️  stub — not yet implemented
  POST /api/scenario                 ⚠️  stub — not yet implemented
  GET  /api/scenarios                ⚠️  stub — not yet implemented
  POST /api/scenarios                ⚠️  stub — not yet implemented
  GET  /api/scenario/<id>            ⚠️  stub — not yet implemented
  GET  /api/params/StopInfrastructures
  GET  /api/params/compositions
  GET  /api/params/TrackInfrastructures
  POST /api/route/planOrUpdate
  POST /api/evaluation/calc
"""

import logging
import time

import psycopg2.extras
from flask import Flask, jsonify, g, request
from flask_cors import CORS

from api.limiter import limiter
from api.auth_utils import check_auth_config
from api.dependencies import DataNotLoadedError, init, get_db
from api import health, params, route, evaluation, auth, feedback, scenarios

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def create_app() -> Flask:
    # --- startup checks & DB init (runs in every worker under Gunicorn) ---
    check_auth_config()
    init()

    app = Flask(__name__)
    CORS(app)

    # --- rate limiter ---
    limiter.init_app(app)

    # --- request logging ---
    @app.before_request
    def _start_timer():
        g.start_time = time.monotonic()

    @app.after_request
    def _log_request(response):
        duration_ms = int((time.monotonic() - g.start_time) * 1000)
        status      = response.status_code
        is_error    = status >= 400

        try:
            with get_db() as cur:
                cur.execute(
                    """
                    INSERT INTO admin.api_request_log
                        (method, endpoint, status_code, duration_ms, request_body, error_log)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        request.method,
                        request.path,
                        status,
                        duration_ms,
                        psycopg2.extras.Json(request.get_json(silent=True)) if is_error else None,
                        None,
                    ),
                )
        except Exception as e:
            logger.warning("Failed to write to api_request_log: %s", e)

        return response

    # --- blueprints ---
    app.register_blueprint(health.bp,      url_prefix="/api")
    app.register_blueprint(params.bp,      url_prefix="/api/params")
    app.register_blueprint(route.bp,       url_prefix="/api/route")
    app.register_blueprint(evaluation.bp,  url_prefix="/api/evaluation")
    app.register_blueprint(auth.bp,        url_prefix="/api/auth")
    app.register_blueprint(feedback.bp,    url_prefix="/api")
    app.register_blueprint(scenarios.bp,   url_prefix="/api")

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

    @app.errorhandler(429)
    def handle_rate_limit(e):
        return jsonify({
            "error":   "rate_limited",
            "message": "Too many requests. Please wait a moment and try again.",
        }), 429

    @app.errorhandler(500)
    def handle_internal_error(e):
        logger.exception("Unhandled error: %s", e)
        return jsonify({"error": "internal_error", "message": "An unexpected error occurred."}), 500

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)