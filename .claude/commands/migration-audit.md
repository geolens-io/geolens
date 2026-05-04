# /migration-audit — Alembic + PostGIS/pgvector/pg_trgm Migration Audit

Audit the Alembic migration chain for correctness, safety, and compatibility with GeoLens's spatial extension stack. This stack (PostGIS + pgvector + pg_trgm on PostgreSQL) has migration failure modes that generic tools miss: extension ordering dependencies, spatial index gaps, embedding dimension mismatches, and downgrade paths that silently destroy geometry data.

---

## INTAKE (Serial — do this first)

### Step 1: Map the migration landscape

```bash
# Alembic config
cat alembic.ini 2>/dev/null || cat backend/alembic.ini 2>/dev/null

# Migration directory
find . -path "*/alembic/versions/*.py" 2>/dev/null | sort
find . -path "*/alembic/versions/*.py" 2>/dev/null | wc -l

# Alembic env.py (how migrations connect to the app)
find . -path "*/alembic/env.py" 2>/dev/null | while read f; do
  echo "=== $f ==="
  cat "$f"
done

# Current head(s)
cd backend 2>/dev/null || true
uv run alembic heads 2>/dev/null
uv run alembic branches 2>/dev/null
uv run alembic history --verbose 2>/dev/null | head -60
cd - 2>/dev/null || true
```

### Step 2: Read the SQLAlchemy models

```bash
# All model files
find backend/app -name "models.py" -o -name "model.py" 2>/dev/null | sort

# Read each to build a mental model of the schema
find backend/app -name "models.py" -o -name "model.py" 2>/dev/null | while read f; do
  echo "=== $f ==="
  cat "$f"
done

# GeoAlchemy2 / pgvector / pg_trgm usage in models
grep -rn "Geometry\|Geography\|Vector\|TSVECTOR\|tsvector\|geoalchemy\|pgvector" backend/app/ --include="*.py" | grep -v __pycache__
```

### Step 3: Check the database connection and extension state

```bash
# If a running database is available
psql "$DATABASE_URL" -c "SELECT extname, extversion FROM pg_extension ORDER BY extname;" 2>/dev/null || echo "NO_DB_CONNECTION"

# Check current migration state
cd backend 2>/dev/null || true
uv run alembic current 2>/dev/null
cd - 2>/dev/null || true
```

---

## EXTENSION DEPENDENCY RULES (Embedded)

These are the hard rules for PostgreSQL extension management in migrations. Violations cause silent deployment failures.

### Extension creation ordering

Extensions MUST be created before any objects that depend on them:

1. `postgis` — before any `geometry`/`geography` columns, spatial indexes, or `ST_*` function calls
2. `pgvector` — before any `vector` columns or `<->`, `<#>`, `<=>` operators
3. `pg_trgm` — before any `gin_trgm_ops` or `gist_trgm_ops` indexes or `%` similarity operator
4. `btree_gist` — if using exclusion constraints or GiST indexes on non-geometric types (sometimes a PostGIS dependency)

### Extension creation rules

- Extensions should be created via `op.execute('CREATE EXTENSION IF NOT EXISTS ...')` in a migration, NOT assumed to pre-exist
- Extension creation MUST happen in the earliest migration that uses extension-dependent types
- `CREATE EXTENSION IF NOT EXISTS` is idempotent and safe to repeat — but only within the same migration chain
- Air-gapped deployments may have extensions pre-installed at different versions — migrations must not assume a specific extension version

### Downgrade rules

- `DROP EXTENSION CASCADE` in downgrades will destroy ALL dependent objects (columns, indexes, functions) — this is almost never what you want
- Downgrades should drop extension-dependent columns/indexes explicitly BEFORE dropping extensions
- Geometry columns cannot be "safely" downgraded to text and back — geometry metadata is lost
- Vector columns lose dimension information on downgrade if recreated as text

### Spatial index rules

- Every `geometry`/`geography` column used in spatial queries SHOULD have a GiST index
- PostGIS spatial indexes use `USING GIST` — not btree
- pgvector indexes use `USING ivfflat` or `USING hnsw` — index type affects query semantics
- pg_trgm indexes use `USING GIN (column gin_trgm_ops)` or `USING GIST (column gist_trgm_ops)`
- Missing spatial indexes don't cause errors — they cause silent full-table scans on spatial queries

---

## SUBAGENT DISPATCH (Parallel)

Run these 6 subagents in parallel.

### Subagent 1: Migration Chain Integrity

**Goal:** Verify the Alembic migration chain is linear, complete, and has no orphaned or conflicting revisions.

**Process:**

1. **Chain linearity:**
   ```bash
   cd backend 2>/dev/null || true

   # Check for multiple heads (branching)
   uv run alembic heads 2>/dev/null

   # Check for branches
   uv run alembic branches 2>/dev/null

   # Full history
   uv run alembic history --verbose 2>/dev/null
   cd - 2>/dev/null || true
   ```
   - Multiple heads indicate an unmerged branch — this will break `alembic upgrade head`
   - Branches are acceptable only if intentional (rare in single-developer projects)

2. **Revision linkage:**
   ```bash
   # Extract revision IDs and down_revision from every migration
   find . -path "*/alembic/versions/*.py" 2>/dev/null | while read f; do
     echo "=== $(basename $f) ==="
     grep -E "^revision|^down_revision|^depends_on" "$f"
   done
   ```
   - Every `down_revision` must point to an existing revision (or `None` for the first)
   - No two migrations should share the same `down_revision` (creates a branch)
   - `depends_on` should be used for cross-branch dependencies, not for linear chains

3. **Naming and ordering:**
   ```bash
   # List migrations by filename to check naming convention
   find . -path "*/alembic/versions/*.py" 2>/dev/null | sort | while read f; do
     basename "$f"
   done
   ```
   - Are migrations named descriptively (e.g., `001_add_datasets_table.py`) or auto-generated hex?
   - Is the ordering unambiguous from filenames alone?

4. **Empty or no-op migrations:**
   ```bash
   # Find migrations with empty upgrade/downgrade
   find . -path "*/alembic/versions/*.py" 2>/dev/null | while read f; do
     upgrade_lines=$(sed -n '/def upgrade/,/def downgrade/p' "$f" | grep -v "def \|pass\|^$\|^#\|\"\"\"" | wc -l)
     if [ "$upgrade_lines" -eq 0 ]; then
       echo "EMPTY UPGRADE: $(basename $f)"
     fi
   done
   ```

5. **Live chain validation (if DB available):**
   ```bash
   cd backend 2>/dev/null || true
   # Check current position
   uv run alembic current 2>/dev/null

   # Check if head matches current
   uv run alembic check 2>/dev/null
   cd - 2>/dev/null || true
   ```

**Output:** Chain health summary — linear/branched, head count, any broken links, orphaned migrations.

---

### Subagent 2: Model ↔ Migration Drift

**Goal:** Detect differences between SQLAlchemy models and the schema that migrations would produce. Drift means either a model change wasn't migrated or a migration was manually edited without updating models.

**Process:**

1. **Auto-generate a diff migration:**
   ```bash
   cd backend 2>/dev/null || true
   # Generate but DO NOT apply — just capture the output
   uv run alembic revision --autogenerate -m "drift_check_DO_NOT_COMMIT" --sql 2>/dev/null || \
   uv run alembic revision --autogenerate -m "drift_check_DO_NOT_COMMIT" 2>/dev/null

   # Read the generated migration
   DRIFT_FILE=$(find . -path "*/alembic/versions/*drift_check*" 2>/dev/null | head -1)
   if [ -n "$DRIFT_FILE" ]; then
     echo "=== DRIFT DETECTED ==="
     cat "$DRIFT_FILE"
     # Clean up — DO NOT leave drift check migrations in the tree
     rm "$DRIFT_FILE"
   else
     echo "NO DRIFT FILE GENERATED"
   fi
   cd - 2>/dev/null || true
   ```

   If autogenerate produces a non-empty migration, there is drift. Classify each operation:

   - **🔴 Missing migration** — Model has a column/table that no migration creates
   - **🟡 Migration without model** — A migration creates something the model doesn't define (manual SQL)
   - **🟢 Intentional divergence** — Raw SQL operations (extension creation, custom indexes) that Alembic can't autogenerate

2. **Known autogenerate blind spots:**
   Alembic autogenerate CANNOT detect these changes — check manually:
   ```bash
   # Check types — renamed, changed (e.g., String(50) → String(100))
   grep -rn "Column\|mapped_column" backend/app/ --include="*.py" | grep -v __pycache__ | grep -i "string\|varchar\|integer\|float\|boolean\|text\|json\|numeric"

   # Check constraints — check constraints, unique constraints, foreign key changes
   grep -rn "CheckConstraint\|UniqueConstraint\|ForeignKey\|Index\|__table_args__" backend/app/ --include="*.py" | grep -v __pycache__

   # GeoAlchemy2 types — autogenerate often misses geometry type/srid changes
   grep -rn "Geometry\|Geography" backend/app/ --include="*.py" | grep -v __pycache__
   ```

   For each spatial column, verify:
   - The migration that creates it specifies the correct geometry type (Point, Polygon, etc.)
   - The migration specifies the correct SRID
   - The model and migration agree on nullability

3. **Index drift:**
   ```bash
   # Indexes defined in models
   grep -rn "Index\|index=True\|__table_args__" backend/app/ --include="*.py" | grep -v __pycache__

   # Indexes created in migrations
   grep -rn "create_index\|op.create_index\|CREATE INDEX\|USING GIST\|USING GIN\|USING ivfflat\|USING hnsw" . --path "*/alembic/versions/*.py" 2>/dev/null || \
   find . -path "*/alembic/versions/*.py" -exec grep -ln "create_index\|CREATE INDEX\|USING GIST\|USING GIN\|USING ivfflat\|USING hnsw" {} \;
   ```

**Output:** Drift inventory table — Model field | Migration status | Type match | Nullable match | Index match.

---

### Subagent 3: Extension & Spatial Type Safety

**Goal:** Audit every migration that touches PostGIS, pgvector, or pg_trgm for correct extension ordering, type safety, and safe upgrade/downgrade.

**Process:**

1. **Extension creation audit:**
   ```bash
   # Find all extension creation/drop statements in migrations
   find . -path "*/alembic/versions/*.py" 2>/dev/null | while read f; do
     hits=$(grep -n "CREATE EXTENSION\|DROP EXTENSION\|postgis\|pgvector\|pg_trgm\|btree_gist" "$f" 2>/dev/null)
     if [ -n "$hits" ]; then
       echo "=== $(basename $f) ==="
       echo "$hits"
     fi
   done
   ```

   For each extension reference, verify:
   - `CREATE EXTENSION IF NOT EXISTS` used (not just `CREATE EXTENSION`)
   - Extension is created BEFORE any dependent columns/indexes in the same migration
   - Extension is created in an earlier migration than any migration that uses dependent types
   - No `DROP EXTENSION CASCADE` in downgrade (catastrophic data loss)

2. **Geometry column audit:**
   ```bash
   # Find all geometry/geography column operations
   find . -path "*/alembic/versions/*.py" 2>/dev/null | while read f; do
     hits=$(grep -n "geometry\|geography\|Geometry\|Geography\|SRID\|srid\|4326\|CRS84" "$f" 2>/dev/null | grep -iv "^#\|\"\"\"")
     if [ -n "$hits" ]; then
       echo "=== $(basename $f) ==="
       echo "$hits"
     fi
   done
   ```

   For each geometry column operation:
   - Is the geometry type specified (Point, Polygon, MultiPolygon, etc.) or generic?
   - Is the SRID specified? (Default 0 means unspecified — almost always a bug)
   - Does the migration create a spatial GiST index for the column?
   - Does the downgrade correctly drop the spatial index before the column?
   - Is `nullable` consistent with the model?

3. **Vector column audit:**
   ```bash
   # Find all pgvector operations
   find . -path "*/alembic/versions/*.py" 2>/dev/null | while read f; do
     hits=$(grep -n "vector\|Vector\|embedding\|ivfflat\|hnsw\|<->\|<#>\|<=>" "$f" 2>/dev/null | grep -iv "^#\|\"\"\"")
     if [ -n "$hits" ]; then
       echo "=== $(basename $f) ==="
       echo "$hits"
     fi
   done
   ```

   For each vector column:
   - Is the dimension specified (e.g., `Vector(1536)`)? Mismatched dimensions cause runtime errors.
   - Does the migration match the model's dimension?
   - If an index exists: is it `ivfflat` or `hnsw`? Are `lists` (ivfflat) or `m`/`ef_construction` (hnsw) parameters reasonable?
   - Does the downgrade safely drop the index before the column?

4. **Trigram index audit:**
   ```bash
   # Find all pg_trgm operations
   find . -path "*/alembic/versions/*.py" 2>/dev/null | while read f; do
     hits=$(grep -n "trgm\|trigram\|gin_trgm_ops\|gist_trgm_ops\|similarity\|%" "$f" 2>/dev/null | grep -iv "^#\|\"\"\"")
     if [ -n "$hits" ]; then
       echo "=== $(basename $f) ==="
       echo "$hits"
     fi
   done
   ```

   For each trigram index:
   - Is `pg_trgm` extension created before the index?
   - Is the correct operator class used (`gin_trgm_ops` for GIN, `gist_trgm_ops` for GiST)?
   - Is the indexed column actually a text/varchar type?

5. **Cross-reference extensions with models:**
   ```bash
   # Which models use spatial types?
   grep -rn "Geometry\|Geography" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v alembic

   # Which models use vector types?
   grep -rn "Vector\|embedding" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v alembic

   # Which models use tsvector/trigram?
   grep -rn "TSVECTOR\|tsvector\|TSVector" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v alembic
   ```

   Verify every model using extension types has a corresponding migration creating the extension.

**Output:** Extension safety matrix — Extension | First created (migration) | Dependent objects | Ordering safe? | Downgrade safe?

---

### Subagent 4: Downgrade Safety & Data Loss Risk

**Goal:** Audit every downgrade path for data loss risks, with special attention to spatial/vector data that cannot be round-tripped through text.

**Process:**

1. **Downgrade completeness:**
   ```bash
   # Check every migration has a downgrade function
   find . -path "*/alembic/versions/*.py" 2>/dev/null | while read f; do
     has_downgrade=$(grep -c "def downgrade" "$f")
     downgrade_has_pass=$(sed -n '/def downgrade/,/^def \|^class \|^$/p' "$f" | grep -c "pass")
     if [ "$has_downgrade" -eq 0 ]; then
       echo "🔴 NO DOWNGRADE: $(basename $f)"
     elif [ "$downgrade_has_pass" -gt 0 ]; then
       # Check if pass is the ONLY statement
       downgrade_ops=$(sed -n '/def downgrade/,/^def \|^class /p' "$f" | grep -v "def downgrade\|pass\|^$\|^#\|\"\"\"" | wc -l)
       if [ "$downgrade_ops" -eq 0 ]; then
         echo "🟡 EMPTY DOWNGRADE (pass only): $(basename $f)"
       fi
     fi
   done
   ```

2. **Destructive downgrade operations:**
   ```bash
   # Find DROP TABLE, DROP COLUMN, DROP INDEX in downgrades
   find . -path "*/alembic/versions/*.py" 2>/dev/null | while read f; do
     # Extract only the downgrade function
     downgrade_section=$(sed -n '/def downgrade/,/^def \|^class /p' "$f")
     drops=$(echo "$downgrade_section" | grep -n "drop_table\|drop_column\|drop_index\|DROP TABLE\|DROP COLUMN\|DROP INDEX\|DROP EXTENSION" 2>/dev/null)
     if [ -n "$drops" ]; then
       echo "=== $(basename $f) ==="
       echo "$drops"
     fi
   done
   ```

   For each destructive operation:
   - **DROP TABLE** — Is data in this table recoverable? Is there a backup step?
   - **DROP COLUMN** — If it's a geometry/vector column, data is irrecoverable
   - **DROP EXTENSION CASCADE** — Nuclear option. Flag as 🔴 always.
   - **DROP INDEX** — Safe but may degrade performance during partial rollback

3. **Type change reversibility:**
   ```bash
   # Find ALTER COLUMN / type changes in both upgrade and downgrade
   find . -path "*/alembic/versions/*.py" 2>/dev/null | while read f; do
     hits=$(grep -n "alter_column\|ALTER.*TYPE\|type_=\|server_default" "$f" 2>/dev/null)
     if [ -n "$hits" ]; then
       echo "=== $(basename $f) ==="
       echo "$hits"
     fi
   done
   ```

   Dangerous type changes:
   - `geometry` → `text` in downgrade → loses SRID, geometry type metadata
   - `vector(N)` → `text` in downgrade → loses dimension enforcement
   - `jsonb` → `json` or `text` → loses query capability
   - `integer` → `smallint` → potential overflow on downgrade
   - Any column with `server_default` changes — default only applies to new rows

4. **Downgrade ordering:**
   For each downgrade with multiple operations, verify the order is the reverse of the upgrade:
   - Indexes dropped before columns
   - Columns dropped before tables
   - Foreign keys dropped before referenced tables
   - Extension-dependent objects dropped before extensions

5. **Data migration safety:**
   ```bash
   # Find data migrations (INSERT, UPDATE, DELETE in migrations)
   find . -path "*/alembic/versions/*.py" 2>/dev/null | while read f; do
     hits=$(grep -n "INSERT\|UPDATE\|DELETE\|bulk_insert\|execute.*SELECT" "$f" 2>/dev/null | grep -iv "^#\|\"\"\"")
     if [ -n "$hits" ]; then
       echo "=== $(basename $f) ==="
       echo "$hits"
     fi
   done
   ```

   Data migrations:
   - Are they idempotent (safe to re-run)?
   - Do they handle NULL values?
   - Do they have a corresponding reverse in the downgrade?
   - Do they operate on large tables without batching? (lock risk)

**Output:** Downgrade safety matrix — Migration | Has downgrade | Destructive ops | Data loss risk | Reversibility rating (Safe/Lossy/Irreversible).

---

### Subagent 5: Index Coverage & Performance

**Goal:** Verify that every column used in queries has appropriate indexes, with special attention to spatial, vector, and trigram indexes that require specific index types.

**Process:**

1. **Spatial index coverage:**
   ```bash
   # All geometry/geography columns in models
   grep -rn "Geometry\|Geography" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v alembic

   # All spatial indexes in migrations
   find . -path "*/alembic/versions/*.py" -exec grep -ln "USING GIST\|gist.*geom\|spatial.*index\|create_index.*geom" {} 2>/dev/null \;

   # Spatial queries that need indexes
   grep -rn "ST_Intersects\|ST_Contains\|ST_Within\|ST_DWithin\|ST_Distance\|ST_Covers\|ST_Touches\|ST_Crosses\|&&" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v alembic
   ```

   For every geometry column used in a spatial query: verify a GiST index exists.

2. **Vector index coverage:**
   ```bash
   # All vector columns
   grep -rn "Vector\|embedding" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v alembic | grep -i "column\|mapped"

   # All vector indexes
   find . -path "*/alembic/versions/*.py" -exec grep -ln "ivfflat\|hnsw\|vector_.*ops\|vector_cosine\|vector_l2\|vector_ip" {} 2>/dev/null \;

   # Vector similarity queries
   grep -rn "<->\|<#>\|<=>\|cosine_distance\|l2_distance\|inner_product\|similarity_search\|nearest" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v alembic
   ```

   For every vector column used in similarity search:
   - Is there an index? (`ivfflat` or `hnsw`)
   - Are index parameters appropriate for the dataset size?
     - ivfflat `lists`: rule of thumb is `sqrt(num_rows)` for <1M rows
     - hnsw `m`: 16 is standard, `ef_construction`: 64-200
   - Is the distance operator (`<->` L2, `<=>` cosine, `<#>` inner product) consistent between index and query?

3. **Trigram index coverage:**
   ```bash
   # Text search patterns that benefit from trigram indexes
   grep -rn "LIKE\|ILIKE\|similar\|%\|trgm\|similarity\|word_similarity" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v alembic

   # Full-text search setup
   grep -rn "tsvector\|to_tsvector\|to_tsquery\|plainto_tsquery\|@@" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v alembic

   # Trigram indexes in migrations
   find . -path "*/alembic/versions/*.py" -exec grep -ln "gin_trgm_ops\|gist_trgm_ops\|trgm" {} 2>/dev/null \;
   ```

4. **Foreign key index coverage:**
   ```bash
   # Foreign keys in models
   grep -rn "ForeignKey\|relationship" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v alembic

   # Indexes on foreign key columns
   # FK columns without indexes cause slow JOINs and DELETE cascades
   grep -rn "ForeignKey" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v alembic | while read line; do
     col=$(echo "$line" | grep -oP '\w+(?=.*ForeignKey)')
     echo "FK column: $col — check for index"
   done
   ```

5. **Composite and partial indexes:**
   ```bash
   # Multi-column indexes
   grep -rn "Index.*,.*," backend/app/ --include="*.py" | grep -v __pycache__
   find . -path "*/alembic/versions/*.py" -exec grep -n "create_index.*\[" {} 2>/dev/null \;

   # Partial indexes (WHERE clause)
   find . -path "*/alembic/versions/*.py" -exec grep -n "where\|postgresql_where\|partial" {} 2>/dev/null \;
   ```

6. **Live index check (if DB available):**
   ```bash
   psql "$DATABASE_URL" -c "
     SELECT
       schemaname, tablename, indexname, indexdef
     FROM pg_indexes
     WHERE schemaname = 'public'
     ORDER BY tablename, indexname;
   " 2>/dev/null

   # Tables without any indexes (excluding small lookup tables)
   psql "$DATABASE_URL" -c "
     SELECT relname, n_live_tup
     FROM pg_stat_user_tables t
     WHERE NOT EXISTS (
       SELECT 1 FROM pg_indexes i WHERE i.tablename = t.relname
     )
     AND n_live_tup > 100
     ORDER BY n_live_tup DESC;
   " 2>/dev/null

   # Unused indexes (if stats available)
   psql "$DATABASE_URL" -c "
     SELECT
       schemaname, relname, indexrelname, idx_scan, idx_tup_read
     FROM pg_stat_user_indexes
     WHERE idx_scan = 0
     ORDER BY relname;
   " 2>/dev/null
   ```

**Output:** Index coverage matrix — Column | Type | Used in queries | Has index | Index type correct | Parameters appropriate.

---

### Subagent 6: Air-Gap & Cross-Version Compatibility

**Goal:** Verify migrations work across PostgreSQL versions and in air-gapped deployments where extensions may be pre-installed at different versions.

**Process:**

1. **PostgreSQL version assumptions:**
   ```bash
   # What Postgres version does the Docker image use?
   grep -n "postgres\|postgis" docker-compose.yml Dockerfile* backend/Dockerfile* 2>/dev/null

   # SQL syntax that may be version-dependent
   find . -path "*/alembic/versions/*.py" 2>/dev/null | while read f; do
     hits=$(grep -n "GENERATED\|IDENTITY\|STORED\|VIRTUAL\|JSONB_PATH\|json_array\|MERGE\|CREATE.*IF NOT EXISTS" "$f" 2>/dev/null)
     if [ -n "$hits" ]; then
       echo "=== $(basename $f) ==="
       echo "$hits"
     fi
   done

   # PostgreSQL 14+ features used
   grep -rn "multirange\|MERGE INTO\|json_array\|json_object" . --path "*/alembic/versions/*.py" 2>/dev/null
   ```

   Flag any SQL syntax that requires a specific PostgreSQL version.

2. **Extension version sensitivity:**
   ```bash
   # Do migrations specify extension versions?
   find . -path "*/alembic/versions/*.py" -exec grep -n "CREATE EXTENSION.*VERSION\|ALTER EXTENSION.*UPDATE" {} 2>/dev/null \;

   # PostGIS version-specific features
   find . -path "*/alembic/versions/*.py" -exec grep -n "ST_AsGeoJSON.*options\|ST_MakeValid\|ST_QuantizeCoordinates\|geography_columns" {} 2>/dev/null \;

   # pgvector version-specific features
   # hnsw requires pgvector 0.5.0+, halfvec requires 0.7.0+
   find . -path "*/alembic/versions/*.py" -exec grep -n "hnsw\|halfvec\|bit\|sparsevec" {} 2>/dev/null \;
   ```

   Key version boundaries:
   - pgvector `hnsw` index: requires pgvector ≥ 0.5.0
   - pgvector `halfvec`: requires pgvector ≥ 0.7.0
   - PostGIS `ST_AsGeoJSON` with `options` parameter: PostGIS ≥ 3.0
   - PostGIS `geography` type: PostGIS ≥ 1.5 (safe, but worth noting)

3. **Air-gapped deployment compatibility:**
   ```bash
   # Do migrations download anything or reference external resources?
   find . -path "*/alembic/versions/*.py" -exec grep -n "http\|https\|download\|fetch\|curl\|pip\|apt" {} 2>/dev/null \;

   # Do migrations assume specific filesystem paths?
   find . -path "*/alembic/versions/*.py" -exec grep -n "/tmp\|/var\|/usr\|/opt\|os.path\|pathlib" {} 2>/dev/null \;

   # Can extensions be created without network access?
   # (This is about the database, not the migration runner — just flag if relevant)
   ```

4. **Migration idempotency:**
   ```bash
   # Are migrations safe to re-run? (important for retry scenarios)
   find . -path "*/alembic/versions/*.py" 2>/dev/null | while read f; do
     # Check for IF NOT EXISTS / IF EXISTS patterns
     safe=$(grep -c "IF NOT EXISTS\|IF EXISTS" "$f")
     unsafe_create=$(grep -c "create_table\|add_column\|CREATE TABLE\|ADD COLUMN" "$f")
     if [ "$unsafe_create" -gt 0 ] && [ "$safe" -eq 0 ]; then
       echo "⚠️  NON-IDEMPOTENT: $(basename $f) — creates objects without IF NOT EXISTS"
     fi
   done
   ```

5. **Transaction safety:**
   ```bash
   # Migrations that shouldn't run in a transaction (CREATE INDEX CONCURRENTLY, etc.)
   find . -path "*/alembic/versions/*.py" -exec grep -n "CONCURRENTLY\|autocommit\|non_transactional" {} 2>/dev/null \;

   # Check if env.py supports non-transactional migrations
   find . -path "*/alembic/env.py" -exec grep -n "transaction\|autocommit\|context.begin_transaction\|context.execute" {} 2>/dev/null \;
   ```

   `CREATE INDEX CONCURRENTLY` cannot run inside a transaction. If any migration uses it, the Alembic env.py must support `autocommit` mode.

6. **Migration performance on large tables:**
   ```bash
   # ALTER TABLE operations that lock the table
   find . -path "*/alembic/versions/*.py" 2>/dev/null | while read f; do
     hits=$(grep -n "add_column\|drop_column\|alter_column\|ADD COLUMN\|DROP COLUMN\|ALTER COLUMN\|ALTER TABLE.*ADD\|ALTER TABLE.*DROP\|ALTER TABLE.*ALTER" "$f" 2>/dev/null)
     if [ -n "$hits" ]; then
       echo "=== $(basename $f) ==="
       echo "$hits"
       # Check if these might be large tables
     fi
   done
   ```

   Flag ALTER TABLE on potentially large tables (features, embeddings, audit_events) — these acquire ACCESS EXCLUSIVE locks and block all reads/writes.

**Output:** Compatibility matrix — Migration | PG version requirement | Extension version requirement | Air-gap safe | Idempotent | Transaction safe | Lock risk.

---

## SYNTHESIS (Serial — after all subagents complete)

### Scoring

| Dimension | What it measures |
|-----------|-----------------|
| **Chain Integrity** | Linear chain, no orphans, no broken links |
| **Model ↔ Migration Sync** | Models and migrations agree on schema |
| **Extension Safety** | Correct ordering, safe downgrades, no CASCADE drops |
| **Downgrade Safety** | Every migration can be reversed without data loss (or loss is documented) |
| **Index Coverage** | Spatial, vector, trigram, and FK indexes present where needed |
| **Cross-Version Safety** | Migrations work across PG versions and in air-gapped deploys |

Grade each A–F using:
- **A** — No issues. Production-ready migration chain.
- **B** — Minor issues. Missing indexes, cosmetic naming. No data risk.
- **C** — Significant issues. Drift detected, missing downgrades. Deployable but risky.
- **D** — Dangerous issues. Extension ordering bugs, CASCADE drops, data loss paths.
- **F** — Broken. Chain doesn't resolve, migrations fail to apply.

**Overall migration health** = minimum grade (like standards compliance, the weakest link determines deployability).

### Action Items

| Field | Description |
|-------|-------------|
| Priority | P0 (migration will fail on clean deploy), P1 (data loss risk on downgrade), P2 (performance/maintenance concern) |
| Action | Specific fix — include migration filename and line number |
| Dimension | Which audit dimension |
| Effort | Hours estimate |
| Risk if unfixed | What breaks |

Sort by priority, then effort.

### Migration Debt Summary

Summarize total migration debt:
- Number of migrations with no downgrade
- Number of extension-dependent columns without extension creation guard
- Number of spatial columns without indexes
- Number of vector columns with dimension mismatches
- Total estimated hours to resolve all P0 + P1 items

---

## DELIVERY

### Output format

Write the report to: `docs-internal/audits/migration-audit-{YYYYMMDD}.md`

### Report structure

```markdown
# Migration Audit — {YYYY-MM-DD}

## Scorecard
<!-- Letter grades + overall health -->

## Executive Summary
<!-- 3-5 sentences: migration chain state, biggest risks, top fix -->

## 1. Migration Chain Integrity
<!-- Subagent 1 findings -->

## 2. Model ↔ Migration Drift
<!-- Subagent 2 findings -->

## 3. Extension & Spatial Type Safety
### 3a. PostGIS
### 3b. pgvector
### 3c. pg_trgm
<!-- Subagent 3 findings -->

## 4. Downgrade Safety & Data Loss Risk
<!-- Subagent 4 findings -->

## 5. Index Coverage & Performance
### 5a. Spatial Indexes
### 5b. Vector Indexes
### 5c. Trigram Indexes
### 5d. Foreign Key Indexes
<!-- Subagent 5 findings -->

## 6. Air-Gap & Cross-Version Compatibility
<!-- Subagent 6 findings -->

## 7. Migration Debt Summary
<!-- Aggregate metrics -->

## 8. Prioritized Action Items
<!-- Action items table -->

## 9. Comparison to Prior Audit
<!-- If a previous migration-audit exists, diff findings -->
```

### Post-delivery

1. If `lessons.md` exists, append reusable insights about Alembic + PostGIS/pgvector/pg_trgm migration patterns.
2. Print one-line summary: overall grade + P0 count + total migration debt hours.

---

## WHAT NOT TO FLAG

Avoid false positives on these:

- **Autogenerated migration names** — Hex-named migrations are the Alembic default. Ugly but functional. Flag as P2 cosmetic issue, not a real problem.
- **Empty downgrades on early migrations** — The first few schema-creation migrations sometimes intentionally have `pass` downgrades because dropping the entire schema is the downgrade. Only flag if there's data in those tables.
- **Missing CONCURRENTLY on small-table indexes** — `CREATE INDEX CONCURRENTLY` is only needed on tables that will have significant data. For tables under ~100K rows, regular index creation is fine.
- **`CREATE EXTENSION IF NOT EXISTS` outside of migrations** — Some projects create extensions in Docker entrypoints or init scripts. This is valid. Check entrypoint scripts before flagging missing extension creation in migrations.
- **Geometry type `Geometry` (generic)** — While specific types (Point, Polygon) are better, generic `Geometry` is valid for collections that accept mixed geometry types. Only flag if the model uses a specific type but the migration uses generic.
- **No vector index on small embedding tables** — pgvector sequential scan is faster than index scan under ~10K rows. Only flag missing indexes on tables expected to be large.
- **Manual SQL in migrations** — Raw `op.execute()` SQL is sometimes necessary for PostGIS/pgvector operations that Alembic can't express. Don't flag the pattern itself, only flag if the SQL is unsafe.
