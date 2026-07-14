# Alembic migrations

Conventions for writing migrations in this project. `env.py` (this directory)
runs migrations online via an async engine; the live extension stack is
PostGIS + pgvector + pg_trgm + unaccent on PostgreSQL.

## Transaction model (and `CREATE INDEX CONCURRENTLY`)

`env.py` runs the whole migration run inside **one** transaction
(`do_run_migrations` → `with context.begin_transaction(): context.run_migrations()`),
which is Alembic's default for transactional-DDL PostgreSQL. This means an
`alembic upgrade` is **atomic**: if any migration in the run fails, the entire
run rolls back (no partial/resumable schema). This is the intended, safer
behavior.

`env.py` performs a `connection.rollback()` immediately after the raw `COMMIT`
that persists its preamble DDL (schema + version table). That rollback clears
SQLAlchemy's empty autobegun transaction so that `context.begin_transaction()`
owns a real, committing transaction. **Without it, `op.get_context().autocommit_block()`
raises `AssertionError`** (`context.begin_transaction()` would return a
`nullcontext` and never set `ctx._transaction`). See finding CV-1.

Because the run is one transaction, statements that **cannot** run inside a
transaction (notably `CREATE INDEX CONCURRENTLY`) must use an autocommit escape
hatch:

```python
def upgrade() -> None:
    # CONCURRENTLY cannot run in a transaction block. autocommit_block() commits
    # the current transaction, switches the connection to AUTOCOMMIT, runs the
    # body, then restarts the transaction.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_records_embedding_hnsw "
            "ON catalog.record_embeddings USING hnsw (embedding vector_cosine_ops)"
        )
```

Prefer `CONCURRENTLY` (in `autocommit_block`) for any index build on a
table that may be large in production (`records`, `record_embeddings`,
`audit_logs`, `ingest_jobs`, per-dataset `data.*` tables). For small/transient
tables a plain `CREATE INDEX` is fine.

### Embedding cache after migration 0012

Migration `0012_type_embedding_vector` deliberately truncates
`catalog.record_embeddings` before fixing the vector dimension. Embeddings are
derived cache data, and clearing them keeps the type-change lock short even on a
large catalog. The migration then commits that transition and builds HNSW with
`CREATE INDEX CONCURRENTLY`; a retry repairs an invalid interrupted index.
Strong-lock acquisition is capped at five seconds. If PostgreSQL reports a lock
timeout, let the blocking transaction finish (or choose a quieter window) and
rerun Alembic; the transition is unchanged and retry-safe.

After the API starts with its embedding provider configured, an administrator
should call `POST /admin/backfill-embeddings/` (or use the corresponding admin
control) to restore embedding coverage. Until that backfill or later record edits
complete, semantic search has no cached vectors for pre-existing records.

## Large-table CHECK / FK constraints (NOT VALID + VALIDATE)

A bare `ALTER TABLE ... ADD CONSTRAINT ... CHECK (...)` takes `ACCESS EXCLUSIVE`
and validates **every row** under that lock. On a large table, split it so the
row-scan phase runs under the weaker `SHARE UPDATE EXCLUSIVE` lock, and run the
`VALIDATE` in its **own** transaction (via `autocommit_block`) so the lock is
actually released between the two steps:

```python
def upgrade() -> None:
    op.execute(
        "ALTER TABLE catalog.<t> ADD CONSTRAINT <name> CHECK (<expr>) NOT VALID"
    )
    with op.get_context().autocommit_block():
        op.execute("ALTER TABLE catalog.<t> VALIDATE CONSTRAINT <name>")
```

Important: inside `env.py`'s single transaction (i.e. **without** an
`autocommit_block`), `NOT VALID` + `VALIDATE` gives **no** concurrency benefit.
The `ACCESS EXCLUSIVE` from `ADD ... NOT VALID` is held until commit, so the
split only helps when `VALIDATE` runs in a separate (autocommit) transaction.
Migration `0018` (`chk_ingest_jobs_status`) is deliberately left as a single
`ADD CONSTRAINT`: `ingest_jobs` is small/transient, so its full-scan validation
is cheap and re-validating an already-released migration is unwarranted churn
(finding CV-3).

If existing rows need repair before validation, commit the idempotent `ADD ...
NOT VALID` first, repair only changed rows in the restarted transaction, then
enter a second `autocommit_block` for `VALIDATE`. Migration `0014` follows this
pattern. The first commit makes the constraint enforce new writes before the
repair begins; the second releases repair locks before the validation scan.
Both DDL phases cap lock acquisition at five seconds and can be retried after a
lock-timeout failure without manual schema repair.

## Functional / expression indexes and `alembic check`

`alembic check` must stay green (it is the drift gate). SQLAlchemy cannot
reflect a raw-SQL expression index unless an equivalent `Index(text(...))` is
declared in the model's `__table_args__`. When you add an expression index in a
migration (e.g. a trigram GIN or a functional `to_tsvector` index), **also**
declare it on the model.

The `text()` literal must byte-match the expression SQLAlchemy *reflects*, NOT
the raw `pg_get_indexdef` output (they differ; e.g. the reflected form of the
`to_tsvector` index in `Record.__table_args__` has one fewer outer paren than
`pg_get_indexdef`). To regenerate the literal after a change: run `alembic check`
and copy the expression verbatim from the diff error message, or read
`inspect(conn).get_indexes('<table>', schema='catalog')`. Then confirm
`alembic check` is green.

## Minimum versions

A fresh `alembic upgrade head` requires **PostgreSQL 13+** (`gen_random_uuid()`
is used as a column default; migration `0001` RAISEs a clear error on older
servers) and **pgvector 0.5+** (HNSW index in migration `0012`). Required
extensions (`postgis`, `pg_trgm`, `vector`, `unaccent`) are provisioned
out-of-band by `scripts/init-db.sh`; `0001` verifies their presence and RAISEs
if any is missing.
