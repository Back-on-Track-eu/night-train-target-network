#!/usr/bin/env bash
set -e

# Wait for the API to be healthy (max 60 attempts = ~2 minutes)
echo "Waiting for API..."
attempts=0
until curl -sf http://localhost:5000/api/health > /dev/null; do
  attempts=$((attempts + 1))
  if [ $attempts -ge 60 ]; then
    echo "API did not become healthy after 2 minutes. Aborting."
    exit 1
  fi
  sleep 2
done

echo "API is ready."