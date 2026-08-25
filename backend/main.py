"""
main.py
=======
Night Train API — Flask application entry point.

Start with:
    uv run python main.py            (development)
    uv run flask --app main run      (alternative)

Endpoints — see api/README.md for full documentation.

  GET  /api/health
  POST /api/auth/request-code
  POST /api/auth/verify
  POST /api/auth/guest
  POST /api/feedback
  GET  /api/feedback/categories
  POST /api/proposal/calc
  POST /api/proposal/publish
  GET  /api/proposals
  POST /api/proposals
  GET  /api/proposals/stats
  POST /api/proposals/compare
  GET  /api/proposal/<id>
  GET  /api/proposal/<id>/share            HTML link-preview stub, not JSON
  GET    /api/proposal/<id>/engagements
  POST   /api/proposal/<id>/like
  DELETE /api/proposal/<id>/like
  POST   /api/proposal/<id>/comment
  PATCH  /api/proposal/<id>/comment/<cid>
  DELETE /api/proposal/<id>/comment/<cid>
  GET  /api/params/StopInfrastructures
  GET  /api/params/compositions
  GET  /api/params/TrackInfrastructures
  GET  /api/scenarios

POST /api/proposal/calc is the merged ephemeral compute endpoint and
POST /api/proposal/publish the only user write path (adapters/proposal/README.md
§2).
"""

import logging

from flask import Flask, jsonify
from flask_compress import Compress
from flask_cors import CORS

from api import config
from api.auth_utils import check_auth_config
from api.helpers.dependencies import DataNotLoadedError, init
from api.limiter import limiter
from api import (
    health,
    params,
    proposal_calc,
    proposal_compare,
    proposal_publish,
    proposal_stats,
    auth,
    feedback,
    gate,
    proposals,
    proposal_engagement,
    proposal_share,
    scenarios,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def create_app() -> Flask:
    # Fails fast on a missing JWT_SECRET; warns when no OTP mail lane is
    # configured; validates the optional Keycloak OIDC config (dormant
    # until KEYCLOAK_ISSUER_URL is set — see api/auth_oidc.py).
    check_auth_config()
    # One INFO line per resolved non-secret setting, so "what is this
    # deployment actually running with" is answered by the boot log.
    config.log_effective_config()
    init()

    app = Flask(__name__)
    CORS(app)

    # --- response compression ---
    # Nothing in front of this app compresses: gunicorn cannot at any worker
    # class, and the Caddy vhost fronting the servers has no `encode` directive
    # (it also lives outside this repo). In the dev stack there is no proxy hop
    # at all. So Flask is the only layer that covers every environment — which
    # matters most for the gallery's map sections, large GeoJSON that gzips by
    # roughly an order of magnitude. Level/threshold: api/config.py.
    app.config["COMPRESS_LEVEL"] = config.COMPRESS_LEVEL
    app.config["COMPRESS_MIN_SIZE"] = config.COMPRESS_MIN_SIZE
    Compress(app)

    # --- rate limiter (per-endpoint limits live in api/auth.py) ---
    limiter.init_app(app)

    # --- blueprints ---
    app.register_blueprint(health.bp, url_prefix="/api")
    app.register_blueprint(params.bp, url_prefix="/api/params")
    # Merged ephemeral compute (calc) + the only user write path
    # (publish) — adapters/proposal/README.md §2.
    app.register_blueprint(proposal_calc.bp, url_prefix="/api/proposal")
    app.register_blueprint(proposal_publish.bp, url_prefix="/api/proposal")
    app.register_blueprint(auth.bp, url_prefix="/api/auth")
    app.register_blueprint(feedback.bp, url_prefix="/api")
    app.register_blueprint(proposals.bp, url_prefix="/api")
    app.register_blueprint(proposal_compare.bp, url_prefix="/api")
    app.register_blueprint(proposal_stats.bp, url_prefix="/api")
    app.register_blueprint(proposal_engagement.bp, url_prefix="/api")
    # Returns HTML, not JSON — a link-preview stub for chat clients, which
    # only reaches Flask under /api because that is the prefix Caddy routes
    # here (api/proposal_share.py).
    app.register_blueprint(proposal_share.bp, url_prefix="/api")
    app.register_blueprint(scenarios.bp, url_prefix="/api")
    # Testing gate (2026-08-13 Decision 2). Registered without a prefix:
    # it owns both /gate (the page) and /api/gate/* (check + redeem), and
    # all three must stay reachable without a gate cookie — everything
    # else on the site sits behind forward_auth -> /api/gate/check.
    app.register_blueprint(gate.bp)

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

    @app.errorhandler(429)
    def handle_rate_limit(e):
        return (
            jsonify(
                {
                    "error": "rate_limited",
                    "message": "Too many requests. Please wait a moment and try again.",
                }
            ),
            429,
        )

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
    import os

    app = create_app()
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("API_CONTAINER_PORT", "5000")),
        debug=True,
    )
