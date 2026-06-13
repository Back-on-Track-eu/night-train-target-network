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
DOWNLOAD_URL="https://drive.google.com/uc?export=download&id=${GDRIVE_FILE_ID}"
ZIP_PATH="/tmp/graph-cache.zip"

if [ -f "$GRAPH_CACHE_MARKER" ]; then
    echo "[entrypoint] Graph cache found — skipping download."
else
    echo "[entrypoint] Graph cache not found — downloading from Google Drive..."

    # Google Drive large file download requires confirming the virus scan warning
    # Step 1: get the confirm token
    CONFIRM=$(curl -sc /tmp/gcookie "${DOWNLOAD_URL}" | \
        grep -o 'confirm=[^&"]*' | head -1 | sed 's/confirm=//')

    if [ -n "$CONFIRM" ]; then
        echo "[entrypoint] Got confirm token — downloading with token..."
        curl -Lb /tmp/gcookie \
            "https://drive.google.com/uc?export=download&confirm=${CONFIRM}&id=${GDRIVE_FILE_ID}" \
            -o "$ZIP_PATH"
    else
        echo "[entrypoint] No confirm token needed — downloading directly..."
        curl -L "$DOWNLOAD_URL" -o "$ZIP_PATH"
    fi

    echo "[entrypoint] Download complete. Extracting..."
    mkdir -p "$GRAPH_CACHE_DIR"
    unzip -o "$ZIP_PATH" -d "$GRAPH_CACHE_DIR"
    rm "$ZIP_PATH"
    echo "[entrypoint] Graph cache ready."
fi

# Start OpenRailRouting
exec java -jar /app/railway_routing.jar server /app/config.yml
