#!/bin/bash
# =============================================================================
# entrypoint.sh
# =============================================================================
# OpenRailRouting container startup script.
# Checks if the graph cache exists — downloads and extracts it from
# Google Drive if not. Then starts the routing server.

set -e

# Any arguments override the server start. `docker compose run` passes the
# command through as "$@", but ENTRYPOINT means it never replaces this
# script — so without this branch a documented one-off like
#
#   docker compose run --rm openrailrouting \
#     java -Xmx24g -Xms1g -jar railway_routing.jar import config.yml
#
# was silently ignored and the SERVER started instead, after downloading a
# prebuilt cache over the very graph-cache/ the import was meant to rebuild.
# Handled before the download for the same reason: an import must start from
# an empty cache, never from the Drive artifact.
if [ "$#" -gt 0 ]; then
    echo "[entrypoint] command override — running: $*"
    exec "$@"
fi

GRAPH_CACHE_DIR="/app/graph-cache"
GRAPH_CACHE_MARKER="${GRAPH_CACHE_DIR}/properties.txt"
# Configured via GRAPH_CACHE_FILE_ID in backend/docker/.env (see
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