"""Stages 5 and 6 — build a graph cache for a target, and serve it.

Reuses the `docker-openrailrouting` image the backend already builds, so the
profiles, custom models and encoded values stay defined in exactly one place
(`backend/models/route/routing/docker/`). Only `datareader.file` and
`graph.location` are rewritten per target, plus whatever the target's
`graphhopper.config` block overrides.

Deriving the config from the container's own `config.yml` is what makes these
caches interchangeable with the app's: same profile hash, same encoded values,
so GraphHopper loads the directory without complaint. The image's entrypoint
(which downloads a prebuilt cache from Google Drive) is bypassed with
`--entrypoint java`, since the whole point here is to build our own.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

from .config import (
    CACHE_MARKER,
    GRAPH_CACHES,
    INTERIM,
    ORR_BASE_CONFIG,
    ORR_IMAGE,
    Target,
)

CONTAINER_PORT = 8989
# Which targets currently have a routing server up, and on what port.
REGISTRY = GRAPH_CACHES / "servers.json"

_RUNNING_TTL_S = 5.0
_running_cache: tuple[float, set[str] | None] | None = None


def _running_containers() -> set[str] | None:
    """Names of our containers docker says are up, or None if docker cannot
    be asked (not installed, not running, too slow)."""
    global _running_cache
    now = time.monotonic()
    if _running_cache is not None and now - _running_cache[0] < _RUNNING_TTL_S:
        return _running_cache[1]

    names: set[str] | None = None
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=osmpipe-", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        pass
    else:
        if result.returncode == 0:
            names = {ln.strip() for ln in result.stdout.splitlines() if ln.strip()}

    _running_cache = (now, names)
    return names


def load_registry() -> dict[str, dict]:
    """Targets with a live routing server, reconciled against docker.

    The file records what we started. Containers die with a reboot or a
    `docker stop`, and a stale entry is worse than a missing one: it points
    `verify` at a port that answers /health from a completely different
    dataset's graph, so the next command looks fine and routes over the wrong
    network. Plausible wrong answers beat errors every time, so ask docker.
    """
    if not REGISTRY.exists():
        return {}
    try:
        entries = json.loads(REGISTRY.read_text())
    except json.JSONDecodeError:
        return {}
    live = _running_containers()
    if live is None:
        return entries
    return {slug: e for slug, e in entries.items() if e.get("container") in live}


def _save_registry(reg: dict[str, dict]) -> None:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(reg, indent=2))


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def render_config(target: Target, extra: dict[str, Any] | None = None) -> Path:
    """Write the target's GraphHopper config next to its graph cache.

    `extra` overrides the target's own `graphhopper.config` block, for settings
    that belong to one machine rather than to the model — heap-sized knobs like
    `graph.dataaccess.default_type` have no business in a checked-in file other
    people import on different hardware.
    """
    if not ORR_BASE_CONFIG.exists():
        raise FileNotFoundError(
            f"base OpenRailRouting config not found: {ORR_BASE_CONFIG}\n"
            "osm_pipe derives every import config from the backend's own, so "
            "the caches it builds match the profile the app serves."
        )
    config = yaml.safe_load(ORR_BASE_CONFIG.read_text())
    gh = config.setdefault("graphhopper", {})
    gh["datareader.file"] = f"/app/data/{target.pbf.name}"
    gh["graph.location"] = "/app/graph-cache"
    merged = _deep_merge(gh, target.gh_config_overrides)
    config["graphhopper"] = _deep_merge(merged, extra or {})

    target.graph_cache.mkdir(parents=True, exist_ok=True)
    # Keyed by slug, not name — the same target on two datasets needs two
    # configs, since datareader.file differs.
    path = GRAPH_CACHES / f"{target.slug}.config.yml"
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    return path


def _mounts(target: Target, config: Path) -> list[str]:
    return [
        "-v",
        f"{INTERIM.resolve()}:/app/data:ro",
        "-v",
        f"{target.graph_cache.resolve()}:/app/graph-cache",
        "-v",
        f"{config.resolve()}:/app/config.yml:ro",
    ]


def _check_image() -> None:
    result = subprocess.run(
        ["docker", "image", "inspect", ORR_IMAGE],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"docker image {ORR_IMAGE!r} not found. Build it once:\n"
            "  cd backend/models/route/routing/docker && docker compose build"
        )


_XMX_UNITS = {"k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}


def _heap_bytes(xmx: str) -> int:
    """Parse a JVM heap string like `24g`. 0 if it cannot be read."""
    text = xmx.strip().lower().removeprefix("-xmx")
    if not text:
        return 0
    unit = _XMX_UNITS.get(text[-1])
    digits = text[:-1] if unit else text
    if not digits.isdigit():
        return 0
    return int(digits) * (unit or 1)


def _docker_memory_bytes() -> int:
    """What the docker daemon says it has. 0 if it cannot be asked."""
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.MemTotal}}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return 0
    if result.returncode != 0:
        return 0
    value = result.stdout.strip()
    return int(value) if value.isdigit() else 0


def _check_heap_fits(xmx: str, hint: str) -> None:
    """Refuse a heap the container cannot have.

    On Docker Desktop the daemon runs in a VM with its own memory limit, and
    `-Xmx` is only a promise the JVM makes to itself. Ask for more than the
    limit and the heap grows past the cgroup before the collector sees any
    pressure, so the kernel kills the container rather than the JVM running a
    GC. It surfaces as exit 137 half an hour into a Europe import with nothing
    in the log naming the cause — worth one check here.
    """
    heap = _heap_bytes(xmx)
    limit = _docker_memory_bytes()
    if not heap or not limit or heap < limit:
        return
    gib = 1024**3
    raise RuntimeError(
        f"-Xmx{xmx} ({heap / gib:.1f} GiB) does not fit docker's "
        f"{limit / gib:.1f} GiB. The JVM would be OOM-killed mid-import "
        f"(exit 137), typically after half an hour.\n"
        f"Either give docker more memory (Docker Desktop -> Settings -> "
        f"Resources -> Memory), or fit the heap to what it has:\n"
        f"  osm-pipe build {hint} --xmx {max(1, int(limit / gib) - 2)}g\n"
        f"If that is too small, trade speed for heap by memory-mapping the "
        f"graph instead of holding it:\n"
        f"  --gh-set graph.dataaccess.default_type=MMAP"
    )


def gh_import(
    target: Target,
    *,
    overwrite: bool = False,
    xmx: str = "",
    config_overrides: dict[str, Any] | None = None,
) -> Path:
    """Run the OpenRailRouting import for this target."""
    _check_image()
    if not target.pbf.exists():
        raise FileNotFoundError(
            f"target extract missing: {target.pbf}\n"
            f"Run `osm-pipe build {target.command}` first."
        )

    cache = target.graph_cache
    # The same marker the routing container's entrypoint checks, so "built"
    # means the same thing here as it does there.
    marker = cache / CACHE_MARKER
    if marker.exists() and not overwrite:
        print(f"[import] graph cache exists at {cache} — skipping (use --overwrite)")
        return cache
    if cache.exists() and overwrite:
        shutil.rmtree(cache)
    cache.mkdir(parents=True, exist_ok=True)

    heap = xmx or target.gh_xmx
    _check_heap_fits(heap, target.command)
    config = render_config(target, config_overrides)
    cmd = [
        "docker",
        "run",
        "--rm",
        *_mounts(target, config),
        "--entrypoint",
        "java",
        ORR_IMAGE,
        f"-Xmx{heap}",
        "-Xms1g",
        "-jar",
        "/app/railway_routing.jar",
        "import",
        "/app/config.yml",
    ]
    print("[import]", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"[import] graph cache ready: {cache}")
    return cache


# Docker allows only [a-zA-Z0-9][a-zA-Z0-9_.-] in a container name. A slug
# carries an `@<date>` under --as-of, which is legal in a path and in our own
# output but not here, so it has to be substituted rather than passed through.
_UNSAFE_IN_CONTAINER_NAME = re.compile(r"[^A-Za-z0-9_.-]")


def container_name(target: Target) -> str:
    return "osmpipe-" + _UNSAFE_IN_CONTAINER_NAME.sub("-", target.slug)


def gh_serve(
    target: Target,
    *,
    port: int,
    xmx: str = "",
    config_overrides: dict[str, Any] | None = None,
) -> str:
    """Start a routing server on this target's cache."""
    _check_image()
    if not target.graph_cache.joinpath(CACHE_MARKER).exists():
        raise FileNotFoundError(
            f"no graph cache at {target.graph_cache}\n"
            f"Run `osm-pipe build {target.command}` first."
        )
    name = container_name(target)
    # Docker would refuse the bound port anyway, but its error does not say
    # *which* target is squatting, and the leftover server keeps answering
    # /health from another dataset's graph — so the next command looks fine and
    # routes over the wrong network.
    for slug, entry in load_registry().items():
        if entry.get("container") != name and int(entry.get("port", 0)) == port:
            raise RuntimeError(
                f"port {port} is already serving {slug!r}. Pick another port, "
                f"or stop it first:\n"
                f"  osm-pipe stop {entry.get('target', '<target>')} "
                f"-d {entry.get('dataset', '<dataset>')}"
            )
    heap = xmx or target.gh_xmx
    _check_heap_fits(heap, target.command)
    config = render_config(target, config_overrides)
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    cmd = [
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "-p",
        f"{port}:{CONTAINER_PORT}",
        *_mounts(target, config),
        "--entrypoint",
        "java",
        ORR_IMAGE,
        f"-Xmx{heap}",
        "-jar",
        "/app/railway_routing.jar",
        "server",
        "/app/config.yml",
    ]
    print("[serve]", " ".join(cmd))
    subprocess.run(cmd, check=True)

    reg = load_registry()
    reg[target.slug] = {
        "target": target.name,
        "dataset": target.dataset.name,
        "as_of": target.as_of.isoformat(),
        "description": target.description,
        "port": port,
        "container": name,
    }
    _save_registry(reg)

    url = f"http://localhost:{port}"
    print(f"[serve] {target.slug} serving on {url} (container {name})")
    print("[serve] the graph takes ~30 s to load before /route answers")
    return url


def gh_stop(target: Target) -> None:
    """Stop this target's routing server and drop it from the registry."""
    name = container_name(target)
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    reg = load_registry()
    if reg.pop(target.slug, None) is not None:
        _save_registry(reg)
    print(f"[serve] stopped {name}")
