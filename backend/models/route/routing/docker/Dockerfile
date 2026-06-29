# Stage 1 — Build the JAR
FROM maven:3.9-eclipse-temurin-21 AS builder

WORKDIR /build

RUN git clone https://github.com/geofabrik/OpenRailRouting.git . && \
    git submodule init && \
    git submodule update

RUN --mount=type=cache,target=/root/.m2 \
    mvn clean install -DskipTests

# Stage 2 — Lean runtime image
FROM eclipse-temurin:21-jre

WORKDIR /app

# Install curl and unzip for graph cache download
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /build/target/railway_routing-1.1.jar railway_routing.jar

# Only copy OUR custom models — do NOT copy built-in models
COPY custom_models /app/custom_models/
COPY config.yml /app/config.yml

# Startup script — downloads graph cache if not present, then starts server
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8989 8990

ENTRYPOINT ["/app/entrypoint.sh"]
