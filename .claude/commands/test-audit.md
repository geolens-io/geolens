# /test-audit — Test Health & Coverage Audit

Audit test suite health across the GeoLens backend (pytest) and frontend (vitest): coverage gaps, test quality, flaky tests, missing edge cases, and test infrastructure. GeoLens's spatial + vector + trigram stack has testing challenges that generic tools miss: spatial assertion precision, embedding dimension fixtures, database-dependent test isolation, and MapLibre component testability.

**Usage:** `/test-audit` (full audit) or `/test-audit <scope>` where scope is `backend`, `frontend`, `coverage`, `flaky`, or `quality`

---

## INTAKE (Serial — do this first)

### Step 1: Discover test configuration

```bash
# Backend pytest config
cat backend/pyproject.toml 2>/dev/null | grep -A 30 "\[tool.pytest"
cat backend/pytest.ini 2>/dev/null
cat backend/setup.cfg 2>/dev/null | grep -A 20 "\[tool:pytest\]"

# Frontend vitest config
cat frontend/vitest.config.ts 2>/dev/null || cat frontend/vitest.config.js 2>/dev/null
cat frontend/vite.config.ts 2>/dev/null | grep -A 20 "test"

# Coverage config
cat backend/.coveragerc 2>/dev/null
cat backend/pyproject.toml 2>/dev/null | grep -A 20 "\[tool.coverage"
cat frontend/vitest.config.ts 2>/dev/null | grep -A 10 "coverage"
```

### Step 2: Count tests and get the lay of the land

```bash
# Backend test count
cd backend && python -m pytest --collect-only -q 2>/dev/null | tail -1
cd - 2>/dev/null || true

# Frontend test count
cd frontend && npx vitest run --reporter=verbose 2>/dev/null | tail -5
cd - 2>/dev/null || true

# Test file inventory
find backend/tests -name "test_*.py" -o -name "*_test.py" 2>/dev/null | sort
find frontend/src -name "*.test.ts" -o -name "*.test.tsx" -o -name "*.spec.ts" -o -name "*.spec.tsx" 2>/dev/null | sort
```

### Step 3: Read conftest.py files for fixture patterns

```bash
# All conftest files
find backend/tests -name "conftest.py" 2>/dev/null | while read f; do
  echo "=== $f ==="
  cat "$f"
done

# Frontend test setup
cat frontend/src/test-setup.ts 2>/dev/null || cat frontend/src/setupTests.ts 2>/dev/null
find frontend/src -name "test-utils.*" -o -name "testUtils.*" 2>/dev/null | while read f; do
  echo "=== $f ==="
  cat "$f"
done
```

### Step 4: Check CI test commands

```bash
# GitHub Actions workflows referencing tests
find .github/workflows -name "*.yml" -o -name "*.yaml" 2>/dev/null | while read f; do
  echo "=== $f ==="
  grep -n "pytest\|vitest\|test\|coverage" "$f" 2>/dev/null
done
```

---

## TEST QUALITY RULES (Embedded)

These are the hard rules for test health in a spatial + vector + trigram stack. Violations cause silent test rot.

### Spatial assertion precision

- Never use exact equality for geometry coordinates after transformation — floating point drift is expected
- `pytest.approx()` or a tolerance-based comparison is required for any coordinate assertion
- Comparing geometries by WKT string is fragile — use `ST_Equals` or `shapely.equals_exact(other, tolerance)`
- SRID must be asserted separately from coordinates — a correct shape in the wrong CRS is a silent bug

### Embedding dimension fixtures

- Test fixtures for pgvector columns MUST match the model's declared dimension (e.g., `Vector(1536)`)
- A dimension mismatch between fixture and model produces a database error, not a test failure — this masquerades as a flaky test
- Embedding fixtures should be deterministic (seeded random or hardcoded), not `random.random()`

### Database test isolation

- Tests that mutate database state MUST use transaction rollback or per-test database setup
- Session-scoped fixtures that insert data create order-dependent test coupling
- Tests sharing a database connection without isolation are flaky by construction

### MapLibre component testability

- MapLibre GL JS requires a canvas/WebGL context — `vitest` with `jsdom` cannot provide this natively
- Map components should be tested via: (a) mocking `maplibre-gl`, (b) testing hooks/logic separately from rendering, or (c) using `@testing-library/react` with the map mocked
- Tests that import `maplibre-gl` without mocking will fail in CI with `ReferenceError: WebGLRenderingContext is not defined`

---

## SUBAGENT DISPATCH (Parallel)

Run these 6 subagents in parallel.

### Subagent 1: Coverage Analysis

**Goal:** Map test coverage by module and identify untested code. Find modules with <50% coverage and routes/components with zero test coverage.

**Process:**

1. **Backend coverage:**
   ```bash
   cd backend 2>/dev/null || true
   python -m pytest --cov=app --cov-report=term-missing -q 2>/dev/null | head -100
   cd - 2>/dev/null || true
   ```

   Parse the output to build a coverage map:
   - Group by module (auth, datasets, features, ogc, settings, search, etc.)
   - Flag any module under 50% line coverage
   - Flag any module at 0% (completely untested)

2. **Frontend coverage:**
   ```bash
   cd frontend 2>/dev/null || true
   npx vitest run --coverage 2>/dev/null | head -100
   cd - 2>/dev/null || true
   ```

   Parse the output similarly. Group by directory (api, components, hooks, lib, pages).

3. **Zero-coverage route detection:**
   ```bash
   # Every backend router file
   find backend/app -name "router.py" -o -name "routes.py" 2>/dev/null | while read f; do
     module=$(echo "$f" | sed 's|backend/app/||;s|/router.py||;s|/routes.py||')
     test_file=$(find backend/tests -name "test_${module}*" -o -name "test_*${module}*" 2>/dev/null | head -1)
     if [ -z "$test_file" ]; then
       echo "UNTESTED ROUTER: $f"
     else
       echo "COVERED: $f -> $test_file"
     fi
   done
   ```

4. **Zero-coverage component detection:**
   ```bash
   # Frontend components without co-located tests
   find frontend/src/components -name "*.tsx" ! -name "*.test.*" ! -name "*.spec.*" 2>/dev/null | while read f; do
     test_file="${f%.tsx}.test.tsx"
     spec_file="${f%.tsx}.spec.tsx"
     if [ ! -f "$test_file" ] && [ ! -f "$spec_file" ]; then
       echo "UNTESTED COMPONENT: $f"
     fi
   done
   ```

**Output:** Coverage map — Module | Line coverage % | Branch coverage % | Untested files list.

---

### Subagent 2: Test Quality & Patterns

**Goal:** Identify tests that exist but provide weak signal — they pass but don't actually catch bugs.

**Process:**

1. **Assert-only tests (no arrange/act/assert structure):**
   ```bash
   # Tests with a single assertion and no setup
   find backend/tests -name "test_*.py" 2>/dev/null | while read f; do
     grep -n "def test_" "$f" | while read line; do
       lineno=$(echo "$line" | cut -d: -f1)
       # Get the function body (next 10 lines)
       body=$(sed -n "${lineno},$((lineno+10))p" "$f" | grep -v "def test_\|^$\|^#\|\"\"\"")
       assert_count=$(echo "$body" | grep -c "assert\|assertEqual\|assertIn\|raises\|pytest.raises")
       total_lines=$(echo "$body" | grep -v "^$" | wc -l | tr -d ' ')
       if [ "$assert_count" -le 1 ] && [ "$total_lines" -le 2 ]; then
         echo "THIN TEST: $f:$lineno"
       fi
     done
   done
   ```

2. **Overly broad assertions:**
   ```bash
   # Tests that only check status code without body validation
   grep -rn "assert.*status_code.*200\|assert.*200.*status_code\|assertEqual.*200\|assertEqual.*status_code" backend/tests/ --include="*.py" | while read line; do
     file=$(echo "$line" | cut -d: -f1)
     lineno=$(echo "$line" | cut -d: -f2)
     # Check if there's a body/json assertion within 5 lines
     body_check=$(sed -n "$((lineno+1)),$((lineno+5))p" "$file" | grep -c "json\|data\|content\|body\|response\.\|assert")
     if [ "$body_check" -eq 0 ]; then
       echo "STATUS-ONLY: $line"
     fi
   done
   ```

3. **Missing parametrize opportunities:**
   ```bash
   # Test functions with multiple near-identical test functions
   find backend/tests -name "test_*.py" 2>/dev/null | while read f; do
     # Count tests in the file
     test_count=$(grep -c "def test_" "$f")
     parametrize_count=$(grep -c "@pytest.mark.parametrize\|@parametrize" "$f")
     if [ "$test_count" -gt 10 ] && [ "$parametrize_count" -eq 0 ]; then
       echo "NO PARAMETRIZE ($test_count tests): $f"
     fi
   done
   ```

4. **Tests testing implementation not behavior:**
   ```bash
   # Tests that assert on mock call counts or internal method names
   grep -rn "assert_called_once\|assert_called_with\|call_count\|call_args" backend/tests/ --include="*.py" 2>/dev/null
   grep -rn "toHaveBeenCalled\|toHaveBeenCalledWith\|toHaveBeenCalledTimes" frontend/src/ --include="*.test.*" 2>/dev/null
   ```

5. **Test names that don't describe behavior:**
   ```bash
   # Test names that are just "test_1", "test_foo", or generic
   grep -rn "def test_[0-9]\|def test_it\b\|def test_that\b\|def test_foo\|def test_bar\|def test_basic\b" backend/tests/ --include="*.py" 2>/dev/null
   grep -rn "it\(\"test\|it\(\"should work\|it\(\"works\|test\(\"test\|describe.*test" frontend/src/ --include="*.test.*" 2>/dev/null
   ```

6. **Hardcoded test data that should be fixtures:**
   ```bash
   # Inline geometry WKT/GeoJSON repeated across test files
   grep -rn "POINT\|POLYGON\|LINESTRING\|MultiPolygon\|FeatureCollection" backend/tests/ --include="*.py" | cut -d: -f1 | sort | uniq -c | sort -rn | head -10

   # Inline auth tokens or user data repeated
   grep -rn "Bearer\|admin.*password\|test.*@.*test\|test_user" backend/tests/ --include="*.py" | cut -d: -f1 | sort | uniq -c | sort -rn | head -10
   ```

**Output:** Test quality summary — Pattern | Count | Files affected | Severity (Low/Medium/High).

---

### Subagent 3: Flaky & Slow Test Detection

**Goal:** Identify tests that fail intermittently or are suspiciously slow, with special attention to spatial/database-dependent flakiness.

**Process:**

1. **Slow test detection:**
   ```bash
   cd backend 2>/dev/null || true
   python -m pytest --durations=20 -q 2>/dev/null | head -30
   cd - 2>/dev/null || true
   ```

   - Unit tests >2s are suspicious — likely hitting real database or external service
   - Integration tests >10s should be reviewed for unnecessary setup

2. **Non-deterministic assertions:**
   ```bash
   # Timestamp comparisons (fragile if not frozen)
   grep -rn "datetime.now\|datetime.utcnow\|time.time()\|Date.now()" backend/tests/ frontend/src/ --include="*.py" --include="*.test.*" 2>/dev/null

   # Random values without seeding
   grep -rn "random\.\|Math.random\|uuid4\|uuid.uuid4" backend/tests/ frontend/src/ --include="*.py" --include="*.test.*" 2>/dev/null | grep -v "seed\|deterministic\|fixture"

   # Floating point equality (spatial coordinate comparisons)
   grep -rn "assertEqual.*\.\|assert.*==.*\.\|expect.*toBe.*\." backend/tests/ frontend/src/ --include="*.py" --include="*.test.*" 2>/dev/null | grep -i "coord\|lat\|lng\|lon\|x\|y\|geom\|point"
   ```

3. **Global state and execution order dependence:**
   ```bash
   # Class-level mutable state
   grep -rn "class Test.*:" backend/tests/ --include="*.py" -A 5 2>/dev/null | grep -E "^\s+\w+ = \[|^\s+\w+ = \{|^\s+\w+ = set"

   # Module-level mutable state
   grep -rn "^[A-Z_]* = \[\|^[A-Z_]* = {" backend/tests/ --include="*.py" 2>/dev/null

   # Tests that modify global/module state
   grep -rn "global \|os.environ\[" backend/tests/ --include="*.py" 2>/dev/null
   ```

4. **External service dependencies without mocking:**
   ```bash
   # Titiler calls
   grep -rn "titiler\|tileserver\|/cog/\|/mosaicjson/" backend/tests/ --include="*.py" 2>/dev/null | grep -v "mock\|patch\|monkeypatch\|Mock"

   # LLM/embedding API calls
   grep -rn "openai\|anthropic\|embeddings\|completions\|llm" backend/tests/ --include="*.py" 2>/dev/null | grep -v "mock\|patch\|monkeypatch\|Mock\|fixture"

   # HTTP calls without mocking
   grep -rn "httpx\.\|requests\.\|aiohttp\.\|fetch(" backend/tests/ frontend/src/ --include="*.py" --include="*.test.*" 2>/dev/null | grep -v "mock\|patch\|Mock\|AsyncMock\|vi.mock\|msw\|TestClient\|AsyncClient"
   ```

5. **Sleep-based timing:**
   ```bash
   grep -rn "time.sleep\|asyncio.sleep\|setTimeout\|waitFor.*timeout" backend/tests/ frontend/src/ --include="*.py" --include="*.test.*" 2>/dev/null
   ```

6. **Database ordering assumptions:**
   ```bash
   # Tests asserting on list order without ORDER BY
   grep -rn "assert.*\[0\]\|assert.*\[1\]\|response.json()\[0\]\|data\[0\]" backend/tests/ --include="*.py" 2>/dev/null | grep -v "sort\|order"
   ```

**Output:** Flaky risk inventory — Test | Risk type (timing/ordering/state/external) | Severity | Suggested fix.

---

### Subagent 4: Missing Test Identification

**Goal:** Cross-reference production code with tests to find untested code paths. Focus on spatial, vector, auth, and error handling paths.

**Process:**

1. **Router-to-test mapping:**
   ```bash
   # Every router endpoint
   find backend/app -name "router.py" -o -name "routes.py" 2>/dev/null | while read f; do
     echo "=== $f ==="
     grep -n "@router\.\|@app\." "$f" | grep -E "get|post|put|patch|delete"
   done

   # Every test that hits an endpoint
   grep -rn "client\.\(get\|post\|put\|patch\|delete\)" backend/tests/ --include="*.py" 2>/dev/null | grep -oP '"\K[^"]+' | sort -u
   ```

   Cross-reference to find endpoints with no test.

2. **Service function coverage:**
   ```bash
   # Every public function in service files
   find backend/app -name "service.py" -o -name "services.py" 2>/dev/null | while read f; do
     echo "=== $f ==="
     grep -n "^async def \|^def " "$f" | grep -v "^.*def _"
   done

   # Functions referenced in test files
   grep -rn "from.*service import\|from.*services import" backend/tests/ --include="*.py" 2>/dev/null
   ```

3. **Spatial operation coverage:**
   ```bash
   # Spatial functions used in production code
   grep -rn "ST_Intersects\|ST_DWithin\|ST_Contains\|ST_Transform\|ST_Area\|ST_Distance\|ST_Union\|ST_Buffer\|ST_Centroid\|ST_AsGeoJSON\|ST_GeomFromGeoJSON\|ST_MakeValid\|ST_SetSRID" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v alembic

   # Same functions in test files
   grep -rn "ST_Intersects\|ST_DWithin\|ST_Contains\|ST_Transform\|ST_Area\|ST_Distance\|ST_Union\|ST_Buffer\|ST_Centroid\|ST_AsGeoJSON\|ST_GeomFromGeoJSON" backend/tests/ --include="*.py"
   ```

   For each spatial function in production code, verify a test exercises it with real geometries.

4. **Vector operation coverage:**
   ```bash
   # Embedding/similarity operations in production
   grep -rn "embedding\|similarity\|cosine_distance\|l2_distance\|<->\|<=>" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v alembic

   # Same in tests
   grep -rn "embedding\|similarity\|cosine_distance\|l2_distance\|<->\|<=>" backend/tests/ --include="*.py"
   ```

5. **Auth and permission testing:**
   ```bash
   # Auth decorators/dependencies in routes
   grep -rn "Depends.*auth\|Depends.*current_user\|Depends.*api_key\|require_role\|get_current_user\|permission" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test

   # Auth tests
   grep -rn "unauthorized\|forbidden\|403\|401\|permission\|role\|anonymous\|api_key" backend/tests/ --include="*.py"
   ```

   For each protected endpoint, verify tests exist for: (a) authenticated access, (b) unauthenticated rejection, (c) wrong-role rejection.

6. **Error path testing:**
   ```bash
   # HTTPException raises in production code
   grep -rn "raise HTTPException\|raise.*Error\|raise.*Exception" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v alembic

   # Error status codes tested
   grep -rn "status_code.*400\|status_code.*404\|status_code.*403\|status_code.*422\|status_code.*500\|status_code.*409\|status_code.*429" backend/tests/ --include="*.py"
   ```

   Compare the count of error raises to error assertions. Large gaps indicate missing negative-path tests.

7. **Edge case gaps:**
   ```bash
   # Check for tests with edge case geometries
   grep -rn "GEOMETRYCOLLECTION EMPTY\|POINT EMPTY\|null.*geom\|None.*geom\|empty.*geometry\|antimeridian\|180\|-180\|dateline" backend/tests/ --include="*.py"

   # Check for null/empty embedding tests
   grep -rn "null.*embedding\|None.*embedding\|empty.*vector\|\[\].*embedding\|dimension.*mismatch" backend/tests/ --include="*.py"

   # Check for Unicode edge cases in search
   grep -rn "unicode\|utf-8\|emoji\|CJK\|arabic\|cyrillic\|accented" backend/tests/ --include="*.py"
   ```

**Output:** Missing test inventory — Code path | File:line | Test exists? | Priority (P0=auth/data-loss, P1=core-feature, P2=edge-case).

---

### Subagent 5: Test Infrastructure Health

**Goal:** Audit the scaffolding that makes tests reliable — fixtures, isolation, factories, CI alignment.

**Process:**

1. **conftest.py organization:**
   ```bash
   # conftest hierarchy
   find backend/tests -name "conftest.py" 2>/dev/null | while read f; do
     echo "=== $f ==="
     grep -n "^@pytest.fixture\|^def \|^async def " "$f"
   done

   # Fixture count per conftest
   find backend/tests -name "conftest.py" 2>/dev/null | while read f; do
     count=$(grep -c "@pytest.fixture" "$f")
     echo "$count fixtures: $f"
   done
   ```

   - Is the root conftest overloaded (>20 fixtures)?
   - Are module-specific fixtures in module-level conftest files?
   - Are there fixture name collisions between conftest levels?

2. **Fixture scope analysis:**
   ```bash
   # Session-scoped fixtures (shared across all tests — expensive but risky for isolation)
   grep -rn "@pytest.fixture.*scope.*session\|@pytest.fixture.*scope.*module" backend/tests/ --include="*.py" 2>/dev/null

   # Function-scoped fixtures (default, safest for isolation)
   grep -rn "@pytest.fixture" backend/tests/ --include="*.py" 2>/dev/null | grep -v "scope"
   ```

   - Session-scoped database fixtures are efficient but create coupling
   - Are expensive fixtures (DB connections, test data) session-scoped?
   - Are cheap fixtures (request builders, test objects) function-scoped?

3. **Database isolation strategy:**
   ```bash
   # Transaction rollback pattern
   grep -rn "rollback\|savepoint\|begin_nested\|transaction" backend/tests/ --include="*.py" 2>/dev/null

   # Database cleanup
   grep -rn "truncate\|delete.*from\|DROP TABLE\|teardown\|cleanup\|clear" backend/tests/ --include="*.py" 2>/dev/null

   # TestClient / AsyncClient setup
   grep -rn "TestClient\|AsyncClient\|app.*override\|dependency_overrides" backend/tests/ --include="*.py" 2>/dev/null
   ```

   Determine isolation strategy: transaction rollback (best), truncation (slower), or recreation (slowest).

4. **Factory vs inline patterns:**
   ```bash
   # Factory classes/functions
   grep -rn "class.*Factory\|def create_\|def make_\|def build_" backend/tests/ --include="*.py" 2>/dev/null

   # Inline object creation (repeated across files = should be a factory)
   grep -rn "Dataset(\|Feature(\|User(" backend/tests/ --include="*.py" | cut -d: -f1 | sort | uniq -c | sort -rn | head -10
   ```

5. **CI vs local alignment:**
   ```bash
   # CI test commands
   find .github/workflows -name "*.yml" -o -name "*.yaml" 2>/dev/null | while read f; do
     echo "=== $f ==="
     grep -A 2 -B 2 "pytest\|vitest" "$f"
   done

   # Local test scripts
   cat Makefile 2>/dev/null | grep -A 3 "test"
   cat package.json 2>/dev/null | grep "test"
   cat backend/Makefile 2>/dev/null | grep -A 3 "test"
   ```

   Compare: same flags? Same coverage thresholds? Same markers excluded?

6. **Environment documentation:**
   ```bash
   # Test env vars documented?
   cat backend/.env.example 2>/dev/null | grep -i "test\|database_url"
   cat backend/.env.test 2>/dev/null
   cat .env.example 2>/dev/null | grep -i "test\|database"

   # Environment-dependent test skips
   grep -rn "skipIf\|skipUnless\|skip.*env\|skip.*CI\|skip.*database\|mark.skip" backend/tests/ --include="*.py" 2>/dev/null
   ```

**Output:** Infrastructure health summary — Aspect | Status | Recommendation.

---

### Subagent 6: Frontend Test Patterns

**Goal:** Audit frontend test quality with attention to React 19 patterns, TanStack Query, MapLibre testability, and accessibility.

**Process:**

1. **Component test quality:**
   ```bash
   # Tests using Testing Library (behavior-focused)
   grep -rn "render\|screen\.\|getByRole\|getByText\|getByLabelText\|findByRole\|queryByRole\|userEvent\|fireEvent" frontend/src/ --include="*.test.*" 2>/dev/null | wc -l

   # Tests using implementation details (brittle)
   grep -rn "container.querySelector\|innerHTML\|wrapper.instance\|component.state\|getByTestId" frontend/src/ --include="*.test.*" 2>/dev/null | wc -l
   ```

   Higher Testing Library usage = healthier tests. Heavy `querySelector`/`getByTestId` = implementation coupling.

2. **Hook tests:**
   ```bash
   # Custom hooks
   find frontend/src -name "use-*.ts" -o -name "use-*.tsx" -o -name "use*.ts" 2>/dev/null | grep -v "test\|spec\|node_modules"

   # Hook tests
   grep -rn "renderHook\|act(" frontend/src/ --include="*.test.*" 2>/dev/null
   ```

   Are complex hooks (TanStack Query, zustand stores) tested independently?

3. **API mocking patterns:**
   ```bash
   # MSW usage
   grep -rn "setupServer\|http\.\|rest\.\|handlers\|msw" frontend/src/ --include="*.test.*" --include="*.ts" 2>/dev/null

   # vi.mock usage
   grep -rn "vi.mock\|jest.mock\|vi.spyOn" frontend/src/ --include="*.test.*" 2>/dev/null

   # Consistency — are some tests using MSW and others vi.mock for the same APIs?
   ```

4. **Missing state tests:**
   ```bash
   # Error state testing
   grep -rn "error\|Error\|isError\|onError" frontend/src/ --include="*.test.*" 2>/dev/null | wc -l

   # Loading state testing
   grep -rn "loading\|Loading\|isLoading\|isPending\|Skeleton\|spinner" frontend/src/ --include="*.test.*" 2>/dev/null | wc -l

   # Empty state testing
   grep -rn "empty\|Empty\|no results\|no data\|nothing" frontend/src/ --include="*.test.*" 2>/dev/null | wc -l

   # Compare to production usage
   grep -rn "isLoading\|isPending\|isError\|error" frontend/src/ --include="*.tsx" | grep -v test | grep -v node_modules | wc -l
   ```

5. **MapLibre component testability:**
   ```bash
   # Map component imports in tests
   grep -rn "maplibre\|MapLibre\|react-maplibre\|Map\b" frontend/src/ --include="*.test.*" 2>/dev/null

   # MapLibre mocking
   grep -rn "mock.*maplibre\|mock.*map\|vi.mock.*maplibre\|vi.mock.*map" frontend/src/ --include="*.test.*" 2>/dev/null

   # Map components without tests
   find frontend/src -name "*map*" -name "*.tsx" ! -name "*.test.*" 2>/dev/null | while read f; do
     test_file="${f%.tsx}.test.tsx"
     if [ ! -f "$test_file" ]; then
       echo "UNTESTED MAP COMPONENT: $f"
     fi
   done
   ```

6. **Accessibility assertions:**
   ```bash
   # A11y-focused queries (good)
   grep -rn "getByRole\|getByLabelText\|getByAltText\|toBeAccessible\|axe\|aria-" frontend/src/ --include="*.test.*" 2>/dev/null | wc -l

   # Non-a11y queries that could be a11y queries
   grep -rn "getByTestId\|container.querySelector" frontend/src/ --include="*.test.*" 2>/dev/null | wc -l
   ```

   Ratio of a11y queries to non-a11y queries indicates test accessibility health.

**Output:** Frontend test health — Pattern | Count | Health indicator | Recommendation.

---

## SYNTHESIS (Serial — after all subagents complete)

### Scoring

| Dimension | What it measures |
|-----------|-----------------|
| **Coverage** | Percentage of modules/routes/components with meaningful test coverage |
| **Test Quality** | Whether tests catch real bugs (behavior-focused, good assertions, parametrized) |
| **Flaky Resistance** | Freedom from non-determinism, timing issues, and order dependence |
| **Missing Tests** | Coverage of critical paths: auth, error handling, spatial ops, vector ops |
| **Infrastructure** | Fixture organization, isolation strategy, CI alignment |
| **Frontend Patterns** | Behavior-focused tests, hook coverage, a11y assertions, state coverage |

Grade each A-F using:
- **A** — Excellent. Comprehensive coverage, strong patterns, minimal gaps.
- **B** — Good. Most critical paths covered, minor quality issues. Low risk.
- **C** — Adequate. Significant gaps in coverage or quality. Moderate risk of bugs shipping.
- **D** — Poor. Major coverage gaps, flaky tests, weak assertions. High risk.
- **F** — Failing. Tests don't run, infrastructure broken, or coverage so low tests provide false confidence.

**Overall test health** = minimum grade (a suite is only as strong as its weakest dimension).

### Action Items

| Field | Description |
|-------|-------------|
| Priority | P0 (tests are broken/misleading), P1 (critical path untested), P2 (quality/maintenance concern) |
| Action | Specific fix — include file path and what to test |
| Dimension | Which audit dimension |
| Effort | Hours estimate |
| Risk if unfixed | What bugs slip through |

Sort by priority, then effort.

### Test Debt Summary

Summarize total test debt:
- Number of backend routes with zero test coverage
- Number of frontend components with zero test coverage
- Number of service functions without tests
- Number of spatial operations tested vs untested
- Number of error paths tested vs untested
- Count of flaky-risk tests
- Total estimated hours to resolve all P0 + P1 items

---

## DELIVERY

### Output format

Write the report to: `docs-internal/audits/test-audit-{YYYYMMDD}.md`

### Report structure

```markdown
# Test Audit — {YYYY-MM-DD}

## Scorecard
<!-- Letter grades + overall health -->

## Executive Summary
<!-- 3-5 sentences: test suite state, biggest gaps, top fix -->

## 1. Coverage Analysis
### 1a. Backend Coverage
### 1b. Frontend Coverage
### 1c. Zero-Coverage Modules
<!-- Subagent 1 findings -->

## 2. Test Quality & Patterns
<!-- Subagent 2 findings -->

## 3. Flaky & Slow Test Detection
<!-- Subagent 3 findings -->

## 4. Missing Test Identification
### 4a. Untested Routes & Services
### 4b. Spatial Operation Coverage
### 4c. Vector Operation Coverage
### 4d. Auth & Permission Coverage
### 4e. Error Path Coverage
<!-- Subagent 4 findings -->

## 5. Test Infrastructure Health
<!-- Subagent 5 findings -->

## 6. Frontend Test Patterns
<!-- Subagent 6 findings -->

## 7. Test Debt Summary
<!-- Aggregate metrics -->

## 8. Prioritized Action Items
<!-- Action items table -->

## 9. Comparison to Prior Audit
<!-- If a previous test-audit exists, diff findings -->
```

### Post-delivery

1. If `lessons.md` exists, append reusable insights about testing spatial/vector/trigram stacks.
2. Print one-line summary: overall grade + P0 count + total test debt hours.

---

## RELATIONSHIP TO OTHER COMMANDS

- `/post-impl` — covers code quality including test-adjacent concerns. This command dives deep into test-specific health.
- `/ship` — runs tests and auto-fixes failures. This command audits whether the test suite itself is healthy.
- `/sec-audit` — checks for security vulnerabilities. This command checks whether security-sensitive code paths have test coverage.

---

## WHAT NOT TO FLAG

Avoid false positives on these:

- **Tests that intentionally skip with `@pytest.mark.skip(reason=...)`** — the reason is documented.
- **Integration tests that require a running database** — these are valid, just note the dependency.
- **Low coverage on auto-generated Alembic migrations** — migration code is tested by the migration-audit.
- **Missing tests on `__init__.py` files that only re-export** — nothing to test.
- **Frontend snapshot tests being absent** — snapshot tests are fragile; component behavior tests are preferred.
- **Tests using `monkeypatch` or `vi.mock`** — mocking is valid when testing in isolation.
- **Low coverage on CLI scripts or one-off management commands** — these change rarely and are tested manually.
- **Missing tests for trivial Pydantic schema definitions** — Pydantic validates itself; only test custom validators.
- **Frontend tests not rendering every CSS class** — visual correctness is a design-review concern, not a test concern.
