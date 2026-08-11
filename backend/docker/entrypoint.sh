#!/usr/bin/env bash
set -e

echo "Running database seed..."
python /app/db/dev/seed.py

# ONTD reference data (existing night trains) — loaded in the BACKGROUND
# so the API is serving within seconds. The gallery shows proposals
# immediately and existing routes appear once the load finishes (well
# under a minute; routing runs concurrently, see db/ontd/projection.py).
#
# Guarded on ontd.route_summaries being empty, so restarts cost nothing,
# and soft-failing by design: the API is fully functional without
# existing-route context, so a Drive outage or a router that is not ready
# must not keep the container down. Its output still goes to the
# container log. Control with ONTD_BOOTSTRAP=auto|force|off.
echo "Bootstrapping ONTD reference data in the background..."
python /app/db/ontd/bootstrap.py &

echo "Starting API..."
exec gunicorn --bind "0.0.0.0:${API_CONTAINER_PORT:-5000}" --workers 4 --timeout 120 "main:create_app()"
