# /post-impl — Post-Implementation Engineering Audit

Post-implementation code quality audit for GeoLens: simplification, performance optimization, dead code removal, type safety, and error handling. Runs after a feature ships to reduce complexity, catch performance regressions, and eliminate technical debt before it compounds.

**Usage:** `/post-impl` (full audit) or `/post-impl <scope>` where scope is a file path, feature name, `backend`, or `frontend`

---

## MANDATES (Priority Order)

1. **Simplify** — remove complexity that earns no benefit (KISS)
2. **Optimize** — improve performance where it measurably matters
3. **Clean up** — eliminate dead code, stale deps, type gaps, and resilience holes

Arguments: $ARGUMENTS (optional — file path, feature name, `backend`, or `frontend` to scope the analysis)

---

## INTAKE (Serial — do this first)

### Step 1: Load project conventions

```bash
# Project-level instructions
cat CLAUDE.md 2>/dev/null || true

# Design guide (UI patterns, component conventions, theme tokens)
cat docs/DESIGN-GUIDE.md 2>/dev/null || true
```

Read both files fully. These define what is intentional and what is accidental complexity. Do NOT flag patterns documented in CLAUDE.md or DESIGN-GUIDE.md as simplification targets.

### Step 2: Map recent changes

```bash
# Recent commits and files touched
git log --oneline --since="14 days ago" --name-only

# Summary of change volume by directory
git log --since="14 days ago" --name-only --pretty=format: | sort | uniq -c | sort -rn | head -30

# Any recent refactors or cleanups already done
git log --oneline --since="14 days ago" --grep="refactor\|cleanup\|simplify\|fix:" | head -20
```

This establishes the change surface. Concentrate the audit on recently-touched files — that is where fresh debt accumulates.

### Step 3: Determine scope

If `$ARGUMENTS` is set:
- **File path** (e.g., `backend/app/modules/catalog/datasets/`) — restrict ALL subagents to files under that path
- **Feature name** (e.g., `raster-mosaic`) — use `git log --all --oneline --grep="<name>"` to identify relevant files, then restrict to those
- **`backend`** — restrict to `backend/app/` and `backend/tests/`
- **`frontend`** — restrict to `frontend/src/`
- **Empty / full** — audit everything

Record the resolved scope. Every subagent must respect it.

### Step 4: Establish green baseline

Run the full test suite BEFORE making any changes. A green baseline is mandatory.

```bash
# Backend tests
cd backend && python -m pytest -q --tb=short 2>&1 | tail -20

# Frontend tests
cd frontend && npx vitest run 2>&1 | tail -20
```

**If any suite is red — STOP.** Report failures. Do not proceed until baseline is green. Existing failures are not part of this audit — they belong to whoever broke them.

Record the pass counts for the delivery report.

### Step 5: Run static analysis baseline

```bash
# Backend lint + type check
cd backend && ruff check app/ --statistics 2>&1 | tail -20
cd backend && mypy app/ --ignore-missing-imports --no-error-summary 2>&1 | tail -30

# Frontend lint + type check
cd frontend && npx eslint src/ --format compact 2>&1 | tail -20
cd frontend && npx tsc --noEmit 2>&1 | tail -20
```

Record counts. These are the "before" numbers for the delivery report.

---

## SUBAGENT DISPATCH (Parallel — 5 subagents)

Run these 5 subagents in parallel using the Task tool. Do NOT wait for one to finish before starting the next. Collect all 5 results before proceeding to SYNTHESIS.

Each subagent must:
1. Respect the scope from INTAKE Step 3
2. Produce a numbered list of findings with `file:line` references
3. Label each finding with its category tag
4. Include evidence (code snippet, grep output, or metric) for every finding

---

### Subagent 1: KISS & Simplification

**Goal:** Find code that is more complex than it needs to be. Every line of code is a liability — fewer lines, fewer bugs.

**Process:**

1. **Long functions (>40 lines):**
   ```bash
   # Python functions — find definitions and count lines to next def/class
   grep -rn "def " backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test

   # React components — find component definitions
   grep -rn "function \|const .* = (" frontend/src/ --include="*.tsx" --include="*.ts" | grep -v node_modules | grep -v ".test." | grep -v ".spec."
   ```
   For each long function, determine:
   - Can it be split into two functions with clear single responsibilities?
   - Does it mix levels of abstraction (HTTP handling + business logic + DB queries)?
   - Are there repeated blocks that could be extracted?

2. **Deep nesting (>3 levels):**
   ```bash
   # Python — look for triple+ indentation
   grep -rn "^                " backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | head -30

   # TypeScript — nested ternaries, nested callbacks
   grep -rn "? .* ? \|\.then.*\.then\|if.*{.*if.*{" frontend/src/ --include="*.tsx" --include="*.ts" | grep -v node_modules | head -30
   ```
   Prefer early returns, guard clauses, and extraction over deep nesting.

3. **Single-callsite abstractions:**
   ```bash
   # Find all function/component definitions, then check how many times each is referenced
   # Python
   grep -rn "^def \|^async def " backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test

   # For each function name, count references
   # (Do this selectively for functions in recently-changed files)
   ```
   If a function/component is defined in one file and used exactly once — inline it unless:
   - It is a public API (route handler, exported hook)
   - It improves readability at the call site by hiding genuine complexity
   - It is a test helper

4. **Wrapper functions with no logic:**
   ```bash
   # Python — functions that just call another function and return
   grep -rn "return " backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test

   # Look for patterns like: def foo(x): return bar(x)
   ```
   Remove wrappers that add no validation, transformation, or error handling.

5. **Unnecessary state:**
   ```bash
   # React useState that could be derived
   grep -rn "useState" frontend/src/ --include="*.tsx" --include="*.ts" | grep -v node_modules | grep -v ".test." | head -30

   # Zustand stores — check for state that duplicates other state
   find frontend/src -name "*store*" -o -name "*Store*" | head -10
   ```
   State that can be computed from other state or from props should be a derived value (`useMemo`, computed property), not a separate `useState`.

6. **React effects with too many responsibilities:**
   ```bash
   # Find useEffect calls and inspect their dependency arrays
   find frontend/src -name "*.tsx" -o -name "*.ts" | xargs grep -l "useEffect" 2>/dev/null | grep -v node_modules | grep -v ".test." | head -20
   ```
   For each file with useEffect:
   - Read the effect bodies. Does one effect do multiple unrelated things?
   - Are there effects that could be replaced with event handlers?
   - Are there effects that synchronize state that should be derived?
   - Do dependency arrays have 4+ items? (likely doing too much)

7. **FastAPI route handlers with business logic:**
   ```bash
   # Find route handlers
   grep -rn "@router\.\(get\|post\|put\|patch\|delete\)" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test
   ```
   Route handlers should:
   - Parse request → call service → return response
   - NOT contain loops, conditionals on business rules, or direct DB queries
   - Business logic belongs in `service.py` files

8. **Over-parameterized functions (5+ params):**
   ```bash
   # Python
   grep -rn "def .*,.*,.*,.*,.*," backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | head -20

   # TypeScript
   grep -rn "function.*,.*,.*,.*,.*,\|=> {" frontend/src/ --include="*.tsx" --include="*.ts" | grep -v node_modules | head -20
   ```
   Consider: options object, splitting into smaller functions, or whether some params are always the same value.

9. **Props drilling 3+ levels:**
   ```bash
   # Find components that pass many props to children
   grep -rn "props\.\|{.*,.*,.*,.*}" frontend/src/ --include="*.tsx" | grep -v node_modules | grep -v ".test." | head -20
   ```
   If the same prop passes through 3+ component layers, consider context, composition, or co-location.

10. **Reimplemented standard library features:**
    ```bash
    # Custom implementations that React/FastAPI/Pydantic already handle
    grep -rn "debounce\|throttle\|deepEqual\|deepClone\|isEqual\|merge(" frontend/src/ --include="*.ts" --include="*.tsx" | grep -v node_modules | head -10

    # Python — custom retry, custom JSON parsing, custom validation
    grep -rn "retry\|json\.loads\|json\.dumps\|validate" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | head -20
    ```
    Use Context7 to verify whether a standard solution exists before flagging.

**Output:** Numbered findings, each with `[KISS]` label, `file:line`, and one-sentence rationale.

---

### Subagent 2: Performance

**Goal:** Find performance problems that affect user experience or server cost. Do not optimize cold paths.

**Process:**

1. **React re-renders:**
   ```bash
   # Components that receive new object/array literals as props
   grep -rn "={{" frontend/src/ --include="*.tsx" | grep -v node_modules | grep -v ".test." | head -20

   # Inline arrow functions in JSX (creates new reference every render)
   grep -rn "onClick={() =>\|onChange={() =>\|onSubmit={() =>" frontend/src/ --include="*.tsx" | grep -v node_modules | head -20

   # Missing memo on expensive components
   grep -rn "export default function\|export function\|export const" frontend/src/ --include="*.tsx" | grep -v node_modules | grep -v ".test." | head -30
   ```
   Focus on:
   - Components in lists (rendered N times) — these benefit most from `React.memo`
   - Components that receive map/GIS data as props — large objects cause expensive diffing
   - `useMemo`/`useCallback` usage: only flag MISSING memoization on genuinely expensive computations (>1ms), not micro-optimizations

2. **Bundle size:**
   ```bash
   # Check for barrel imports that defeat tree-shaking
   grep -rn "from ['\"]lodash['\"]" frontend/src/ --include="*.ts" --include="*.tsx" | grep -v node_modules | head -10
   grep -rn "import \* as" frontend/src/ --include="*.ts" --include="*.tsx" | grep -v node_modules | head -10

   # Large dependencies imported in hot paths
   grep -rn "import.*from ['\"]@turf\|import.*from ['\"]d3\|import.*from ['\"]moment\|import.*from ['\"]date-fns" frontend/src/ --include="*.ts" --include="*.tsx" | grep -v node_modules | head -10

   # Dynamic imports — are they used for large, rarely-needed modules?
   grep -rn "React.lazy\|import(" frontend/src/ --include="*.tsx" --include="*.ts" | grep -v node_modules | head -10

   # Build output (if available)
   cd frontend && npx vite build 2>&1 | grep -E "dist/|\.js|\.css" | tail -20
   ```

3. **N+1 query patterns:**
   ```bash
   # Python — await inside loops (classic N+1)
   grep -rn "for.*:" backend/app/ --include="*.py" -A 5 | grep -B 5 "await.*session\|await.*db\|\.execute\|\.scalars" | grep -v __pycache__ | grep -v test | head -40

   # Eager loading — are relationships loaded with joinedload/selectinload?
   grep -rn "selectinload\|joinedload\|subqueryload\|lazyload\|lazy=" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | head -20

   # Relationship definitions without explicit loading strategy
   grep -rn "relationship(" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | head -20
   ```
   For each N+1 candidate: is it inside a request handler that returns a list? If so, it multiplies by the number of items.

4. **Missing pagination:**
   ```bash
   # List endpoints that return all rows
   grep -rn "\.all()\|\.scalars()\.all()\|select(" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | grep -v "limit\|offset\|paginate" | head -20

   # Route handlers returning lists
   grep -rn "response_model=list\|List\[" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | head -20
   ```
   Every list endpoint that could return >100 rows must have pagination (limit/offset or cursor).

5. **PostGIS query performance:**
   ```bash
   # Spatial queries in the codebase
   grep -rn "ST_Intersects\|ST_Contains\|ST_Within\|ST_DWithin\|ST_Distance\|ST_Transform\|ST_Buffer\|ST_Area\|ST_AsGeoJSON\|ST_SetSRID\|ST_MakeValid\|ST_Simplify" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | head -30

   # Are spatial queries using indexes? (check for && bbox operator or ST_DWithin)
   # ST_Intersects without && hint can cause full table scans
   grep -rn "ST_Intersects\|ST_Contains\|ST_Within" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | head -20
   ```
   For spatial queries on large tables:
   - Verify GiST index exists on the geometry column
   - `ST_DWithin` is index-friendly, `ST_Distance < N` is NOT
   - `ST_Transform` inside a WHERE clause defeats index usage — transform the query geometry instead
   - `ST_Simplify` on tile-serving paths reduces payload size

6. **pgvector index parameters:**
   ```bash
   # Vector similarity searches
   grep -rn "cosine_distance\|l2_distance\|<->\|<=>\|<#>\|order_by.*embedding\|nearest" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | head -20

   # HNSW/IVFFlat index configuration
   grep -rn "hnsw\|ivfflat\|ef_construction\|lists\|probes\|ef_search" backend/app/ --include="*.py" | grep -v __pycache__ | head -10
   find . -path "*/alembic/versions/*.py" -exec grep -l "hnsw\|ivfflat" {} 2>/dev/null \;
   ```
   Check:
   - Is `ef_search` set at query time for HNSW? (default 40 may be too low for recall-sensitive queries)
   - Is `probes` set for IVFFlat? (default 1 gives poor recall)
   - Do index dimensions match query dimensions?

7. **TanStack Query configuration:**
   ```bash
   # Check staleTime, cacheTime, refetchOnWindowFocus settings
   grep -rn "useQuery\|useMutation\|useInfiniteQuery\|queryOptions\|staleTime\|gcTime\|refetchOnWindowFocus\|refetchInterval" frontend/src/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v ".test." | head -30
   ```
   Common issues:
   - Default `staleTime: 0` causes unnecessary refetches on every mount
   - Missing `gcTime` on expensive queries (map tiles, large GeoJSON)
   - `refetchOnWindowFocus` left on for data that rarely changes (settings, basemaps)

8. **Docker layer ordering:**
   ```bash
   # Read Dockerfiles
   find . -name "Dockerfile*" -not -path "*/node_modules/*" | head -10
   ```
   For each Dockerfile:
   - Does `COPY requirements.txt` / `COPY package.json` come BEFORE `COPY . .`?
   - Are dev dependencies excluded from production images?
   - Is `.dockerignore` present and comprehensive?
   - Are multi-stage builds used where appropriate?

9. **Frontend data loading waterfalls:**
   ```bash
   # Nested queries that could be parallelized
   grep -rn "useQuery" frontend/src/ --include="*.tsx" --include="*.ts" | grep -v node_modules | grep -v ".test."
   ```
   Check for components that make 2+ sequential queries where the second does NOT depend on the first result — these should use `useQueries` or parallel fetching.

10. **Large payload serialization:**
    ```bash
    # Response models that include geometry/GeoJSON in list endpoints
    grep -rn "response_model\|ResponseModel" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | head -20

    # Are there list endpoints that serialize full geometry?
    grep -rn "geom\|geometry\|geojson" backend/app/ --include="*.py" | grep -i "schema\|response\|model" | grep -v __pycache__ | grep -v test | head -20
    ```
    List endpoints should NOT return full geometry — use simplified geometry or omit it entirely. Full geometry should only be on detail endpoints.

**Output:** Numbered findings, each with `[PERF]` label, `file:line`, and evidence (metric, query plan, or bundle size).

---

### Subagent 3: Cleanup & Dead Code

**Goal:** Remove code that serves no purpose. Every dead line is a distraction and a maintenance burden.

**Process:**

1. **Unused imports (automated):**
   ```bash
   # Backend — ruff catches unused imports (F401) and unused variables (F841)
   cd backend && ruff check app/ --select F401,F841 2>&1 | head -40

   # Frontend — eslint catches unused vars
   cd frontend && npx eslint src/ --rule '{"@typescript-eslint/no-unused-vars": "error"}' --format compact 2>&1 | head -40
   ```

2. **Dead functions and components:**
   ```bash
   # Python — exported functions that are never imported elsewhere
   grep -rn "^def \|^async def " backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | grep -v "__"

   # For each function name found, check if it's referenced anywhere else
   # (Do this selectively for recently-changed files)

   # React — exported components that are never imported
   grep -rn "export function\|export const\|export default" frontend/src/ --include="*.tsx" --include="*.ts" | grep -v node_modules | grep -v ".test." | grep -v ".spec." | grep -v "index.ts"
   ```
   For each candidate, verify it is not:
   - A route handler (called by FastAPI, not by your code)
   - An exported hook used by consumers
   - A component registered in routes/lazy imports

3. **Dead routes:**
   ```bash
   # All registered routes
   grep -rn "@router\.\(get\|post\|put\|patch\|delete\)" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test

   # Cross-reference with frontend API calls
   grep -rn "apiFetch\|fetch(\|axios\.\|api\." frontend/src/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v ".test." | head -40
   ```
   Dead routes: registered in backend but never called from frontend or tests. Be careful — some routes are consumed by external clients (OGC, Titiler, share links).

4. **Console/print artifacts:**
   ```bash
   # Python debug prints
   grep -rn "print(" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | grep -v "# noqa" | head -20

   # Python debugger artifacts
   grep -rn "pdb\|breakpoint()\|ipdb\|pudb" backend/app/ --include="*.py" | grep -v __pycache__ | head -10

   # Frontend console statements
   grep -rn "console\.\(log\|debug\|info\|warn\|error\)" frontend/src/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v ".test." | head -30
   ```
   Allow `console.error` in error boundaries and catch blocks. Remove everything else.

5. **TODO/FIXME/HACK comments:**
   ```bash
   # All TODO/FIXME/HACK/XXX comments
   grep -rn "TODO\|FIXME\|HACK\|XXX\|TEMP\|TEMPORARY" backend/app/ frontend/src/ --include="*.py" --include="*.ts" --include="*.tsx" | grep -v __pycache__ | grep -v node_modules | grep -v ".test." | head -30
   ```
   For each:
   - Is the TODO still relevant? If so, convert to a tracked issue.
   - Is the TODO done? Remove the comment.
   - Is the FIXME a known bug? Flag it.

6. **Unused environment variables:**
   ```bash
   # Env vars defined in docker-compose.yml
   grep -rn "environment:" docker-compose*.yml -A 50 | grep -E "^\s+- \w+=" | head -30

   # Env vars defined in .env files
   cat .env .env.example .env.local 2>/dev/null | grep -v "^#" | grep "=" | head -30

   # Cross-reference with backend config
   grep -rn "os\.environ\|os\.getenv\|env(" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | head -20

   # Cross-reference with frontend env
   grep -rn "import\.meta\.env\|VITE_" frontend/src/ --include="*.ts" --include="*.tsx" | grep -v node_modules | head -20
   ```

7. **Unused dependencies:**
   ```bash
   # Backend — look for requirements.txt entries not imported
   cat backend/requirements*.txt 2>/dev/null | grep -v "^#" | grep -v "^$" | head -40

   # Frontend — look for package.json deps not imported
   cat frontend/package.json 2>/dev/null | grep -E '^\s+"[^@]' | head -40
   ```
   For each dependency, check if any source file imports it. Be careful with:
   - Transitive dependencies (imported by other deps, not directly)
   - CLI tools (ruff, mypy, eslint — used in scripts, not imported)
   - Plugins (Vite plugins, pytest plugins — loaded by config, not imported)

8. **Duplicate logic:**
   ```bash
   # Similar function names across files
   grep -rn "def format_\|def parse_\|def validate_\|def transform_\|def convert_" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | head -20

   # Similar utility functions in frontend
   grep -rn "export function\|export const" frontend/src/lib/ --include="*.ts" --include="*.tsx" 2>/dev/null | head -20
   grep -rn "export function\|export const" frontend/src/utils/ --include="*.ts" --include="*.tsx" 2>/dev/null | head -20
   ```
   If two functions do the same thing in different files, extract to a shared utility.

9. **Stale feature flags:**
   ```bash
   # Feature flag usage
   grep -rn "feature_toggle\|feature_flag\|isEnabled\|is_enabled\|FEATURE_" backend/app/ frontend/src/ --include="*.py" --include="*.ts" --include="*.tsx" | grep -v __pycache__ | grep -v node_modules | grep -v ".test." | head -20
   ```
   Flags that are 100% rolled out: remove the flag and keep only the winning code path.

10. **Inconsistent naming:**
    ```bash
    # Python files using camelCase
    grep -rn "def [a-z][a-zA-Z]*[A-Z]" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | head -10

    # TypeScript files using snake_case
    grep -rn "const [a-z]+_[a-z]" frontend/src/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v ".test." | head -10
    ```
    Python = snake_case. TypeScript = camelCase. API response fields may bridge both — that is acceptable.

**Output:** Numbered findings, each with `[CLEANUP]` label, `file:line`, and one-sentence rationale.

---

### Subagent 4: Type Safety

**Goal:** Close type gaps that allow runtime errors to reach users. Strong types are free documentation and free bug prevention.

**Process:**

1. **mypy strictness:**
   ```bash
   # Run mypy with strict mode to see what's missing
   cd backend && mypy app/ --strict --ignore-missing-imports 2>&1 | head -60

   # Check mypy config
   cat backend/mypy.ini backend/pyproject.toml 2>/dev/null | grep -A 20 "\[mypy\]\|\[tool.mypy\]"
   ```
   Focus on:
   - Missing return type annotations on public functions (route handlers, service functions)
   - Missing parameter type annotations on public functions
   - `Any` return types that could be specific
   - Functions that return `None` implicitly but should be explicit

2. **Missing type annotations on public functions:**
   ```bash
   # Python — public functions without return types
   grep -rn "^def \|^async def " backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | grep -v "-> "

   # Python — functions with untyped parameters
   grep -rn "def .*(self,\|cls,\|\*\*kwargs\|\*args)" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | head -20
   ```
   Every public function should have typed parameters and a return type. Private functions (prefixed with `_`) are lower priority.

3. **`as any` and type assertions in frontend:**
   ```bash
   # TypeScript — unsafe casts
   grep -rn "as any\|as unknown\|// @ts-ignore\|// @ts-expect-error\|// eslint-disable.*typescript" frontend/src/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v ".test." | head -30

   # Type assertions that could be narrowed
   grep -rn " as [A-Z]" frontend/src/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v ".test." | grep -v "as const" | head -20
   ```
   For each `as any`:
   - Is it working around a library type bug? (check Context7 for updated types)
   - Is it covering up a genuine type mismatch that should be fixed?
   - Can it be replaced with a type guard or generic?

4. **response_model coverage on FastAPI routes:**
   ```bash
   # Routes WITH response_model
   grep -rn "@router\.\(get\|post\|put\|patch\|delete\)" backend/app/ --include="*.py" -A 2 | grep "response_model" | head -20

   # Routes WITHOUT response_model
   grep -rn "@router\.\(get\|post\|put\|patch\|delete\)" backend/app/ --include="*.py" -A 2 | grep -v "response_model" | grep "@router\." | head -20
   ```
   Every route that returns data MUST have a `response_model`. This ensures:
   - Automatic response validation
   - OpenAPI schema accuracy
   - No accidental data leakage (e.g., hashed passwords in user objects)

5. **Frontend-backend type alignment:**
   ```bash
   # Backend Pydantic schemas
   find backend/app -name "schemas.py" -o -name "schema.py" | head -20

   # Frontend TypeScript types/interfaces for API responses
   find frontend/src -name "types.ts" -o -name "types.tsx" -o -name "*.types.ts" | head -20
   grep -rn "interface \|type " frontend/src/api/ --include="*.ts" --include="*.tsx" | head -20
   ```
   For each API endpoint, verify:
   - The frontend type matches the backend schema field-for-field
   - Field names match (accounting for camelCase↔snake_case conversion if configured)
   - Nullable fields are marked optional in the frontend type
   - Enum values match between frontend and backend

6. **Pydantic model completeness:**
   ```bash
   # Models without validators where they should have them
   grep -rn "class.*BaseModel\|class.*Schema" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | head -20

   # Fields that should have constraints (positive integers, bounded strings, valid URLs)
   grep -rn "Field(\|Optional\[" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | head -20
   ```
   Check:
   - String fields with no `max_length` on user input
   - Integer fields with no bounds on user input
   - URL fields not using `HttpUrl` type
   - Datetime fields not using `datetime` type (using `str` instead)

7. **SQLAlchemy model type alignment with Pydantic schemas:**
   ```bash
   # SQLAlchemy models
   find backend/app -name "models.py" -o -name "model.py" | head -20

   # Compare column types with schema field types
   grep -rn "Column\|mapped_column\|Mapped\[" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | grep -v alembic | head -30
   ```
   Verify:
   - SQLAlchemy `String(255)` matches Pydantic `str` with `max_length=255`
   - SQLAlchemy `nullable=True` matches Pydantic `Optional[...]`
   - SQLAlchemy `Enum` matches Pydantic `Literal[...]` or Python `enum.Enum`

8. **Generic error responses:**
   ```bash
   # Untyped error responses
   grep -rn "HTTPException\|raise.*Exception\|JSONResponse" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | head -20
   ```
   Are error responses consistent? Do they use a standard error schema? Are HTTP status codes correct (not everything is 400)?

**Output:** Numbered findings, each with `[TYPE]` label, `file:line`, evidence, and recommended fix.

---

### Subagent 5: Error Handling & Resilience

**Goal:** Find crash paths, missing error boundaries, and unhandled failure modes. Users should never see a raw stack trace or a blank white screen.

**Process:**

1. **Unhandled route exceptions:**
   ```bash
   # Route handlers without try/except or HTTPException
   grep -rn "@router\.\(get\|post\|put\|patch\|delete\)" backend/app/ --include="*.py" -A 20 | grep -v __pycache__ | grep -v test | head -60

   # Global exception handlers
   grep -rn "exception_handler\|ExceptionMiddleware\|@app.exception" backend/app/ --include="*.py" | grep -v __pycache__ | head -10
   ```
   Check:
   - Do route handlers catch service-layer exceptions and translate them to HTTP errors?
   - Is there a global exception handler for unexpected errors?
   - Are 500 errors logged with enough context to debug?
   - Does the global handler avoid leaking internal details in production?

2. **Missing React error boundaries:**
   ```bash
   # Error boundary components
   grep -rn "ErrorBoundary\|errorElement\|error.*boundary" frontend/src/ --include="*.tsx" --include="*.ts" | grep -v node_modules | grep -v ".test." | head -20

   # Route definitions — do they have errorElement?
   grep -rn "createBrowserRouter\|createRoutesFromElements\|RouterProvider\|Route " frontend/src/ --include="*.tsx" | grep -v node_modules | head -10

   # Components that access external data without error boundaries above them
   grep -rn "useQuery\|useSuspenseQuery" frontend/src/ --include="*.tsx" | grep -v node_modules | grep -v ".test." | head -20
   ```
   Every route should have an error boundary. Components that fetch data need error boundaries above them in the tree.

3. **Missing loading/error states in TanStack Query:**
   ```bash
   # Find components using useQuery
   grep -rn "useQuery\|useInfiniteQuery" frontend/src/ --include="*.tsx" | grep -v node_modules | grep -v ".test."
   ```
   For each component using `useQuery`:
   - Does it handle `isLoading`? (should show skeleton/spinner)
   - Does it handle `isError`? (should show error message with retry)
   - Does it handle `data` being `undefined`? (should not crash)
   - Does it use `isPending` vs `isLoading` correctly? (TanStack Query v5)

4. **Retry logic for external services:**
   ```bash
   # Titiler calls
   grep -rn "titiler\|tiler\|cog\|raster" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | head -20

   # LLM/embedding calls
   grep -rn "openai\|anthropic\|embedding\|llm\|generate\|chat\.completion\|encode" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | head -20

   # External HTTP calls
   grep -rn "httpx\|aiohttp\|requests\.\|urllib" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | head -20
   ```
   External service calls should have:
   - Timeout configuration (not infinite)
   - Retry with exponential backoff for transient failures
   - Circuit breaker pattern for repeatedly failing services
   - Graceful degradation (serve stale data, disable feature, show message)

5. **Graceful degradation patterns:**
   ```bash
   # Frontend — features that depend on optional services
   grep -rn "titiler\|embed\|llm\|semantic\|vector\|search" frontend/src/ --include="*.tsx" --include="*.ts" | grep -v node_modules | grep -v ".test." | head -20

   # Backend — optional feature checks
   grep -rn "feature.*toggle\|feature.*flag\|is_available\|try.*import\|optional" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | head -20
   ```
   When an optional service (Titiler, LLM, pgvector) is unavailable:
   - Does the UI degrade gracefully? (hide feature, show message)
   - Does the backend return a meaningful error? (not 500)
   - Are there health checks for optional services?

6. **Database connection resilience:**
   ```bash
   # Session management
   grep -rn "get_session\|async_session\|AsyncSession\|SessionLocal\|get_db" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | head -20

   # Connection pool configuration
   grep -rn "pool_size\|max_overflow\|pool_recycle\|pool_timeout\|pool_pre_ping" backend/app/ --include="*.py" | grep -v __pycache__ | head -10
   ```
   Check:
   - Is `pool_pre_ping` enabled? (detects stale connections)
   - Is `pool_recycle` set? (prevents connection timeout on long-lived pools)
   - Are sessions properly closed in error paths? (use `async with`)
   - Is there a health check endpoint that tests DB connectivity?

7. **File upload error handling:**
   ```bash
   # File upload endpoints
   grep -rn "UploadFile\|File(\|multipart\|form.*data" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | head -20
   ```
   Check:
   - File size limits enforced?
   - File type validation (not just extension — check magic bytes)?
   - Cleanup on failure (temp files deleted)?
   - Disk space checks?

8. **Frontend form validation:**
   ```bash
   # Form components
   grep -rn "useForm\|onSubmit\|handleSubmit\|form.*action" frontend/src/ --include="*.tsx" | grep -v node_modules | grep -v ".test." | head -20

   # Validation schemas
   grep -rn "zod\|yup\|joi\|validate\|schema" frontend/src/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v ".test." | head -20
   ```
   Forms should validate client-side AND server-side. Check:
   - Are required fields enforced before submission?
   - Are error messages shown next to the field that failed?
   - Is the submit button disabled during submission? (prevent double-submit)
   - Does form state survive a failed submission? (don't clear the form)

9. **Map error handling:**
   ```bash
   # MapLibre error handling
   grep -rn "map\.on.*error\|mapError\|onError\|onerror\|mapRef.*error" frontend/src/ --include="*.tsx" --include="*.ts" | grep -v node_modules | grep -v ".test." | head -10

   # Tile loading errors
   grep -rn "source.*error\|tile.*error\|load.*error" frontend/src/ --include="*.tsx" --include="*.ts" | grep -v node_modules | grep -v ".test." | head -10
   ```
   Map components should:
   - Handle tile source failures (show message, not blank map)
   - Handle WebGL context loss
   - Handle invalid GeoJSON gracefully (don't crash the entire app)
   - Show appropriate messages when no data matches filters

10. **Logging adequacy:**
    ```bash
    # Python logging
    grep -rn "logger\.\|logging\." backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | head -20

    # Are errors logged with context?
    grep -rn "logger\.error\|logger\.exception\|logger\.warning" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | head -20
    ```
    Check:
    - Are exceptions logged with `logger.exception()` (includes traceback) or just `logger.error()`?
    - Is there enough context to debug? (request ID, user ID, dataset ID)
    - Are sensitive values excluded from logs? (passwords, tokens, API keys)

**Output:** Numbered findings, each with `[RESILIENCE]` label, `file:line`, severity (crash/degraded/cosmetic), and recommended fix.

---

## SYNTHESIS (Serial — after all subagents complete)

### Scoring

| Dimension | Weight | What it measures |
|-----------|--------|-----------------|
| **KISS & Simplification** | 25% | Code complexity, abstraction quality, function size, nesting depth |
| **Performance** | 25% | Re-renders, N+1 queries, pagination, spatial index usage, bundle size |
| **Cleanup & Dead Code** | 20% | Unused code, stale deps, debug artifacts, naming consistency |
| **Type Safety** | 15% | Type coverage, response_model usage, frontend-backend alignment |
| **Error Handling & Resilience** | 15% | Error boundaries, loading states, retry logic, graceful degradation |

Grade each dimension A-F using:
- **A** — No issues. Clean, well-structured code. Ship with confidence.
- **B** — Minor issues. Style nits, small optimization opportunities. No user impact.
- **C** — Significant issues. Missing error handling, type gaps, dead code accumulation. Users may hit edge cases.
- **D** — Dangerous issues. N+1 queries on hot paths, missing error boundaries on critical routes, crash paths. Users will hit these.
- **F** — Broken. Crashes on common paths, data leaks, unusable performance.

**Overall health** = weighted average of dimension grades (A=4, B=3, C=2, D=1, F=0), converted back to letter grade:
- 3.5-4.0 = A
- 2.5-3.49 = B
- 1.5-2.49 = C
- 0.5-1.49 = D
- 0.0-0.49 = F

### Action Items Table

| Priority | Finding | File:line | Fix | Effort |
|----------|---------|-----------|-----|--------|
| P0 | [User-facing crash or data loss] | path/file.py:42 | [Specific fix description] | 15m |
| P1 | [Performance regression or type gap on hot path] | path/file.tsx:88 | [Specific fix description] | 30m |
| P2 | [Code quality / maintainability] | path/file.py:15 | [Specific fix description] | 10m |
| P3 | [Cosmetic / nice-to-have] | path/file.ts:7 | [Specific fix description] | 5m |

**Priority definitions:**
- **P0** — User-facing crash, data loss, security leak. Fix immediately.
- **P1** — Performance regression on hot path, missing error handling on critical route, type gap that allows bad data through. Fix before next release.
- **P2** — Dead code, unnecessary complexity, missing types on cold paths. Fix when convenient.
- **P3** — Naming, style, minor optimization on cold paths. Fix only after P0-P2 are clean.

Sort by priority, then by effort (smallest first within priority).

### Debt Summary

Summarize total technical debt:
- Total findings by dimension
- P0 + P1 count (must-fix)
- P2 + P3 count (should-fix)
- Estimated total effort for P0 + P1 items
- Comparison to prior audit (if one exists in `docs-internal/audits/`)

---

## DELIVERY

### Output file

Write the report to: `docs-internal/audits/post-impl-{YYYYMMDD}.md`

### Report structure

```markdown
# Post-Implementation Audit — {YYYY-MM-DD}

## Scorecard

| Dimension | Grade | Findings | P0 | P1 | P2 | P3 |
|-----------|-------|----------|----|----|----|----|
| KISS & Simplification | | | | | | |
| Performance | | | | | | |
| Cleanup & Dead Code | | | | | | |
| Type Safety | | | | | | |
| Error Handling & Resilience | | | | | | |
| **Overall** | | | | | | |

## Executive Summary
<!-- 3-5 sentences: scope, biggest risks, top recommendation -->

## Scope
<!-- What was audited: full repo / backend / frontend / specific feature -->
<!-- Recent changes analyzed (git log summary) -->
<!-- Test baseline: X backend pass, Y frontend pass -->

## 1. KISS & Simplification
### Findings
<!-- Subagent 1 findings with evidence -->
### Recommendations
<!-- Top 3 simplification opportunities -->

## 2. Performance
### Findings
<!-- Subagent 2 findings with evidence -->
### Recommendations
<!-- Top 3 performance improvements -->

## 3. Cleanup & Dead Code
### Findings
<!-- Subagent 3 findings with evidence -->
### Recommendations
<!-- Top 3 cleanup actions -->

## 4. Type Safety
### Findings
<!-- Subagent 4 findings with evidence -->
### Recommendations
<!-- Top 3 type safety improvements -->

## 5. Error Handling & Resilience
### Findings
<!-- Subagent 5 findings with evidence -->
### Recommendations
<!-- Top 3 resilience improvements -->

## 6. Prioritized Action Items
<!-- Full action items table from synthesis -->

## 7. Debt Summary
<!-- Aggregate metrics and comparison to prior audit -->

## 8. Static Analysis Baseline
<!-- Before/after lint and type check counts -->

## 9. Explicitly NOT Flagged
<!-- Items reviewed and intentionally excluded, with rationale -->
```

### Post-delivery

1. If a previous `docs-internal/audits/post-impl-*.md` exists, diff the findings and note improvements/regressions.
2. Print one-line summary: `Post-impl audit: [GRADE] overall | [N] P0s | [N] P1s | [N] total findings | Report: docs-internal/audits/post-impl-{YYYYMMDD}.md`

---

## RELATIONSHIP TO OTHER COMMANDS

- **`/perf-profile`** — Deeper performance profiling with live benchmarks, flame graphs, and load testing. `/post-impl` catches perf issues alongside simplification and cleanup; `/perf-profile` goes deep on performance alone.
- **`/ship`** — Runs CI and auto-fixes lint/type errors. `/post-impl` analyzes code quality beyond what linters catch — structural complexity, dead code, resilience gaps.
- **`/design-audit`** — Covers frontend design token conformance, accessibility, and visual consistency. `/post-impl` covers the code behind the UI, not the UI itself.
- **`/test-audit`** — Covers test health, coverage, and quality. `/post-impl` covers whether the *tested code itself* is clean — complementary, not overlapping.
- **`/migration-audit`** — Covers Alembic migration chain integrity, extension safety, and downgrade paths. `/post-impl` may flag migration-adjacent issues (missing indexes on new columns) but defers migration chain analysis to `/migration-audit`.
- **`/dep-audit`** — Covers dependency freshness, security vulnerabilities, and license compliance. `/post-impl` flags unused deps but defers version/security analysis to `/dep-audit`.

---

## WHAT NOT TO FLAG

Avoid false positives on these known patterns:

- **MapLibre imperative code** — `map.addSource()` + `map.addLayer()` is a documented requirement in CLAUDE.md for vector tile sources. The declarative `<Source>/<Layer>` API is known-broken in @vis.gl/react-maplibre v8. Do NOT flag imperative map code as a simplification target.
- **`map.setTransformRequest()` in `onLoad`** — The `transformRequest` prop is silently ignored. The imperative workaround is intentional and documented.
- **Abstractions with genuine multi-site usage** — If a function/component is used in 3+ places, it is a legitimate abstraction, even if each call site only uses a subset of its features.
- **Performance "issues" on cold paths** — Code that runs <1x per request (startup, migration, admin-only routes) is not worth optimizing. Only flag performance issues on hot paths (list endpoints, map tile serving, search).
- **Dead code behind active feature flags** — If a feature flag controls access to code, the code is not dead. Only flag code behind flags that are 100% rolled out.
- **Type annotations on private functions** — Functions prefixed with `_` are internal implementation details. Type annotations are nice-to-have, not required. Focus type audit on public API surfaces.
- **Third-party library idioms** — Before flagging a library usage pattern as non-idiomatic, check Context7. Libraries often have specific patterns (e.g., TanStack Query's `queryKey` arrays, SQLAlchemy's `select()` style) that look odd but are correct.
- **Zustand store patterns** — `getState()` for non-React contexts is documented and intentional. Do not suggest converting to hooks.
- **Trailing-slash patterns** — FastAPI trailing slash handling is documented in CLAUDE.md. The OGC `/collections/datasets` exception is intentional.
- **Inline styles in map/canvas components** — MapLibre and canvas overlays often need inline styles for dynamic positioning. These cannot be Tailwind classes.
- **`console.error` in error boundaries and catch blocks** — Error logging in error-handling code is intentional.
- **`# noqa` and `// eslint-disable` annotations** — These are intentional suppression of known false positives. Only flag if the suppression is no longer needed.
- **Empty downgrades on early migrations** — Defer to `/migration-audit` for migration-specific concerns.
- **GDAL/ogr2ogr subprocess calls** — GDAL Python bindings are unreliable. Subprocess calls are the documented ingestion pattern.

---

## GUARDRAILS — Never do these

- Rewrite working code in a different paradigm without an explicit request
- Change public API response shapes without flagging as a BREAKING CHANGE
- Remove code you don't fully understand — research it with Context7 or grep first
- Introduce new dependencies to simplify something that already works
- Optimize without measurement evidence (no query plan = no index suggestion, no profile = no memo)
- Touch files outside the agreed scope "while you're in there"
- Suggest a library API that Context7 contradicts
- Create new abstractions during a cleanup audit — the goal is to simplify, not to reorganize
- Flag something as dead code if you haven't verified it is unreachable from all entry points (routes, CLI commands, background tasks, external API consumers)
- Conflate "unfamiliar" with "unnecessary" — if you don't understand why code exists, research it before flagging
