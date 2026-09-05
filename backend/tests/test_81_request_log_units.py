"""
Unit tests for api/request_log.py — the exclusion rule, the client
pseudonym, identity resolution and failure isolation. No DB and no live
stack: a bare Flask app plus a stub repository is enough, and the point of
most of these is that the hook cannot affect the response.

The persisted end (a row actually landing in admin.request_log with the
right endpoint and user) belongs to the integration suite against a
seeded database.
"""

import os
from datetime import datetime, timezone

import pytest
from flask import Flask, g, jsonify

from api import config, request_log


class StubRepo:
    """Records what would have been written; optionally explodes."""

    def __init__(self, fail: bool = False) -> None:
        self.rows: list[dict] = []
        self.fail = fail

    def insert(self, **kwargs) -> None:
        if self.fail:
            raise RuntimeError("database is on fire")
        self.rows.append(kwargs)


@pytest.fixture
def app(monkeypatch) -> Flask:
    """A minimal app with the hooks attached and the repository stubbed.
    Blueprint names match the real ones so the exclusion prefixes bite."""
    app = Flask(__name__)
    repo = StubRepo()
    monkeypatch.setattr(
        "api.helpers.dependencies.get_request_log_repository", lambda: repo
    )

    @app.get("/api/params/compositions")
    def params_compositions():
        return jsonify(ok=True)

    @app.get("/api/health", endpoint="health.health")
    def health():
        return jsonify(ok=True)

    @app.get("/api/gate/check", endpoint="gate.check")
    def gate_check():
        return jsonify(ok=True)

    @app.get("/api/boom")
    def boom():
        raise RuntimeError("handler failed")

    # main.py registers the same handler. It matters here: without it a
    # raising view never produces a response and after_request never runs,
    # so the 500 would go unlogged.
    @app.errorhandler(500)
    def internal(e):
        return jsonify(error="internal_error"), 500

    request_log.register(app)
    app.repo = repo
    return app


class TestExclusion:
    def test_options_is_never_logged(self):
        # CORS preflight doubles every cross-origin call and says nothing
        # about usage.
        assert request_log.is_excluded("params.compositions", "OPTIONS")

    @pytest.mark.parametrize(
        "endpoint", ["health.health", "health.data_status", "gate.check", "gate.page"]
    )
    def test_configured_prefixes_are_excluded(self, endpoint):
        assert request_log.is_excluded(endpoint, "GET")

    @pytest.mark.parametrize(
        "endpoint",
        ["params.compositions", "proposals.list_proposals", "proposal_calc.calc"],
    )
    def test_real_traffic_is_logged(self, endpoint):
        assert not request_log.is_excluded(endpoint, "GET")

    def test_unmatched_path_is_logged(self):
        # endpoint is None on a 404. A client calling something that does
        # not exist is worth seeing, so this is deliberately NOT excluded.
        assert not request_log.is_excluded(None, "GET")

    def test_prefix_covers_future_views(self):
        # Prefix rather than exact match, so a new view on an excluded
        # blueprint is excluded by default — the safe direction for a
        # table that grows once per request.
        assert request_log.is_excluded("health.something_new", "GET")


class TestClientHash:
    def _hash(self, app, address, secret="s3cret", headers=None):
        with app.test_request_context(
            "/api/params/compositions",
            environ_base={"REMOTE_ADDR": address},
            headers=headers or {},
        ):
            os.environ["REQUEST_LOG_HASH_SECRET"] = secret
            try:
                return request_log._client_hash()
            finally:
                os.environ.pop("REQUEST_LOG_HASH_SECRET", None)

    def test_is_a_hex_digest_not_an_address(self, app):
        digest = self._hash(app, "203.0.113.7")
        assert len(digest) == 64
        assert "203.0.113" not in digest

    def test_stable_for_one_client_within_a_day(self, app):
        assert self._hash(app, "203.0.113.7") == self._hash(app, "203.0.113.7")

    def test_differs_between_clients(self, app):
        assert self._hash(app, "203.0.113.7") != self._hash(app, "203.0.113.8")

    def test_differs_between_secrets(self, app):
        assert self._hash(app, "203.0.113.7", secret="a") != self._hash(
            app, "203.0.113.7", secret="b"
        )

    def test_rotates_daily(self, app):
        # The date is part of the HMAC MESSAGE, so yesterday's clients
        # cannot be recovered even by someone holding the secret.
        today = self._hash(app, "203.0.113.7")
        message = f"{datetime.now(timezone.utc).date().isoformat()}|203.0.113.7"
        assert message not in today

    def test_forwarded_for_wins_over_the_socket(self, app):
        # Behind Caddy every socket address is the proxy's; without the
        # header this column would hash one value for the whole internet.
        proxied = self._hash(
            app, "10.0.0.1", headers={"X-Forwarded-For": "203.0.113.7, 10.0.0.1"}
        )
        assert proxied == self._hash(app, "203.0.113.7")

    def test_none_without_a_secret(self, app):
        with app.test_request_context(
            "/api/params/compositions", environ_base={"REMOTE_ADDR": "203.0.113.7"}
        ):
            for key in ("REQUEST_LOG_HASH_SECRET", "JWT_SECRET"):
                os.environ.pop(key, None)
            # An unsalted hash of an IPv4 address is a lookup table, so no
            # secret means no column rather than a weak one.
            assert request_log._client_hash() is None


class TestIdentity:
    def test_reused_from_g_when_a_decorator_already_resolved_it(self, app):
        with app.test_request_context("/api/params/compositions"):
            g.user_id = 42
            g.is_guest = True
            g.trust_level = 0
            assert request_log._identity() == (42, True, 0)

    def test_falls_back_to_quiet_resolution(self, app, monkeypatch):
        monkeypatch.setattr(
            "api.auth_middleware.resolve_identity_quietly",
            lambda: {"user_id": 7, "is_guest": False, "trust_level": 1},
        )
        with app.test_request_context("/api/params/compositions"):
            assert request_log._identity() == (7, False, 1)

    def test_anonymous_when_nothing_resolves(self, app, monkeypatch):
        monkeypatch.setattr(
            "api.auth_middleware.resolve_identity_quietly", lambda: None
        )
        with app.test_request_context("/api/params/compositions"):
            assert request_log._identity() == (None, False, None)


class TestHooks:
    def test_a_served_request_is_recorded(self, app):
        client = app.test_client()
        assert client.get("/api/params/compositions").status_code == 200
        (row,) = app.repo.rows
        assert row["endpoint"] == "params_compositions"
        assert row["method"] == "GET"
        assert row["status_code"] == 200
        assert row["route_rule"] == "/api/params/compositions"
        assert row["duration_ms"] >= 0

    def test_excluded_endpoints_write_nothing(self, app):
        client = app.test_client()
        client.get("/api/health")
        client.get("/api/gate/check")
        assert app.repo.rows == []

    def test_a_write_failure_cannot_fail_the_request(self, app):
        app.repo.fail = True
        response = app.test_client().get("/api/params/compositions")
        assert response.status_code == 200
        assert response.get_json() == {"ok": True}

    def test_a_failed_request_is_recorded_too(self, app):
        # The operations half of this table is worthless if only the
        # successes land. Flask runs after_request for a HANDLED error, so
        # this depends on the errorhandler main.py registers.
        assert app.test_client().get("/api/boom").status_code == 500
        (row,) = app.repo.rows
        assert row["endpoint"] == "boom"
        assert row["status_code"] == 500

    def test_missing_repository_is_a_skip_not_an_error(self, app, monkeypatch):
        monkeypatch.setattr(
            "api.helpers.dependencies.get_request_log_repository", lambda: None
        )
        assert app.test_client().get("/api/params/compositions").status_code == 200

    def test_no_hooks_at_all_when_disabled(self, monkeypatch):
        monkeypatch.setattr(config, "REQUEST_LOG_ENABLED", False)
        app = Flask(__name__)

        @app.get("/api/params/compositions")
        def view():
            return jsonify(ok=True)

        request_log.register(app)
        assert app.before_request_funcs == {}
        assert app.after_request_funcs == {}


class TestTruncation:
    def test_long_user_agents_are_cut_to_the_column_width(self):
        assert (
            len(request_log._truncate("x" * 5000))
            == config.REQUEST_LOG_USER_AGENT_MAX_LEN
        )

    def test_absent_user_agent_is_null(self):
        assert request_log._truncate(None) is None
        assert request_log._truncate("") is None
