"""Index the origin_ref keys the duplicate-source guards query.

perf(#1324). Follow-up to #1286 / PR #1320, which re-keyed the
service-preview and STAC-import duplicate-source guards from the
`origin_uri` string onto the structured `origin_ref` identity —
`origin_ref->>'url'` / `origin_ref->>'layer_id'` for services
(``catalog/sources/router.py``) and `origin_ref->>'asset_href'` for STAC
(``catalog/sources/stac_router.py``). Migration 0036 indexed only
`origin_uri`, so both re-keyed guards fell back to a sequential scan with
per-row JSONB extraction.

All three indexes below are `USING hash`, scoped with `IS NOT NULL` on the
indexed expression itself rather than on `source_format`, mirroring
`ix_datasets_origin_uri` (0036) rather than the
`_SERVICE_FORMATS`/`SERVICE_SOURCE_FORMATS` value list. The guards send
`source_format` as a bound parameter, and proving a partial index predicate
implied by a parameterized equality (`source_format = $1` implies
`source_format IN (...)`) only holds for a custom plan built from the
literal value; once postgres's plan cache promotes a query to a generic
plan (``plan_cache_mode = auto``, the default, after enough executions on
one prepared statement), the parameter is opaque and the implication is no
longer provable, silently discarding the index. `origin_ref->>'url' = $1`
implying `origin_ref->>'url' IS NOT NULL` is a strict-operator implication
postgres proves independent of the parameter's value, so it holds under
both custom and generic plans regardless of access method. It is also
self-maintaining: a new service kind that starts writing `url` is covered
without a migration, where a `source_format` list would need one.

Why hash, not btree, for EVERY one of these three (closing the class, not
patching per-column — round 2 caught it on `source_url`, round 4 caught the
same hazard on the two `origin_ref` columns): all three call sites compare
with pure equality only — `origin_ref->>'url' == base_url` /
`origin_ref->>'asset_href'` `.in_(hrefs)` / `source_url == enriched_url` /
`source_url.in_(hrefs)` (postgres decomposes an `IN` list into an OR of `=`
conditions at plan time, so a hash index serves it exactly like a btree
would, confirmed by EXPLAIN) — never a range, prefix, or LIKE comparison,
so hash loses nothing a btree would have offered here. It gains something a
btree cannot: a btree index stores the value itself and has a ~2704-byte
tuple limit on standard 8kB pages, while `source_url` is `VARCHAR(2000)`
(caps CHARACTER count, not bytes) and WFS/OGC API `layer_name` — which
migration 0036's backfill and every subsequent write flow into
`origin_ref->>'layer_id'` for those service types — is a separate
`max_length=500` field with no charset restriction, so a multibyte-heavy
`url` (astral-plane/CJK-dense, reproduced: 2000 random astral-plane
characters is 8000 bytes) combined with a multibyte `layer_id` can exceed
the btree ceiling in the COMPOSITE key even when neither column alone
would, and a scratch btree `CREATE INDEX` on such a row fails outright with
"index row size exceeds btree ... maximum". A hash index stores a
fixed-size hash of the value, never the value itself, so it has no such
ceiling regardless of how long or how multibyte-heavy the source string is.

Postgres hash indexes are single-column only, so `layer_id` is NOT part of
`ix_datasets_origin_ref_url` (it was a second btree column in an earlier
revision of this migration). The service-preview guard's `layer_id`
equality/`IS NULL` check becomes a residual Filter on whatever rows the
`url` hash index narrows to, rather than an Index Cond — confirmed
acceptable by EXPLAIN: `url` alone is the selective key for this guard
(it is unique per remote service+base-path combination in practice), the
endpoint is interactive and low-frequency, and every row the hash index
does NOT filter out still gets the exact right answer from the Filter, so
correctness is identical to the composite-btree shape; only the width of
the candidate set before the Filter changes.

Plain, transactional `CREATE INDEX` -- not `CONCURRENTLY` -- for all three,
which is a deliberate reversal from an earlier revision of this migration.
`catalog.datasets` is the core catalog table, but is small in any realistic
install (thousands of rows, not millions): the Clean-DB CI job's own log
shows the WHOLE migration chain up to and including this one completing in
about 1.5 seconds, so a brief SHARE lock during the build is cheap in every
environment this actually runs in. `CREATE INDEX CONCURRENTLY` trades that
brief lock for a much sharper failure mode under this test suite's own
bootstrap: pytest-xdist migrates each worker's database with
`alembic.command.upgrade` running several workers against one Postgres
instance in parallel, and a CIC interrupted mid-build (lock contention from
a sibling worker's migration, a killed process) leaves an INVALID index
behind; `IF NOT EXISTS` then treats that husk as "already there" and never
retries or errors. An invalid index is invisible to SQLAlchemy's reflection
(autogenerate reports it as missing -> `alembic check` drift) and is never
chosen by the planner (the guard queries silently stop using it) --
reproduced exactly in CI: `test_email_verification_migration.py`'s
drift check and this migration's own EXPLAIN tests both failed against a
worker database that turned out to hold invalid copies of all three
indexes. The post-squash migration chain (0001 onward) has no other
`CONCURRENTLY` migration, so this bootstrap path had no prior green run to
catch the pattern. A plain `CREATE INDEX` participates in the migration's
ambient transaction: it either fully commits or the whole migration rolls
back, so there is no invalid-index state to leave behind, no
`_index_state()` resumability check needed, and no `autocommit_block()`
needed either. `IF NOT EXISTS` is kept only for idempotency on a retried
migration, not because a partial build is possible under plain DDL.
Index-only, additive: no column added, no existing index touched, no table
rewrite.

Revision ID: 0040_dataset_origin_ref_indexes
Revises: 0039_raster_assets_built_from
Create Date: 2026-08-10
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0040_dataset_origin_ref_indexes"
down_revision: Union[str, None] = "0039_raster_assets_built_from"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (index_name, index_expression_sql, partial_where_sql). All USING hash,
# hence all single-column expressions -- see the module docstring's
# `layer_id` paragraph for why the service-url index dropped its second
# column rather than staying a composite.
_ORIGIN_REF_INDEXES: tuple[tuple[str, str, str], ...] = (
    (
        "ix_datasets_origin_ref_url",
        "(origin_ref ->> 'url')",
        "(origin_ref ->> 'url') IS NOT NULL",
    ),
    (
        "ix_datasets_origin_ref_asset_href",
        "(origin_ref ->> 'asset_href')",
        "(origin_ref ->> 'asset_href') IS NOT NULL",
    ),
    (
        "ix_datasets_source_url",
        "source_url",
        "source_url IS NOT NULL",
    ),
)


def upgrade() -> None:
    for index_name, expr_sql, where_sql in _ORIGIN_REF_INDEXES:
        op.execute(
            f'CREATE INDEX IF NOT EXISTS "{index_name}" '
            f'ON catalog."datasets" USING hash ({expr_sql}) '
            f"WHERE {where_sql}"
        )


def downgrade() -> None:
    for index_name, _expr_sql, _where_sql in reversed(_ORIGIN_REF_INDEXES):
        op.execute(f'DROP INDEX IF EXISTS catalog."{index_name}"')
