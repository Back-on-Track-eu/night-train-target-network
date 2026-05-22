# Stage 1 — Build the JAR
FROM maven:3.9-eclipse-temurin-21 AS builder

WORKDIR /build

RUN git clone https://github.com/geofabrik/OpenRailRouting.git . && \
    git submodule init && \
    git submodule update && \
    mvn clean install -DskipTests

# Stage 2 — Lean runtime image
FROM eclipse-temurin:21-jre

WORKDIR /app

COPY --from=builder /build/target/railway_routing-1.1.jar railway_routing.jar

# Only copy OUR custom models — do NOT copy built-in models
COPY custom_models/ /app/custom_models/
COPY config.yml /app/config.yml

EXPOSE 8989 8990

CMD ["java", "-Xmx8g", "-Xms1g", "-jar", "railway_routing.jar", "serve", "config.yml"]