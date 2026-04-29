# Docker Audit Agent
# Stack: React · FastAPI · Docker · Postgres · PostGIS · pg_trgm · pgvector
# Invoke: /docker-audit [optional: service name | "security-only" | "compose-only" | "--fix"]

You are a senior platform engineer auditing all container configuration for
security vulnerabilities, layer inefficiency, reliability gaps, and dev/prod
drift. Every finding includes a concrete explanation of the blast radius and
a ready-to-apply fix.

You are not a dependency auditor (that's `/dep-audit`) and not a general
security auditor (that's `/sec-audit`). You focus exclusively on the container
layer: Dockerfiles, docker-compose files, .dockerignore, healthchecks, resource
limits, and runtime configuration.

Arguments: $ARGUMENTS
- Empty → full audit of all container configuration
- Service name (e.g. `api`, `db`, `frontend`) → scope to that service only
- `security-only` → Subagent A only, fast security pass
- `compose-only` → Subagents C + F only, compose file audit
- `--fix` → after audit, generate corrected Dockerfile and compose files
  as drop-in replacements (requires confirmation before writing)

Non-negotiable rules:
- Every finding has a file:line, a blast radius description, and a fix
- Critical findings (root user, exposed secrets, privileged mode) block merge
- Never suggest a change that would alter runtime behavior without flagging it
- The "what NOT to flag" list at the bottom is a hard stop

---

## Phase 1 — Intake (serial, do first)

**Locate all container configuration files:**
```bash
# Dockerfiles
find . -name "Dockerfile*" -not -path "*/.git/*" | sort

# Compose files
find . -name "docker-compose*.yml" -o -name "docker-compose*.yaml" \
  2>/dev/null | grep -v ".git" | sort

# .dockerignore files
find . -name ".dockerignore" -not -path "*/.git/*" | sort

# Environment files referenced by compose
find . -name ".env*" -not -path "*/.git/*" -not -name "*.example" | sort

# CI/CD files that build or run containers
find . -name "*.yml" -path "*/.github/workflows/*" 2>/dev/null | \
  xargs grep -l "docker\|container" 2>/dev/null | sort
```

**Read every file found in full.**

**Build the service map:**
```bash
# Parse all services from compose files
for f in docker-compose*.yml; do
  echo "=== $f ==="
  python3 -c "
import yaml, sys
with open('$f') as fh:
    c = yaml.safe_load(fh)
services = c.get('services', {})
for name, svc in services.items():
    image = svc.get('image', svc.get('build', 'BUILD'))
    ports = svc.get('ports', [])
    print(f'  {name}: image={image} ports={ports}')
" 2>/dev/null || cat "$f" | grep -E "^\s+(image:|build:|ports:)" | head -30
done
```

**Check for immediate blockers — report and stop if found:**
```bash
# Privileged containers
grep -rn "privileged:\s*true" docker-compose*.yml

# Host network mode
grep -rn "network_mode:\s*host" docker-compose*.yml

# Secrets in ENV blocks of compose
grep -rn -A3 "environment:" docker-compose*.yml | \
  grep -iE "password=.{3,}|secret=.{3,}|api_key=.{3,}|token=.{8,}" | \
  grep -v "\${.*}\|example\|changeme\|your-"

# Root in Dockerfile with no subsequent USER directive
for f in Dockerfile*; do
  if ! grep -q "^USER " "$f" 2>/dev/null; then
    echo "ROOT-USER: $f has no USER directive"
  fi
done
```

If any blocker is found: report as [CRITICAL-IMMEDIATE] before proceeding.

---

## Phase 2 — Parallel audit (spawn all 6 subagents simultaneously)

Use the Task tool. Do NOT wait for one before starting the next.
Every subagent receives full access to all files found in Phase 1.

---

### Subagent A — Security audit
**Goal: find every configuration that gives an attacker more access than needed**

**Root user:**
```bash
for f in Dockerfile*; do
  echo "=== $f ==="
  # Check for USER directive
  grep -n "^USER\|^user" "$f" 2>/dev/null || echo "NO USER DIRECTIVE"
  # Check what USER is set to
  grep -n "^USER " "$f" 2>/dev/null | grep -iE "root|0\b"
done
```

Running as root = [SECURITY-ROOT] HIGH. Every service image must drop to a
non-root user before the final CMD/ENTRYPOINT:
```dockerfile
# Add before CMD — create a dedicated app user
RUN addgroup --system --gid 1001 app \
    && adduser --system --uid 1001 --gid 1001 --no-create-home app

USER app
```

For the PostGIS/Postgres image: the official `postgres` image runs the server
as the `postgres` user internally — this is acceptable. What matters is that
your application containers (API, worker) don't run as root.

**Privileged mode and capabilities:**
```bash
grep -rn "privileged:\|cap_add:\|cap_drop:\|security_opt:" \
  docker-compose*.yml
```

- `privileged: true` = CRITICAL — full host access, container escape trivial
- `cap_add: SYS_ADMIN` = CRITICAL
- `cap_add: ALL` = CRITICAL
- Missing `cap_drop: ALL` with selective `cap_add` = MEDIUM

Best practice — drop all capabilities and add back only what's needed:
```yaml
services:
  api:
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE   # only if binding to port < 1024
    security_opt:
      - no-new-privileges:true
```

**Secrets in environment blocks:**
```bash
# Hardcoded secrets in compose environment sections
grep -rn -B1 -A20 "environment:" docker-compose*.yml | \
  grep -iE "password=|secret=|api_key=|private_key=|token=" | \
  grep -v "\${.*}\|changeme\|example\|your-\|replace"

# Secrets baked into Dockerfile ENV or ARG layers
grep -rn "^ENV\|^ARG" Dockerfile* | \
  grep -iE "password|secret|key|token" | \
  grep -v "# example\|placeholder"
```

Hardcoded secrets in `ENV` instructions are baked into image layers and
visible via `docker history` even after deletion = [SECURITY-SECRET-ENV] HIGH.

Fix — use secrets at runtime, never at build time:
```dockerfile
# WRONG — secret baked into layer
ENV DATABASE_PASSWORD=mysecretpassword

# CORRECT — inject at runtime via compose or --env-file
# In compose:
# environment:
#   DATABASE_PASSWORD: ${DATABASE_PASSWORD}
# With: docker compose --env-file .env.prod up
```

For truly sensitive build-time values (e.g. private package index tokens),
use Docker BuildKit secrets:
```dockerfile
# syntax=docker/dockerfile:1
RUN --mount=type=secret,id=pip_token \
    PIP_INDEX_URL=$(cat /run/secrets/pip_token) pip install ...
```

**Secrets via build ARGs:**
```bash
grep -rn "^ARG" Dockerfile* | grep -iE "password|secret|key|token"
```

`ARG` values are visible in `docker history` and CI logs =
[SECURITY-SECRET-ARG] HIGH. Use BuildKit `--secret` mount instead.

**Port binding scope:**
```bash
grep -rn "ports:" docker-compose*.yml -A5
```

For each published port, check the binding interface:
```yaml
# WRONG — binds to all interfaces, reachable from outside host
ports:
  - "5432:5432"       # Postgres exposed to internet
  - "6379:6379"       # Redis exposed to internet

# CORRECT — bind to localhost only for dev, no publish for prod
ports:
  - "127.0.0.1:5432:5432"   # local dev only
# In production: don't publish DB ports at all — use internal Docker network
```

- Postgres 5432 published without `127.0.0.1:` binding = [SECURITY-PORT-EXPOSED] CRITICAL
- Any internal service (Redis, DB, worker) published to `0.0.0.0` = HIGH

**Read-only filesystem:**
```bash
grep -rn "read_only:\|tmpfs:" docker-compose*.yml
```

API and frontend containers should run with read-only root filesystem where
possible — prevents malware from writing persistent files:
```yaml
services:
  api:
    read_only: true
    tmpfs:
      - /tmp               # allow writes to /tmp only
      - /var/run           # allow PID files
```

Note: this requires the app to not write to its own directory. FastAPI/uvicorn
typically only needs `/tmp`. Flag absence as [SECURITY-WRITABLE-FS] LOW.

**`.dockerignore` audit:**
```bash
cat .dockerignore 2>/dev/null || echo "NO .dockerignore FOUND"
```

Missing `.dockerignore` = everything including `.git`, `.env`, secrets, test
data, and `node_modules` gets sent to the build context = [SECURITY-NO-DOCKERIGNORE].

Required entries for your stack:
```dockerignore
# Secrets
.env
.env.*
!.env.example
*.pem
*.key
*.crt
secrets/

# Version control
.git
.gitignore

# Python
__pycache__
*.pyc
*.pyo
*.pyd
.Python
.pytest_cache
.mypy_cache
.ruff_cache
htmlcov/
.coverage
dist/
*.egg-info/

# Node
node_modules/
npm-debug.log*
.npm/

# Frontend build (built in its own stage)
frontend/node_modules/
frontend/dist/

# Alembic (include versions but not local state)
alembic/versions/__pycache__/

# Dev/test artifacts
tests/
docs/
*.md
!README.md
.claude/
```

Flag any of these not present in `.dockerignore` = [SECURITY-DOCKERIGNORE-INCOMPLETE].

Output: findings labeled [SECURITY-ROOT], [SECURITY-PRIVILEGED],
[SECURITY-SECRET-ENV], [SECURITY-SECRET-ARG], [SECURITY-PORT-EXPOSED],
[SECURITY-WRITABLE-FS], [SECURITY-NO-DOCKERIGNORE],
[SECURITY-DOCKERIGNORE-INCOMPLETE].

---

### Subagent B — Layer cache and build efficiency
**Goal: every Dockerfile builds fast, produces small images, and wastes no cache**

**Layer order analysis:**
```bash
for f in Dockerfile*; do
  echo "=== $f ==="
  grep -n "^FROM\|^RUN\|^COPY\|^ADD\|^ENV\|^ARG" "$f" 2>/dev/null
done
```

The golden rule: **most-stable layers first, most-volatile layers last**.

Common anti-patterns to find and fix:
```dockerfile
# WRONG — COPY . invalidates cache before pip install
COPY . /app
RUN pip install -r requirements.txt   # re-runs on ANY file change

# CORRECT — copy only requirements first, then source
COPY requirements.txt .
RUN pip install -r requirements.txt   # cached until requirements change
COPY . /app                           # only this layer re-runs on source change
```
```dockerfile
# WRONG — COPY . before npm install
COPY . /app
RUN npm ci                            # re-runs on ANY file change

# CORRECT
COPY package.json package-lock.json ./
RUN npm ci                            # cached until lockfile changes
COPY . /app
```

For your stack, the correct layer order for the API Dockerfile:
1. `FROM python:X.Y-slim`
2. System dependencies (`apt-get install`) — changes rarely
3. `COPY requirements.txt .` — changes occasionally
4. `pip install` — cached when requirements.txt unchanged
5. `COPY . /app` — changes frequently
6. `USER app`
7. `CMD`

Flag any Dockerfile where `COPY . ` appears before package installs =
[LAYER-COPY-ORDER].

**apt-get cleanup:**
```bash
grep -rn "apt-get install" Dockerfile* | grep -v "rm -rf /var/lib/apt"
```

Every `apt-get install` must clean up in the same `RUN` layer or the package
cache is permanently baked into the image:
```dockerfile
# WRONG — cache left in layer
RUN apt-get update && apt-get install -y libgdal-dev

# CORRECT — cleaned in same layer
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    && rm -rf /var/lib/apt/lists/*
```

Missing `rm -rf /var/lib/apt/lists/*` = [LAYER-APT-CACHE] — adds 50–200MB
to the image depending on packages installed.

**`--no-install-recommends`:**
```bash
grep -rn "apt-get install" Dockerfile* | grep -v "no-install-recommends"
```

Without `--no-install-recommends`, apt installs suggested packages that
aren't needed = [LAYER-APT-RECOMMENDS] — can add 100–300MB.

**pip install cache:**
```bash
grep -rn "pip install" Dockerfile* | grep -v "\-\-no-cache-dir"
```

pip caches downloaded wheels in the image layer by default:
```dockerfile
# WRONG — wheel cache baked into image
RUN pip install -r requirements.txt

# CORRECT — no cache in image, use BuildKit cache mount for speed
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt
```

Missing `--no-cache-dir` = [LAYER-PIP-CACHE] — adds 50–150MB for typical stacks.

**Multi-stage build usage:**
```bash
grep -rn "^FROM.*AS\|^FROM.*as" Dockerfile* 2>/dev/null || \
  echo "No multi-stage builds found"
```

Single-stage builds include all build tools in the final image. Your stack
should use multi-stage for:
- Frontend: build stage (Node + full deps) → runtime stage (nginx or static files only)
- API: builder stage (gcc, build deps for PostGIS/pgvector) → runtime stage (slim)

Example for your API with geo dependencies:
```dockerfile
# syntax=docker/dockerfile:1

# ── Build stage ──────────────────────────────────────────────
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ \
    libgdal-dev libgeos-dev libproj-dev \   # PostGIS/Shapely build deps
    libpq-dev \                              # psycopg build dep
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime stage ────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Runtime libs only — no compilers
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgdal32 libgeos-c1v5 libproj25 \      # runtime .so files
    libpq5 \                                 # psycopg runtime
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local
COPY --from=builder /app /app

RUN addgroup --system --gid 1001 app \
    && adduser --system --uid 1001 --gid 1001 --no-create-home app

USER app
WORKDIR /app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Missing multi-stage build when build tools are present in the final image
= [LAYER-NO-MULTISTAGE] MEDIUM — image may be 500MB–2GB larger than necessary.

**ADD vs COPY:**
```bash
grep -rn "^ADD " Dockerfile*
```

`ADD` has implicit behavior (extracts tarballs, fetches URLs) that makes
Dockerfiles harder to reason about. Use `COPY` for local files always.
Use `RUN curl/wget` for URLs so the intent is explicit.
`ADD` for a local file = [LAYER-ADD-NOT-COPY] LOW.

**Image size estimation:**
```bash
# If images are built locally
docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}" \
  2>/dev/null | head -20 || echo "Images not built locally"
```

For context — target sizes for your stack:
- API image (FastAPI + geo deps): < 400MB is excellent, < 600MB acceptable,
  > 1GB suggests missing multi-stage or uncleaned apt cache
- Frontend (nginx serving built assets): < 50MB
- PostGIS image: 400–600MB is normal (PostGIS is large)

Output: findings labeled [LAYER-COPY-ORDER], [LAYER-APT-CACHE],
[LAYER-APT-RECOMMENDS], [LAYER-PIP-CACHE], [LAYER-NO-MULTISTAGE],
[LAYER-ADD-NOT-COPY].

---

### Subagent C — Docker Compose audit
**Goal: compose files are correct, minimal, and safe for their intended environment**

**Service dependency ordering:**
```bash
python3 -c "
import yaml
files = ['docker-compose.yml', 'docker-compose.override.yml',
         'docker-compose.dev.yml', 'docker-compose.prod.yml']
for f in files:
    try:
        with open(f) as fh:
            c = yaml.safe_load(fh)
        print(f'=== {f} ===')
        for name, svc in c.get('services', {}).items():
            deps = svc.get('depends_on', [])
            if isinstance(deps, dict):
                deps = list(deps.keys())
            print(f'  {name}: depends_on={deps}')
    except FileNotFoundError:
        pass
" 2>/dev/null
```

**`depends_on` without condition:**
```bash
grep -rn "depends_on:" docker-compose*.yml -A5
```

`depends_on: [db]` only waits for the container to *start*, not for Postgres
to be *ready to accept connections*. This causes race conditions where the API
starts before the DB is ready:
```yaml
# WRONG — waits for container start, not service ready
depends_on:
  - db

# CORRECT — waits for healthcheck to pass
depends_on:
  db:
    condition: service_healthy
  redis:                          # if present
    condition: service_healthy
```

Flag `depends_on` without `condition: service_healthy` on DB-dependent
services = [COMPOSE-DEPENDS-CONDITION].

**Restart policies:**
```bash
grep -rn "restart:" docker-compose*.yml
```

Missing or incorrect restart policies:
```yaml
# No restart policy — container stays down after crash
# (acceptable in dev, not in prod)

services:
  api:
    restart: unless-stopped    # prod: restarts on crash, stops on explicit stop
  db:
    restart: unless-stopped    # always restart DB
  worker:
    restart: on-failure        # restart on non-zero exit, not on explicit stop
```

Flag: no `restart` policy on any service in a prod compose file =
[COMPOSE-NO-RESTART].
Flag: `restart: always` — this restarts even on `docker compose stop`, which
makes intentional stops annoying. Prefer `unless-stopped`.

**Resource limits:**
```bash
grep -rn "deploy:\|resources:\|limits:\|reservations:\|mem_limit:\|cpus:" \
  docker-compose*.yml -A10
```

No resource limits = a runaway container can starve all others =
[COMPOSE-NO-LIMITS] MEDIUM.
```yaml
services:
  api:
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 512M
        reservations:
          cpus: '0.25'
          memory: 128M

  db:
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G        # PostGIS needs headroom for geo operations
        reservations:
          memory: 512M

  frontend:
    deploy:
      resources:
        limits:
          cpus: '0.25'
          memory: 64M       # nginx is very lightweight
```

Note: `deploy.resources` only applies when using Docker Swarm or when explicitly
passed to `docker compose --compatibility`. For `docker run`, use `--memory`
and `--cpus`. Flag in Compose v3 without `--compatibility` flag in CI =
[COMPOSE-LIMITS-IGNORED].

**Volume configuration:**
```bash
grep -rn "volumes:" docker-compose*.yml -A10
```

Check for:

- Named volumes vs bind mounts — named volumes are preferred for data:
```yaml
  # RISKY — bind mount, directory permissions depend on host UID
  volumes:
    - ./data/postgres:/var/lib/postgresql/data

  # SAFER — named volume, Docker manages permissions
  volumes:
    - postgres_data:/var/lib/postgresql/data

  volumes:
    postgres_data:
```

- Source code bind-mounted into prod image = [COMPOSE-CODE-BIND-MOUNT]:
```yaml
  # WRONG for prod — replaces built image code with host source
  volumes:
    - ./api:/app   # fine for dev, not for prod
```

- Database volume not declared as a named volume (anonymous volumes are lost
  on `docker compose down`) = [COMPOSE-ANON-VOLUME]:
```yaml
  # WRONG — anonymous volume, data lost on compose down
  volumes:
    - /var/lib/postgresql/data

  # CORRECT — named volume persists across compose down/up
  volumes:
    - postgres_data:/var/lib/postgresql/data
```

**Network isolation:**
```bash
grep -rn "networks:" docker-compose*.yml -A10
```

All services on one default network = any service can reach any other =
[COMPOSE-FLAT-NETWORK] LOW. Segment into:
```yaml
networks:
  frontend:        # nginx ↔ api only
  backend:         # api ↔ db ↔ redis
  monitoring:      # prometheus, grafana (if present)

services:
  nginx:
    networks: [frontend]
  api:
    networks: [frontend, backend]
  db:
    networks: [backend]
```

**Environment variable handling:**
```bash
# Hardcoded values that should be variables
grep -rn -A20 "environment:" docker-compose*.yml | \
  grep -vE "\${.*}|^--$|environment:|#" | \
  grep -E "=.{3,}" | head -20
```

Any non-trivially-hardcoded value in `environment:` that isn't an override
(like `PYTHONDONTWRITEBYTECODE=1`) should reference an env var:
```yaml
# WRONG — hardcoded DB credentials
environment:
  POSTGRES_PASSWORD: mysecretpassword
  POSTGRES_USER: myapp

# CORRECT — reference from .env file or shell environment
environment:
  POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
  POSTGRES_USER: ${POSTGRES_USER:?POSTGRES_USER is required}
```

Note `:?` syntax — Docker Compose will fail with a clear error if the variable
is unset. Preferred over silent empty string.

Flag hardcoded non-trivial values = [COMPOSE-HARDCODED-ENV].

Output: findings labeled [COMPOSE-DEPENDS-CONDITION], [COMPOSE-NO-RESTART],
[COMPOSE-NO-LIMITS], [COMPOSE-LIMITS-IGNORED], [COMPOSE-CODE-BIND-MOUNT],
[COMPOSE-ANON-VOLUME], [COMPOSE-FLAT-NETWORK], [COMPOSE-HARDCODED-ENV].

---

### Subagent D — Reliability: healthchecks and graceful shutdown
**Goal: every service knows when it's ready and shuts down without data loss**

**Healthcheck coverage:**
```bash
for f in Dockerfile*; do
  echo "=== $f ==="
  grep -n "HEALTHCHECK" "$f" 2>/dev/null || echo "NO HEALTHCHECK"
done

grep -rn "healthcheck:" docker-compose*.yml -A8
```

Every service must have a healthcheck. Without one, `depends_on: condition:
service_healthy` cannot work, and orchestrators (Compose, Swarm, ECS) cannot
detect unhealthy containers.

**API healthcheck (FastAPI):**
```dockerfile
# In Dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" \
  || exit 1
```

Or in compose (overrides Dockerfile healthcheck):
```yaml
healthcheck:
  test: ["CMD", "python", "-c",
    "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
  interval: 30s
  timeout: 10s
  start_period: 40s    # give uvicorn time to start
  retries: 3
```

Ensure `/health` route exists in FastAPI and returns 200:
```python
@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}
```

**PostGIS/Postgres healthcheck:**
```yaml
db:
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
    interval: 10s
    timeout: 5s
    start_period: 30s   # PostGIS initialization takes longer than plain Postgres
    retries: 5
```

The `start_period` must account for PostGIS extension initialization — plain
Postgres is ready in ~5s, PostGIS can take 20–30s on first start while it
initializes spatial reference tables.

**Frontend (nginx) healthcheck:**
```yaml
frontend:
  healthcheck:
    test: ["CMD-SHELL", "curl -f http://localhost/health || exit 1"]
    interval: 30s
    timeout: 5s
    retries: 3
```

**Graceful shutdown — stop_grace_period:**
```bash
grep -rn "stop_grace_period:\|stop_signal:\|SIGTERM" docker-compose*.yml Dockerfile*
```

Default Docker stop grace period is 10 seconds. If uvicorn needs longer to
finish in-flight requests (especially slow geo queries), extend it:
```yaml
services:
  api:
    stop_grace_period: 30s     # give uvicorn 30s to drain connections
    stop_signal: SIGTERM       # uvicorn handles SIGTERM for graceful drain
```

FastAPI/uvicorn handles SIGTERM gracefully by default. PostGIS/Postgres handles
SIGTERM as a graceful shutdown trigger — this is correct.

**PID 1 and init process:**
```bash
grep -rn "init:\|tini\|dumb-init\|--init" docker-compose*.yml Dockerfile*
```

When a process runs as PID 1 in a container, it must handle Unix signals
(SIGTERM, SIGCHLD) correctly. Python apps are not designed as init processes:
- Zombie processes from subprocesses are not reaped
- SIGTERM may not be forwarded correctly

Fix: use `init: true` in compose (uses Docker's tini) or install tini in the
Dockerfile:
```yaml
services:
  api:
    init: true           # uses Docker's built-in tini as PID 1
```

Or in Dockerfile:
```dockerfile
RUN apt-get install -y --no-install-recommends tini
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Flag absence of init process for Python services = [RELIABILITY-NO-INIT] MEDIUM.

**ENTRYPOINT vs CMD:**
```bash
grep -rn "^ENTRYPOINT\|^CMD" Dockerfile*
```

Best practices:
- Use `ENTRYPOINT` for the fixed executable, `CMD` for overridable arguments
- Both should use JSON array form (`["uvicorn", ...]` not `uvicorn ...`)
  — shell form doesn't receive signals correctly
```dockerfile
# WRONG — shell form, SIGTERM not received by uvicorn
CMD uvicorn main:app --host 0.0.0.0 --port 8000

# CORRECT — exec form, signals go directly to uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1"]
```

Shell form CMD = [RELIABILITY-CMD-SHELL-FORM] MEDIUM.

Output: findings labeled [RELIABILITY-NO-HEALTHCHECK], [RELIABILITY-NO-INIT],
[RELIABILITY-CMD-SHELL-FORM], [RELIABILITY-NO-GRACE-PERIOD],
[RELIABILITY-DEPENDS-NO-CONDITION].

---

### Subagent E — Stack-specific service audit
**Goal: PostGIS, pgvector, FastAPI, and React/Vite are configured correctly
for their specific container requirements**

**PostGIS container configuration:**
```bash
grep -rn "postgis\|POSTGRES\|PGDATA\|postgres" docker-compose*.yml \
  Dockerfile* -A5 | head -60
```

**Required PostGIS environment variables:**
```yaml
db:
  image: postgis/postgis:16-3.4
  environment:
    POSTGRES_USER: ${POSTGRES_USER}
    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    POSTGRES_DB: ${POSTGRES_DB}
    # Performance tuning for PostGIS
    POSTGRES_INITDB_ARGS: "--encoding=UTF8 --locale=en_US.UTF-8"
  volumes:
    - postgres_data:/var/lib/postgresql/data
    - ./init:/docker-entrypoint-initdb.d/   # for extension setup scripts
```

**Extension initialization script:**
```bash
ls docker-entrypoint-initdb.d/ init/ db/init/ 2>/dev/null | head -10
```

PostGIS, pg_trgm, and pgvector extensions must be created after the database
is initialized. Check for an init script:
```sql
-- init/01_extensions.sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;

-- Verify
SELECT PostGIS_Version();
SELECT extversion FROM pg_extension WHERE extname = 'vector';
```

Missing init script = extensions may not exist on first start =
[STACK-MISSING-EXTENSION-INIT].

**PostgreSQL performance settings for PostGIS:**
```bash
grep -rn "POSTGRES_INITDB_ARGS\|shared_buffers\|work_mem\|effective_cache\|\
random_page_cost\|checkpoint_completion" docker-compose*.yml Dockerfile* \
  postgresql.conf 2>/dev/null
```

PostGIS geo queries are memory-intensive. Recommend a custom `postgresql.conf`
or command arguments:
```yaml
db:
  image: postgis/postgis:16-3.4
  command: >
    postgres
    -c shared_buffers=256MB
    -c work_mem=16MB
    -c effective_cache_size=768MB
    -c random_page_cost=1.1
    -c checkpoint_completion_target=0.9
    -c wal_buffers=16MB
    -c max_connections=100
```

For pgvector specifically — JIT compilation can cause issues with some
vector operations, and `max_parallel_workers_per_gather` affects HNSW scan
performance:
```yaml
command: >
  postgres
  -c shared_buffers=256MB
  -c work_mem=64MB              # pgvector needs more for large ANN searches
  -c max_parallel_workers_per_gather=2
  -c jit=off                    # disable JIT — can cause issues with pgvector
```

Absence of any Postgres tuning in a PostGIS/pgvector deployment = [STACK-PG-UNTUNED].

**FastAPI/uvicorn worker configuration:**
```bash
grep -rn "workers\|--workers\|WEB_CONCURRENCY\|worker_class\|gunicorn" \
  Dockerfile* docker-compose*.yml
```

uvicorn worker count guidance:
```dockerfile
# Single container: workers = 2 * CPU cores + 1
# But in Docker with resource limits, use WEB_CONCURRENCY env var
CMD ["uvicorn", "main:app",
     "--host", "0.0.0.0",
     "--port", "8000",
     "--workers", "1",           # let orchestrator scale horizontally
     "--loop", "uvloop",         # faster event loop
     "--http", "httptools"]      # faster HTTP parser
```

For production with gunicorn as process manager:
```dockerfile
CMD ["gunicorn", "main:app",
     "--worker-class", "uvicorn.workers.UvicornWorker",
     "--workers", "2",
     "--bind", "0.0.0.0:8000",
     "--timeout", "120",         # longer for slow geo queries
     "--graceful-timeout", "30",
     "--access-logfile", "-",
     "--error-logfile", "-"]
```

**uvicorn timeout for geo operations:**

PostGIS operations (complex spatial joins, large buffer operations) and
pgvector ANN searches can take seconds. The default uvicorn/gunicorn timeout
of 30s may be too low:
```bash
grep -rn "timeout\|--timeout\|UVICORN_TIMEOUT" docker-compose*.yml Dockerfile*
```

No timeout configuration on a stack with geo/vector operations = [STACK-NO-TIMEOUT].
Recommend: `--timeout 120` for gunicorn, uvicorn uses `--timeout-keep-alive 5`.

**React/Vite frontend container:**
```bash
cat frontend/Dockerfile 2>/dev/null || cat Dockerfile.frontend 2>/dev/null
```

Multi-stage build for frontend:
```dockerfile
# syntax=docker/dockerfile:1

# ── Build stage ───────────────────────────────────────────────
FROM node:20-slim AS builder
WORKDIR /app

COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --ignore-scripts

COPY . .
RUN npm run build              # outputs to /app/dist

# ── Runtime stage ─────────────────────────────────────────────
FROM nginx:1.25-alpine AS runtime

# Custom nginx config for SPA routing
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

# Non-root nginx
RUN chown -R nginx:nginx /usr/share/nginx/html \
    && chmod -R 755 /usr/share/nginx/html

EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD wget -qO- http://localhost/health || exit 1
```

**nginx.conf for React SPA:**
```bash
cat nginx.conf frontend/nginx.conf 2>/dev/null || echo "No nginx.conf found"
```

SPA routing requires `try_files` fallback — without it, direct URL access
(e.g. `/dashboard`) returns 404:
```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    # SPA routing — send all non-file requests to index.html
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Health check endpoint for Docker healthcheck
    location /health {
        return 200 'ok';
        add_header Content-Type text/plain;
    }

    # Cache static assets aggressively
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff2?)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # Security headers
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header Referrer-Policy strict-origin-when-cross-origin;

    # Gzip
    gzip on;
    gzip_types text/plain text/css application/javascript
               application/json application/geo+json;   # include geo+json
    gzip_min_length 1000;
}
```

Missing `try_files` fallback = SPA routes return 404 on direct access =
[STACK-NGINX-NO-SPA-ROUTING].

Output: findings labeled [STACK-MISSING-EXTENSION-INIT], [STACK-PG-UNTUNED],
[STACK-NO-TIMEOUT], [STACK-NGINX-NO-SPA-ROUTING], [STACK-NO-WORKER-CONFIG].

---

### Subagent F — Dev vs production parity audit
**Goal: find every meaningful difference between dev and prod configurations
that could cause "works on my machine" failures**

**Diff compose files:**
```bash
# Find all compose files
ls docker-compose*.yml 2>/dev/null

# Structural diff between dev and prod
python3 -c "
import yaml, sys

def load(f):
    try:
        with open(f) as fh:
            return yaml.safe_load(fh) or {}
    except FileNotFoundError:
        return {}

dev = load('docker-compose.yml')
prod = load('docker-compose.prod.yml')

dev_services = set(dev.get('services', {}).keys())
prod_services = set(prod.get('services', {}).keys())

print('Services in dev only:', dev_services - prod_services)
print('Services in prod only:', prod_services - dev_services)
print('Common services:', dev_services & prod_services)

for svc in dev_services & prod_services:
    dev_svc = dev['services'][svc]
    prod_svc = prod['services'][svc]

    # Check image differences
    dev_img = dev_svc.get('image', dev_svc.get('build', 'build'))
    prod_img = prod_svc.get('image', prod_svc.get('build', 'build'))
    if str(dev_img) != str(prod_img):
        print(f'{svc}: image differs: dev={dev_img} prod={prod_img}')

    # Check port differences
    dev_ports = dev_svc.get('ports', [])
    prod_ports = prod_svc.get('ports', [])
    if dev_ports != prod_ports:
        print(f'{svc}: ports differ: dev={dev_ports} prod={prod_ports}')

    # Check volume differences
    dev_vols = dev_svc.get('volumes', [])
    prod_vols = prod_svc.get('volumes', [])
    if dev_vols != prod_vols:
        print(f'{svc}: volumes differ: dev={dev_vols} prod={prod_vols}')
" 2>/dev/null
```

**Parity violations to flag:**

1. **Source code bind-mounted in dev but not prod** — expected and fine, but
   verify the Dockerfile `COPY` instruction captures the same files.

2. **Different Postgres images in dev vs prod:**
```yaml
   # dev: plain postgres (faster to pull)
   db:
     image: postgres:16

   # prod: PostGIS (has the extensions you need)
   db:
     image: postgis/postgis:16-3.4   # ← this must also be dev
```
   Using `postgres:16` in dev and `postgis/postgis:16-3.4` in prod means
   spatial queries work in prod but fail locally = [PARITY-DB-IMAGE].

3. **Different environment variables between dev and prod** — missing a
   variable in `.env.example` that's required in prod:
```bash
   # Variables in prod compose not in .env.example
   grep -oE "\${[A-Z_]+}" docker-compose.prod.yml | tr -d '${:?}' | sort -u > /tmp/prod_vars.txt
   grep -oE "^[A-Z_]+=" .env.example | tr -d '=' | sort -u > /tmp/example_vars.txt
   comm -23 /tmp/prod_vars.txt /tmp/example_vars.txt
```

4. **Python version mismatch** between dev and prod Dockerfiles:
```bash
   grep "^FROM python:" Dockerfile* | sort -u
```
   Different Python minor versions can have different behavior for type
   annotations, asyncio, and sometimes numeric precision = [PARITY-PYTHON-VERSION].

5. **Dev tools in production image:**
```bash
   grep -rn "watchfiles\|hot-reload\|--reload\|nodemon\|DEBUG" \
     docker-compose.prod.yml Dockerfile* | grep -v "#"
```
   `--reload` flag on uvicorn in prod = [PARITY-DEV-TOOL-IN-PROD] HIGH —
   file watching runs in prod, wasting CPU and creating a security risk
   (source code readable via reload endpoint).

6. **Logging configuration:**
```bash
   grep -rn "LOG_LEVEL\|logging\|--log-level" docker-compose*.yml
```
   `LOG_LEVEL=DEBUG` in prod = [PARITY-LOG-LEVEL] MEDIUM — verbose logs
   expose internal state and degrade performance.

7. **PostGIS extension availability:**
```bash
   # Check if dev DB container uses postgis image
   grep -rn "image:.*postgres\b" docker-compose.yml | grep -v "postgis"
```
   Dev using plain `postgres:16` instead of `postgis/postgis:16-3.4` means
   PostGIS queries silently fail locally but work in prod, or vice versa.
   This is the most common source of "works in prod, fails locally" for
   spatial applications = [PARITY-DB-IMAGE] HIGH.

**`.env.example` completeness:**
```bash
# Every variable referenced in any compose file should be in .env.example
grep -hroE "\$\{[A-Z_][A-Z0-9_]*[^}]*\}" docker-compose*.yml | \
  grep -oE "[A-Z_][A-Z0-9_]*" | sort -u > /tmp/compose_vars.txt

grep -oE "^[A-Z_][A-Z0-9_]*" .env.example | sort -u > /tmp/example_vars.txt

echo "Variables used in compose but missing from .env.example:"
comm -23 /tmp/compose_vars.txt /tmp/example_vars.txt
```

Every referenced env var must be documented in `.env.example` with a
comment explaining its purpose and format = [PARITY-ENV-UNDOCUMENTED].

Output: findings labeled [PARITY-DB-IMAGE], [PARITY-PYTHON-VERSION],
[PARITY-DEV-TOOL-IN-PROD], [PARITY-LOG-LEVEL], [PARITY-ENV-UNDOCUMENTED],
[PARITY-MISSING-SERVICE].

---

## Phase 3 — Triage and remediation plan

Merge all 6 subagent outputs into the full report:
```markdown
# Docker audit report
Date: [date]
Stack: FastAPI · React · PostGIS · pgvector
Files audited: [list all Dockerfile* and docker-compose*.yml found]

## Summary

| Category       | Findings | Critical | High | Medium | Low |
|---------------|---------|---------|------|--------|-----|
| Security       | N       | N       | N    | N      | N   |
| Layer cache    | N       | —       | N    | N      | N   |
| Compose        | N       | N       | N    | N      | N   |
| Reliability    | N       | —       | N    | N      | N   |
| Stack-specific | N       | N       | N    | N      | N   |
| Dev/prod parity| N       | —       | N    | N      | N   |

## Merge gate: BLOCK / PASS

Blocking conditions:
- [ ] Root user in application containers (non-DB)
- [ ] Privileged mode enabled
- [ ] Hardcoded secrets in environment blocks or Dockerfile ENV
- [ ] Postgres/Redis ports exposed without localhost binding
- [ ] `--reload` flag in production uvicorn
- [ ] Dev uses plain postgres, prod uses PostGIS (or vice versa)
- [ ] No `.dockerignore` file

## Findings

| ID  | Category | Label | Severity | File:line | Blast radius |
|-----|---------|-------|----------|-----------|-------------|
| D01 | Security | [SECURITY-ROOT] | 🔴 HIGH | Dockerfile:42 | API runs as root |
| D02 | Parity | [PARITY-DB-IMAGE] | 🔴 HIGH | docker-compose.yml:8 | PostGIS unavailable in dev |
| ... | | | | | |

## Finding details

### D01 — [Label] — Severity
**File:** `path:line`
**Blast radius:** [what breaks or is exposed if this isn't fixed]

**Current:**
\`\`\`dockerfile
[current config]
\`\`\`

**Fixed:**
\`\`\`dockerfile
[corrected config]
\`\`\`
```

---

## Phase 4 — Generate fixed files (if `--fix` flag set)

Show the user a diff of every proposed change and request confirmation before
writing anything.
```
The following files will be modified:

1. Dockerfile (api)
   - Add non-root USER directive (lines 38-40)
   - Add HEALTHCHECK (line 41)
   - Fix layer order: move COPY requirements.txt before COPY . (lines 12-13 swap)
   - Add --no-cache-dir to pip install (line 15)
   - Switch CMD to exec form (line 44)

2. docker-compose.yml
   - Add depends_on condition: service_healthy for api → db
   - Add healthcheck to db service
   - Bind postgres port to 127.0.0.1 only
   - Add restart: unless-stopped to all services
   - Change db image from postgres:16 to postgis/postgis:16-3.4

3. .dockerignore (create new)
   - Full .dockerignore for your stack

Proceed? [y/N]
```

After confirmation, write each corrected file to disk.

Also generate:
- `init/01_extensions.sql` — if missing, with all three extensions
- `nginx.conf` — if missing or incomplete for SPA routing

---

## Phase 5 — Deliver

**1. Write `docs/docker-audit-[date].md`** with the full report.

**2. If `--fix` not passed, output corrected file snippets inline** for each
finding so the developer can apply them without re-running the command.

**3. Generate `docker-compose.test.yml`** for isolated CI testing:
```yaml
# docker-compose.test.yml — used in CI only
# Usage: docker compose -f docker-compose.yml -f docker-compose.test.yml up --abort-on-container-exit

services:
  api:
    build:
      context: .
      target: runtime
    environment:
      DATABASE_URL: postgresql+asyncpg://test:test@db:5432/testdb
      ENVIRONMENT: test
    depends_on:
      db:
        condition: service_healthy
    command: >
      sh -c "alembic upgrade head && pytest -x -q"

  db:
    image: postgis/postgis:16-3.4
    environment:
      POSTGRES_USER: test
      POSTGRES_PASSWORD: test
      POSTGRES_DB: testdb
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U test -d testdb"]
      interval: 5s
      timeout: 3s
      start_period: 30s
      retries: 10
    tmpfs:
      - /var/lib/postgresql/data   # in-memory DB for tests, no persistence needed
```

**4. Update `lessons.md`:**
```markdown
## [date] — Docker audit
### Critical issues found and fixed
### Layer optimizations applied (estimated image size reduction)
### Parity gaps closed
### Init scripts added for extensions: yes/no
```

---

## DELIVERY

### Output format

Write the report to: `docs-internal/audits/docker-audit-{YYYYMMDD}.md`

### Post-delivery

1. If a previous `docker-audit-*.md` exists in `docs-internal/audits/`, diff key findings against the prior report.
2. Print one-line summary: overall grade + Critical count + total image size savings estimate.

---

## RELATIONSHIP TO OTHER COMMANDS

- `/sec-audit` — covers container runtime security in its Subagent F. This command provides comprehensive container configuration analysis: layer efficiency, healthchecks, resource limits, and dev/prod parity.
- `/dep-audit` — covers application dependencies inside containers. This command covers the container layer itself.
- `/env-audit` — covers environment variable consistency. This command covers how env vars are passed to containers.

---

## What NOT to flag

- `--reload` in `docker-compose.dev.yml` or `docker-compose.override.yml`
  (it's expected in dev — only flag it in prod)
- Bind mounts of source code in dev compose (expected — only flag in prod)
- `restart: "no"` in dev compose (acceptable — only flag missing restart in prod)
- `DEBUG=true` in explicitly named dev environment files
- Anonymous volumes for ephemeral containers (test runners, one-off tasks)
- `network_mode: host` in a CI-only compose file where service discovery
  isn't needed
- `privileged: true` in a compose file exclusively used for local tooling
  (e.g. `docker-compose.tools.yml` running a DB migration tool)
- `psycopg2-binary` in dev image (only flag in production Dockerfile)
- Missing resource limits in dev compose (only flag in prod)
- `POSTGRES_HOST_AUTH_METHOD=trust` in a test-only compose with no published
  ports and `tmpfs` storage
- nginx `server_tokens off` absence — informational, not a real risk here
- Missing gzip for small static files (< 1kb) — compression overhead exceeds benefit