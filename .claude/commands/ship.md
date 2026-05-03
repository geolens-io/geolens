# /ship — GeoLens Local CI Gate

Run the real GeoLens pre-merge checks locally, fix obvious failures conservatively, then commit/push only after explicit user confirmation. This command is sequential: do not advance to git operations while any required gate is red.

**Usage:** `/ship` or `/ship <commit message>`

Arguments: `$ARGUMENTS`

---

## PHASE 0: PREFLIGHT

Read the current state before running tools:

```bash
git branch --show-current
git status --short
git diff --stat
git diff --cached --stat
find .github/workflows -name "*.yml" -o -name "*.yaml" 2>/dev/null | sort
```

If on `main`/`master`, stop before committing and ask whether to create a branch. Never revert unrelated user changes. If the CI workflow and this command disagree, treat `.github/workflows/ci.yml` and `docs/testing-and-ci.md` as source of truth and note the drift.

---

## PHASE 1: DEPENDENCIES & SERVICES

Install dependencies and start the database used by backend tests:

```bash
docker compose up -d --wait db

cd backend
uv sync --locked --dev
cd ../frontend
npm ci
cd ..
```

If dependency installation fails, report the failing package/command. Do not switch package managers.

---

## PHASE 2: BACKEND GATES

Run from `backend/` unless noted:

```bash
cd backend
uv run ruff check .
uv run ruff format --check .
uv run bandit -r app/ -c pyproject.toml --severity-level high --confidence-level high
uv run pip-audit --strict --desc --ignore-vuln CVE-2026-4539 --ignore-vuln CVE-2026-3219
```

Run the full coverage suite with the local Compose database:

```bash
env \
  PYTHONPATH=. \
  POSTGRES_USER="${POSTGRES_USER:-geolens}" \
  POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-geolens}" \
  POSTGRES_HOST=localhost \
  POSTGRES_PORT="${DB_PORT:-5434}" \
  POSTGRES_DB="${POSTGRES_DB:-geolens}" \
  JWT_SECRET_KEY=test-secret-key-for-ci-padding-32chars \
  GEOLENS_ADMIN_USERNAME=admin \
  GEOLENS_ADMIN_PASSWORD=admin \
  uv run pytest -v --tb=short -m 'not perf' --cov=app --cov-report=term-missing --cov-report=html:htmlcov --cov-report=xml:coverage.xml --cov-fail-under=58.5
cd ..
```

If tests fail, read the failing test and source before patching. Never delete or skip a test to pass the gate.

---

## PHASE 3: CONTRACT, SDK, AND CLI GATES

Run from the repository root:

```bash
make openapi-check
make sdks-check
make cli-test
```

`backend/openapi.json` is the contract snapshot and SDK source of truth. If route or schema changes require a refresh, run `make openapi` and `make sdks`, review generated output, and commit only the required generated files.

---

## PHASE 4: FRONTEND GATES

Run from `frontend/`:

```bash
cd frontend
npm run test:i18n
npm run check:i18n:changed
npm run lint
npx tsc --noEmit
npm run test:coverage
cd ..
```

Treat new lint errors as blocking. Coverage output stays uncommitted.

---

## PHASE 5: E2E SMOKE WHEN RELEVANT

Run Playwright smoke checks for UI, auth, upload, builder, sharing, viewer, export, or routing changes:

```bash
npm run e2e:smoke
npm run e2e:export
```

For targeted checks, use `/smoke-check <scope>` or the root npm scripts in `package.json`.

---

## PHASE 6: FIX LOOP RULES

Use a bounded fix loop per failed gate:

1. Capture the exact failing command and error.
2. Read the relevant source, tests, and docs.
3. Apply the smallest fix that preserves product behavior.
4. Rerun the failed gate.
5. If the same failure remains after two attempts, stop that gate and report the blocker.

Do not auto-fix public API changes, security findings, dependency upgrades, migrations, or CI workflow edits without explicit user approval.

---

## PHASE 7: SUMMARY AND GIT OPERATIONS

Before staging anything:

```bash
git status --short
git diff --stat
git diff --cached --stat
```

Report a table with each gate, status, and command run. If all required gates pass, ask before staging, committing, pushing, or opening a PR. If `$ARGUMENTS` contains a commit message, use it only after confirmation.

Never force-push, never commit to `main`/`master`, and never stage ignored files or unrelated user changes.
