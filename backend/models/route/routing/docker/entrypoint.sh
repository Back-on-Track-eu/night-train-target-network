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
GDRIVE_FILE_ID="1tWt1OX7mzPA7Ylo9KqmTK6YluRXEtt8z"
# Use the newer usercontent endpoint with confirm=t to bypass the virus-scan warning page
DOWNLOAD_URL="https://drive.usercontent.google.com/download?id=${GDRIVE_FILE_ID}&export=download&confirm=t"
ZIP_PATH="/tmp/graph-cache.zip"

if [ -f "$GRAPH_CACHE_MARKER" ]; then
    echo "[entrypoint] Graph cache found — skipping download."
else
    echo "[entrypoint] Graph cache not found — downloading from Google Drive..."
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