# /doc-audit — Documentation Health & Accuracy Audit

Audit documentation completeness, accuracy, and maintenance health across GeoLens. Government and enterprise procurement processes weight documentation quality heavily — stale docs, broken quickstarts, or undocumented APIs signal immature software. This command catches documentation-code drift before it reaches evaluators.

**Usage:** `/doc-audit` (full audit) or `/doc-audit <scope>` where scope is `readme`, `api`, `code`, `setup`, `accuracy`, or `claude`

---

## INTAKE (Serial — do this first)

### Step 1: Inventory all documentation

```bash
# All markdown files in the repo (excluding noise)
find . -name "*.md" -not -path "*/node_modules/*" -not -path "*/.git/*" -not -path "*/.planning/*" | sort

# Doc directory structure
ls docs/ 2>/dev/null
ls docs/GTM/ 2>/dev/null

# CLAUDE.md files
find .claude/ -name "*.md" 2>/dev/null | sort
ls .claude/commands/ 2>/dev/null
```

### Step 2: Read core documentation

```bash
cat README.md 2>/dev/null
cat docs/DESIGN-GUIDE.md 2>/dev/null
cat CLAUDE.md 2>/dev/null
```

### Step 3: Check API documentation availability

```bash
# Probe for a running instance
curl -s http://localhost:8000/openapi.json 2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'Endpoints: {len(d.get(\"paths\", {}))}; Schemas: {len(d.get(\"components\", {}).get(\"schemas\", {}))}')
" || echo "NO_RUNNING_INSTANCE"
```

### Step 4: Determine scope

If `$ARGUMENTS` is empty, run all 6 subagents (full audit).

If `$ARGUMENTS` matches a scope keyword, run only the corresponding subagent:
- `readme` → Subagent 1 only
- `api` → Subagent 2 only
- `code` → Subagent 3 only
- `setup` → Subagent 4 only
- `accuracy` → Subagent 6 only
- `claude` → Subagent 5 only

Always run INTAKE regardless of scope.

---

## SUBAGENT DISPATCH (Parallel)

Run these 6 subagents in parallel (or the single targeted subagent if a scope was specified).

### Subagent 1: README & Public-Facing Docs

**Goal:** Assess whether public-facing documentation creates confidence in GeoLens for government and enterprise evaluators.

**Process:**

1. **README existence and substance:**
   ```bash
   wc -l README.md 2>/dev/null
   # Must be >50 lines to be non-trivial
   ```

   Check for these sections:

   | Section | Required? | What to look for |
   |---------|-----------|-----------------|
   | Project description | Yes | Clear one-liner + paragraph explaining what GeoLens is |
   | Key features | Yes | Categorized list matching actual capabilities |
   | Screenshot or demo link | Yes | Visual proof — gov evaluators need this |
   | Quick start / installation | Yes | `git clone` → `.env` → `docker compose up` → working in <10 min |
   | Prerequisites | Yes | Docker, Docker Compose, minimum specs |
   | Configuration | Should | `.env` vars explained, at least required ones |
   | License | Yes | License badge and/or section |
   | Contributing | Should | Link to CONTRIBUTING.md or inline guidance |
   | API documentation | Should | Link to OpenAPI docs or usage examples |

2. **Quickstart accuracy:**
   ```bash
   # Does the quickstart match docker-compose.yml?
   cat docker-compose.yml | grep -E "^\s+\w+:" | head -20

   # Do documented ports match actual port mappings?
   grep -n "ports:" -A 2 docker-compose.yml

   # Does .env.example exist as README likely references it?
   ls -la .env.example .env.sample .env.template 2>/dev/null
   cat .env.example 2>/dev/null | grep -v "^#" | grep -v "^$" | wc -l
   ```

3. **Version accuracy:**
   ```bash
   # Check pyproject.toml and package.json versions
   grep -A 2 "version" backend/pyproject.toml 2>/dev/null | head -5
   cat frontend/package.json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('version','NOT SET'))" 2>/dev/null

   # Compare with any version claims in README
   grep -i "version\|v[0-9]" README.md 2>/dev/null
   ```

4. **Referenced assets exist:**
   ```bash
   # Extract image references from README
   grep -oP '!\[.*?\]\(\K[^)]+' README.md 2>/dev/null | while read img; do
     if [[ "$img" != http* ]]; then
       [ -f "$img" ] && echo "OK: $img" || echo "MISSING: $img"
     fi
   done

   # Extract relative links from README
   grep -oP '\[.*?\]\(\K[^)]+' README.md 2>/dev/null | grep -v "^http" | while read link; do
     target="${link%%#*}"  # strip anchors
     [ -z "$target" ] && continue
     [ -e "$target" ] && echo "OK: $link" || echo "BROKEN: $link"
   done
   ```

5. **Supporting files:**
   ```bash
   ls -la LICENSE* LICENCE* 2>/dev/null
   ls -la CHANGELOG* CHANGES* 2>/dev/null
   ls -la CONTRIBUTING* 2>/dev/null

   # Do git tags match CHANGELOG entries?
   git tag --list 2>/dev/null | tail -10
   ```

6. **Public-facing quality signals:**
   ```bash
   # Red flags in public docs
   grep -i "wip\|todo\|not ready\|coming soon\|under construction\|placeholder\|hack\|fixme" README.md 2>/dev/null
   grep -i "internal\|private\|our team\|our company" README.md 2>/dev/null

   # Localhost URLs that shouldn't be in public docs
   grep -n "localhost\|127\.0\.0\.1" README.md 2>/dev/null | grep -v "quickstart\|install\|setup\|getting.started\|development"
   ```

**Output:** README completeness scorecard with section-by-section assessment, broken links list, and accuracy findings.

---

### Subagent 2: API Documentation

**Goal:** Verify that API endpoints are documented, accurate, and useful for integrators.

**Process:**

1. **OpenAPI spec coverage (if instance running):**
   ```bash
   curl -s http://localhost:8000/openapi.json 2>/dev/null > /tmp/geolens_openapi.json

   if [ -s /tmp/geolens_openapi.json ]; then
     python3 -c "
import json
with open('/tmp/geolens_openapi.json') as f:
    spec = json.load(f)

paths = spec.get('paths', {})
schemas = spec.get('components', {}).get('schemas', {})

# Count endpoints by method
methods = {}
undocumented = []
for path, ops in paths.items():
    for method, detail in ops.items():
        if method in ('get','post','put','patch','delete'):
            methods[method] = methods.get(method, 0) + 1
            if not detail.get('summary') and not detail.get('description'):
                undocumented.append(f'{method.upper()} {path}')

print('Endpoint counts:', methods)
print(f'Schemas: {len(schemas)}')
print(f'Undocumented endpoints: {len(undocumented)}')
for ep in undocumented[:15]:
    print(f'  - {ep}')
"
   fi
   ```

2. **Route-level documentation in source:**
   ```bash
   # Routers with docstrings/summaries
   find backend/app -name "router.py" -o -name "routes.py" 2>/dev/null | while read f; do
     echo "=== $f ==="
     grep -n "summary=\|description=\|tags=\|response_model=\|responses=" "$f" | head -20
   done

   # Routes missing response_model
   grep -rn "@router\.\(get\|post\|put\|patch\|delete\)" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v "response_model"

   # Routes missing error response documentation
   grep -rn "@router\.\(get\|post\|put\|patch\|delete\)" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v "responses="
   ```

3. **Pydantic schema documentation:**
   ```bash
   # Schema files
   find backend/app -name "schemas.py" -o -name "schema.py" 2>/dev/null | sort

   # Fields with descriptions vs without
   find backend/app -name "schemas.py" -o -name "schema.py" 2>/dev/null | while read f; do
     total=$(grep -c "Field\|:\s*\w" "$f" 2>/dev/null || echo 0)
     described=$(grep -c "description=" "$f" 2>/dev/null || echo 0)
     echo "$f — Fields: ~$total, With description: $described"
   done

   # Example values in schemas
   grep -rn "example=\|examples=\|json_schema_extra" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v alembic | wc -l
   ```

4. **Tag organization:**
   ```bash
   # Tags used in routers
   grep -rn "tags=\[" backend/app/ --include="*.py" | grep -v __pycache__

   # App-level tag metadata
   grep -rn "openapi_tags\|tags_metadata" backend/app/ --include="*.py" | grep -v __pycache__
   ```

**Output:** API documentation coverage report — endpoints without summaries, schemas without field descriptions, missing response models, and tag organization assessment.

---

### Subagent 3: Code Documentation

**Goal:** Assess inline documentation quality for code maintainability and onboarding.

**Process:**

1. **Public function docstring coverage (backend):**
   ```bash
   # Public functions in backend (exclude _ prefix, tests, alembic)
   grep -rn "def [a-z][a-z_]*(" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v "test_" | grep -v alembic | wc -l

   # Functions with docstrings (triple-quote on next lines)
   grep -rn '"""' backend/app/ --include="*.py" | grep -v __pycache__ | grep -v alembic | wc -l

   # Find complex functions (>20 lines) without docstrings
   # Check key service files
   find backend/app -name "service.py" -o -name "services.py" 2>/dev/null | while read f; do
     echo "=== $f ==="
     # Count public functions
     grep -c "def [a-z]" "$f"
   done
   ```

2. **Module-level docstrings:**
   ```bash
   # __init__.py files that should describe their module
   find backend/app -name "__init__.py" -not -empty 2>/dev/null | while read f; do
     first_line=$(head -1 "$f")
     if echo "$first_line" | grep -q '"""'; then
       echo "HAS DOCSTRING: $f"
     else
       echo "NO DOCSTRING: $f"
     fi
   done
   ```

3. **Return type annotations:**
   ```bash
   # Public functions missing return type annotations
   grep -rn "def [a-z][a-z_]*(" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v "test_" | grep -v alembic | grep -v "\->" | head -30
   ```

4. **Frontend component documentation:**
   ```bash
   # Exported components
   grep -rn "export.*function\|export.*const.*=" frontend/src/ --include="*.tsx" | grep -v node_modules | wc -l

   # Components with JSDoc comments
   grep -rn "/\*\*" frontend/src/ --include="*.tsx" | grep -v node_modules | wc -l

   # Props interfaces/types — self-documenting via TypeScript
   grep -rn "interface.*Props\|type.*Props" frontend/src/ --include="*.tsx" --include="*.ts" | grep -v node_modules | wc -l
   ```

5. **Complex code without comments:**
   ```bash
   # Files with high complexity but few comments
   find backend/app -name "*.py" -not -name "test_*" -not -path "*/alembic/*" 2>/dev/null | while read f; do
     lines=$(wc -l < "$f")
     comments=$(grep -c "^[[:space:]]*#\|\"\"\"" "$f" 2>/dev/null || echo 0)
     if [ "$lines" -gt 100 ] && [ "$comments" -lt 5 ]; then
       echo "LOW COMMENTS ($comments comments in $lines lines): $f"
     fi
   done
   ```

**Output:** Code documentation coverage summary — docstring coverage percentage, modules without docs, complex undocumented code hotspots.

---

### Subagent 4: Architecture & Setup Docs

**Goal:** Determine whether a new developer or deployer can get productive from documentation alone.

**Process:**

1. **Architecture overview:**
   ```bash
   # Is there an architecture document?
   find docs/ -iname "*architect*" -o -iname "*overview*" -o -iname "*design*" 2>/dev/null

   # Does README cover architecture?
   grep -i "architect\|stack\|infrastructure\|services\|components" README.md 2>/dev/null | head -10
   ```

2. **Docker Compose documentation:**
   ```bash
   # Are services explained?
   grep -B 1 -A 3 "^\s\+\w\+:" docker-compose.yml 2>/dev/null | head -40

   # Are there comments in docker-compose.yml?
   grep -c "^[[:space:]]*#" docker-compose.yml 2>/dev/null
   ```

3. **Environment variable documentation:**
   ```bash
   # .env.example with comments?
   cat .env.example 2>/dev/null

   # Count documented vs undocumented env vars
   if [ -f .env.example ]; then
     total=$(grep -v "^#" .env.example | grep -v "^$" | wc -l)
     # Check for inline comments
     commented=$(grep -v "^#" .env.example | grep -v "^$" | grep "#" | wc -l)
     echo "Env vars: $total, With inline comments: $commented"
   fi

   # Env vars used in code but not in .env.example
   grep -rn "os.getenv\|os.environ\|settings\.\|config\." backend/app/core/config.py 2>/dev/null | head -30
   ```

4. **Deployment documentation:**
   ```bash
   # Dedicated deployment docs?
   find docs/ -iname "*deploy*" -o -iname "*production*" -o -iname "*hosting*" 2>/dev/null

   # nginx config documented?
   find . -name "nginx*" -not -path "*/node_modules/*" -not -path "*/.git/*" 2>/dev/null
   ```

5. **Database setup documentation:**
   ```bash
   # Migration documentation
   grep -i "migrat\|alembic\|database\|schema" README.md docs/*.md 2>/dev/null | head -10

   # Is the migration auto-run or manual?
   grep -rn "alembic\|upgrade\|migrate" docker-compose.yml backend/Dockerfile* backend/entrypoint* 2>/dev/null
   ```

6. **External service dependencies:**
   ```bash
   # Are Titiler, nginx, and other services documented?
   grep -i "titiler\|nginx\|reverse.proxy" README.md docs/*.md 2>/dev/null | head -10

   # Docker services that a deployer needs to understand
   grep -E "^\s+\w+:" docker-compose.yml | head -20
   ```

**Output:** Setup documentation completeness scorecard — can a new developer go from zero to contributing? Can a deployer go from zero to production?

---

### Subagent 5: CLAUDE.md Accuracy

**Goal:** Verify that CLAUDE.md instructions still reflect the actual codebase. Stale instructions cause Claude Code to produce incorrect output.

**Process:**

1. **Read all CLAUDE.md files:**
   ```bash
   cat CLAUDE.md 2>/dev/null
   find .claude/ -name "*.md" 2>/dev/null | while read f; do
     echo "=== $f ==="
     cat "$f"
   done
   ```

2. **Verify path references:**
   For every file path mentioned in CLAUDE.md or memory files, verify the file exists:
   ```bash
   # Extract paths from CLAUDE.md and check each
   grep -oP '`[^`]*\.(py|ts|tsx|md|json|yml|yaml)`' CLAUDE.md 2>/dev/null | tr -d '`' | while read p; do
     [ -e "$p" ] && echo "OK: $p" || echo "MISSING: $p"
   done
   ```

3. **Verify documented patterns:**
   For each "use X instead of Y" or "do X because of Y" instruction:
   - Verify the referenced code/pattern still exists
   - Verify the workaround is still necessary
   ```bash
   # Example: check if apiFetch still exists at documented path
   ls -la frontend/src/api/client.ts 2>/dev/null
   grep -n "apiFetch" frontend/src/api/client.ts 2>/dev/null | head -3

   # Check if useAuthStore exists
   grep -rn "useAuthStore" frontend/src/ --include="*.ts" --include="*.tsx" | head -3

   # Check if documented workarounds reference still-existing components
   grep -rn "transformRequest\|setTransformRequest" frontend/src/ --include="*.ts" --include="*.tsx" | head -5
   ```

4. **Verify known issues are still current:**
   For each documented known issue, check if the underlying cause still exists or has been fixed.

5. **Verify command descriptions match content:**
   ```bash
   # Read the first line of each command file and verify it describes what the command does
   for f in .claude/commands/*.md; do
     echo "=== $(basename $f) ==="
     head -1 "$f"
   done
   ```

6. **Memory file accuracy:**
   ```bash
   # Check memory files in .claude/projects/
   find .claude/ -name "MEMORY.md" -o -name "memory.md" 2>/dev/null | while read f; do
     echo "=== $f ==="
     cat "$f"
   done
   ```
   For each milestone, credential, pattern, or path reference in memory files — spot-check that it still reflects reality.

**Output:** CLAUDE.md accuracy report — stale entries, broken path references, outdated workarounds, and recommended updates.

---

### Subagent 6: Documentation-Code Drift

**Goal:** Detect documentation that has fallen behind code changes, and code changes that were never documented.

**Process:**

1. **Recent change velocity comparison:**
   ```bash
   # Doc changes in last 30 days
   echo "=== DOCUMENTATION CHANGES (last 30 days) ==="
   git log --since="30 days ago" --name-only --pretty=format: -- "*.md" | sort -u | grep -v "^$" | head -30

   # Code changes in last 30 days
   echo "=== CODE CHANGES (last 30 days) ==="
   git log --since="30 days ago" --name-only --pretty=format: -- "*.py" "*.ts" "*.tsx" | sort -u | grep -v "^$" | head -30
   ```
   If code changed significantly but docs didn't, flag drift risk areas.

2. **Removed features still documented:**
   ```bash
   # Features mentioned in docs — check if referenced modules/components still exist
   grep -oP '`[^`]+`' README.md 2>/dev/null | sort -u | while read ref; do
     clean=$(echo "$ref" | tr -d '`')
     # Skip things that aren't file/module references
     echo "$clean" | grep -qP '\.(py|ts|tsx|yml|md)$' || continue
     [ -e "$clean" ] || echo "REFERENCED BUT MISSING: $clean"
   done
   ```

3. **New features not yet documented:**
   ```bash
   # Router files added recently but not mentioned in docs
   git log --since="60 days ago" --diff-filter=A --name-only --pretty=format: -- "backend/app/*/router.py" 2>/dev/null | grep -v "^$" | while read f; do
     module=$(basename $(dirname "$f"))
     grep -qi "$module" README.md docs/*.md 2>/dev/null || echo "NEW MODULE NOT DOCUMENTED: $module ($f)"
   done

   # Frontend pages/routes added recently
   git log --since="60 days ago" --diff-filter=A --name-only --pretty=format: -- "frontend/src/pages/*" "frontend/src/routes/*" 2>/dev/null | grep -v "^$"
   ```

4. **Version string drift:**
   ```bash
   # Version in package metadata vs docs
   BACKEND_VER=$(grep "version" backend/pyproject.toml 2>/dev/null | head -1 | grep -oP '[\d.]+')
   FRONTEND_VER=$(cat frontend/package.json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('version','UNKNOWN'))" 2>/dev/null)
   echo "Backend version: $BACKEND_VER"
   echo "Frontend version: $FRONTEND_VER"

   # Version references in docs
   grep -rn "version\|v[0-9]\+\.[0-9]" README.md docs/*.md 2>/dev/null | grep -v "node_modules" | head -10
   ```

5. **Config examples vs actual config:**
   ```bash
   # Env vars documented in README/docs vs actual config
   grep -oP '[A-Z_]{3,}' .env.example 2>/dev/null | sort > /tmp/env_example_vars.txt
   grep -oP '[A-Z_]{3,}' README.md 2>/dev/null | sort -u > /tmp/readme_vars.txt

   echo "=== In .env.example but not in README ==="
   comm -23 /tmp/env_example_vars.txt /tmp/readme_vars.txt 2>/dev/null | head -20
   ```

6. **Dead links in documentation:**
   ```bash
   # Internal references to files/routes/components that no longer exist
   find docs/ -name "*.md" 2>/dev/null | while read f; do
     grep -oP '\[.*?\]\(\K[^)]+' "$f" 2>/dev/null | grep -v "^http" | while read link; do
       target="${link%%#*}"
       [ -z "$target" ] && continue
       # Resolve relative to the doc file's directory
       dir=$(dirname "$f")
       [ -e "$dir/$target" ] || [ -e "$target" ] || echo "DEAD LINK in $f: $link"
     done
   done
   ```

**Output:** Drift inventory — stale documentation areas, undocumented new features, version mismatches, and dead links.

---

## SYNTHESIS (Serial — after all subagents complete)

### Scoring

Grade each dimension A–F:

| Dimension | Weight | What it measures |
|-----------|--------|-----------------|
| **README & Public Docs** | 25% | Completeness, accuracy, first-impression quality for evaluators |
| **API Documentation** | 20% | Coverage, accuracy, usefulness for integrators |
| **Documentation-Code Drift** | 20% | How stale is the documentation relative to recent code changes |
| **Architecture & Setup** | 15% | Can a new developer or deployer get productive from docs alone |
| **Code Documentation** | 10% | Coverage of complex code, docstring quality |
| **CLAUDE.md Accuracy** | 10% | Does it still reflect reality |

Grading criteria:
- **A** — Comprehensive, accurate, well-maintained. Procurement-ready.
- **B** — Good coverage with minor gaps. Would pass a casual evaluation.
- **C** — Significant gaps or drift. Evaluator would notice missing pieces.
- **D** — Major omissions or inaccuracies. Documentation actively misleads.
- **F** — Documentation is absent or fundamentally broken.

**Overall doc health** = weighted average of all dimension grades.

### Action Items

| Field | Description |
|-------|-------------|
| Priority | P0 (misleading docs that damage credibility), P1 (significant gap visible to evaluators), P2 (improvement that raises quality) |
| Action | Specific, implementable task |
| Dimension | Which audit dimension |
| Effort | Hours estimate |
| Impact | What improves when fixed |

Sort by priority, then effort.

---

## DELIVERY

### Output format

Write the report to: `docs-internal/audits/doc-audit-{YYYYMMDD}.md`

### Report structure

```markdown
# Documentation Audit — {YYYY-MM-DD}

## Scorecard
<!-- Letter grades + overall health + weighted score -->

## Executive Summary
<!-- 3-5 sentences: documentation state, biggest risks, top fixes -->

## 1. README & Public-Facing Docs
<!-- Subagent 1 findings -->

## 2. API Documentation
<!-- Subagent 2 findings -->

## 3. Code Documentation
<!-- Subagent 3 findings -->

## 4. Architecture & Setup Docs
<!-- Subagent 4 findings -->

## 5. CLAUDE.md Accuracy
<!-- Subagent 5 findings -->

## 6. Documentation-Code Drift
<!-- Subagent 6 findings -->

## 7. Prioritized Action Items
<!-- Action items table -->

## 8. Comparison to Prior Audit
<!-- If a previous doc-audit exists, diff findings -->
```

### Post-delivery

1. If `lessons.md` exists, append reusable insights about documentation maintenance patterns discovered during this audit.
2. Print one-line summary: overall grade + P0 count + total estimated hours to resolve P0 + P1 items.

---

## RELATIONSHIP TO OTHER COMMANDS

- `/demo-ready` — covers launch readiness including README and quickstart. This command goes deeper into all documentation.
- `/star-audit` — covers README from a marketing/discoverability angle. This command covers README from an accuracy/completeness angle.
- `/design-audit` — covers DESIGN-GUIDE.md conformance. This command covers whether DESIGN-GUIDE.md itself is accurate and current.
- `/api-contract` — covers API schema correctness. This command covers whether the API is documented.

---

## WHAT NOT TO FLAG

Avoid false positives on these:

- **Missing docstrings on private/internal functions** (prefix `_`) — these are implementation details, not public API.
- **Missing documentation on test files** — tests are self-documenting by convention.
- **Missing documentation on auto-generated code** (Alembic migrations) — generated code does not need handwritten docs.
- **`.planning/` directory files** — these are internal GSD workflow artifacts, not project documentation. Do not audit them.
- **Missing docstrings on trivially obvious functions** (getters, simple property accessors) — `def get_name(self)` does not need a docstring.
- **README not mentioning every single feature** — the README should highlight key features, not be an exhaustive catalog.
- **Missing API docs on internal/admin-only endpoints** — lower priority than public-facing endpoints. Flag as P2 at most.
- **Comments explaining "what" on obvious code** — only flag missing comments on complex logic. `x = x + 1  # increment x` is worse than no comment.
- **Missing inline code comments on straightforward CRUD operations** — standard patterns don't need narration.
