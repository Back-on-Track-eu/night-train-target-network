"""Put a built graph cache where the app's routing container will load it.

`backend/docker/docker-compose.yml` mounts a fixed host path into the routing
container, and the container's entrypoint downloads a prebuilt cache from
Google Drive only when `properties.txt` is absent from it. So installing a
target's cache is a matter of making that one path resolve to our directory —
whereupon the entrypoint finds the marker, skips the download, and serves the
network we built.

A symlink rather than a copy, for three reasons: a cache is 5–10 GB, it is
instant either way to swap back, and the `network.json` manifest that says
which network this is comes along for free instead of needing to be kept in
sync.
"""

from __future__ import annotations

import shutil

from . import manifest
from .config import APP_GRAPH_CACHE, CACHE_MARKER, Target

STOCK_DIR = APP_GRAPH_CACHE.parent / "graph-cache.stock"


def _is_our_link() -> bool:
    return APP_GRAPH_CACHE.is_symlink()


def current() -> str:
    """What network the app would serve right now."""
    if not APP_GRAPH_CACHE.exists() and not APP_GRAPH_CACHE.is_symlink():
        return "nothing installed — the container would download the stock cache"
    target = f" -> {APP_GRAPH_CACHE.resolve()}" if APP_GRAPH_CACHE.is_symlink() else ""
    if not (APP_GRAPH_CACHE / CACHE_MARKER).exists():
        return (
            f"a directory with no {CACHE_MARKER}{target} — the container would "
            "download the stock cache over it"
        )
    return manifest.describe(manifest.read(APP_GRAPH_CACHE)) + target


def install(target: Target) -> None:
    """Point the app's mount at this target's cache."""
    cache = target.graph_cache
    if not (cache / CACHE_MARKER).exists():
        raise FileNotFoundError(
            f"no usable graph cache at {cache} — {CACHE_MARKER} is missing.\n"
            f"Run `osm-pipe build {target.command}` first."
        )

    print(f"[install] currently: {current()}")

    if _is_our_link():
        APP_GRAPH_CACHE.unlink()
    elif APP_GRAPH_CACHE.exists():
        if STOCK_DIR.exists():
            # Never overwrite a saved stock cache: it may be the only copy on
            # this machine, and re-fetching it is a 5–10 GB download.
            raise RuntimeError(
                f"{STOCK_DIR} already exists, and {APP_GRAPH_CACHE} is a real "
                "directory rather than one of ours. Refusing to overwrite what "
                "may be the only copy of the stock cache.\n"
                "Sort it out by hand: keep whichever of the two you want at "
                f"{APP_GRAPH_CACHE}, remove the other, then re-run."
            )
        print(f"[install] moving the existing cache aside -> {STOCK_DIR}")
        shutil.move(str(APP_GRAPH_CACHE), str(STOCK_DIR))

    APP_GRAPH_CACHE.parent.mkdir(parents=True, exist_ok=True)
    APP_GRAPH_CACHE.symlink_to(cache.resolve(), target_is_directory=True)

    print(f"[install] {APP_GRAPH_CACHE} -> {cache}")
    print(f"[install] now serving: {manifest.describe(manifest.read(cache))}")
    print()
    print("[install] Restart the routing container for this to take effect:")
    print(
        "[install]   docker compose -f backend/docker/docker-compose.yml "
        "up -d --force-recreate openrailrouting"
    )
    print()
    print(
        "[install] NOTE: a route computed on this graph is not reproducible "
        "from a stored request — the network is now an input and"
    )
    print(
        "[install]       ROUTE_BUILDER_VERSION does not know it changed. "
        "Do not publish a proposal from it."
    )


def restore() -> None:
    """Put the stock cache back."""
    if not _is_our_link():
        if APP_GRAPH_CACHE.exists():
            print(f"[install] {APP_GRAPH_CACHE} is not one of ours — nothing to undo")
            return
        print("[install] nothing installed")
        return

    APP_GRAPH_CACHE.unlink()
    if STOCK_DIR.exists():
        shutil.move(str(STOCK_DIR), str(APP_GRAPH_CACHE))
        print(f"[install] restored {STOCK_DIR} -> {APP_GRAPH_CACHE}")
    else:
        print(
            f"[install] link removed. No stock cache was saved, so the "
            f"container will download one into {APP_GRAPH_CACHE} on next start."
        )
    print("[install] Restart the routing container:")
    print(
        "[install]   docker compose -f backend/docker/docker-compose.yml "
        "up -d --force-recreate openrailrouting"
    )
