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

# Activate venv
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Gate page media (api/gate_media/, gitignored): fetched from Drive at BUILD
# time so no request ever depends on Drive, and so every deploy path gets it —
# the server compose files replace the entrypoint below with plain gunicorn,
# so a start-time hook would never run there. A checkout that already holds
# the files (a developer's local fetch) is copied in above and skips the
# download. Soft-failing: the API is fully functional without the media and
# the page hides the slideshow rather than showing broken pictures.
RUN python scripts/fetch_gate_media.py \
    || echo "WARNING: gate media not fetched — the gate page ships without its slideshow."

EXPOSE 5000

# entrypoint seeds the database then starts the API
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
CMD ["/entrypoint.sh"]