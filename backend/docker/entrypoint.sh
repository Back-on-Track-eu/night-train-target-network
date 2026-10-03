#!/usr/bin/env bash
set -e

# Country border polygons (input_params.countries.country_geom) — built
# from the Drive-hosted Marine Regions EEZ land union, before the seed that
# loads them. A no-op once db/dev/data/country_geoms.geojson.gz exists, so
# restarts cost nothing. Soft-failing on purpose: seed.py degrades to NULL
# geometry with a loud banner rather than the container refusing to start,
# and the failure is already printed above.
echo "Building country geometries..."
python /app/scripts/export_country_geoms.py || echo "  WARNING: country geometry build failed — see above."

echo "Running database seed..."
python /app/db/dev/seed.py

# Data tasks (db/run_tasks.py — the batch half of the database pipeline,
# next to the schema migrations server deploys run). A fresh seed has
# nothing to backfill, so on a dev stack this is a few idempotent no-ops
# recorded in admin.data_task_runs — but running them here keeps the dev
# stack on the same path as the deploy's `data-tasks` one-shot, so a task
# that would fail on a server fails here first. Backgrounded and
# soft-failing like the loads below: the api is fully functional before
# any task has run (every consumer falls back until its task is through).
# A seed IS every migration (create_*.sql are the latest schema), so record
# them as applied the way a server's first seed does by hand — the task
# runner refuses to start on a database with pending migrations.
echo "Recording migrations as applied (fresh seed)..."
python /app/db/migrate.py --baseline

echo "Running data tasks in the background..."
python /app/db/run_tasks.py &

# ONTD reference data (existing night trains) — loaded in the BACKGROUND
# so the API is serving within seconds. The gallery shows proposals
# immediately and existing routes appear once the load finishes (well
# under a minute; routing runs concurrently, see db/ontd/projection.py).
#
# Guarded on ontd.route_summaries holding ROUTED geometry (a straight-line
# placeholder left by an earlier run is re-routed), so restarts cost
# nothing, and soft-failing by design: the API is fully functional without
# existing-route context, so a Drive outage or a router that is not ready
# must not keep the container down. Its output still goes to the
# container log. Control with ONTD_BOOTSTRAP=auto|force|off.
echo "Bootstrapping ONTD reference data in the background..."
python /app/db/ontd/bootstrap.py &

# Country relation candidate set (input_params.country_relations) — the
# pairs of countries close enough by RAIL for one night train to connect
# them, which GET /api/proposals/stats ranks its top/flop relations over.
# Backgrounded and soft-failing for the same reason as the ONTD load: it
# needs the routing engine, and the API is fully functional without it
# (the statistics return an empty relations block). Idempotent, so a
# restart costs one cheap rebuild rather than being skipped by a guard
# that could go stale when the stop catalog changes.
echo "Building country relations in the background..."
python /app/scripts/build_country_relations.py &

# gthread since WP14: every adapter borrows a pooled connection per call,
# so one worker process serves GUNICORN_THREADS requests concurrently (a
# quick /like no longer waits behind a slow family build) and the family
# builder can fan out its prewarm. Sizing: DB_POOL_MAX >= GUNICORN_THREADS +
# FAMILY_WORKERS per process — see backend/docker/.env.example.
echo "Starting API..."
exec gunicorn --bind "0.0.0.0:${API_CONTAINER_PORT:-5000}" \
  --worker-class gthread \
  --workers "${GUNICORN_WORKERS:-2}" \
  --threads "${GUNICORN_THREADS:-8}" \
  --timeout 120 "main:create_app()"
