#!/bin/bash
# =============================================================================
# entrypoint.sh
# =============================================================================
# OpenRailRouting container startup script.
# Checks if the graph cache exists — downloads and extracts it from
# Google Drive if not. Then starts the routing server.

set -e

GRAPH_CACHE_DIR="/app/graph-cache"
GRAPH_CACHE_MARKER="${GRAPH_CACHE_DIR}/properties.txt"

# config.yml's datareader.file, baked into the image and shared by every
# instance — so each graph's host-side data-<key>/ directory must present
# its OSM extract under this one name. A file named anything else is not
# read at all.
OSM_FILE="/app/data/europe-latest.osm.pbf"

# Pre-flight for graph imports. Both conditions below fail quietly enough to
# cost hours if unchecked: a missing OSM file surfaces as a GraphHopper stack
# trace some way into the run, and a populated cache directory makes the
# import LOAD the existing graph and report success without ever reading the
# new extract.
preflight_import() {
    local failed=0

    if [ ! -f "$OSM_FILE" ]; then
        echo "[entrypoint] ERROR: ${OSM_FILE} not found."
        echo "[entrypoint]   config.yml reads exactly this path. Rename the"
        echo "[entrypoint]   extract in this graph's data-<key>/ directory."
        echo "[entrypoint]   Contents of /app/data:"
        ls -la /app/data 2>/dev/null | sed 's/^/[entrypoint]     /'
        failed=1
    fi

    if [ -f "$GRAPH_CACHE_MARKER" ]; then
        echo "[entrypoint] ERROR: ${GRAPH_CACHE_DIR} already holds a graph."
        echo "[entrypoint]   An import over a populated cache loads that graph"
        echo "[entrypoint]   instead of rebuilding it, and succeeds without"
        echo "[entrypoint]   reading ${OSM_FILE}. Delete this graph's"
        echo "[entrypoint]   graph-cache-<key>/ directory and re-run."
        failed=1
    fi

    [ "$failed" -eq 0 ] || exit 1
    echo "[entrypoint] Import pre-flight passed — OSM file present, cache empty."
}

# Any arguments override the server start. `docker compose run` passes the
# command through as "$@", but ENTRYPOINT means it never replaces this
# script — so without this branch a documented one-off like
#
#   docker compose run --rm openrailrouting-infra-2026 \
#     java -Xmx24g -Xms1g -jar railway_routing.jar import config.yml
#
# was silently ignored and the SERVER started instead, after downloading a
# prebuilt cache over the very graph-cache/ the import was meant to rebuild.
# Handled before the download for the same reason: an import must start from
# an empty cache, never from the Drive artifact.
if [ "$#" -gt 0 ]; then
    echo "[entrypoint] command override — running: $*"
    # Padded on both sides so "import" matches as an argument, never as a
    # substring of a path. Other overrides (a shell, a version probe) skip
    # the pre-flight, which asserts import preconditions only.
    case " $* " in
        *" import "*) preflight_import ;;
    esac
    exec "$@"
fi

# Passed in by compose as GRAPH_CACHE_FILE_ID — unsuffixed, because a
# container serves exactly one graph and does not know its key. The
# host-side variable IS suffixed (GRAPH_CACHE_FILE_ID_<KEY>); see
# .env.example), alongside the ONTD workbook ids — same class of value,
# same place. The literal below is only a fallback for compose stacks
# that do not inject it yet; there is no reason for this id to live in
# two places once they all do.
GDRIVE_FILE_ID="${GRAPH_CACHE_FILE_ID:-1tWt1OX7mzPA7Ylo9KqmTK6YluRXEtt8z}"
# Use the newer usercontent endpoint with confirm=t to bypass the virus-scan warning page
DOWNLOAD_URL="https://drive.usercontent.google.com/download?id=${GDRIVE_FILE_ID}&export=download&confirm=t"
ZIP_PATH="/tmp/graph-cache.zip"

if [ -f "$GRAPH_CACHE_MARKER" ]; then
    echo "[entrypoint] Graph cache found — skipping download."
else
    echo "[entrypoint] Graph cache not found — downloading from Google Drive (id ${GDRIVE_FILE_ID})..."
    curl -L "$DOWNLOAD_URL" -o "$ZIP_PATH"

    # Sanity-check: unzip rejects HTML pages immediately, so this also catches auth failures
    echo "[entrypoint] Download complete. Extracting..."
    mkdir -p "$GRAPH_CACHE_DIR"
    unzip -o "$ZIP_PATH" -d "$GRAPH_CACHE_DIR"
    rm "$ZIP_PATH"
    echo "[entrypoint] Graph cache ready."
fi

# Start OpenRailRouting
exec java -jar /app/railway_routing.jar server /app/config.yml
