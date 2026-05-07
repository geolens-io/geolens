# Database Index Deferrals

Indexes that audits or routine review have considered but explicitly deferred
to a later milestone, with the trigger condition for revisiting.

The intent of this file: prevent the same index from being re-proposed every
audit cycle, and turn each deferral into an actionable revisit signal rather
than a forgotten note in a milestone archive.

## Format

Each entry has:

- **REQ-ID** — the originating audit finding identifier
- **Audit citation** — which audit and which severity bucket
- **Proposed index** — exact DDL or model declaration
- **Why deferred** — the cost/benefit reasoning at deferral time
- **Revisit trigger** — the operational signal that flips the decision

## Active Deferrals

### DBM-06: `Map.visibility` composite index

- **REQ-ID**: DBM-06 (v13.13 / Phase 271)
- **Audit citation**: db-audit MED-06 / migration-audit M-18 (v13.12)
- **Proposed index**: `Index("ix_maps_visibility_creator", "visibility", "created_by")` on `catalog.maps`
- **Why deferred**: The `WHERE visibility = ? AND created_by = ?` filter combo runs on the public-maps list path. Today, total row count in `catalog.maps` is small enough (typically <1k for any single deployment) that PostgreSQL's planner picks an efficient strategy without the index. Adding the index now means paying the write-maintenance cost on every map mutation for a query latency improvement that is currently below the noise floor.
- **Revisit trigger**: When EXPLAIN (ANALYZE) on the public-maps list query (`GET /maps?visibility=public&...`) shows a sequential scan against `catalog.maps` AND total `catalog.maps` row count exceeds ~10k, add the composite index in a new Alembic revision. Re-validate with EXPLAIN after.

## Closed Deferrals

(None yet — entries move here once the index is created and the revision shipped.)
