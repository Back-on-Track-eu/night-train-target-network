#!/usr/bin/env bash
set -e

cd /workspace/backend
pip install uv --quiet
uv sync

until curl -sf http://localhost:5000/api/health; do
  sleep 2
done

curl -X POST http://localhost:5000/api/data/load
