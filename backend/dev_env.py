"""
dev_env.py
==========
One resolver for every host-run tool in this backend — scripts/, tests/,
and the db/ontd loaders. Reads backend/docker/.env (the single dev-side
configuration file, see AGENTS.md "Parameter placement") and publishes a
consistent view of the stack's wiring, so a manual script, pytest, and an
ontd load all talk to the same database and the same routing engine.

Exists because the previous state was three copies of the same defaults
that had drifted apart: db/ontd/connection.py still carried the retired
production names (night_train_db / nighttrain) while tests/conftest.py
and .env.example said target_network_test_db / bot_admin — so an ontd
script run without a .env connected to a database nothing else in the
repo assumed. This module is now the only place dev-side connection
defaults are written down.

In-container code does NOT use this module: containers get their full
environment from docker-compose (env_file + explicit overrides) and must
fail loudly on missing wiring rather than fall back to dev values.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv

# Anchored to the repo layout, NOT to whichever file happens to call this.
# load_dotenv() with no argument searches upward from the *calling* file,
# so moving a script between directories silently changes which .env it
# finds — that is exactly how the ontd scripts once lost
# POSTGRES_PASSWORD when they moved between directories.
_BACKEND_ROOT = Path(__file__).resolve().parent

# Priority order, first value wins. backend/.env stays as a personal
# escape hatch for overrides that should not live in the shared file.
ENV_FILES = (
    _BACKEND_ROOT / "docker" / ".env",
    _BACKEND_ROOT / ".env",
)

# The dev stack's connection defaults — the ONE place they are defined.
# Matches backend/docker/.env.example; a real environment variable or a
# value from an ENV_FILES entry always beats these.
_DB_DEFAULTS = {
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "target_network_test_db",
    "POSTGRES_USER": "bot_admin",
    "POSTGRES_PASSWORD": "devpassword",
}

_DEFAULT_API_HOST_PORT = "5050"
_DEFAULT_ROUTING_HOST_PORT = "8989"
_DEFAULT_API_CONTAINER_NAME = "night-train-api"


def load_env_files() -> list[Path]:
    """Load every known .env without overriding what's already set, so a
    real environment variable still beats a file. Returns what was found,
    for reporting."""
    found = []
    for path in ENV_FILES:
        if path.is_file():
            load_dotenv(path, override=False)
            found.append(path)
    return found


def in_container() -> bool:
    return Path("/.dockerenv").exists()


def _resolvable(host: str) -> bool:
    try:
        socket.getaddrinfo(host, None)
        return True
    except socket.gaierror:
        return False


def resolve_host(host: str) -> str:
    """Translate a compose service name to localhost when running on the
    host machine.

    backend/docker/.env is written for containers, where POSTGRES_HOST is
    the compose service name ('postgres'). That name has no meaning on the
    developer's machine, where the same database is reached through the
    published port on localhost — so host-run tools, which share the same
    .env, would otherwise need two conflicting values for one variable.

    Only rewritten when BOTH conditions hold: we are not inside a
    container, and the configured name genuinely does not resolve. A real
    remote host that is merely unreachable keeps its name, so a DNS blip
    can never silently redirect a load to a local database.
    """
    if host in ("localhost", "127.0.0.1", "::1"):
        return host
    if in_container() or _resolvable(host):
        return host
    print(
        f"  note: '{host}' does not resolve here and we are not in a "
        f"container — treating it as a compose service name and using "
        f"localhost instead."
    )
    return "localhost"


def resolve_service_url(var: str = "OPENRAILROUTING_URL") -> Optional[str]:
    """Point a compose service URL at localhost when run from the host.

    Same problem as resolve_host, one layer out: containers reach the
    routing engine as http://openrailrouting:<container-port>, which only
    resolves inside the stack. Compose publishes the service on the host
    as OPENRAILROUTING_HOST_PORT, which need not equal the container port
    — so the port is swapped along with the hostname, or the rewritten
    URL would point at a closed port on localhost.

    Rewritten in place on os.environ because RailRouter reads the
    variable itself; returns the effective URL, or None if unset.
    """
    url = os.environ.get(var)
    if not url:
        return None

    parsed = urlsplit(url)
    host = parsed.hostname or ""
    resolved = resolve_host(host)
    if resolved == host:
        return url

    port = os.environ.get("OPENRAILROUTING_HOST_PORT") or (
        str(parsed.port) if parsed.port else None
    )
    netloc = f"{resolved}:{port}" if port else resolved
    rewritten = urlunsplit(parsed._replace(netloc=netloc))
    os.environ[var] = rewritten
    print(f"  note: {var} → {rewritten}")
    return rewritten


def resolve_env() -> dict[str, str]:
    """Fill in dev defaults for anything unset and publish them to
    os.environ, so every consumer in this process sees the same
    connection — DBDataLoader included, which requires all five
    POSTGRES_* variables explicitly."""
    load_env_files()
    for key, default in _DB_DEFAULTS.items():
        os.environ.setdefault(key, default)
    os.environ["POSTGRES_HOST"] = resolve_host(os.environ["POSTGRES_HOST"])
    resolve_service_url()
    return {key: os.environ[key] for key in _DB_DEFAULTS}


def db_config() -> dict:
    """Resolved connection settings in the psycopg2 keyword shape used by
    tests/conftest.py and the manual scripts."""
    settings = resolve_env()
    return {
        "host": settings["POSTGRES_HOST"],
        "port": int(settings["POSTGRES_PORT"]),
        "dbname": settings["POSTGRES_DB"],
        "user": settings["POSTGRES_USER"],
        "password": settings["POSTGRES_PASSWORD"],
    }


def api_base_url() -> str:
    """Where host-run tools reach the API. API_BASE_URL wins outright;
    otherwise built from API_HOST_PORT (the published port of the dev
    stack), falling back to the standard dev port."""
    load_env_files()
    explicit = os.environ.get("API_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    port = os.environ.get("API_HOST_PORT", _DEFAULT_API_HOST_PORT)
    return f"http://localhost:{port}"


def routing_base_url() -> str:
    """Where host-run tools reach the routing engine directly, through its
    published host port."""
    load_env_files()
    port = os.environ.get("OPENRAILROUTING_HOST_PORT", _DEFAULT_ROUTING_HOST_PORT)
    return f"http://localhost:{port}"


def api_container_name() -> str:
    """Container name of the API service — what `docker logs` / `docker
    exec` need. Both dev stacks (backend/docker and the devcontainer
    overlay) run the same compose project, so there is one name."""
    load_env_files()
    return os.environ.get("API_CONTAINER_NAME", _DEFAULT_API_CONTAINER_NAME)
