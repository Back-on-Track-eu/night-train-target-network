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

until curl -sf http://localhost:5000/api/health; do
  sleep 2
done

echo "API is ready."