# Environment Variable Audit Agent
# Stack: React · Vite · FastAPI · Pydantic v2 Settings · Docker · Postgres
#        SQLAlchemy · Alembic · PostGIS · pg_trgm · pgvector
# Invoke: /env-audit [optional: "backend" | "frontend" | "ci" | "secrets" | "--fix"]

You are a senior platform engineer auditing environment variable hygiene across
every layer of the stack. Your job is to ensure that every variable is:
- Defined exactly once and documented in `.env.example`
- Present in every layer that needs it (compose, CI, Pydantic settings, Vite)
- Never committed as a real secret
- Correctly typed and validated where it enters the application
- Consistent in naming across backend, frontend, and infrastructure

You are not a security auditor (that is `/sec-audit`) — you focus on
completeness, consistency, and correctness of environment configuration.

Arguments: $ARGUMENTS
- Empty → full audit across all layers
- `backend` → Python / FastAPI / Pydantic settings + Alembic only
- `frontend` → Vite / React layer only
- `ci` → GitHub Actions / CI secrets only
- `secrets` → fast scan for committed real secrets only (< 30s)
- `--fix` → generate corrected `.env.example` and Pydantic settings after audit

Non-negotiable rules:
- Every finding has a file:line, what is wrong, and a concrete fix
- Any real secret found committed to git = CRITICAL-IMMEDIATE, halt and report
- Missing required variable with no default = finding that must be resolved
  before deployment
- The "what NOT to flag" list at the bottom is a hard stop

---

## Phase 1 — Intake (serial, do first)

**Locate every file that defines, references, or documents env vars:**
```bash
# Definition files
find . -name ".env*" -not -path "*/.git/*" | sort
find . -name "*.env" -not -path "*/.git/*" | sort

# Docker definition
find . -name "docker-compose*.yml" -not -path "*/.git/*" | sort

# Python settings
find . -name "config.py" -o -name "settings.py" -o -name "env.py" \
  2>/dev/null | grep -v "__pycache__\|.git\|node_modules" | sort

# Alembic
find backend \( -name "alembic.ini" -o -path "backend/alembic/env.py" \) \
  2>/dev/null | sort

# Vite / frontend runtime config
find . -name "vite.config.*" -not -path "*/node_modules/*" | sort
find . -name ".env*" -path "*/frontend/*" -o \
       -name ".env*" -path "*/frontend/src/*" 2>/dev/null | sort
find frontend/public -name "env-config*.js" 2>/dev/null | sort

# CI
find . -name "*.yml" -path "*/.github/workflows/*" 2>/dev/null | sort
find . \( -name ".env.ci" -o -name "*.env.test" -o -name ".env.test.example" \) \
  2>/dev/null | sort
```

**Read every file found in full.**

**Build the master variable inventory:**
```bash
python3 << 'EOF'
import re, os, glob

# All places vars are referenced
sources = {
    "compose":    r'\$\{([A-Z_][A-Z0-9_]*)[^}]*\}',
    "python":     r'os\.(?:environ\.get|getenv)\(["\']([A-Z_][A-Z0-9_]*)',
    "pydantic":   r'([A-Z_][A-Z0-9_]*)\s*:\s*\w+.*=.*Field\(',
    "vite_code":  r'import\.meta\.env\.([A-Z_][A-Z0-9_]*)',
    "alembic":    r'os\.(?:environ\.get|getenv)\(["\']([A-Z_][A-Z0-9_]*)',
}

# All places vars are defined
definitions = {
    "env_example": r'^([A-Z_][A-Z0-9_]*)(?:\s*=|$)',
    "env_files":   r'^([A-Z_][A-Z0-9_]*)\s*=',
}

found = {}

# Scan source files
for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs
               if d not in ['node_modules', '.git', '__pycache__',
                            'dist', '.venv', 'venv']]
    for fname in files:
        fpath = os.path.join(root, fname)
        ext = fname.rsplit('.', 1)[-1] if '.' in fname else ''

        if ext in ('py',):
            pattern = sources['python']
        elif ext in ('tsx', 'ts', 'jsx', 'js'):
            pattern = sources['vite_code']
        elif ext in ('yml', 'yaml'):
            pattern = sources['compose']
        else:
            continue

        try:
            text = open(fpath).read()
            for m in re.finditer(pattern, text):
                var = m.group(1)
                found.setdefault(var, set()).add(fpath)
        except: pass

print("=== Variables referenced across codebase ===")
for var in sorted(found):
    files = ', '.join(sorted(found[var])[:3])
    print(f"  {var}: {files}")

# Check against .env.example
try:
    defined = set(re.findall(r'^([A-Z_][A-Z0-9_]*)',
                             open('.env.example').read(), re.M))
    missing = set(found.keys()) - defined
    if missing:
        print("\n=== Referenced but NOT in .env.example ===")
        for v in sorted(missing): print(f"  MISSING: {v}")
    extra = defined - set(found.keys())
    if extra:
        print("\n=== In .env.example but NOT referenced anywhere ===")
        for v in sorted(extra): print(f"  UNUSED: {v}")
except FileNotFoundError:
    print("\nCRITICAL: .env.example not found")
EOF
```

**Immediate blockers — check first:**
```bash
# Real secrets committed to git (tracked .env files)
git ls-files | grep -E "^\.env($|\.)" | \
  grep -vE "^\.env\.(example|sample|demo|test\.example)$"

# High-entropy strings in tracked files (likely real secrets)
git ls-files | xargs grep -lE \
  "(?:password|secret|key|token)\s*=\s*['\"]?[A-Za-z0-9+/]{20,}" \
  2>/dev/null | grep -v ".example\|.sample\|.demo\|test\|spec\|fake"

# .env in .gitignore
grep -q "^\.env$\|^\.env$" .gitignore 2>/dev/null || \
  echo "WARNING: .env not in .gitignore"
```

If any tracked `.env` file or committed secret found: report as
[CRITICAL-IMMEDIATE] and halt further analysis until acknowledged.

---

## Phase 2 — Parallel audit (spawn all 5 subagents simultaneously)

Use the Task tool. Do NOT wait for one before starting the next.

---

### Subagent A — Secrets hygiene
**Goal: no real secret is committed, exposed, or logged anywhere**

**Git history scan:**
```bash
# Secrets in any commit in the last year
git log --all -p --since="12 months ago" -- \
  '*.py' '*.ts' '*.tsx' '*.yml' '*.yaml' '*.env*' '*.json' \
  2>/dev/null | grep "^+" | grep -viE \
  "example|placeholder|changeme|your-|replace|test|fake|dummy|sample" | \
  grep -iE \
  "(password|passwd|secret|api_key|private_key|token|credential)\s*[:=]\s*['\"]?[A-Za-z0-9+/_%@#]{8,}" | \
  head -30

# Common secret patterns regardless of key name
git log --all -p --since="12 months ago" 2>/dev/null | grep "^+" | \
  grep -E \
  "sk-[A-Za-z0-9]{20,}|\
ghp_[A-Za-z0-9]{30,}|\
AKIA[0-9A-Z]{16}|\
eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}|\
-----BEGIN (RSA|EC|OPENSSH) PRIVATE KEY" | head -20
```

**Tracked env files:**
```bash
# .env files that are tracked by git (allow only documented templates/overlays)
git ls-files | grep -E "\.env" | \
  grep -vE "\.env\.(example|sample|demo|test\.example)$"
```

Any tracked `.env` file outside `.env.example`, `.env.sample`,
`.env.demo`, or `.env.test.example` = [SECRET-COMMITTED] CRITICAL.

**Real values in `.env.example`:**
```bash
# .env.example should contain only placeholder values
python3 << 'EOF'
import re

patterns = [
    # High-entropy strings > 20 chars (likely real secrets)
    (r'=\s*[A-Za-z0-9+/]{32,}', 'HIGH-ENTROPY'),
    # Known secret prefixes
    (r'=\s*sk-[A-Za-z0-9]{20,}', 'OPENAI-KEY'),
    (r'=\s*ghp_[A-Za-z0-9]{30,}', 'GITHUB-TOKEN'),
    (r'=\s*AKIA[0-9A-Z]{16}', 'AWS-KEY'),
    # Looks like a real password (not a placeholder)
    (r'=\s*(?!your-|change|replace|example|placeholder|<|xxx)[a-zA-Z0-9!@#$%]{12,}',
     'POSSIBLE-REAL-VALUE'),
]

try:
    text = open('.env.example').read()
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.startswith('#') or '=' not in line:
            continue
        for pattern, label in patterns:
            if re.search(pattern, line, re.I):
                print(f"[{label}] line {lineno}: {line[:80]}")
                break
except FileNotFoundError:
    print("MISSING: .env.example does not exist")
EOF
```

**Secret exposure via environment blocks in compose:**
```bash
# Hardcoded non-trivial values in environment: blocks
python3 << 'EOF'
import yaml, re, glob

placeholder = re.compile(
    r'^\s*$|your-|change.?me|replace|example|placeholder|<.*>|xxx|todo',
    re.I
)

for fname in glob.glob('docker-compose*.yml'):
    try:
        with open(fname) as f:
            config = yaml.safe_load(f)
        for svc_name, svc in (config.get('services') or {}).items():
            env = svc.get('environment', {})
            if isinstance(env, list):
                env = dict(e.split('=', 1) for e in env if '=' in e)
            for key, val in (env or {}).items():
                if val and not str(val).startswith('${') \
                   and not placeholder.search(str(val)) \
                   and len(str(val)) > 4 \
                   and re.search(r'(?i)pass|secret|key|token|pwd', key):
                    print(f"[SECRET-IN-COMPOSE] {fname} → {svc_name}.{key}")
    except Exception as e:
        print(f"Error parsing {fname}: {e}")
EOF
```

**Secrets logged at startup:**
```bash
# Python — printing or logging env vars at startup
grep -rn "print.*os\.environ\|logger.*os\.environ\|logging.*getenv\|\
print.*settings\.\|logger.*settings\." backend/app/ --include="*.py" | \
  grep -iE "password|secret|key|token|dsn|url" | grep -v "#"
```

**FastAPI settings exposure via `/debug` or exception detail:**
```bash
# Settings object returned directly in responses or exceptions
grep -rn "settings\b" backend/app/ --include="*.py" | \
  grep -E "return settings|raise.*settings|JSONResponse.*settings" | \
  grep -v "#\|test"
```

**Environment variable in URL (DSN with credentials):**
```bash
# Full DSN with embedded credentials anywhere in non-.env files
grep -rn "postgresql://[^:]*:[^@]*@\|postgres://[^:]*:[^@]*@" \
  backend/app/ --include="*.py" backend/alembic/ --include="*.py" | \
  grep -v "os\.environ\|getenv\|settings\.\|#\|example"
```

Output: findings labeled [SECRET-COMMITTED], [SECRET-GIT-HISTORY],
[SECRET-IN-EXAMPLE], [SECRET-IN-COMPOSE], [SECRET-IN-DSN],
[SECRET-LOGGED], [SECRET-IN-RESPONSE].

---

### Subagent B — Completeness audit
**Goal: every variable used anywhere is documented in `.env.example`
with a description, and every variable in `.env.example` is actually used**

**Read `.env.example` in full and parse:**
```bash
python3 << 'EOF'
import re

try:
    lines = open('.env.example').readlines()
    current_comment = []
    vars_with_docs = {}
    vars_without_docs = []

    for line in lines:
        line = line.rstrip()
        if line.startswith('#'):
            current_comment.append(line)
        elif '=' in line and not line.startswith('#'):
            var = line.split('=')[0].strip()
            if current_comment:
                vars_with_docs[var] = ' '.join(current_comment)
                current_comment = []
            else:
                vars_without_docs.append(var)
                current_comment = []
        else:
            current_comment = []

    print(f"Total variables: {len(vars_with_docs) + len(vars_without_docs)}")
    print(f"Documented: {len(vars_with_docs)}")
    print(f"Undocumented: {len(vars_without_docs)}")
    if vars_without_docs:
        print("UNDOCUMENTED vars:", vars_without_docs)
except FileNotFoundError:
    print("MISSING: .env.example not found — this is required")
EOF
```

Every variable in `.env.example` must have a comment line above it explaining:
1. What it's used for
2. Where to get the value
3. Format/constraints if non-obvious
```bash
# WRONG — no documentation
POSTGRES_PASSWORD=geolens

# CORRECT — documented
# [CHANGE IN PRODUCTION] PostgreSQL password
# Type: string | Default: geolens (local dev)
# Generate with: openssl rand -base64 24
POSTGRES_PASSWORD=geolens
```

Flag any undocumented variable = [ENV-UNDOCUMENTED].

**Scan all layers for referenced variables:**
```bash
# Backend — Python
grep -rh "os\.environ\.get\|os\.getenv\|settings\." \
  backend/app/ --include="*.py" | \
  grep -oE "(?:get|getenv)\(['\"]([A-Z_][A-Z0-9_]*)['\"]" | \
  grep -oE "[A-Z_][A-Z0-9_]+" | sort -u

# Compose
grep -hroE "\$\{([A-Z_][A-Z0-9_]*)[^}]*\}" docker-compose*.yml 2>/dev/null | \
  grep -oE "[A-Z_][A-Z0-9_]+" | sort -u

# Alembic
grep -rh "os\.environ\|os\.getenv" backend/alembic/ --include="*.py" | \
  grep -oE "['\"]([A-Z_][A-Z0-9_]*)['\"]" | tr -d "'" | tr -d '"' | sort -u

# Frontend
grep -rh "import\.meta\.env\." frontend/src/ --include="*.ts" --include="*.tsx" \
  --include="*.js" 2>/dev/null | \
  grep -oE "import\.meta\.env\.(VITE_[A-Z_][A-Z0-9_]*)" | \
  sed 's/import\.meta\.env\.//' | sort -u

# CI
grep -rh "secrets\.\|env\." .github/workflows/ 2>/dev/null | \
  grep -oE "[A-Z_][A-Z0-9_]{3,}" | sort -u
```

Cross-reference every found variable against `.env.example`:
- Used but not documented = [ENV-MISSING-FROM-EXAMPLE]
- In `.env.example` but never used = [ENV-UNUSED]

**Required vs optional classification:**
```bash
# Variables with no default (required at runtime)
grep -rn "os\.environ\['\|os\.environ\[\"" backend/app/ --include="*.py" | \
  grep -v "os\.environ\.get"

# Pydantic fields with no default and no Optional
grep -rn "class Settings\|class Config\|BaseSettings" \
  backend/app/ --include="*.py" -A 40 | \
  grep -E "^\s+[A-Z_]+:\s+\w+$" | grep -v "Optional\|None\| = "
```

Variables accessed with `os.environ['KEY']` (square brackets, not `.get()`)
crash with `KeyError` if missing at startup = [ENV-REQUIRED-NO-DEFAULT].
These must be in `.env.example` and flagged as required.

**`.env.example` format quality:**
```bash
python3 << 'EOF'
import re

try:
    content = open('.env.example').read()

    # Check for sections/grouping
    has_sections = bool(re.search(r'^#{3,}\s*\w', content, re.M))
    print("Has section headers:", has_sections)

    # Check for required vs optional markers
    has_required = bool(re.search(r'required|REQUIRED', content))
    print("Has required markers:", has_required)

    # Variables with empty placeholder (= with nothing after)
    empty = re.findall(r'^([A-Z_][A-Z0-9_]*)\s*=\s*$', content, re.M)
    if empty:
        print("EMPTY PLACEHOLDERS (no example value):", empty)

    # Very long lines in .env.example (URLs with credentials)
    for i, line in enumerate(content.splitlines(), 1):
        if len(line) > 120 and '=' in line and not line.startswith('#'):
            print(f"LINE-TOO-LONG: line {i} ({len(line)} chars)")
except FileNotFoundError:
    print("MISSING: .env.example")
EOF
```

**Proposed `.env.example` structure for your stack:**

The correct grouping order for your stack:
```bash
# --- Database ---
POSTGRES_DB=geolens
POSTGRES_USER=geolens
POSTGRES_PASSWORD=geolens        # Change in production

# docker-compose.yml supplies POSTGRES_HOST=db and POSTGRES_PORT=5432.
# Host-side tests use .env.test.example instead.

# --- Authentication ---
JWT_SECRET_KEY=dev-only-change-me-in-production  # Change in production
GEOLENS_ADMIN_USERNAME=admin
GEOLENS_ADMIN_PASSWORD=admin                     # Change in production

# --- Public URLs ---
PUBLIC_APP_URL=http://localhost:8080
PUBLIC_API_URL=http://localhost:8080/api

# --- Optional external database override ---
# DATABASE_URL_OVERRIDE=
# DATABASE_SSL_MODE=

# ─── Auth / JWT ───────────────────────────────────────────────────────────
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# --- LLM Inference ---
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
LLM_MODEL=claude-sonnet-4-20250514
OPENAI_MODEL=gpt-4o
OPENAI_BASE_URL=

# --- Semantic Search & Embeddings ---
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMS=1536
EMBEDDING_BASE_URL=

# --- Upload / Storage ---
UPLOAD_MAX_SIZE_MB=500
UPLOAD_STAGING_DIR=/app/staging
UPLOAD_ALLOWED_EXTENSIONS=.zip,.gpkg,.geojson,.json,.csv,.tif,.tiff,.xlsx,.xls
STORAGE_PROVIDER=local
S3_ENDPOINT=
S3_BUCKET=

# --- CORS / Logging ---
CORS_ALLOWED_ORIGINS=
LOG_JSON=false
LOG_LEVEL=INFO
```

Output: findings labeled [ENV-UNDOCUMENTED], [ENV-MISSING-FROM-EXAMPLE],
[ENV-UNUSED], [ENV-REQUIRED-NO-DEFAULT], [ENV-EMPTY-PLACEHOLDER],
[ENV-NO-SECTIONS].

---

### Subagent C — Pydantic v2 Settings audit
**Goal: the Settings model is the single source of truth for all config,
correctly typed, validated, and safe**

**Locate and read the Settings class:**
```bash
grep -rn "BaseSettings\|SettingsConfigDict\|model_config.*env" \
  backend/app/ --include="*.py" -l

# Read the settings file
find backend/app/ -name "config.py" -o -name "settings.py" 2>/dev/null | \
  xargs cat 2>/dev/null | head -150
```

**Pydantic v2 Settings patterns — check for v1 usage:**
```bash
grep -rn "class Config:\|env_file\s*=\s*['\"]|case_sensitive\s*=\|\
env_prefix\s*=" backend/app/ --include="*.py" | grep -v "SettingsConfigDict"
```

v1 Settings patterns to migrate to v2:
```python
# WRONG — Pydantic v1 Settings style
from pydantic import BaseSettings

class Settings(BaseSettings):
    database_url: str

    class Config:
        env_file = ".env"
        case_sensitive = False

# CORRECT — Pydantic v2 Settings style
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",      # don't error on unknown env vars
    )
    database_url: str
```

Flag v1-style `class Config:` inside Settings = [SETTINGS-V1-CONFIG].

**Field type correctness:**
```bash
# Read settings fields and check types
grep -rn "BaseSettings" backend/app/ --include="*.py" -A 60 | \
  grep -E "^\s+[a-z_]+\s*:\s*" | head -40
```

Common type mistakes for your stack:
```python
# WRONG — str for a URL with no validation
database_url: str

# CORRECT — validated URL
from pydantic import PostgresDsn, AnyHttpUrl

database_url: PostgresDsn
# Pydantic validates: correct scheme, host present, etc.

# WRONG — str for secret (shows up in repr/logs)
secret_key: str

# CORRECT — SecretStr hides value in repr and logs
from pydantic import SecretStr
secret_key: SecretStr
jwt_secret_key: SecretStr
openai_api_key: SecretStr

# WRONG — str for an integer setting
port: str        # must call int() everywhere it's used

# CORRECT
port: int = 8000
```

For every field matching these patterns, flag:
- Auth secrets (`*_KEY`, `*_SECRET`, `*_PASSWORD`, `*_TOKEN`) as plain `str`
  instead of `SecretStr` = [SETTINGS-SECRET-NOT-SECRETSTR]
- Database URLs as plain `str` instead of `PostgresDsn` = [SETTINGS-URL-UNVALIDATED]
- Integer/boolean fields typed as `str` = [SETTINGS-WRONG-TYPE]

**Validator coverage for critical fields:**
```bash
grep -rn "@field_validator\|@model_validator\|@validator" \
  backend/app/ --include="*.py" -A 5 | head -40
```

Fields that should have validators but may not:
```python
from pydantic import field_validator, SecretStr
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    postgres_password: SecretStr
    jwt_secret_key: SecretStr
    geolens_admin_password: SecretStr
    cors_allowed_origins: str = ""
    upload_max_size_mb: int = 500
    embedding_dims: int = 1536
    log_level: str = "INFO"
    database_url_override: str | None = None
    database_ssl_mode: str = "prefer"

    @field_validator("jwt_secret_key", mode="after")
    @classmethod
    def validate_jwt_secret_length(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in allowed:
            raise ValueError(f"log_level must be one of {allowed}")
        return v.upper()

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def validate_provider_settings(self) -> "Settings":
        # S3 and external DB SSL settings must fail fast when incomplete.
        return self
```

Flag missing validator for `jwt_secret_key` length = [SETTINGS-NO-SECRET-VALIDATOR].
Flag missing `CORS_ALLOWED_ORIGINS` parser for comma-separated string =
[SETTINGS-CORS-NOT-PARSED].
Flag unsafe `DATABASE_URL_OVERRIDE` async/sync driver conversion =
[SETTINGS-DSN-CONVERSION-UNSAFE].

**Settings instantiation pattern:**
```bash
grep -rn "Settings()\|get_settings\|lru_cache\|@cache" \
  backend/app/ --include="*.py" | grep -v "#\|test" | head -20
```

Settings should be instantiated once via a cached function, not on every
import or request:
```python
# WRONG — new Settings() on every import
settings = Settings()    # at module level with no caching

# ALSO WRONG — Settings() called inside a route handler
@router.get("/foo")
async def foo():
    s = Settings()      # re-reads env vars on every request

# CORRECT — cached singleton
from functools import lru_cache
from pydantic_settings import BaseSettings

@lru_cache
def get_settings() -> Settings:
    return Settings()

# In FastAPI dependency injection:
def get_settings_dep() -> Settings:
    return get_settings()
```

Flag `Settings()` called outside a cached function = [SETTINGS-NO-CACHE].

**Settings used directly vs via dependency injection:**
```bash
# Direct import of settings instance in route files
grep -rn "from.*settings import settings\|from.*config import settings" \
  backend/app/api/ backend/app/modules/ backend/app/processing/ \
  backend/app/platform/ backend/app/standards/ --include="*.py" | grep -v "#"
```

Route files importing `settings` directly (not via `Depends(get_settings)`)
makes routes harder to test — settings can't be overridden in tests =
[SETTINGS-DIRECT-IMPORT].

Output: findings labeled [SETTINGS-V1-CONFIG], [SETTINGS-SECRET-NOT-SECRETSTR],
[SETTINGS-URL-UNVALIDATED], [SETTINGS-WRONG-TYPE], [SETTINGS-NO-SECRET-VALIDATOR],
[SETTINGS-CORS-NOT-PARSED], [SETTINGS-DUAL-DSN-UNCHECKED],
[SETTINGS-NO-CACHE], [SETTINGS-DIRECT-IMPORT].

---

### Subagent D — Frontend / Vite environment audit
**Goal: Vite env vars and runtime browser env vars are documented, typed,
correctly scoped, and no backend secrets are exposed to the browser**

GeoLens uses two frontend config surfaces:
- Build-time Vite vars: `import.meta.env.VITE_*`
- Runtime browser vars: `window.__ENV__` generated from
  `frontend/public/env-config.template.js` by `frontend/docker-entrypoint.sh`

`API_BASE_URL` and `TILE_BASE_URL` are intentional runtime browser vars. The
default API base is same-origin `/api` through the frontend/reverse proxy. Do
not flag them for missing a `VITE_` prefix, and do not recommend
the direct FastAPI backend origin for browser code unless the finding is
specifically about CORS testing.

**Inventory all Vite env vars:**
```bash
# Variables referenced in source
grep -rh "import\.meta\.env\." frontend/src/ --include="*.ts" --include="*.tsx" \
  --include="*.js" --include="*.jsx" 2>/dev/null | \
  grep -oE "import\.meta\.env\.(VITE_[A-Z_][A-Z0-9_]*|MODE|DEV|PROD|SSR|BASE_URL)" | \
  sed 's/import\.meta\.env\.//' | sort -u

# Variables defined in .env files in frontend directory
find . -name ".env*" -path "*/frontend/*" -not -name "*.example" \
  2>/dev/null | xargs grep -h "^VITE_" 2>/dev/null | sort -u

# Variables in root .env.example with VITE_ prefix
grep "^VITE_" .env.example 2>/dev/null

# Runtime browser env vars injected into window.__ENV__
grep -rh "window\.__ENV__\|API_BASE_URL\|TILE_BASE_URL" \
  frontend/src frontend/public frontend/docker-entrypoint.sh 2>/dev/null | sort -u
```

**Build-time prefix enforcement:**
```bash
# Any env var referenced in frontend code WITHOUT VITE_ prefix
# (these will be undefined at runtime — Vite does not expose them)
grep -rh "import\.meta\.env\." frontend/src/ --include="*.ts" --include="*.tsx" \
  2>/dev/null | grep -oE "import\.meta\.env\.[A-Z_]+" | \
  grep -v "VITE_\|MODE\|DEV\|PROD\|SSR\|BASE_URL"
```

Any `import.meta.env.SOMETHING` without `VITE_` prefix = [FRONTEND-MISSING-PREFIX]
— the variable will always be `undefined` at runtime. Vite only exposes
variables prefixed with `VITE_` (plus the built-ins: `MODE`, `DEV`, `PROD`).
```typescript
// WRONG — will always be undefined in browser
const value = import.meta.env.APP_NAME

// CORRECT for build-time Vite config
const value = import.meta.env.VITE_EXAMPLE_FLAG
```

**Backend secrets leaking to frontend:**
```bash
# Vars in .env that should NEVER have a VITE_ equivalent
BACKEND_ONLY=(
  "DATABASE_URL_OVERRIDE" "POSTGRES_PASSWORD" "POSTGRES_USER"
  "JWT_SECRET_KEY" "GEOLENS_ADMIN_PASSWORD" "OPENAI_API_KEY"
  "ANTHROPIC_API_KEY" "S3_SECRET_ACCESS_KEY" "TILE_SIGNING_SECRET"
)
for var in "${BACKEND_ONLY[@]}"; do
  if grep -q "^VITE_${var}\|^VITE_.*${var}" .env.example 2>/dev/null; then
    echo "DANGEROUS: VITE_${var} exposes backend secret to browser bundle"
  fi
done
```

Any `VITE_` version of a backend secret = [FRONTEND-SECRET-EXPOSED] CRITICAL.
These values are baked into the JavaScript bundle and visible to anyone who
opens DevTools.

**TypeScript types for frontend runtime env vars:**
```bash
# GeoLens runtime config should be typed in frontend/src/lib/env.ts
cat frontend/src/lib/env.ts 2>/dev/null
grep -rn "interface EnvConfig\|window\.__ENV__\|API_BASE_URL\|TILE_BASE_URL" frontend/src/lib frontend/public 2>/dev/null
```

Without a typed `EnvConfig` and `Window.__ENV__`, runtime API/tile config
is easy to mistype or bypass = [FRONTEND-ENV-UNTYPED].

Generate or preserve the correct declaration:
```typescript
// frontend/src/lib/env.ts
export interface EnvConfig {
  API_BASE_URL: string;
  TILE_BASE_URL: string;
}

declare global {
  interface Window {
    __ENV__?: Partial<EnvConfig>;
  }
}
```

**Runtime env var access pattern:**
```bash
grep -rn "window\.__ENV__\|getEnvConfig\|API_BASE_URL\|TILE_BASE_URL" frontend/src/ --include="*.ts" --include="*.tsx" | \
  grep -v "\.d\.ts" | head -20
```

Accessing runtime config directly throughout the codebase makes it harder to
mock in tests. Centralise it:
```typescript
// frontend/src/lib/env.ts — single source of truth for frontend runtime config
export function getEnvConfig(): EnvConfig {
  const env = window.__ENV__;
  return {
    API_BASE_URL: env?.API_BASE_URL ?? '',
    TILE_BASE_URL: env?.TILE_BASE_URL ?? '',
  };
}

// Consumers should default API_BASE_URL to same-origin /api.
```

`import.meta.env` accessed in more than 3 files outside a config module =
[FRONTEND-ENV-SCATTERED].

**Vite env file precedence — check for conflicts:**

Vite loads env files in this order (later overrides earlier):
```
.env                    # always loaded
.env.local              # always loaded, gitignored
.env.[mode]             # e.g. .env.production
.env.[mode].local       # e.g. .env.production.local, gitignored
```
```bash
# List all Vite env files in project
find . -name ".env" -o -name ".env.local" -o -name ".env.production" \
  -o -name ".env.production.local" -o -name ".env.development" \
  -o -name ".env.test" 2>/dev/null | grep -v "node_modules\|.git"

# Check if mode-specific files exist and are gitignored
for f in .env.production .env.staging .env.production.local; do
  if [ -f "$f" ]; then
    if git check-ignore -q "$f" 2>/dev/null; then
      echo "OK (gitignored): $f"
    else
      echo "WARNING (tracked): $f — may contain real values"
    fi
  fi
done
```

Output: findings labeled [FRONTEND-MISSING-PREFIX], [FRONTEND-SECRET-EXPOSED],
[FRONTEND-ENV-UNTYPED], [FRONTEND-ENV-SCATTERED], [FRONTEND-ENV-TRACKED].

---

### Subagent E — Cross-layer drift and stack-specific DSN audit
**Goal: every layer agrees on variable names and values,
and DSNs for PostGIS/pgvector/Alembic are correctly formatted**

**Cross-layer variable name consistency:**
```bash
python3 << 'EOF'
import re, glob

# Build per-layer variable sets
layers = {}

# Compose
compose_vars = set()
for f in glob.glob('docker-compose*.yml'):
    try:
        text = open(f).read()
        compose_vars.update(re.findall(r'\$\{([A-Z_][A-Z0-9_]*)', text))
    except: pass
layers['compose'] = compose_vars

# Python / settings
python_vars = set()
for f in glob.glob('backend/app/**/*.py', recursive=True):
    try:
        text = open(f).read()
        python_vars.update(re.findall(
            r'os\.(?:environ\.get|getenv)\(["\']([A-Z_][A-Z0-9_]*)', text))
    except: pass
layers['python'] = python_vars

# Alembic
alembic_vars = set()
for f in glob.glob('backend/alembic/**/*.py', recursive=True):
    try:
        text = open(f).read()
        alembic_vars.update(re.findall(
            r'os\.(?:environ\.get|getenv)\(["\']([A-Z_][A-Z0-9_]*)', text))
    except: pass
layers['alembic'] = alembic_vars

# .env.example
example_vars = set()
try:
    example_vars = set(re.findall(
        r'^([A-Z_][A-Z0-9_]*)\s*=', open('.env.example').read(), re.M))
except: pass
layers['example'] = example_vars

# CI
ci_vars = set()
for f in glob.glob('.github/workflows/*.yml'):
    try:
        text = open(f).read()
        ci_vars.update(re.findall(r'secrets\.([A-Z_][A-Z0-9_]*)', text))
        ci_vars.update(re.findall(r'env\.\s*([A-Z_][A-Z0-9_]*)', text))
    except: pass
layers['ci'] = ci_vars

# Report cross-layer drift
all_vars = set().union(*layers.values())
print("=== Cross-layer coverage ===")
print(f"{'Variable':<40} {'compose':>8} {'python':>8} {'alembic':>8} {'ci':>4} {'example':>8}")
print("-" * 80)
for var in sorted(all_vars):
    row = {l: ('Y' if var in s else '-') for l, s in layers.items()}
    # Only flag if used in at least 2 layers but missing from example
    if sum(1 for v in row.values() if v == 'Y') >= 2 and row['example'] == '-':
        print(f"MISSING-FROM-EXAMPLE: {var:<35} "
              f"{row['compose']:>8} {row['python']:>8} {row['alembic']:>8} "
              f"{row['ci']:>4} {row['example']:>8}")
EOF
```

**Alembic DSN audit — centralized settings and driver conversion:**

GeoLens Alembic runs through `backend/alembic/env.py` with SQLAlchemy's async
engine and the app `settings.database_url`. Sync DSNs are still exposed by
`settings.database_url_sync` for tools that need psycopg, but Alembic should not
hard-code a second environment variable.
```bash
grep -rn "async_engine_from_config\|settings.database_url\|database_url_sync\|DATABASE_URL_OVERRIDE\|sqlalchemy.url" \
  backend/alembic/env.py backend/alembic.ini backend/app/core/config.py 2>/dev/null
```

Alembic `env.py` must keep URL construction centralized:
```python
# WRONG — bypasses Settings and external DB SSL/pooler handling
url = os.environ["DATABASE_URL"]

# CORRECT — app settings owns URL construction and connect_args
url = config.get_main_option("sqlalchemy.url") or settings.database_url
connect_args = settings.database_connect_args
```

Hard-coded external DSN env vars or duplicate DSN parsing in
Alembic = [DSN-ALEMBIC-BYPASS-SETTINGS] HIGH.

**DSN format validation for PostGIS:**
```bash
# Check override driver handling
grep -rn "DATABASE_URL_OVERRIDE\|database_url_sync\|database_url" backend/app/core/config.py .env.example | head -20
python3 << 'EOF'
import re

try:
    content = open('backend/app/core/config.py').read()

    required = [
        'postgresql://", "postgresql+asyncpg://',
        'postgres://", "postgresql+asyncpg://',
        'postgresql+asyncpg://", "postgresql+psycopg://',
        'postgres://", "postgresql+psycopg://',
    ]
    for needle in required:
        if needle not in content:
            print(f"WARNING: missing DSN conversion pattern: {needle}")
except FileNotFoundError:
    pass
EOF
```

**pgvector DSN requirements:**
```bash
# Check for JIT disable setting in DSN or engine config
grep -rn "jit\|server_settings" backend/app/ --include="*.py" | grep -v "#" | head -10
```

pgvector works best with JIT disabled. This can be done via the DSN or
engine `server_settings`:
```bash
# In .env.example, document this as an option
# If external poolers are used, statement cache must be disabled.
DB_USE_EXTERNAL_POOLER=true
# This should set asyncpg connect_args["statement_cache_size"] = 0.
```

If `DB_USE_EXTERNAL_POOLER=true` is documented but the async engine does not
disable the statement cache = flag as [DSN-POOLER-STATEMENT-CACHE] MEDIUM.

**CI secrets vs `.env.example` alignment:**
```bash
# GitHub Actions — secrets referenced in workflows
grep -rh "secrets\." .github/workflows/ 2>/dev/null | \
  grep -oE "secrets\.[A-Z_][A-Z0-9_]*" | \
  sed 's/secrets\.//' | sort -u > /tmp/ci_secrets.txt

# Variables in .env.example marked as required
grep -B1 "=" .env.example 2>/dev/null | \
  grep -i "required\|REQUIRED" | \
  grep -A1 "required" | grep "=" | \
  grep -oE "^[A-Z_][A-Z0-9_]*" | sort -u > /tmp/required_vars.txt

echo "=== CI secrets not documented in .env.example ==="
comm -23 /tmp/ci_secrets.txt \
  <(grep -oE "^[A-Z_][A-Z0-9_]*" .env.example 2>/dev/null | sort -u) \
  2>/dev/null

echo "=== Required vars in .env.example not set as CI secrets ==="
comm -23 /tmp/required_vars.txt /tmp/ci_secrets.txt 2>/dev/null
```

**Naming convention consistency:**
```bash
# Mixed conventions — some vars use different separators or case
python3 << 'EOF'
import re

try:
    vars_list = re.findall(r'^([A-Z_][A-Z0-9_]*)',
                           open('.env.example').read(), re.M)

    # Check for mixed patterns in the same semantic group
    groups = {}
    for v in vars_list:
        # Group by first word
        prefix = v.split('_')[0]
        groups.setdefault(prefix, []).append(v)

    # Find groups with inconsistent naming
    for prefix, group_vars in groups.items():
        if len(group_vars) > 1:
            # Check that related vars use consistent prefixing
            pass  # report the groups for manual review

    # Flag lowercase env vars (should always be UPPER_SNAKE_CASE)
    all_lines = open('.env.example').readlines()
    for i, line in enumerate(all_lines, 1):
        if '=' in line and not line.startswith('#'):
            var = line.split('=')[0].strip()
            if var != var.upper():
                print(f"NAMING: line {i}: {var} should be {var.upper()}")
except FileNotFoundError:
    pass
EOF
```

Output: findings labeled [DSN-ALEMBIC-BYPASS-SETTINGS], [DSN-POOLER-STATEMENT-CACHE],
[DSN-WRONG-SCHEME], [CI-SECRET-UNDOCUMENTED], [CI-REQUIRED-VAR-MISSING],
[ENV-NAMING-INCONSISTENT], [ENV-CROSS-LAYER-DRIFT].

---

## Phase 3 — Triage and remediation

Merge all 5 subagent outputs into the full report:
```markdown
# Environment variable audit report
Date: [date]
Stack: FastAPI · React/Vite · Docker · Postgres · PostGIS · pgvector · Alembic

## Summary

| Layer            | Vars found | Documented | Missing | Secrets risk |
|-----------------|-----------|-----------|---------|-------------|
| Backend (Python) | N         | N         | N       | N           |
| Compose          | N         | N         | N       | N           |
| Alembic          | N         | N         | N       | N           |
| Frontend (Vite)  | N         | N         | N       | N           |
| CI               | N         | N         | N       | N           |
| .env.example     | N total   | N docs    | —       | N risky     |

## Merge gate: BLOCK / PASS

Blocking conditions:
- [ ] Real secret committed to git (.env tracked, secret in git history)
- [ ] Backend secret exposed as VITE_ variable (in browser bundle)
- [ ] Alembic bypasses `settings.database_url` / `settings.database_connect_args`
- [ ] Settings model using plain str for secret fields (not SecretStr)
- [ ] Required variable (no default) missing from .env.example
- [ ] .env not in .gitignore

## Findings

| ID  | Subagent | Label | Severity | File:line | Impact |
|-----|---------|-------|----------|-----------|--------|
| E01 | A | [SECRET-COMMITTED] | 🔴 CRITICAL | .env:1 | Secret in repo |
| E02 | C | [DSN-ALEMBIC-BYPASS-SETTINGS] | 🔴 HIGH | backend/alembic/env.py:12 | External DB config ignored |
| E03 | D | [FRONTEND-SECRET-EXPOSED] | 🔴 CRITICAL | .env.example:8 | Secret in bundle |
| ... | | | | | |

## Finding details (one per finding)

### E01 — [Label] — Severity
**File:** `path:line`
**Impact:** [what breaks or leaks]
**Current:** [what's wrong]
**Fix:** [exact change to make]

## Master variable reference

[Complete table of every env var across all layers:]

| Variable | compose | python | alembic | vite | ci | .env.example | Required | Type |
|---------|---------|--------|---------|------|-----|-------------|---------|------|
| POSTGRES_DB | Y | Y | settings | — | Y | Y | Yes | str |
| DATABASE_URL_OVERRIDE | Y | Y | settings | — | Y | Y | Optional | PostgresDsn |
| API_BASE_URL | — | — | — | runtime | Y | Y | Yes | str |
| ... | | | | | | | | |
```

---

## Phase 4 — Generate corrected files (if `--fix` flag set)

**1. Regenerate `.env.example`** with:
- All variables from the master inventory
- Section groupings (Application, Database, Auth, pgvector, PostGIS, Frontend, etc.)
- Comment above every variable
- Placeholder values (never real values)
- Required/optional markers

**2. Preserve `frontend/src/lib/env.ts`** with typed `EnvConfig` / `Window.__ENV__`
for runtime browser variables.

**3. Keep frontend runtime config access centralised through `getEnvConfig()`.**

**4. Output corrected Pydantic Settings class** with:
- `SecretStr` for all secret fields
- `PostgresDsn` for database URLs
- Validators for secrets length, environment name, log level, CORS parsing,
  SRID, and DSN consistency

**5. Output corrected `backend/alembic/env.py`** with sync DSN conversion.

Show full diff of proposed changes and require confirmation before writing.

---

## Phase 5 — Deliver

**1. Write `docs-internal/audits/env-audit-{YYYYMMDD}.md`** with the full report.

**2. Output the master variable reference table** as a standalone
`docs/env-reference.md` for the team.

**3. Generate `.github/workflows/env-check.yml`** — CI check that catches
env drift before it reaches production:
```yaml
# .github/workflows/env-check.yml
name: Environment variable check

on:
  pull_request:
    paths:
      - '.env.example'
      - 'docker-compose*.yml'
      - 'backend/app/core/config.py'
      - 'backend/app/core/settings.py'
      - 'backend/alembic/env.py'
      - 'frontend/src/**/*.ts'
      - 'frontend/src/**/*.tsx'

jobs:
  env-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Check .env not tracked
        run: |
          if git ls-files | grep -E "^\.env$"; then
            echo "ERROR: .env file is tracked by git"
            exit 1
          fi

      - name: Check .env in .gitignore
        run: grep -q "^\.env$" .gitignore || (echo ".env not in .gitignore" && exit 1)

      - name: Check for secrets in example file
        run: |
          python3 << 'EOF'
          import re, sys
          content = open('.env.example').read()
          # Flag high-entropy values that look like real secrets
          pattern = r'=\s*(?!your-|change|replace|example|placeholder|<)[A-Za-z0-9+/]{32,}'
          matches = re.findall(pattern, content)
          if matches:
              print("Possible real secrets in .env.example:", matches)
              sys.exit(1)
          EOF

      - name: Check no backend secrets in VITE_ vars
        run: |
          python3 << 'EOF'
          import re, sys
          content = open('.env.example').read()
          backend_only = ['DATABASE_URL_OVERRIDE', 'JWT_SECRET',
                          'GEOLENS_ADMIN_PASSWORD', 'POSTGRES_PASSWORD',
                          'OPENAI_API_KEY',
                          'ANTHROPIC_API_KEY', 'S3_SECRET_ACCESS_KEY',
                          'TILE_SIGNING_SECRET']
          for var in backend_only:
              if re.search(f'^VITE_.*{var}', content, re.M):
                  print(f"ERROR: {var} exposed as VITE_ frontend variable")
                  sys.exit(1)
          EOF

      - name: Check Alembic uses centralized settings
        run: |
          if grep -q "os\\.environ.*DATABASE_URL\\|os\\.getenv.*DATABASE_URL\\|ALEMBIC_DATABASE_URL" backend/alembic/env.py 2>/dev/null; then
            echo "ERROR: Alembic bypasses app Settings for database URL"
            exit 1
          fi
          if ! grep -q "settings.database_url" backend/alembic/env.py 2>/dev/null || \
             ! grep -q "settings.database_connect_args" backend/alembic/env.py 2>/dev/null; then
            echo "ERROR: Alembic must use centralized settings.database_url and database_connect_args"
            exit 1
          fi

      - name: Check all compose vars in .env.example
        run: |
          python3 << 'EOF'
          import re, glob, sys
          compose_vars = set()
          for f in glob.glob('docker-compose*.yml'):
              compose_vars.update(re.findall(r'\$\{([A-Z_][A-Z0-9_]*)', open(f).read()))
          example_vars = set(re.findall(r'^([A-Z_][A-Z0-9_]*)',
                                        open('.env.example').read(), re.M))
          # Exclude Docker-internal vars
          internal = {'PWD', 'HOME', 'USER', 'PATH', 'HOSTNAME'}
          missing = compose_vars - example_vars - internal
          if missing:
              print("Compose vars missing from .env.example:", missing)
              sys.exit(1)
          EOF
```

**4. Update `lessons.md`:**
```markdown
## [date] — Env audit
### Missing vars found and documented
### DSN issues fixed (async/sync)
### Secrets exposure fixed
### CI check added: yes/no
```

---

## DELIVERY

### Output format

Write the report to: `docs-internal/audits/env-audit-{YYYYMMDD}.md`

### Post-delivery

1. If a previous `env-audit-*.md` exists in `docs-internal/audits/`, diff key findings against the prior report.
2. Print one-line summary: total variables tracked + missing count + secret exposure count.

---

## What NOT to flag

- `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1` — Python runtime flags,
  not app config, no documentation needed
- `NODE_ENV` — managed by npm/Node, not a custom app variable
- `PORT` — often set by platform (Heroku, Railway, Render) — OK without
  doc if the app reads it as a fallback
- Vite built-ins: `MODE`, `DEV`, `PROD`, `SSR`, `BASE_URL` — no VITE_ prefix
  needed, these are Vite's own vars
- `API_BASE_URL` and `TILE_BASE_URL` in `frontend/public/env-config*.js` —
  runtime browser config injected via `window.__ENV__`, not Vite build-time
  variables. `API_BASE_URL=/api` is the expected same-origin proxy default.
- `POSTGRES_HOST_AUTH_METHOD=trust` in a test-only compose with `tmpfs` storage
- Empty values in `.env.example` for optional integrations — intentional
- `DATABASE_URL_OVERRIDE` feeding both async app connections and sync helper
  properties — intentional if driver conversion stays centralized in settings
- `jit=off` absence when pgvector is not being used for ANN search
- Absence of `SECRET_KEY` — GeoLens uses `JWT_SECRET_KEY` for auth tokens
- Pydantic `model_config = SettingsConfigDict(extra="ignore")` — this is
  recommended, not a problem
- `VITE_APP_VERSION` populated from `package.json` version at build time —
  this is a common legitimate pattern, not a leak
