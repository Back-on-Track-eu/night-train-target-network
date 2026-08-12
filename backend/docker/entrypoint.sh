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

echo "Starting API..."
exec gunicorn --bind "0.0.0.0:${API_CONTAINER_PORT:-5000}" --workers 4 --timeout 120 "main:create_app()"
