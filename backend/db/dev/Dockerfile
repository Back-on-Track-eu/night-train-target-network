# =============================================================================
# Night Train — standalone seeder (db/dev/docker-compose.yml)
# =============================================================================
# Build context is the BACKEND ROOT, not this directory (see the compose
# file): seed.py imports db.schema and runs alongside the country geometry
# build script, so the image needs the same relative tree the repo has.

FROM python:3.12-slim

WORKDIR /app

# psycopg2/dotenv for the seed itself; pyshp/shapely for the country
# geometry build below. Deliberately not the full API dependency set —
# this image only seeds.
RUN pip install --no-cache-dir psycopg2-binary python-dotenv pyshp shapely

COPY db/ ./db/
COPY scripts/export_country_geoms.py ./scripts/

# Country border polygons first (a no-op once the artifact exists, and
# soft-failing — seed.py degrades to NULL geometry with a loud banner),
# then the seed that loads them.
CMD ["sh", "-c", "python scripts/export_country_geoms.py || echo '  WARNING: country geometry build failed — see above.'; python db/dev/seed.py"]
