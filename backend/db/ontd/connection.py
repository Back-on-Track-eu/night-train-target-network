"""
Database connection for the ontd scripts.

Named connection.py, not db.py: backend/db/ is a namespace package, and
while a regular module still wins the import, the two would be one
__init__.py away from colliding.

Exists to keep one connection definition rather than three. It also
resolves a real trap: these scripts fall back to localhost/5432 when a
POSTGRES_* variable is unset, but DBDataLoader (which projection.py needs
for tracks, compositions and country geometries) requires all five
explicitly and raises otherwise. A .env without POSTGRES_HOST therefore
let the loaders connect happily while routing failed with "Missing
required environment variable(s)" — and, because routing degrades rather
than aborts, that surfaced only as every route silently falling back to
straight-line geometry.

Resolving once and writing the values back into os.environ means
DBDataLoader connects to exactly the database the script is already
talking to, instead of the two disagreeing about defaults.
"""

import os
import socket
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

import psycopg2
from dotenv import load_dotenv

# Anchored to the repo layout, NOT to whichever file happens to call this.
# load_dotenv() with no argument searches upward from the *calling* file,
# so moving a script between directories silently changes which .env it
# finds — that is exactly how these scripts lost POSTGRES_PASSWORD when
# they moved out of db/dev/ (which has its own .env) into db/ontd/.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Priority order, first value wins: the main compose stack's env is the
# one whose database these scripts actually talk to; db/dev's belongs to
# the standalone schema-inspection stack.
ENV_FILES = (
    _BACKEND_ROOT / "docker" / ".env",
    _BACKEND_ROOT / "db" / "dev" / ".env",
    _BACKEND_ROOT / ".env",
)

DEFAULTS = {
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "night_train_db",
    "POSTGRES_USER": "nighttrain",
}


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


def _in_container() -> bool:
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
    published port on localhost — so these scripts, which are run both
    ways (`uv run ...` and `docker exec ...`), would otherwise need two
    conflicting values for one variable.

    Only rewritten when BOTH conditions hold: we are not inside a
    container, and the configured name genuinely does not resolve. A real
    remote host that is merely unreachable keeps its name, so a DNS blip
    can never silently redirect a load to a local database.
    """
    if host in ("localhost", "127.0.0.1", "::1"):
        return host
    if _in_container() or _resolvable(host):
        return host
    print(
        f"  note: '{host}' does not resolve here and we are not in a "
        f"container — treating it as a compose service name and using "
        f"localhost instead."
    )
    return "localhost"


def resolve_service_url(var: str = "OPENRAILROUTING_URL") -> Optional[str]:
    """Point a compose service URL at localhost when run from the host.

    Same problem as resolve_host, one layer out: docker/.env carries
    http://openrailrouting:<container-port>, which only resolves inside
    the stack. Compose publishes the service on the host as
    OPENRAILROUTING_HOST_PORT, which need not equal the container port —
    so the port is swapped along with the hostname, or the rewritten URL
    would point at a closed port on localhost.

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
    """Fill in defaults for anything unset and publish them to os.environ,
    so every consumer in this process sees the same connection —
    DBDataLoader included, which requires all five explicitly."""
    load_env_files()
    for key, default in DEFAULTS.items():
        os.environ.setdefault(key, default)
    os.environ["POSTGRES_HOST"] = resolve_host(os.environ["POSTGRES_HOST"])
    return {key: os.environ[key] for key in DEFAULTS}


def connect(autocommit: bool = False):
    """Open a connection to the configured database."""
    settings = resolve_env()
    if not os.environ.get("POSTGRES_PASSWORD"):
        checked = "\n  ".join(str(p) for p in ENV_FILES)
        raise SystemExit(
            "POSTGRES_PASSWORD is not set. Checked these files:\n  "
            + checked
            + "\nSet it in one of them, or export it in the shell."
        )
    try:
        conn = psycopg2.connect(
            host=settings["POSTGRES_HOST"],
            port=int(settings["POSTGRES_PORT"]),
            dbname=settings["POSTGRES_DB"],
            user=settings["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
        )
    except psycopg2.OperationalError as e:
        raise SystemExit(
            f"Could not connect to {settings['POSTGRES_USER']}@"
            f"{settings['POSTGRES_HOST']}:{settings['POSTGRES_PORT']}/"
            f"{settings['POSTGRES_DB']}.\n{e}"
            "Is the postgres container up, and is its port published?"
        ) from e
    conn.autocommit = autocommit
    return conn
