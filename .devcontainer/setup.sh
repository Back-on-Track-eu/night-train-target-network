#!/usr/bin/env bash
set -e

cd /workspace/backend
pip install uv --quiet
uv sync

pip install pre-commit --quiet
cd /workspace
pre-commit install

cd /workspace/frontend
npm install

# Runs inside the api container, so the container-side port applies
# (env from backend/docker/.env via env_file).
until curl -sf "http://localhost:${API_CONTAINER_PORT:-5000}/api/health"; do
  sleep 2
done

echo "API is ready."
