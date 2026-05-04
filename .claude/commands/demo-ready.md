# /demo-ready — Launch & Demo Readiness Audit

Validate that GeoLens is ready for public launch and demo deployment. Checks the full critical path: cold-start deployment, public-facing assets, security posture, demo-mode viability, and the GTM launch checklist. This command gates the single highest-ROI activity — shipping publicly.

---

## INTAKE (Serial — do this first)

### Step 1: Read GTM launch requirements

If available, read these for the authoritative launch checklist:

1. `docs-internal/GTM/GTM-EVALUATION.md` — Sections 10 (Easy Wins) and 12 (Launch Checklist)
2. `docs-internal/GTM/free-vs-enterprise.md` — Community edition scope (what must work in a demo)
3. `docs-internal/GTM/pricing-to-tiers.md` — launch-safe tier boundaries and deferred Cloud notes

If missing, use the embedded checklist below.

Public launch evidence comes from the repo plus deployed sites. Verify `https://getgeolens.com` for marketing and `https://docs.getgeolens.com` for docs; do not treat old `docs/GTM/` paths as source-of-truth.

### Step 2: Snapshot the project state

```bash
# Repo basics
ls -la LICENSE* LICENCE* 2>/dev/null
ls -la README* 2>/dev/null
ls -la CHANGELOG* CHANGES* RELEASE* 2>/dev/null
cat .github/FUNDING.yml 2>/dev/null
ls -la .github/DISCUSSION_TEMPLATE* .github/ISSUE_TEMPLATE* 2>/dev/null

# Docker infrastructure
ls -la docker-compose*.yml Dockerfile* 2>/dev/null
ls -la backend/Dockerfile* frontend/Dockerfile* 2>/dev/null

# Env configuration
ls -la .env .env.example .env.sample .env.template 2>/dev/null
cat .env.example 2>/dev/null || cat .env.sample 2>/dev/null || cat .env.template 2>/dev/null

# Docs
ls -la docs/ 2>/dev/null
find docs/ -name "*.md" -maxdepth 2 2>/dev/null | sort
ls -la docs-internal/GTM/ 2>/dev/null
find docs-internal/GTM/ -maxdepth 1 -name "*.md" 2>/dev/null | sort
curl -I https://getgeolens.com 2>/dev/null | head -5
curl -I https://docs.getgeolens.com 2>/dev/null | head -5

# Git state
git tag --list 2>/dev/null | tail -10
git log --oneline -5 2>/dev/null
```

---

## EMBEDDED LAUNCH CHECKLIST

Source of truth if GTM docs are unavailable. Derived from `docs-internal/GTM/GTM-EVALUATION.md` Section 12.

### Launch-blocking (MUST have)

- [ ] Public GitHub repo with clean README
- [ ] Apache-2.0 license file (or chosen license)
- [ ] Installation quickstart: clone → `.env` → `docker compose up` → working deployment in < 10 minutes
- [ ] v1.0 tag with release notes
- [ ] No default credentials, hardcoded secrets, or `.env` files committed to git
- [ ] Live demo instance viable (read-only mode, sample data loadable)

### Launch-supporting (SHOULD have)

- [ ] Landing page or features page (GitHub Pages is fine)
- [ ] GitHub Discussions enabled
- [ ] "Powered by GeoLens" branding in UI footer (monetization precursor)
- [ ] CONTRIBUTING.md or contributor guidance
- [ ] Sample dataset(s) included or easily loadable

### Not required for launch (DO NOT BLOCK ON)

- Pricing page (wait until Team tier features exist)
- Comparison page
- SAML / branding toggle / audit export (ship in month 2)
- CI/CD pipeline (nice-to-have)

---

## SUBAGENT DISPATCH (Parallel)

Run these 6 subagents in parallel.

### Subagent 1: Cold-Start Deployment Test

**Goal:** Verify that a fresh user can go from `git clone` to a working GeoLens instance in under 10 minutes with no prior knowledge.

**Process:**

1. **Docker Compose viability:**
   ```bash
   # Read the primary compose file
   cat docker-compose.yml

   # Check for required services
   grep -E "^\s+\w+:" docker-compose.yml | head -20

   # Look for hard dependencies that might fail on first run
   grep -n "depends_on\|healthcheck\|condition" docker-compose.yml

   # Check for volume mounts that assume pre-existing state
   grep -n "volumes:" -A 5 docker-compose.yml

   # Check for network configs that might conflict
   grep -n "networks:\|ports:" docker-compose.yml
   ```

2. **Environment configuration friction:**
   ```bash
   # Is there an env template?
   ls -la .env* 2>/dev/null

   # How many required env vars exist?
   cat .env.example 2>/dev/null | grep -v "^#" | grep -v "^$" | wc -l

   # Which env vars have no defaults and MUST be set?
   cat .env.example 2>/dev/null | grep -v "^#" | grep -v "^$"

   # Are there env vars that require external service setup (API keys, OAuth, etc.)?
   cat .env.example 2>/dev/null | grep -i "key\|secret\|token\|api_key\|client_id\|password" | grep -v "^#"

   # Check if the app can start without optional services (AI, OAuth)
   grep -rn "required.*=.*True\|raise.*missing\|assert.*env\|getenv.*or.*raise" backend/app/ --include="*.py" | grep -v __pycache__ | head -20
   ```

3. **Database initialization:**
   ```bash
   # Alembic migration setup
   ls -la alembic.ini backend/alembic.ini 2>/dev/null
   ls -la backend/alembic/ alembic/ 2>/dev/null
   find . -path "*/alembic/versions/*.py" 2>/dev/null | wc -l

   # Is migration run automatically on startup or does the user need to run it manually?
   grep -rn "alembic\|upgrade\|migrate" docker-compose.yml Dockerfile* backend/Dockerfile* entrypoint* backend/entrypoint* 2>/dev/null

   # PostGIS/pgvector/pg_trgm extension creation
   grep -rn "CREATE EXTENSION\|create_extension\|postgis\|pgvector\|pg_trgm" . --include="*.py" --include="*.sql" --include="*.sh" 2>/dev/null | grep -v __pycache__ | grep -v node_modules

   # Does the Postgres image include PostGIS or is it vanilla?
   grep -n "postgres\|postgis" docker-compose.yml Dockerfile* 2>/dev/null
   ```

4. **First-run experience:**
   ```bash
   # Is there a default admin user creation mechanism?
   grep -rn "create.*admin\|init.*user\|seed\|superuser\|first.*user\|setup.*admin" backend/ --include="*.py" --include="*.sh" 2>/dev/null | grep -v __pycache__

   # Is there a setup wizard or onboarding flow in the frontend?
   grep -rn "onboard\|setup\|wizard\|first.run\|welcome\|getting.started" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules

   # What URL does the user hit after startup?
   grep -rn "port\|8000\|3000\|5173\|localhost" docker-compose.yml .env.example 2>/dev/null
   ```

5. **Failure modes:** Identify common reasons a cold start would fail:
   - Port conflicts (5432, 8000, 3000)
   - Docker memory limits (PostGIS + pgvector can be hungry)
   - Missing env vars with no defaults that crash on startup
   - Migration ordering issues (extensions must exist before spatial columns)
   - Frontend build failures (npm install during build)

**Classify each finding as:**
- **🔴 Blocks cold start** — Deployment will fail without manual intervention
- **🟡 Degrades cold start** — Deployment works but takes >10 min or is confusing
- **🟢 Clean** — Works as expected for a new user

**Output:** Step-by-step cold-start walkthrough with pass/fail per step, estimated total time, and blocking issues.

---

### Subagent 2: Security & Secrets Audit

**Goal:** Ensure no credentials, secrets, or insecure defaults would be exposed in a public repo or demo instance.

**Process:**

1. **Committed secrets scan:**
   ```bash
   # Check if .env is gitignored
   cat .gitignore 2>/dev/null | grep -i "\.env"

   # Check for .env files in git history
   git log --all --full-history -- ".env" "*.env" 2>/dev/null | head -5

   # Search for hardcoded secrets in source
   grep -rn "password\s*=\s*['\"]" backend/ frontend/ --include="*.py" --include="*.ts" --include="*.tsx" | grep -v __pycache__ | grep -v node_modules | grep -v "test" | grep -v "example" | grep -v "placeholder"

   grep -rn "secret\s*=\s*['\"]" backend/ frontend/ --include="*.py" --include="*.ts" --include="*.tsx" | grep -v __pycache__ | grep -v node_modules | grep -v "test"

   grep -rn "api_key\s*=\s*['\"]" backend/ frontend/ --include="*.py" --include="*.ts" --include="*.tsx" | grep -v __pycache__ | grep -v node_modules | grep -v "test"

   # Check for private keys
   find . -name "*.pem" -o -name "*.key" -o -name "id_rsa" -o -name "*.p12" 2>/dev/null | grep -v node_modules
   ```

2. **Default credential audit:**
   ```bash
   # Default passwords in env template
   cat .env.example 2>/dev/null | grep -i "password\|secret\|key"

   # Default admin credentials
   grep -rn "admin.*password\|default.*password\|changeme\|password123\|secret123" backend/ --include="*.py" --include="*.yml" --include="*.yaml" --include="*.env*" 2>/dev/null | grep -v __pycache__

   # JWT secret defaults
   grep -rn "JWT_SECRET_KEY\|JWT_ALGORITHM" backend/ --include="*.py" 2>/dev/null | grep -v __pycache__
   ```

3. **Debug/development mode exposure:**
   ```bash
   # Debug flags
   grep -rn "DEBUG\s*=\s*True\|debug\s*=\s*True\|reload\s*=\s*True" backend/ docker-compose.yml --include="*.py" --include="*.yml" 2>/dev/null | grep -v __pycache__ | grep -v test

   # Stack trace exposure
   grep -rn "traceback\|show_error\|detail.*error\|exception.*handler" backend/app/ --include="*.py" 2>/dev/null | grep -v __pycache__

   # FastAPI docs exposure (Swagger/ReDoc)
   grep -rn "docs_url\|redoc_url\|openapi_url" backend/app/ --include="*.py" 2>/dev/null | grep -v __pycache__

   # CORS wide-open
   grep -rn "allow_origins\|allow_all\|\*" backend/app/ --include="*.py" | grep -i cors | grep -v __pycache__
   ```

4. **Sensitive data in repo:**
   ```bash
   # Database dumps, backups
   find . -name "*.sql" -o -name "*.dump" -o -name "*.bak" -o -name "*.sqlite" 2>/dev/null | grep -v node_modules | grep -v alembic

   # Log files
   find . -name "*.log" 2>/dev/null | grep -v node_modules

   # Docker volumes with data
   grep -n "\.\/data\|\.\/db_data\|\.\/postgres" docker-compose.yml 2>/dev/null
   ```

5. **Demo-specific security:**
   ```bash
   # Is there a read-only or demo mode?
   grep -rn "READ_ONLY\|DEMO_MODE\|demo\|read.only" backend/ frontend/ --include="*.py" --include="*.ts" --include="*.tsx" --include="*.env*" 2>/dev/null | grep -v __pycache__ | grep -v node_modules

   # Could a demo instance be used to write/delete data without auth?
   grep -rn "@router\.\(post\|put\|patch\|delete\)" backend/app/ --include="*.py" 2>/dev/null | grep -v __pycache__ | head -30
   # Cross-check: do write endpoints require authentication?
   grep -rn "Depends.*get_current_user\|Depends.*require_auth\|Depends.*get_user" backend/app/ --include="*.py" 2>/dev/null | grep -v __pycache__ | wc -l
   ```

**Classify each finding as:**
- **🔴 Launch blocker** — Secret exposure, default credentials that work, or write access without auth
- **🟡 Should fix** — Debug mode on by default, overly permissive CORS, exposed Swagger in prod
- **🟢 Clean** — Properly handled

**Output:** Secrets/security findings table with severity, file:line, and remediation.

---

### Subagent 3: README & Documentation Audit

**Goal:** Evaluate whether the public-facing documentation is sufficient for a new user to understand, install, and evaluate GeoLens.

**Process:**

1. **README completeness:**
   ```bash
   cat README.md 2>/dev/null
   ```
   Check for these sections (all are expected for an open-source launch):

   | Section | Required? | What to look for |
   |---------|-----------|-----------------|
   | Project description | Yes | Clear one-liner + paragraph explaining what GeoLens is |
   | Key features | Yes | Categorized list matching community edition scope |
   | Screenshot or demo link | Yes | Visual proof the product is real — gov evaluators need this |
   | Quick start / installation | Yes | `git clone` → `.env` → `docker compose up` → working in <10 min |
   | Prerequisites | Yes | Docker, Docker Compose, minimum specs |
   | Configuration | Should | `.env` vars explained, at least the required ones |
   | License | Yes | License badge and/or section |
   | Contributing | Should | Link to CONTRIBUTING.md or inline guidance |
   | Community / Support | Should | Discussions link, issue tracker |
   | Roadmap | Nice | Signals project is alive and maintained |

2. **Installation documentation:**
   ```bash
   # Dedicated install docs?
   find docs/ -iname "*install*" -o -iname "*quickstart*" -o -iname "*getting*started*" -o -iname "*setup*" 2>/dev/null

   # Is docker compose up documented step-by-step?
   grep -rn "docker compose\|docker-compose" README.md docs/ 2>/dev/null
   ```

3. **License file:**
   ```bash
   cat LICENSE 2>/dev/null || cat LICENCE 2>/dev/null || cat LICENSE.md 2>/dev/null
   # Verify it's a recognized open-source license
   head -5 LICENSE 2>/dev/null
   ```

4. **Contributing guidance:**
   ```bash
   cat CONTRIBUTING.md 2>/dev/null
   cat CODE_OF_CONDUCT.md 2>/dev/null
   ```

5. **Changelog / release notes:**
   ```bash
   cat CHANGELOG.md 2>/dev/null || cat CHANGES.md 2>/dev/null
   git tag --list 2>/dev/null | tail -5
   ```

6. **Public-facing quality signals:**
   - Is the README free of internal references (local paths, private URLs, team names)?
   - Are there broken links in the README?
   - Is the language confident and professional (not "WIP", "TODO", "not ready")?
   - Does it mention standards compliance (OGC, STAC, DCAT, FAIR)?
     ```bash
     grep -i "wip\|todo\|not ready\|coming soon\|under construction\|placeholder\|hack\|fixme" README.md 2>/dev/null
     grep -i "internal\|private\|our team\|our company" README.md 2>/dev/null
     ```

**Output:** Documentation completeness scorecard with section-by-section assessment and specific copy recommendations.

---

### Subagent 4: Demo Mode & Sample Data

**Goal:** Verify that a public read-only demo instance is viable — government evaluators will click a URL before they run Docker.

**Process:**

1. **Read-only / demo mode:**
   ```bash
   # Is there a demo or read-only mode?
   grep -rn "DEMO\|READ_ONLY\|DISABLE_WRITE\|DISABLE_AUTH\|PUBLIC_MODE" backend/ frontend/ --include="*.py" --include="*.ts" --include="*.tsx" --include="*.env*" --include="*.yml" 2>/dev/null | grep -v __pycache__ | grep -v node_modules

   # Can write endpoints be disabled via configuration?
   grep -rn "if.*settings\.\|if.*config\.\|if.*env\." backend/app/ --include="*.py" 2>/dev/null | grep -v __pycache__ | grep -i "write\|edit\|delete\|create\|upload\|ingest"
   ```

2. **Sample data availability:**
   ```bash
   # Bundled sample data
   find . -name "*.geojson" -o -name "*.gpkg" -o -name "*.shp" -o -name "*.csv" -o -name "*.tif" -o -name "*.tiff" 2>/dev/null | grep -v node_modules | grep -i "sample\|demo\|example\|seed\|fixture\|test"

   # Seed/fixture scripts
   find . -name "*seed*" -o -name "*fixture*" -o -name "*demo*" -o -name "*sample*" 2>/dev/null | grep -E "\.(py|sh|sql)$" | grep -v __pycache__ | grep -v node_modules

   # Data loading documentation
   grep -rn "sample\|demo\|seed\|fixture\|example.*data\|test.*data\|load.*data" README.md docs/ --include="*.md" 2>/dev/null
   ```

3. **Demo showcase capability:** For each core workflow, assess if a demo can show it:

   | Workflow | What to verify |
   |----------|---------------|
   | **Ingest data** | Can be pre-loaded. Does not need to work live in demo. |
   | **Find data** | Search must work. Catalog must have discoverable datasets. |
   | **Visualize data** | Map viewer + map builder must render with sample data. |
   | **Share data** | Share links / public viewer must work without auth. |
   | **Standards** | OGC/STAC/DCAT endpoints must return real data. |
   | **AI** | If provider key is configured, AI chat should work. If not configured, the demo must remain fully usable and AI controls must show a graceful disabled/error state. |

   ```bash
   # Public/unauthenticated access paths
   grep -rn "public\|anonymous\|no.*auth\|optional.*auth" backend/app/ --include="*.py" 2>/dev/null | grep -v __pycache__ | grep -i "router\|endpoint\|view"

   # Public viewer
   find frontend/src -name "*Public*" -o -name "*public*" -o -name "*Viewer*" 2>/dev/null | grep -E "\.(tsx|ts)$"

   # AI dependency on external API keys
   grep -rn "OPENAI\|ANTHROPIC\|GOOGLE_AI\|API_KEY\|LLM" backend/app/processing/ai/ --include="*.py" 2>/dev/null | grep -v __pycache__
   ```

4. **Demo deployment path:**
   ```bash
   # Is there a demo-specific compose or config?
   ls -la docker-compose.demo.yml docker-compose.prod.yml 2>/dev/null

   # Resource requirements
   grep -n "mem_limit\|memory\|cpus\|cpu_shares\|shm_size" docker-compose.yml 2>/dev/null

   # Could this run on a $20/mo VPS (2GB RAM, 1 vCPU)?
   # Count number of services
   grep -E "^\s+\w+:" docker-compose.yml | wc -l
   ```

5. **Demo reset / data protection:**
   ```bash
   # Can demo data be periodically reset?
   # Is there a script to restore to a known state?
   find . -name "*reset*" -o -name "*restore*" -o -name "*snapshot*" 2>/dev/null | grep -E "\.(py|sh|sql)$" | grep -v node_modules
   ```

**Output:** Demo viability assessment with: what works today, what's missing, and a concrete plan to get a public demo running.

---

### Subagent 5: Branding & Monetization Precursors

**Goal:** Verify the "Powered by GeoLens" branding is present in the UI (the monetization precursor) and assess overall branding consistency for public launch.

**Process:**

1. **"Powered by GeoLens" footer:**
   ```bash
   # Search for existing branding
   grep -rn "Powered by\|GeoLens\|geolens" frontend/src/ --include="*.tsx" --include="*.ts" --include="*.css" --include="*.scss" 2>/dev/null | grep -v node_modules | grep -v __pycache__

   # Footer components
   find frontend/src -name "*Footer*" -o -name "*footer*" 2>/dev/null | grep -E "\.(tsx|ts)$"

   # If footer exists, read it
   find frontend/src -name "*Footer*" -o -name "*footer*" 2>/dev/null | grep -E "\.(tsx|ts)$" | while read f; do
     echo "=== $f ==="
     cat "$f"
   done
   ```

2. **Branding consistency:**
   ```bash
   # App title / metadata
   grep -rn "<title>\|document.title\|app.*name\|APP_NAME\|SITE_NAME" frontend/src/ --include="*.tsx" --include="*.ts" --include="*.html" 2>/dev/null | grep -v node_modules

   # Favicon and manifest
   find frontend/public frontend/src -name "favicon*" -o -name "manifest*" -o -name "*.ico" -o -name "apple-touch*" 2>/dev/null

   # Logo files
   find frontend/ -name "*logo*" -o -name "*brand*" 2>/dev/null | grep -v node_modules

   # Meta tags (description, OG tags for link previews)
   grep -rn "og:title\|og:description\|meta.*description\|og:image" frontend/src/ --include="*.html" --include="*.tsx" 2>/dev/null | grep -v node_modules
   ```

3. **Branding toggle readiness:**
   ```bash
   # Is branding configurable via settings?
   grep -rn "brand\|logo\|footer.*text\|app.*name" backend/app/modules/settings/ frontend/src/ --include="*.py" --include="*.ts" --include="*.tsx" 2>/dev/null | grep -v node_modules | grep -v __pycache__ | grep -i "config\|setting\|toggle\|flag"

   # Theme system that could support white-labeling later
   find frontend/src -name "*theme*" -o -name "*Theme*" 2>/dev/null | grep -E "\.(tsx|ts)$"
   ```

4. **Public perception check:**
   - Does the UI look like a finished product or a dev prototype?
   - Are there placeholder images, lorem ipsum, or "TODO" text in the UI?
     ```bash
     grep -rn "lorem\|placeholder\|TODO\|FIXME\|HACK\|coming soon" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | grep -v __pycache__
     ```
   - Are error states handled gracefully (empty states, loading states, error boundaries)?
     ```bash
     grep -rn "ErrorBoundary\|error.*boundary\|fallback\|empty.*state\|no.*data\|no.*results" frontend/src/ --include="*.tsx" 2>/dev/null | grep -v node_modules | head -15
     ```

**Output:** Branding status table, "Powered by" presence (yes/no with location), and monetization-readiness assessment.

---

### Subagent 6: Release & Distribution Readiness

**Goal:** Verify the repo is ready for public release — tagged, licensed, clean history, no internal artifacts.

**Process:**

1. **Version and tagging:**
   ```bash
   # Current version references
   grep -rn "version\|__version__\|VERSION" backend/ frontend/ --include="*.py" --include="*.ts" --include="*.json" 2>/dev/null | grep -v node_modules | grep -v __pycache__ | grep -v ".lock" | head -20

   # Git tags
   git tag --list 2>/dev/null

   # Package versions
   cat backend/pyproject.toml 2>/dev/null | grep -A 2 "version"
   cat frontend/package.json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('version','NOT SET'))" 2>/dev/null
   ```

2. **License compliance:**
   ```bash
   # License file
   cat LICENSE 2>/dev/null | head -20

   # License in package metadata
   grep -i "license" backend/pyproject.toml frontend/package.json 2>/dev/null

   # Third-party license compatibility (quick check)
   # Python
   sed -n '/^dependencies = \\[/,/^\\]/p;/^dev = \\[/,/^\\]/p' backend/pyproject.toml 2>/dev/null | head -40
   # Node
   cat frontend/package.json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); [print(k) for k in {**d.get('dependencies',{}), **d.get('devDependencies',{})}.keys()]" 2>/dev/null | head -30
   ```

3. **Repo hygiene for public release:**
   ```bash
   # Internal/private references
   grep -rn "internal\|private\|confidential\|proprietary\|do not share" . --include="*.md" --include="*.txt" --include="*.py" --include="*.ts" --include="*.tsx" 2>/dev/null | grep -v node_modules | grep -v __pycache__ | grep -v ".git/" | grep -v LICENSE | head -20

   # Private URLs, IPs, internal domains
   grep -rn "192\.168\.\|10\.0\.\|172\.\(1[6-9]\|2[0-9]\|3[01]\)\.\|\.internal\.\|\.local\b\|\.corp\.\|\.lan\b" . --include="*.py" --include="*.ts" --include="*.tsx" --include="*.yml" --include="*.yaml" --include="*.md" --include="*.env*" 2>/dev/null | grep -v node_modules | grep -v __pycache__ | grep -v ".git/" | grep -v "localhost" | head -20

   # Personal info in code (names, emails that shouldn't be public)
   grep -rn "@gmail\|@yahoo\|@hotmail\|@outlook" . --include="*.py" --include="*.ts" --include="*.yml" --include="*.md" 2>/dev/null | grep -v node_modules | grep -v __pycache__ | grep -v ".git/" | head -10

   # Large binary files that shouldn't be in a public repo
   find . -size +5M -not -path "./.git/*" -not -path "*/node_modules/*" 2>/dev/null
   ```

4. **Gitignore completeness:**
   ```bash
   cat .gitignore 2>/dev/null

   # Check for files that SHOULD be ignored but aren't
   git status --porcelain 2>/dev/null | head -20
   git ls-files --others --ignored --exclude-standard 2>/dev/null | head -10

   # Common things that should be gitignored
   for pattern in ".env" "*.pyc" "__pycache__" "node_modules" ".DS_Store" "*.log" "db_data" "*.sqlite"; do
     grep -q "$pattern" .gitignore 2>/dev/null && echo "✅ $pattern ignored" || echo "⚠️  $pattern NOT in .gitignore"
   done
   ```

5. **CI/CD (assess, don't require):**
   ```bash
   ls -la .github/workflows/ .gitlab-ci.yml .circleci/ Jenkinsfile 2>/dev/null
   find .github/workflows -name "*.yml" -o -name "*.yaml" 2>/dev/null | while read f; do
     echo "=== $f ==="
     head -20 "$f"
   done
   ```

**Output:** Release readiness checklist with pass/fail per item, and specific remediation for any blockers.

---

## SYNTHESIS (Serial — after all subagents complete)

### Scorecard

Assign a status to each dimension:

| Dimension | Status options |
|-----------|---------------|
| **Cold Start** | ✅ Works / ⚠️ Works with friction / ❌ Broken |
| **Security** | ✅ Clean / ⚠️ Minor issues / ❌ Secrets exposed |
| **Documentation** | ✅ Launch-ready / ⚠️ Gaps / ❌ Insufficient |
| **Demo Viability** | ✅ Ready / ⚠️ Partial / ❌ Not viable |
| **Branding** | ✅ Present / ⚠️ Incomplete / ❌ Missing |
| **Release Readiness** | ✅ Ship it / ⚠️ Needs cleanup / ❌ Not ready |

**Overall verdict:** One of:
- **🟢 LAUNCH READY** — Ship today. All blockers resolved.
- **🟡 LAUNCH READY WITH CAVEATS** — Can ship but should fix [specific items] within the first week.
- **🔴 NOT LAUNCH READY** — Blockers exist that must be resolved first.

### GTM Checklist Reconciliation

Map findings against the embedded launch checklist. For each item:

| Checklist Item | Status | Evidence | Action needed |
|----------------|--------|----------|---------------|
| Public repo with clean README | ✅/⚠️/❌ | ... | ... |
| Apache-2.0 license file | ✅/⚠️/❌ | ... | ... |
| Installation quickstart (<10 min) | ✅/⚠️/❌ | ... | ... |
| v1.0 tag with release notes | ✅/⚠️/❌ | ... | ... |
| No default credentials | ✅/⚠️/❌ | ... | ... |
| Demo instance viable | ✅/⚠️/❌ | ... | ... |
| "Powered by GeoLens" in footer | ✅/⚠️/❌ | ... | ... |
| GitHub Discussions enabled | ✅/⚠️/❌ | ... | ... |

### Action Items

Prioritized action list:

| Field | Description |
|-------|-------------|
| Priority | P0 (blocks public launch), P1 (blocks demo deployment), P2 (improves launch quality) |
| Action | Specific, implementable task |
| Effort | Hours estimate |
| Rationale | Why this matters for launch |

Sort by priority, then effort.

### Demo Deployment Recipe

If demo mode is viable, output a concrete deployment recipe:

```markdown
### Recommended Demo Deployment

**Target:** $20/mo VPS (2GB RAM, 1 vCPU, 50GB disk)

**Steps:**
1. ...
2. ...
3. ...

**Required env vars:**
- ...

**Data loading:**
- ...

**Security hardening for public demo:**
- ...

**Estimated monthly cost:** $XX
```

If demo mode is not viable, output the minimum changes needed to make it viable.

---

## DELIVERY

### Output format

Write the report to: `docs-internal/audits/demo-ready-{YYYYMMDD}.md`

### Report structure

```markdown
# Launch & Demo Readiness Audit — {YYYY-MM-DD}

## Verdict
<!-- Overall status badge: LAUNCH READY / LAUNCH READY WITH CAVEATS / NOT LAUNCH READY -->

## Scorecard
<!-- Status table for all 6 dimensions -->

## Executive Summary
<!-- 3-5 sentences: can we ship, what blocks us, what's the fastest path -->

## 1. Cold-Start Deployment
<!-- Subagent 1 findings -->

## 2. Security & Secrets
<!-- Subagent 2 findings -->

## 3. README & Documentation
<!-- Subagent 3 findings -->

## 4. Demo Mode & Sample Data
<!-- Subagent 4 findings -->

## 5. Branding & Monetization Precursors
<!-- Subagent 5 findings -->

## 6. Release & Distribution Readiness
<!-- Subagent 6 findings -->

## 7. GTM Checklist Reconciliation
<!-- Checklist table -->

## 8. Prioritized Action Items
<!-- Action items table -->

## 9. Demo Deployment Recipe
<!-- Concrete deployment steps or gap list -->

## 10. Comparison to Prior Audit
<!-- If a previous demo-ready audit exists, diff findings -->
```

### Post-delivery

1. If `lessons.md` exists, append any reusable insights about launch readiness discovered during this audit.
2. Print a summary: overall verdict + count of P0 blockers + estimated hours to launch-ready.

---

## WHAT NOT TO FLAG

Avoid false positives on these:

- **No pricing page** — Explicitly not required for launch per GTM docs. Only build after Team tier features exist.
- **Enterprise overlay features not required in Community demo** — SAML/SCIM and advanced-sharing gates do not need to work in the Community demo. If public docs mention them, verify they are tagged Enterprise and match shipped overlay/gate reality.
- **No CI/CD pipeline** — Nice-to-have for launch, not a blocker. Note if missing but do not mark as P0.
- **Debug mode in development compose** — Only flag if `docker-compose.yml` (the one users run) has debug on. A separate `docker-compose.dev.yml` with debug is fine.
- **Exposed FastAPI docs (/docs, /redoc)** — For an open-source project this is a feature, not a security issue. Only flag if it exposes internal/admin endpoints that should be auth-gated.
- **No HTTPS configuration** — Docker Compose deployments sit behind a reverse proxy. TLS is the deployer's responsibility, not GeoLens's.
- **AI features requiring API keys** — AI is a value-add. Flag the dependency but don't mark it as a launch blocker. The demo should work without AI if no key is set.
- **Comparison page / "Why GeoLens"** — Nice-to-have, not a blocker. Note if missing but P2 at most.
