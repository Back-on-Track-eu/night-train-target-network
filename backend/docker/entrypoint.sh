#!/usr/bin/env bash
set -e

echo "Running database seed..."
python /app/db/dev/seed.py

echo "Starting API..."
exec gunicorn --bind 0.0.0.0:5000 --workers 4 --timeout 120 "main:create_app()"