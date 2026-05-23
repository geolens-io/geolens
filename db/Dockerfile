# INFRA-02 (Phase 1092, ACCEPTED 2026-05-23): the --platform=linux/amd64 pin
# on the FROM line is intentional. pgvector 0.8.2 builds reproducibly against
# the postgis/postgis:17-3.5 base image's amd64 variant; the multi-arch
# postgis+pgvector image build pipeline is a future milestone (cross-build
# matrix + image registry tagging + signature distribution — out of v1021
# scope per REQUIREMENTS.md Out of Scope table).
#
# Expected build warnings (these are NOT bugs):
#   - WARN: FromPlatformFlagConstDisallowed: FROM --platform flag should not
#     use constant value "linux/amd64" (line 1)
#   - The requested image's platform (linux/amd64) does not match the
#     detected host platform (linux/arm64/v8) — emitted at runtime on Apple
#     Silicon hosts (Rosetta/QEMU emulation; functional, slightly degraded
#     postgres performance, acceptable for dev workflow).
#
# TODO (future milestone, NOT v1021): build a multi-arch postgis+pgvector
# image so `--platform=linux/amd64` can be removed and the warnings disappear.
# Requires CI cross-build matrix + signature distribution.
FROM --platform=linux/amd64 postgis/postgis:17-3.5

# Install pgvector extension for semantic search embeddings
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        postgresql-server-dev-17 \
        git \
        ca-certificates && \
    git clone --branch v0.8.2 https://github.com/pgvector/pgvector.git /tmp/pgvector && \
    cd /tmp/pgvector && \
    make && \
    make install && \
    rm -rf /tmp/pgvector && \
    apt-get purge -y build-essential postgresql-server-dev-17 git && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*
