# PostGIS 18 + pgvector, built on the OFFICIAL postgis/postgis image (the source
# maintainer). pgvector is installed from its official PGDG apt package
# (postgresql-18-pgvector), NOT compiled from source — same extension version
# (0.8.x), a small/fast layer, and no build toolchain left in the final image.
#
# Based on 18-3.6 (Debian trixie, GEOS 3.13 / PROJ 9.6; measured 1.5–2.3× over
# the older GEOS 3.9 on ST_Union/ST_Buffer/ST_MakeValid analysis paths). Moving
# an existing pgdata volume across a PostgreSQL major version needs pg_upgrade
# or dump/restore — see RUNBOOK.md.
#
# The --platform=linux/amd64 pin is required: postgis/postgis:18-3.6 only
# publishes an amd64 manifest (no arm64 variant), so arm64 hosts run this under
# emulation.
#
# Expected build/runtime warnings (NOT bugs):
#   - WARN: FromPlatformFlagConstDisallowed: FROM --platform flag should not use
#     a constant value "linux/amd64" (line below).
#   - "The requested image's platform (linux/amd64) does not match the detected
#     host platform (linux/arm64/v8)" on Apple Silicon — Rosetta/QEMU emulation,
#     functional, slightly degraded postgres performance, acceptable for dev.
#
# NOTE: Trivy DS-0002 ("no non-root USER") is accepted for this image (see the
# scoped entry + rationale in .trivyignore.yaml). The official postgis/postgres
# entrypoint runs as root only to initdb/chown on first boot, then drops to the
# unprivileged `postgres` user via gosu for the server process.
FROM --platform=linux/amd64 postgis/postgis:18-3.6@sha256:e84455a058f60f06dd8c40e66a2c628b8fc113d9fca0896e1f308b25b897207f

# pgvector for semantic-search embeddings, from the PGDG apt repository that the
# official postgres/postgis base image already configures.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        postgresql-18-pgvector && \
    rm -rf /var/lib/apt/lists/*
