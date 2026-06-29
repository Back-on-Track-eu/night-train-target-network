# =============================================================================
# Night Train — Flask API
# =============================================================================
# Multi-stage build:
#   1. builder  — installs dependencies with uv
#   2. runtime  — lean image with only what's needed to run

FROM python:3.12-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first (layer cache)
COPY pyproject.toml uv.lock ./

# Install dependencies into /app/.venv
RUN uv sync --frozen --no-install-project

# Download countries.geojson here so the runtime stage doesn't need curl
# URL configured via NATURAL_EARTH_COUNTRIES_URL in .env.example.
ARG NATURAL_EARTH_COUNTRIES_URL=https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson
RUN apt-get -o Acquire::ForceIPv4=true update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL "$NATURAL_EARTH_COUNTRIES_URL" -o /countries.geojson

# =============================================================================
FROM python:3.12-slim AS runtime

# Only libatomic1 and locales needed at runtime
RUN apt-get -o Acquire::ForceIPv4=true update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        git \
        curl \
        openssh-client \
        libatomic1 \
        locales \
    && echo "en_US.UTF-8 UTF-8" > /etc/locale.gen \
    && locale-gen \
    && update-locale LANG=en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*

ENV LANG=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=en_US.UTF-8

WORKDIR /app

# Copy venv from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY . .

# Copy pre-downloaded geojson from builder
COPY --from=builder /countries.geojson models/route/routing/countries.geojson

# Activate venv
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

# entrypoint seeds the database then starts the API
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
CMD ["/entrypoint.sh"]