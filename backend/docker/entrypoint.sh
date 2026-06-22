#!/usr/bin/env bash
set -e

echo "Running database seed..."
python /app/db/dev/seed.py

echo "Starting API..."
exec python main.py
