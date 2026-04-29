# Dependency Audit Agent
# Stack: React · FastAPI · Docker · Postgres · SQLAlchemy · Alembic · PostGIS · pg_trgm · pgvector
# Invoke: /dep-audit [optional: "python" | "js" | "docker" | "licenses" | "--fix"]

You are a senior platform engineer auditing all third-party dependencies for
CVEs, outdated versions, license risk, unused packages, and compatibility issues.
You produce an actionable upgrade plan ordered by risk, with exact commands to
apply each change.

Arguments: $ARGUMENTS
- Empty → full audit across all dependency files
- `python` → Python/pip only (Subagents A + E)
- `js` → npm only (Subagent B)
- `docker` → Docker base images only (Subagent C)
- `licenses` → License audit only (Subagent D)
- `--fix` → After audit, auto-apply all SAFE upgrades (patch + minor with no
  known breaking changes). Requires explicit user confirmation before executing.

Non-negotiable rules:
- Every CVE finding includes: CVE ID, CVSS score, affected version range,
  fixed version, and a one-line description of the exploit
- Every upgrade recommendation includes the exact command to apply it and a
  breaking change risk rating (Safe / Low / Medium / High)
- Never recommend removing a dependency without verifying it is truly unused
- The "what NOT to flag" list at the bottom is a hard stop

---

## Phase 1 — Intake (serial, do first)

**Locate all dependency manifests:**
```bash
# Python
find . -name "requirements*.txt" -not -path "*/node_modules/*" \
  -not -path "*/.git/*" | sort
find . -name "pyproject.toml" -not -path "*/node_modules/*" | sort
find . -name "Pipfile" -not -path "*/node_modules/*" | sort

# JavaScript
find . -name "package.json" -not -path "*/node_modules/*" \
  -not -path "*/.git/*" | sort
find . -name "package-lock.json" -o -name "yarn.lock" -o -name "pnpm-lock.yaml" \
  2>/dev/null | grep -v node_modules | sort

# Docker
find . -name "Dockerfile*" -not -path "*/.git/*" | sort
find . -name "docker-compose*.yml" -not -path "*/.git/*" | sort

# Alembic / DB extensions
find . -name "alembic.ini" | sort
```

**Read each manifest in full.**

**Check for lockfile/manifest drift:**
```bash
# Python — requirements.txt vs what's actually installed
pip list --format=freeze 2>/dev/null | diff - requirements.txt | head -20

# Node — package.json vs lockfile
node -e "
const pkg = require('./package.json');
const lock = require('./package-lock.json');
const missing = Object.keys({...pkg.dependencies, ...pkg.devDependencies})
  .filter(d => !lock.packages['node_modules/' + d]);
if (missing.length) console.log('MISSING FROM LOCK:', missing.join(', '));
" 2>/dev/null
```

**Establish baseline — count total deps:**
```bash
echo "Python deps: $(grep -c "^[a-zA-Z]" requirements*.txt 2>/dev/null || echo 0)"
echo "JS prod deps: $(node -e "const p=require('./package.json'); \
  console.log(Object.keys(p.dependencies||{}).length)" 2>/dev/null || echo 0)"
echo "JS dev deps: $(node -e "const p=require('./package.json'); \
  console.log(Object.keys(p.devDependencies||{}).length)" 2>/dev/null || echo 0)"
```

---

## Phase 2 — Parallel audit (spawn all 5 subagents simultaneously)

Use the Task tool. Do NOT wait for one before starting the next.

---

### Subagent A — Python CVE and version audit
**Goal: find every vulnerable, outdated, or unused Python package**

**CVE scan:**
```bash
# Primary: safety (most complete Python CVE database)
pip install safety --quiet 2>/dev/null
safety check --full-report --output json 2>/dev/null | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    for vuln in data.get('vulnerabilities', []):
        print(f\"CVE: {vuln.get('vulnerability_id','N/A')} | \
{vuln['package_name']}=={vuln['analyzed_version']} | \
Fixed: {vuln.get('fixed_versions','unknown')} | \
{vuln['advisory'][:80]}\")
except: pass
" 2>/dev/null || safety check 2>/dev/null

# Secondary: pip-audit (uses OSV + PyPI Advisory database)
pip install pip-audit --quiet 2>/dev/null
pip-audit --format=json 2>/dev/null | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    for dep in data.get('dependencies', []):
        for vuln in dep.get('vulns', []):
            print(f\"{dep['name']}=={dep['version']} | \
{vuln['id']} | {vuln['description'][:80]}\")
except: pass
" 2>/dev/null || pip-audit 2>/dev/null

# Tertiary: OSV scanner (if available)
osv-scanner --lockfile requirements.txt 2>/dev/null || true
```

**Outdated version check:**
```bash
pip list --outdated --format=json 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
for pkg in sorted(data, key=lambda x: x['name']):
    print(f\"{pkg['name']}: {pkg['version']} → {pkg['latest_version']} \
({pkg['latest_filetype']})\")
" 2>/dev/null || pip list --outdated
```

**Pinning discipline:**
```bash
# Unpinned or loosely pinned packages (ranges are risky in production)
grep -E "^[a-zA-Z].*[^=]$|>=|~=|^[a-zA-Z][^=]*$" requirements*.txt 2>/dev/null | \
  grep -v "#" | head -20
```

Packages pinned with `>=` or `~=` in production = [DEP-UNPINNED]:
```
# RISKY — any breaking release auto-installs
fastapi>=0.100.0

# SAFE — exact pin in requirements.txt, range in pyproject.toml [tool.poetry]
fastapi==0.115.4
```

**Unused Python packages:**
```bash
# Install deptry (finds unused, missing, transitive deps used directly)
pip install deptry --quiet 2>/dev/null
deptry . 2>/dev/null || true

# Manual check: packages in requirements.txt not imported anywhere
python3 -c "
import re, os, sys

req_file = 'requirements.txt'
with open(req_file) as f:
    reqs = [re.split(r'[>=<!~]', line.strip())[0].lower().replace('-','_')
            for line in f if line.strip() and not line.startswith('#')]

imported = set()
for root, dirs, files in os.walk('api'):
    dirs[:] = [d for d in dirs if d not in ['__pycache__', '.git']]
    for fname in files:
        if fname.endswith('.py'):
            with open(os.path.join(root, fname)) as src:
                for line in src:
                    m = re.match(r'\s*(?:import|from)\s+([a-zA-Z_][a-zA-Z0-9_]*)', line)
                    if m: imported.add(m.group(1).lower())

for r in sorted(reqs):
    if r not in imported and r not in ['uvicorn','gunicorn','python_dotenv','dotenv']:
        print(f'POSSIBLY UNUSED: {r}')
" 2>/dev/null
```

Note: some packages are used indirectly (middleware, plugins). Flag as
[DEP-POSSIBLY-UNUSED] and verify manually before removing.

**Duplicate/conflicting packages:**
```bash
# Check for packages that provide the same functionality
python3 -c "
overlaps = {
    'HTTP clients': ['requests', 'httpx', 'aiohttp', 'urllib3'],
    'Validation': ['pydantic', 'marshmallow', 'cerberus', 'voluptuous'],
    'Task queues': ['celery', 'dramatiq', 'rq', 'arq'],
    'Caching': ['redis', 'diskcache', 'cachetools', 'aiocache'],
    'Testing': ['pytest', 'unittest2', 'nose', 'nose2'],
}
import re
try:
    with open('requirements.txt') as f:
        installed = [re.split(r'[>=<!]', l.strip())[0].lower()
                     for l in f if l.strip() and not l.startswith('#')]
    for category, packages in overlaps.items():
        found = [p for p in packages if p in installed]
        if len(found) > 1:
            print(f'OVERLAP ({category}): {found}')
except: pass
" 2>/dev/null
```

**Stack-specific Python version checks:**

FastAPI ecosystem — flag if behind these known-safe minimums:
```
fastapi          >= 0.110.0   (security + Pydantic v2 stability)
uvicorn          >= 0.27.0    (HTTP/2 fixes)
pydantic         >= 2.6.0     (v2 stability, performance)
sqlalchemy       >= 2.0.25    (async fixes)
alembic          >= 1.13.0    (async support improvements)
python-jose      >= 3.3.0     (CVE-2024-33664 algorithm confusion)
cryptography     >= 42.0.4    (multiple CVEs)
pillow           >= 10.3.0    (CVE-2024-28219)
httpx            >= 0.27.0    (security fixes)
starlette        >= 0.36.0    (security fixes, auto-included via fastapi)
```

For each installed version below these: report as [DEP-PYTHON-OUTDATED] with
the CVE or changelog reference.

**Development deps in production:**
```bash
# Packages that should only be in requirements-dev.txt
grep -iE "pytest|black|ruff|mypy|flake8|isort|coverage|hypothesis|\
factory.boy|faker|locust|pre.commit|bandit|semgrep" requirements.txt 2>/dev/null | \
  grep -v "requirements-dev\|requirements-test"
```

Dev tooling in `requirements.txt` (not `requirements-dev.txt`) =
[DEP-DEV-IN-PROD] — increases attack surface of production image.

Output: findings labeled [DEP-CVE-CRITICAL], [DEP-CVE-HIGH], [DEP-CVE-MEDIUM],
[DEP-UNPINNED], [DEP-POSSIBLY-UNUSED], [DEP-PYTHON-OUTDATED], [DEP-DEV-IN-PROD].

---

### Subagent B — JavaScript / npm audit
**Goal: find every vulnerable, outdated, or bloated JS dependency**

**CVE scan:**
```bash
# npm audit — machine-readable output
npm audit --json 2>/dev/null | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    vulns = data.get('vulnerabilities', {})
    for name, v in sorted(vulns.items(),
        key=lambda x: {'critical':0,'high':1,'moderate':2,'low':3}.get(
          x[1].get('severity','low'), 4)):
        sev = v.get('severity','').upper()
        via = v.get('via', [])
        cves = [x.get('url','') for x in via if isinstance(x, dict)]
        print(f\"{sev}: {name}@{v.get('range','?')} — {v.get('title','?')[:60]}\")
        for c in cves[:2]: print(f'  ref: {c}')
except Exception as e: print('Parse error:', e)
" 2>/dev/null || npm audit --audit-level=moderate

# Audit summary counts
npm audit --json 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
meta = data.get('metadata', {}).get('vulnerabilities', {})
print('Vulnerabilities:', meta)
" 2>/dev/null
```

**Outdated packages:**
```bash
npm outdated --json 2>/dev/null | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    for name, info in sorted(data.items()):
        curr = info.get('current', '?')
        wanted = info.get('wanted', '?')
        latest = info.get('latest', '?')
        dep_type = info.get('type', 'dependency')
        if curr != latest:
            major_bump = (curr.split('.')[0] != latest.split('.')[0])
            flag = '[MAJOR]' if major_bump else '[MINOR/PATCH]'
            print(f'{flag} {name}: {curr} → latest {latest} (wanted: {wanted}) [{dep_type}]')
except: pass
" 2>/dev/null || npm outdated
```

**Unused JS packages:**
```bash
# depcheck — finds unused and missing packages
npx depcheck --json 2>/dev/null | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    unused = data.get('dependencies', [])
    unused_dev = data.get('devDependencies', [])
    missing = data.get('missing', {})
    if unused: print('UNUSED PROD:', unused)
    if unused_dev: print('UNUSED DEV:', unused_dev)
    if missing: print('MISSING (used but not in package.json):', list(missing.keys()))
except: pass
" 2>/dev/null || npx depcheck 2>/dev/null
```

**Bundle size impact of new or changed deps:**
```bash
# Check for known large packages that have lighter alternatives
node -e "
const pkg = require('./package.json');
const all = {...(pkg.dependencies||{}), ...(pkg.devDependencies||{})};
const heavy = {
  'moment': 'Use date-fns or dayjs (moment is 67kb gzipped, date-fns is tree-shakeable)',
  'lodash': 'Use lodash-es for tree-shaking, or native JS — full lodash is 24kb gzipped',
  'axios': 'Consider native fetch + wrapping — axios adds 13kb gzipped',
  'styled-components': 'If using Tailwind, styled-components is redundant',
  'classnames': 'Consider clsx (smaller) or the cn() pattern with tailwind-merge',
};
for (const [pkg, note] of Object.entries(heavy)) {
  if (all[pkg]) console.log('BUNDLE-HEAVY:', pkg, '—', note);
}
" 2>/dev/null
```

**Pinning discipline:**
```bash
node -e "
const pkg = require('./package.json');
const all = {...(pkg.dependencies||{}), ...(pkg.devDependencies||{})};
for (const [name, version] of Object.entries(all)) {
  if (version.startsWith('^') || version.startsWith('~') ||
      version === 'latest' || version === '*') {
    const risk = version === 'latest' || version === '*' ? 'CRITICAL' : 'LOW';
    console.log(risk + ' UNPINNED:', name + '@' + version);
  }
}
" 2>/dev/null
```

`^` prefixes in `package.json` + committed `package-lock.json` = acceptable
(lockfile pins the actual version). `^` without a lockfile = [DEP-UNPINNED].
`latest` or `*` anywhere = [DEP-UNPINNED-CRITICAL].

**Stack-specific JS version checks:**

React ecosystem — flag if behind these minimums:
```
react              >= 18.3.0   (concurrent features stability)
react-dom          >= 18.3.0
@tanstack/react-query >= 5.0.0 (v5 has breaking changes from v4 — note if on v4)
react-router-dom   >= 6.22.0   (security + loader fixes)
typescript         >= 5.4.0    (performance + type safety)
vite               >= 5.2.0    (security fixes in dev server)
@vitejs/plugin-react >= 4.2.0
tailwindcss        >= 3.4.0    (JIT stability)
```

Mapping/geo libraries if present:
```
leaflet            >= 1.9.4    (XSS fixes in popup rendering)
mapbox-gl          >= 3.3.0    (security patches)
maplibre-gl        >= 4.1.0
@turf/turf         >= 6.5.0    (geometry correctness fixes)
```

Flag each below minimum as [DEP-JS-OUTDATED] with changelog reference.

**React Query v4 → v5 migration flag:**
```bash
node -e "
const pkg = require('./package.json');
const rq = pkg.dependencies?.['@tanstack/react-query'] ||
           pkg.dependencies?.['react-query'];
if (rq && (rq.startsWith('4') || rq.startsWith('^4'))) {
  console.log('RQ-V4: @tanstack/react-query is v4 — v5 has significant API changes.');
  console.log('Breaking: useQuery options restructured, cacheTime renamed gcTime,');
  console.log('onSuccess/onError/onSettled removed from useQuery.');
  console.log('Plan migration: https://tanstack.com/query/v5/docs/framework/react/guides/migrating-to-v5');
}
" 2>/dev/null
```

Output: findings labeled [DEP-CVE-CRITICAL], [DEP-CVE-HIGH], [DEP-CVE-MODERATE],
[DEP-UNPINNED], [DEP-POSSIBLY-UNUSED], [DEP-JS-OUTDATED], [DEP-BUNDLE-HEAVY].

---

### Subagent C — Docker base image audit
**Goal: every base image is pinned, current, and not EOL**

**Extract all base images:**
```bash
grep -rn "^FROM\|^from" Dockerfile* api/Dockerfile* \
  frontend/Dockerfile* 2>/dev/null | \
  grep -v "^Binary\|#" | sort -u
```

**For each base image, check:**

**Pinning — tags vs digests:**
```
# RISKY — mutable tag, image can change silently
FROM python:3.12-slim

# SAFE — immutable digest
FROM python:3.12-slim@sha256:abc123...

# ACCEPTABLE — specific patch version tag in CI with digest in prod
FROM python:3.12.4-slim
```

Flag `FROM python:latest`, `FROM node:latest`, `FROM postgres:latest`,
or any image without a patch-level version tag = [DOCKER-UNPINNED].

**EOL / support status:**
```bash
# Check Python version EOL
python3 -c "
import datetime
eol = {
    '3.8': '2024-10-07',
    '3.9': '2025-10-05',
    '3.10': '2026-10-04',
    '3.11': '2027-10-24',
    '3.12': '2028-10-02',
    '3.13': '2029-10-08',
}
today = datetime.date.today().isoformat()
for v, date in eol.items():
    if date < today:
        print(f'EOL: Python {v} reached end-of-life {date}')
    elif date < (datetime.date.today() + datetime.timedelta(days=180)).isoformat():
        print(f'EOL-SOON: Python {v} reaches end-of-life {date} (within 6 months)')
" 2>/dev/null
```

Flag any EOL base image = [DOCKER-EOL].
Flag any image reaching EOL within 6 months = [DOCKER-EOL-SOON].

**PostGIS image specifically:**
```bash
grep -rn "postgis" Dockerfile* docker-compose*.yml 2>/dev/null
```

PostGIS images follow the pattern `postgis/postgis:[postgres-version]-[postgis-version]`.
Check:
- Is Postgres version in the image current? (flag if < 15)
- Is PostGIS version current? (flag if < 3.4)
- Is the exact image digest pinned in production compose?
```yaml
# WRONG — unpinned, any new image silently installs
image: postgis/postgis:latest

# SAFE — pinned to specific version
image: postgis/postgis:16-3.4

# PRODUCTION-SAFE — pinned to digest
image: postgis/postgis:16-3.4@sha256:abc123...
```

**pgvector image:**
```bash
grep -rn "pgvector\|ankane/pgvector" Dockerfile* docker-compose*.yml 2>/dev/null
```

If using a custom image with pgvector extension:
- Is the pgvector version pinned in the Dockerfile?
  `RUN apt-get install -y postgresql-16-pgvector=0.7.0*`
- pgvector < 0.7.0 lacks HNSW index type (only IVFFlat) — recommend upgrade
- pgvector < 0.5.0 has accuracy issues with large datasets

**Trivy image scan:**
```bash
# Scan each image for OS-level CVEs
for image in $(grep -h "^FROM" Dockerfile* 2>/dev/null | \
  awk '{print $2}' | grep -v "^--" | sort -u); do
  echo "=== Scanning: $image ==="
  trivy image --severity HIGH,CRITICAL --quiet "$image" 2>/dev/null || \
    echo "trivy not available for $image — run: trivy image $image"
done
```

**Multi-stage build audit:**
```bash
cat Dockerfile* 2>/dev/null | grep -E "^FROM|^COPY --from"
```

Verify build-stage artifacts (dev dependencies, build tools, source code)
are not copied into the final stage. Common mistake:
```dockerfile
# WRONG — copies entire source including dev deps
FROM python:3.12-slim as builder
RUN pip install -r requirements-dev.txt
...
FROM python:3.12-slim
COPY --from=builder / /    # copies EVERYTHING including dev deps

# CORRECT — copy only what runtime needs
COPY --from=builder /app/dist /app/dist
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
```

Output: findings labeled [DOCKER-UNPINNED], [DOCKER-EOL], [DOCKER-EOL-SOON],
[DOCKER-POSTGIS-OUTDATED], [DOCKER-PGVECTOR-OUTDATED], [DOCKER-LAYER-LEAK].

---

### Subagent D — License audit
**Goal: identify every license that could create legal or distribution risk**

**Python license extraction:**
```bash
pip install pip-licenses --quiet 2>/dev/null
pip-licenses --format=json --with-urls --with-description 2>/dev/null | \
  python3 -c "
import json, sys
data = json.load(sys.stdin)
risky = {
    'GPL-2.0': 'COPYLEFT-STRONG',
    'GPL-3.0': 'COPYLEFT-STRONG',
    'AGPL-3.0': 'COPYLEFT-NETWORK',  # triggers on network use
    'LGPL-2.0': 'COPYLEFT-WEAK',
    'LGPL-2.1': 'COPYLEFT-WEAK',
    'LGPL-3.0': 'COPYLEFT-WEAK',
    'SSPL-1.0': 'SOURCE-AVAILABLE',
    'BSL-1.1': 'SOURCE-AVAILABLE',
    'CC-BY-NC': 'NON-COMMERCIAL',
    'UNKNOWN': 'REVIEW-REQUIRED',
}
for pkg in sorted(data, key=lambda x: x['Name']):
    lic = pkg.get('License', 'UNKNOWN')
    for risk_lic, risk_type in risky.items():
        if risk_lic.lower() in lic.lower():
            print(f'[{risk_type}] {pkg[\"Name\"]}=={pkg[\"Version\"]} — {lic}')
            print(f'  URL: {pkg.get(\"URL\", \"N/A\")}')
" 2>/dev/null || pip-licenses 2>/dev/null
```

**JavaScript license extraction:**
```bash
npx license-checker --json --production 2>/dev/null | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    risky_keywords = ['gpl', 'agpl', 'sspl', 'bsl', 'non-commercial', 'unknown']
    for name, info in sorted(data.items()):
        lic = info.get('licenses', 'UNKNOWN')
        if isinstance(lic, list): lic = ', '.join(lic)
        if any(k in lic.lower() for k in risky_keywords):
            print(f'REVIEW: {name} — {lic}')
            print(f'  repo: {info.get(\"repository\", \"N/A\")}')
except: pass
" 2>/dev/null || npx license-checker --onlyAllow \
  'MIT;ISC;BSD-2-Clause;BSD-3-Clause;Apache-2.0;CC0-1.0;Unlicense;Python-2.0;PSF' \
  2>/dev/null
```

**License risk classification:**

| License | Risk | Why |
|---------|------|-----|
| MIT, ISC, BSD-2/3, Apache-2.0 | ✅ None | Permissive |
| LGPL-2/3 | ⚠️ Low | Weak copyleft — OK if dynamically linked, risky if statically linked or modified |
| GPL-2/3 | 🔴 High | Strong copyleft — using GPL code may require open-sourcing your code |
| AGPL-3.0 | 🔴 Critical | Network copyleft — using AGPL over a network (i.e., SaaS) triggers source disclosure |
| SSPL-1.0 | 🔴 Critical | Source-available, not open source — MongoDB license, triggers on service providers |
| BSL-1.1 | ⚠️ Medium | Business Source License — becomes open source after 4 years, but has restrictions before |
| UNKNOWN | ⚠️ Must review | No license = all rights reserved by default |

**PostGIS / pgvector license check:**
```
PostGIS:  GPL-2.0 — server-side, not distributed in your binary, generally safe for SaaS
pgvector: PostgreSQL License (permissive) — safe
GeoAlchemy2: MIT — safe
shapely: BSD-3-Clause — safe
```

Note: PostGIS is GPL-2.0 but runs as a Postgres extension on the server.
Since you're not distributing PostGIS code itself, this is generally not a
licensing issue for a SaaS application. Flag for legal review if the product
is distributed as packaged software (not SaaS).

**Dual-licensed packages:**
```bash
# Some packages have separate commercial licenses for production use
node -e "
const commercial = {
  'ag-grid-community': 'AG Grid has a commercial license for enterprise features',
  'highcharts': 'Highcharts requires commercial license for commercial use',
  'handsontable': 'Handsontable CE is AGPL; Pro requires commercial license',
  'devextreme': 'DevExtreme requires commercial license',
};
const pkg = require('./package.json');
const all = {...(pkg.dependencies||{}), ...(pkg.devDependencies||{})};
for (const [p, note] of Object.entries(commercial)) {
  if (all[p]) console.log('COMMERCIAL-REQUIRED:', p, '—', note);
}
" 2>/dev/null
```

Output: findings labeled [LICENSE-COPYLEFT-STRONG], [LICENSE-AGPL],
[LICENSE-UNKNOWN], [LICENSE-COMMERCIAL-REQUIRED], [LICENSE-REVIEW].

---

### Subagent E — Stack extension audit (PostGIS, pg_trgm, pgvector)
**Goal: verify extension packages, drivers, and integration libraries are
current, compatible, and correctly configured**

**Python extension library versions:**
```bash
pip show geoalchemy2 shapely psycopg2-binary asyncpg \
  pgvector sqlalchemy-utils 2>/dev/null | \
  grep -E "^Name:|^Version:|^Requires:|^Required-by:"
```

**GeoAlchemy2:**
```bash
python3 -c "import geoalchemy2; print('GeoAlchemy2:', geoalchemy2.__version__)" \
  2>/dev/null
```

Version checks:
- `GeoAlchemy2 < 0.14` — missing `WKBElement.as_wkb()`, limited async support
- `GeoAlchemy2 < 0.15` — `ST_AsGeoJSON` serialization issues with custom types
- Current stable: check `pip index versions geoalchemy2 2>/dev/null | head -1`

Compatibility matrix check:
```bash
python3 -c "
import geoalchemy2, sqlalchemy
geo_v = tuple(int(x) for x in geoalchemy2.__version__.split('.')[:2])
sa_v = tuple(int(x) for x in sqlalchemy.__version__.split('.')[:2])
if sa_v >= (2, 0) and geo_v < (0, 14):
    print('COMPAT ERROR: GeoAlchemy2 < 0.14 is not fully compatible with SQLAlchemy 2.0')
    print('Upgrade: pip install geoalchemy2>=0.14')
" 2>/dev/null
```

**Shapely:**
```bash
python3 -c "import shapely; print('Shapely:', shapely.__version__)" 2>/dev/null
```
- `Shapely < 2.0` — slow Python-only operations, missing GEOS 3.11 functions
- `Shapely 2.x` requires GEOS >= 3.11 in the system — verify in Docker image:
```bash
  docker run --rm [api-image] geos-config --version 2>/dev/null || true
```

**pgvector Python client:**
```bash
python3 -c "import pgvector; print('pgvector:', pgvector.__version__)" 2>/dev/null
pip show pgvector 2>/dev/null | grep Version
```

Version checks:
- `pgvector < 0.2.0` — missing `register_vector()` for asyncpg, HNSW not supported
- `pgvector < 0.3.0` — missing `SparseVector` type
- Verify pgvector Python client version matches server extension version:
```bash
# Server extension version (if DB is accessible)
docker compose exec db psql -U postgres -c \
  "SELECT extversion FROM pg_extension WHERE extname = 'vector';" 2>/dev/null || \
  echo "DB not running — check manually"
```

**Database driver — asyncpg vs psycopg:**
```bash
pip show asyncpg psycopg psycopg2-binary psycopg2 2>/dev/null | \
  grep -E "^Name:|^Version:"
```

Driver recommendations for your async FastAPI stack:
- `asyncpg` — fastest async driver, recommended for production
- `psycopg[async]` (psycopg3) — newer, more feature-complete, supports `COPY` protocol
- `psycopg2-binary` in production Docker image = [EXT-PSYCOPG2-BINARY]:
  the binary wheel bundles its own libpq — use `psycopg2` (source build) or
  `psycopg[async]` instead for production
```bash
# Check if psycopg2-binary is in production requirements (not just dev)
grep "psycopg2-binary" requirements.txt 2>/dev/null && \
  echo "WARNING: psycopg2-binary in production requirements — use psycopg2 or psycopg[async]"
```

**Extension version compatibility matrix:**

Check that server-side extensions match client library expectations:
```bash
# PostGIS server version
docker compose exec db psql -U postgres -c \
  "SELECT PostGIS_Version();" 2>/dev/null | grep -oE "[0-9]+\.[0-9]+" | head -1

# pg_trgm (bundled with Postgres, version = postgres version)
docker compose exec db psql -U postgres -c \
  "SELECT extversion FROM pg_extension WHERE extname = 'pg_trgm';" 2>/dev/null

# pgvector server version
docker compose exec db psql -U postgres -c \
  "SELECT extversion FROM pg_extension WHERE extname = 'vector';" 2>/dev/null
```

Flag any mismatch between server extension version and client library
expectations as [EXT-VERSION-MISMATCH].

**Extension registration in app startup:**
```bash
grep -rn "register_vector\|create_engine.*vector\|configure_mappers\|\
register_geometry_type\|setup_all\|listen.*connect" api/ --include="*.py"
```

pgvector requires explicit registration with asyncpg:
```python
# MISSING — pgvector types not registered, queries will fail
engine = create_async_engine(DATABASE_URL)

# CORRECT — register vector type on each new connection
from pgvector.asyncpg import register_vector

async def on_connect(conn):
    await register_vector(conn)

engine = create_async_engine(
    DATABASE_URL,
    connect_args={"server_settings": {"jit": "off"}},
)

@event.listens_for(engine.sync_engine, "connect")
def connect(dbapi_connection, connection_record):
    dbapi_connection.run_async(register_vector)
```

Flag missing `register_vector` when pgvector is in requirements =
[EXT-PGVECTOR-NOT-REGISTERED].

**Alembic extension migrations:**
```bash
# Check that extensions are created in migrations, not assumed to exist
grep -rn "CREATE EXTENSION\|op.execute.*CREATE EXTENSION\|postgis\|pg_trgm\|vector" \
  alembic/versions/ --include="*.py" | head -10
```

Extensions should be created in a migration, not manually:
```python
# In an early Alembic migration
def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

def downgrade():
    # Usually don't drop extensions in downgrade — they may have data
    pass
```

Flag missing extension creation migrations as [EXT-NO-MIGRATION].

Output: findings labeled [EXT-GEOALCHEMY-OUTDATED], [EXT-SHAPELY-OUTDATED],
[EXT-PGVECTOR-OUTDATED], [EXT-VERSION-MISMATCH], [EXT-PSYCOPG2-BINARY],
[EXT-PGVECTOR-NOT-REGISTERED], [EXT-NO-MIGRATION].

---

## Phase 3 — Triage and upgrade plan

Merge all subagent outputs. For every finding, produce:
```markdown
# Dependency audit report
Date: [date]
Stack: FastAPI · React · Docker · Postgres · PostGIS · pg_trgm · pgvector

## Summary

| Category         | Total deps | CVEs | Outdated | Unused | License risk |
|-----------------|-----------|------|---------|--------|-------------|
| Python           | N         | N    | N       | N      | N           |
| JavaScript       | N         | N    | N       | N      | N           |
| Docker images    | N         | —    | N       | —      | —           |
| Stack extensions | N         | N    | N       | —      | N           |

## Merge gate: BLOCK / PASS

Blocking conditions:
- [ ] Critical CVEs (CVSS >= 9.0): [count]
- [ ] High CVEs (CVSS >= 7.0) in direct dependencies: [count]
- [ ] AGPL or GPL dependencies requiring legal review: [count]
- [ ] EOL base images: [count]
- [ ] psycopg2-binary in production image: [yes/no]
- [ ] pgvector not registered with asyncpg: [yes/no]

## Upgrade plan

### 🔴 Immediate (block merge)
[Each: package, current version, target version, CVE/reason, upgrade command,
breaking change risk]

### 🟠 This sprint
[Each: package, current version, target version, reason, upgrade command,
breaking change risk]

### 🟡 Next sprint
[Each: package, outdated by N majors/minors, upgrade command, migration notes]

### 🟢 Backlog
[Low-priority outdated packages, unused packages to consider removing]

## Upgrade commands

\`\`\`bash
# === IMMEDIATE — apply before merge ===

# Python CVE fixes
pip install [package]==[safe-version]
# Update requirements.txt:
sed -i 's/[package]==[old]/[package]==[new]/' requirements.txt

# JS CVE fixes
npm install [package]@[safe-version]
# Force resolution of transitive vulnerabilities:
npm install --save-exact [package]@[safe-version]

# === THIS SPRINT ===
pip install --upgrade [package1] [package2]
npm install [package]@latest

# === DOCKER ===
# Update base image tags in Dockerfile(s)
\`\`\`

## License inventory
[Full table: package, license, risk level, action required]

## Unused packages to remove (verify before deleting)
\`\`\`bash
# Python
pip uninstall [package]
sed -i '/^[package]/d' requirements.txt

# JS
npm uninstall [package]
\`\`\`
```

---

## Phase 4 — Generate CI configuration

Produce `.github/workflows/dep-audit.yml` (or equivalent) to run dependency
scanning on every PR automatically:
```yaml
# .github/workflows/dep-audit.yml
name: Dependency audit

on:
  pull_request:
  schedule:
    - cron: '0 8 * * 1'  # every Monday morning

jobs:
  python-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install deps
        run: pip install -r requirements.txt pip-audit safety

      - name: pip-audit (OSV database)
        run: pip-audit --strict

      - name: safety check
        run: safety check --full-report
        env:
          SAFETY_API_KEY: ${{ secrets.SAFETY_API_KEY }}  # optional, more results

      - name: License check
        run: |
          pip install pip-licenses
          pip-licenses --fail-on="GPL-3.0;AGPL-3.0;SSPL-1.0"

  js-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Node
        uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'

      - name: Install deps
        run: npm ci

      - name: npm audit
        run: npm audit --audit-level=high

      - name: License check
        run: |
          npx license-checker --production \
            --onlyAllow 'MIT;ISC;BSD-2-Clause;BSD-3-Clause;Apache-2.0;CC0-1.0;Unlicense;Python-2.0;PSF-2.0;BlueOak-1.0.0'

  docker-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Trivy scan — API image
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: 'python:3.12-slim'
          format: 'table'
          severity: 'CRITICAL,HIGH'
          exit-code: '1'

      - name: Trivy scan — PostGIS image
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: 'postgis/postgis:16-3.4'
          format: 'table'
          severity: 'CRITICAL,HIGH'
          exit-code: '1'
```

Also output a `dependabot.yml` configuration:
```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: pip
    directory: /
    schedule:
      interval: weekly
      day: monday
      time: "08:00"
    groups:
      fastapi-ecosystem:
        patterns:
          - "fastapi"
          - "uvicorn"
          - "starlette"
          - "pydantic*"
      sqlalchemy-ecosystem:
        patterns:
          - "sqlalchemy*"
          - "alembic"
          - "asyncpg"
          - "psycopg*"
      geo-stack:
        patterns:
          - "geoalchemy2"
          - "shapely"
          - "pgvector"
    ignore:
      - dependency-name: "*"
        update-types: ["version-update:semver-major"]  # major bumps via PR only

  - package-ecosystem: npm
    directory: /
    schedule:
      interval: weekly
      day: monday
      time: "08:00"
    groups:
      react-ecosystem:
        patterns:
          - "react"
          - "react-dom"
          - "@types/react*"
      tanstack:
        patterns:
          - "@tanstack/*"
    ignore:
      - dependency-name: "*"
        update-types: ["version-update:semver-major"]

  - package-ecosystem: docker
    directory: /
    schedule:
      interval: weekly
```

---

## Phase 5 — Deliver

**1. Write `docs-internal/dep-audit-[date].md`** with the full report.

**2. If `--fix` flag is set:**

Show the user exactly what will change and ask for confirmation:
```
The following SAFE upgrades will be applied (patch + minor, no known breaking changes):

Python:
  cryptography: 41.0.7 → 42.0.8   (CVE fixes)
  pillow:       10.2.0 → 10.3.0   (CVE-2024-28219)
  httpx:        0.26.0 → 0.27.2   (security patches)

JavaScript:
  @tanstack/react-query: 5.28.0 → 5.35.1  (bug fixes)
  vite:                  5.1.6  → 5.2.11  (dev server security)

Proceed? [y/N]
```

Only after confirmation, apply:
```bash
# Python safe upgrades
pip install cryptography==42.0.8 pillow==10.3.0 httpx==0.27.2
pip freeze | grep -E "cryptography|pillow|httpx" >> requirements.txt.new
# [merge into requirements.txt]

# JS safe upgrades
npm install @tanstack/react-query@5.35.1 vite@5.2.11
```

**3. Update `lessons.md`:**
```markdown
## [date] — Dependency audit
### CVEs found and fixed
### Packages removed (unused)
### License risks identified
### Extension compatibility issues
### Dependabot config added: yes/no
```

---

## DELIVERY

### Output format

Write the report to: `docs-internal/audits/dependency-audit-{YYYYMMDD}.md`

### Post-delivery

1. If a previous `dependency-audit-*.md` exists in `docs-internal/audits/`, diff key findings against the prior report.
2. Print one-line summary: overall risk grade + CVE count (Critical/High) + total outdated packages.

---

## RELATIONSHIP TO OTHER COMMANDS

- `/sec-audit` — covers dependency CVEs in its Subagent E, but focuses on exploitability. This command provides comprehensive dependency lifecycle management: version freshness, license risk, unused packages, and upgrade paths.
- `/docker-audit` — covers Docker base image versions. This command covers application-level dependencies inside those images.

---

## What NOT to flag

- `^` version prefixes in `package.json` when a committed `package-lock.json`
  pins the actual installed version
- `psycopg2-binary` in `requirements-dev.txt` (fine for local dev, just not prod)
- PostGIS GPL-2.0 license in a SaaS deployment (server-side only, not distributed)
- Outdated `devDependencies` with no CVEs and no production bundle impact
- Major version bumps surfaced by `npm outdated` — these require migration
  planning, not auto-upgrade
- `shapely < 2.0` in files not touched by the current branch unless running
  full audit
- Transitive dependency CVEs with no direct upgrade path and `npm audit fix`
  would introduce a breaking change — note them, don't block
- `UNKNOWN` license on packages that are clearly MIT (some packages omit
  the license field in package.json but have a LICENSE file — verify before flagging)
- pgvector `HNSW` vs `IVFFlat` index choice — that's a `/post-impl` concern,
  not a dependency concern