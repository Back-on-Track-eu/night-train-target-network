#!/usr/bin/env bash
set -e

echo "Running database seed..."
python /app/db/dev/seed.py

echo "Starting API..."
exec gunicorn \
    --bind 0.0.0.0:5000 \
    --workers 2 \
    --threads 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    "main:create_app()"