# Stage 1 — Build the JAR
FROM maven:3.9-eclipse-temurin-21 AS builder

WORKDIR /build

# Pinned upstream commit. An unpinned clone builds whatever master is today:
# on 2026-09-30 upstream released v1.2 (GraphHopper 11.0 -> 11.1), which
# renamed the jar and broke every image build. This is the last commit before
# that upgrade — jar version 1.1, GraphHopper 11.0, the same code the images
# and the Drive-hosted graph caches were built from until then. Not the v1.1
# TAG: that one still bundles the old web frontend through an `npm install`
# Maven step, and this builder image has no npm.
#
# Full SHA on purpose: GitHub serves a shallow fetch of a bare commit only by
# its full id (`--branch` takes no commit at all). Upgrading is a deliberate
# step — see models/route/routing/README.md "Upgrading OpenRailRouting".
ARG OPENRAILROUTING_COMMIT=ad27c18105a6a03088be0f69feacf37092f1395e

RUN git init -q . && \
    git remote add origin https://github.com/geofabrik/OpenRailRouting.git && \
    git fetch -q --depth 1 origin ${OPENRAILROUTING_COMMIT} && \
    git checkout -q FETCH_HEAD && \
    git submodule update --init --depth 1

# Copied to a fixed name so the runtime stage does not depend on the
# upstream version string.
RUN --mount=type=cache,target=/root/.m2 \
    mvn clean install -DskipTests && \
    cp target/railway_routing-*.jar /build/railway_routing.jar

# Stage 2 — Lean runtime image
FROM eclipse-temurin:21-jre

WORKDIR /app

# Install curl and unzip for graph cache download
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /build/railway_routing.jar railway_routing.jar

# Only copy OUR custom models — do NOT copy built-in models
COPY custom_models /app/custom_models/
COPY config.yml /app/config.yml

# Startup script — downloads graph cache if not present, then starts server
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8989 8990

ENTRYPOINT ["/app/entrypoint.sh"]
