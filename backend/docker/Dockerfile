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

# git           — VSCode devcontainer source control
# curl          — used in healthchecks
# openssh-client — git over SSH (keys are mounted from host)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy venv from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY . .

# Activate venv
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

# entrypoint seeds the database then starts the API
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
CMD ["/entrypoint.sh"]