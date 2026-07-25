# PostGIS 18 + pgvector, built on the OFFICIAL postgis/postgis image (the source
# maintainer). pgvector is installed from its official PGDG apt package
# (postgresql-18-pgvector), NOT compiled from source — same extension version
# (0.8.x), a small/fast layer, and no build toolchain left in the final image.
#
# chore(#704): bumped from 17-3.5 (Debian bullseye, EOL 2026-08-31, frozen at
# PG 17.5 / GEOS 3.9) to 18-3.6 (Debian trixie, GEOS 3.13 / PROJ 9.6 — measured
# 1.5–2.3× on ST_Union/ST_Buffer/ST_MakeValid analysis paths; no 17-3.6 tag
# exists upstream). Major-version bump: existing pgdata volumes need
# pg_upgrade or dump/restore — see RUNBOOK.md.
#
# The --platform=linux/amd64 pin is required: postgis/postgis:18-3.6 only
# publishes an amd64 manifest (no arm64 variant), so arm64 hosts run this under
# emulation. This is unchanged from the 17-3.5 image.
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
FROM --platform=linux/amd64 postgis/postgis:18-3.6

# pgvector for semantic-search embeddings, from the PGDG apt repository that the
# official postgres/postgis base image already configures.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        postgresql-18-pgvector && \
    rm -rf /var/lib/apt/lists/*
