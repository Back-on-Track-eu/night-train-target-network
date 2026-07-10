FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir psycopg2-binary python-dotenv

# Download countries.geojson so seed.py can populate country_geom.
# Same source as backend/docker/Dockerfile — kept configurable via the
# same build arg for consistency.
ARG NATURAL_EARTH_COUNTRIES_URL=https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson
RUN apt-get -o Acquire::ForceIPv4=true update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL "$NATURAL_EARTH_COUNTRIES_URL" -o /app/countries.geojson

ENV COUNTRIES_GEOJSON_PATH=/app/countries.geojson

COPY seed.py sql_loader.py ./
COPY sql/ ./sql/

CMD ["python", "seed.py"]