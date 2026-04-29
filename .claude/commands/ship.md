# /ship — Run CI, Fix Issues, Commit & Push

Run all CI checks locally, aggressively auto-fix failures in a loop, then interactively commit, push, and optionally open a PR. This command is sequential — each phase gates the next.

**Usage:** `/ship` or `/ship <commit message>`

If a commit message is provided as an argument, use it. Otherwise, generate one from the changes.

---

## PHASE 0: PREFLIGHT (Serial — always runs first)

### Discover the environment

```bash
# Current branch and git state
git branch --show-current
git status --short
git diff --stat
git stash list

# Uncommitted changes count
UNSTAGED=$(git diff --name-only | wc -l)
STAGED=$(git diff --cached --name-only | wc -l)
UNTRACKED=$(git ls-files --others --exclude-standard | wc -l)
echo "Unstaged: $UNSTAGED | Staged: $STAGED | Untracked: $UNTRACKED"

# Are we on main/master? Warn if so.
BRANCH=$(git branch --show-current)
if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ]; then
  echo "⚠️  ON MAIN BRANCH — should we create a feature branch first?"
fi
```

### Discover CI configuration

```bash
# GitHub Actions workflows
find .github/workflows -name "*.yml" -o -name "*.yaml" 2>/dev/null | while read f; do
  echo "=== $f ==="
  cat "$f"
done

# Package managers and configs
cat backend/pyproject.toml 2>/dev/null | head -60
cat frontend/package.json 2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('Scripts:', json.dumps(d.get('scripts', {}), indent=2))
" 2>/dev/null

# Lint/format configs
ls -la ruff.toml .ruff.toml pyproject.toml setup.cfg .flake8 .black 2>/dev/null
ls -la .eslintrc* eslint.config* .prettierrc* tsconfig*.json 2>/dev/null
ls -la frontend/.eslintrc* frontend/eslint.config* frontend/.prettierrc* frontend/tsconfig*.json 2>/dev/null

# Test configs
ls -la pytest.ini pyproject.toml conftest.py backend/conftest.py backend/pytest.ini 2>/dev/null
ls -la frontend/vitest.config* frontend/jest.config* 2>/dev/null

# Docker
ls -la Dockerfile* docker-compose*.yml backend/Dockerfile* frontend/Dockerfile* 2>/dev/null
```

### Build the check plan

From the discovered configuration, build an ordered execution plan. The canonical order is:

1. **Python lint & format** (ruff check, ruff format, black)
2. **Python type check** (mypy)
3. **Python tests** (pytest)
4. **Frontend lint & format** (eslint, prettier)
5. **Frontend type check** (tsc --noEmit)
6. **Frontend tests** (vitest or jest)
7. **Docker build** (docker compose build)

Skip any step whose tooling is not present. Log which steps are included and which are skipped.

### Set constants

```
MAX_FIX_ATTEMPTS=5        # Max retry loops per phase
MAX_TOTAL_ATTEMPTS=15     # Global circuit breaker across all phases
TOTAL_ATTEMPTS=0          # Running counter
```

---

## PHASE 1: PYTHON LINT, FORMAT & TYPE CHECK (Auto-fix loop)

### Step 1a: Ruff lint + format

```
ATTEMPT=0
while ATTEMPT < MAX_FIX_ATTEMPTS and TOTAL_ATTEMPTS < MAX_TOTAL_ATTEMPTS:
  ATTEMPT++
  TOTAL_ATTEMPTS++

  # Run ruff check
  cd backend (or project root, depending on config)
  ruff check . 2>&1 | tee /tmp/ruff-check-output.txt
  RUFF_CHECK_EXIT=$?

  # Run ruff format check
  ruff format --check . 2>&1 | tee /tmp/ruff-format-output.txt
  RUFF_FORMAT_EXIT=$?

  if RUFF_CHECK_EXIT == 0 and RUFF_FORMAT_EXIT == 0:
    echo "✅ Ruff: clean"
    break

  # Auto-fix
  ruff check --fix .
  ruff format .

  # If ruff reported errors it can't auto-fix, read the output and fix manually
  if still failing after auto-fix:
    Read /tmp/ruff-check-output.txt
    For each remaining error:
      Open the file, understand the error, apply the fix
    Continue loop
```

**Ruff fix strategy:**
- `--fix` handles most import sorting, unused imports, and simple lint violations
- `--unsafe-fixes` can be tried if `--fix` leaves residual errors (but review each change)
- Manual fixes needed for: type errors ruff flags, complex refactors, ambiguous fixes
- If the same error persists for 2 consecutive attempts, flag it and move on

### Step 1b: Black (if used alongside or instead of ruff format)

```bash
black --check backend/ 2>&1 || black backend/
```

### Step 1c: Mypy

```
ATTEMPT=0
while ATTEMPT < MAX_FIX_ATTEMPTS and TOTAL_ATTEMPTS < MAX_TOTAL_ATTEMPTS:
  ATTEMPT++
  TOTAL_ATTEMPTS++

  mypy backend/app/ 2>&1 | tee /tmp/mypy-output.txt
  MYPY_EXIT=$?

  if MYPY_EXIT == 0:
    echo "✅ Mypy: clean"
    break

  # Parse mypy errors and fix
  Read /tmp/mypy-output.txt
  For each error:
    - Missing type annotations → add them
    - Incompatible types → fix the type or add a cast
    - Missing imports → add the import
    - Module has no attribute → fix the reference
    - Cannot find module → check if it's installed, add py.typed or type stub

  # If error count didn't decrease from last attempt, stop looping
  if error_count >= previous_error_count:
    echo "⚠️  Mypy errors not decreasing — stopping after $ATTEMPT attempts"
    break
```

**Mypy fix strategy:**
- Prioritize fixes that unblock other errors (import errors, missing stubs)
- For third-party libraries without stubs, add `# type: ignore[import]` with a comment
- Do NOT blanket `# type: ignore` — only ignore specific error codes
- If mypy config excludes certain paths, respect those exclusions
- Track error count per attempt — if it plateaus, stop and report remaining errors

**IMPORTANT:** After Phase 1 completes, `git diff --stat` to see what changed. If the fixes are substantial, summarize them before moving on.

---

## PHASE 2: PYTHON TESTS (Fix loop)

```
ATTEMPT=0
while ATTEMPT < MAX_FIX_ATTEMPTS and TOTAL_ATTEMPTS < MAX_TOTAL_ATTEMPTS:
  ATTEMPT++
  TOTAL_ATTEMPTS++

  # Run pytest with verbose output for failure context
  pytest backend/ -v --tb=short 2>&1 | tee /tmp/pytest-output.txt
  PYTEST_EXIT=$?

  # Also capture just the failure summary
  pytest backend/ --tb=line -q 2>&1 | tee /tmp/pytest-summary.txt

  if PYTEST_EXIT == 0:
    echo "✅ Pytest: all tests pass"
    break

  # Parse failures
  Read /tmp/pytest-output.txt
  For each failing test:
    1. Read the test file to understand what it tests
    2. Read the source file being tested
    3. Determine if the failure is:
       a. Test is wrong (outdated assertion, changed API) → fix the test
       b. Source is wrong (bug introduced by recent changes) → fix the source
       c. Environment issue (missing fixture, DB not running) → flag and skip
    4. Apply the fix

  # Track passing/failing counts
  if failing_count >= previous_failing_count:
    echo "⚠️  Test failures not decreasing — stopping after $ATTEMPT attempts"
    break
```

**Test fix strategy:**
- Read the FULL test and FULL source under test before attempting a fix
- Prefer fixing tests over fixing source when the source change was intentional
- Prefer fixing source over fixing tests when the test documents intended behavior
- NEVER delete or skip a failing test to make CI pass — fix it or flag it
- For database-dependent tests that fail without a running DB, note them as "requires running services" and continue
- If a test file imports from a path that changed, fix the import
- Track the specific test IDs that pass/fail each iteration to detect regressions (fixing one test breaks another)

**After Phase 2:** `git diff --stat` to summarize source and test changes.

---

## PHASE 3: FRONTEND LINT, FORMAT & TYPE CHECK (Auto-fix loop)

### Step 3a: ESLint

```
ATTEMPT=0
while ATTEMPT < MAX_FIX_ATTEMPTS and TOTAL_ATTEMPTS < MAX_TOTAL_ATTEMPTS:
  ATTEMPT++
  TOTAL_ATTEMPTS++

  cd frontend (or project root)
  npx eslint . 2>&1 | tee /tmp/eslint-output.txt
  ESLINT_EXIT=$?

  if ESLINT_EXIT == 0:
    echo "✅ ESLint: clean"
    break

  # Auto-fix
  npx eslint . --fix

  # If errors remain after --fix, read and fix manually
  if still failing:
    Read /tmp/eslint-output.txt
    For each remaining error:
      Open the file, understand the rule, apply the fix
    Continue loop
```

### Step 3b: Prettier

```bash
cd frontend
npx prettier --check "src/**/*.{ts,tsx,css,json}" 2>&1 || npx prettier --write "src/**/*.{ts,tsx,css,json}"
```

Prettier is fully auto-fixable. If `--write` produces changes, run `--check` again to confirm.

### Step 3c: TypeScript type check

```
ATTEMPT=0
while ATTEMPT < MAX_FIX_ATTEMPTS and TOTAL_ATTEMPTS < MAX_TOTAL_ATTEMPTS:
  ATTEMPT++
  TOTAL_ATTEMPTS++

  cd frontend
  npx tsc --noEmit 2>&1 | tee /tmp/tsc-output.txt
  TSC_EXIT=$?

  if TSC_EXIT == 0:
    echo "✅ TypeScript: clean"
    break

  # Parse tsc errors and fix
  Read /tmp/tsc-output.txt
  For each error:
    - TS2307 (Cannot find module) → check imports, add @types/ package or declaration
    - TS2322 (Type not assignable) → fix the type mismatch
    - TS2339 (Property does not exist) → fix the property access or add to interface
    - TS7006 (Parameter implicitly has 'any') → add type annotation
    - TS2345 (Argument not assignable) → fix the argument type
    - TS18047 (Possibly null) → add null check or non-null assertion if safe

  if error_count >= previous_error_count:
    echo "⚠️  TypeScript errors not decreasing — stopping after $ATTEMPT attempts"
    break
```

**TypeScript fix strategy:**
- Fix type errors in dependency order (interfaces/types first, then components that use them)
- For missing type declarations, check if `@types/` package exists before writing custom `.d.ts`
- Prefer narrowing (type guards, null checks) over assertions (`as`, `!`)
- If a type error stems from a backend API change, update the frontend type to match

---

## PHASE 4: FRONTEND TESTS (Fix loop)

```
ATTEMPT=0
while ATTEMPT < MAX_FIX_ATTEMPTS and TOTAL_ATTEMPTS < MAX_TOTAL_ATTEMPTS:
  ATTEMPT++
  TOTAL_ATTEMPTS++

  cd frontend

  # Detect test runner
  if vitest config exists:
    npx vitest run 2>&1 | tee /tmp/frontend-test-output.txt
  elif jest config exists:
    npx jest --ci 2>&1 | tee /tmp/frontend-test-output.txt
  else:
    echo "⚠️  No frontend test runner detected — skipping"
    break

  TEST_EXIT=$?

  if TEST_EXIT == 0:
    echo "✅ Frontend tests: all pass"
    break

  # Parse and fix
  Read /tmp/frontend-test-output.txt
  For each failing test:
    1. Read the test file and the component/module under test
    2. Determine root cause (same strategy as Python tests)
    3. Apply fix

  if failing_count >= previous_failing_count:
    echo "⚠️  Frontend test failures not decreasing — stopping after $ATTEMPT attempts"
    break
```

**Same test fix principles as Phase 2.** Never delete tests. Fix the test or fix the source.

---

## PHASE 5: DOCKER BUILD CHECK

```bash
# Build all services — catch Dockerfile errors, missing dependencies, build-time failures
docker compose build --no-cache 2>&1 | tee /tmp/docker-build-output.txt
DOCKER_EXIT=$?

if [ $DOCKER_EXIT -eq 0 ]; then
  echo "✅ Docker build: success"
else
  echo "❌ Docker build: failed"
  # Read the build output and identify the failure
  Read /tmp/docker-build-output.txt
  # Common failures:
  # - pip install failure → check requirements.txt / pyproject.toml
  # - npm install failure → check package.json / lockfile
  # - COPY failure → check file paths in Dockerfile
  # - Build arg missing → check docker-compose.yml build args

  # Attempt fix (1 attempt only for Docker — builds are slow)
  Fix the identified issue
  docker compose build --no-cache 2>&1
fi
```

**Docker build gets 1 fix attempt, not a loop.** Builds are slow and failures are usually a single root cause. If the fix attempt fails, report the error and move on — don't burn 15 minutes in a loop.

**IMPORTANT:** Only build, do NOT `docker compose up`. We're checking that the images build, not that the full stack runs.

---

## PHASE 6: RESULTS SUMMARY (Serial — before git operations)

Before any git operations, produce a clear summary:

```markdown
## CI Results Summary

| Check | Status | Attempts | Notes |
|-------|--------|----------|-------|
| Ruff lint | ✅/❌ | N | ... |
| Ruff format | ✅/❌ | N | ... |
| Black | ✅/❌/⏭️ | N | ... |
| Mypy | ✅/❌ | N | ... |
| Pytest | ✅/❌ | N | ... |
| ESLint | ✅/❌ | N | ... |
| Prettier | ✅/❌ | N | ... |
| TypeScript | ✅/❌ | N | ... |
| Frontend tests | ✅/❌ | N | ... |
| Docker build | ✅/❌ | N | ... |

**Total fix attempts:** N / 15
**Files modified:** N
**Remaining failures:** N
```

Then show the full diff summary:

```bash
git diff --stat
git diff --cached --stat
```

### Gate check

If ANY check still fails after all fix attempts:

```
⚠️  Not all checks pass. Remaining failures:
- [list each]

Options:
1. Commit anyway with failures noted in commit message
2. Abort — fix remaining issues manually
3. Commit passing fixes only, leave failing code uncommitted
```

**Ask the user which option to take.** Do not auto-commit with failures.

If ALL checks pass:

```
✅ All CI checks pass. Ready to commit.
```

Proceed to Phase 7.

---

## PHASE 7: COMMIT (Interactive)

### Generate commit message

If the user provided a commit message as an argument, use it.

Otherwise, generate a conventional commit message from the changes:

```bash
# What changed?
git diff --name-only
git diff --cached --name-only
git ls-files --others --exclude-standard
```

**Commit message format:**
```
<type>(<scope>): <short description>

<body — what changed and why>

CI fixes applied:
- <list of auto-fixes, e.g. "ruff: removed 3 unused imports">
- <list of test fixes, e.g. "pytest: updated test_search assertions for new schema">
```

Types: `fix`, `feat`, `refactor`, `style`, `test`, `chore`, `ci`, `docs`

Scope: the primary domain affected (e.g., `auth`, `search`, `maps`, `frontend`)

### Present and confirm

Show the proposed commit message and the file list. Ask:

```
Proposed commit:
---
<commit message>
---

Files to commit:
<file list>

Proceed with commit? [y/n/edit]
```

- **y** — Stage all changes and commit
- **n** — Abort (do not commit)
- **edit** — Let the user modify the commit message

### Execute commit

Stage the specific files from the file list confirmed above. Do NOT use `git add -A` — it may stage secrets (`.env`), generated files, or large binaries.

```bash
git add <file1> <file2> ...
git commit -m "<message>"
```

If there are files the user might not want committed (e.g., generated files, `.env`, large binaries), call them out explicitly and exclude them from staging.

---

## PHASE 8: PUSH (Interactive)

### Check remote state

```bash
# Current branch
BRANCH=$(git branch --show-current)

# Does remote branch exist?
git ls-remote --heads origin "$BRANCH" 2>/dev/null

# Are we behind remote?
git fetch origin "$BRANCH" 2>/dev/null
git log --oneline "origin/$BRANCH..$BRANCH" 2>/dev/null
git log --oneline "$BRANCH..origin/$BRANCH" 2>/dev/null
```

### Handle conflicts

If we're behind the remote:
```
⚠️  Remote has commits not in your local branch.
Options:
1. Rebase onto remote (git pull --rebase)
2. Merge remote into local (git pull)
3. Force push (⚠️  overwrites remote)
4. Abort push
```

Ask the user which option to take.

### Confirm and push

```
Push to origin/$BRANCH? [y/n]
```

- **y** — `git push origin $BRANCH` (or `git push -u origin $BRANCH` if no upstream set)
- **n** — Abort

---

## PHASE 9: PULL REQUEST (Interactive — Optional)

### Check if PR is appropriate

```bash
# Is gh CLI available?
gh --version 2>/dev/null

# Does a PR already exist for this branch?
gh pr list --head "$BRANCH" --state open 2>/dev/null
```

If `gh` is not installed, output the manual PR URL:
```
gh CLI not found. Create PR manually:
https://github.com/<owner>/<repo>/compare/main...$BRANCH
```

If a PR already exists:
```
PR already exists for this branch:
<PR title> — <PR URL>

The push has updated it. No new PR needed.
```

### Generate PR content

```bash
# Commits in this branch not in main
git log --oneline main..$BRANCH 2>/dev/null || git log --oneline master..$BRANCH 2>/dev/null

# Files changed vs main
git diff --stat main..$BRANCH 2>/dev/null || git diff --stat master..$BRANCH 2>/dev/null
```

**PR title:** Derived from the branch name or commit message. Follow conventional format.

**PR body template:**
```markdown
## Summary

<2-3 sentence description of what this PR does>

## Changes

<Bulleted list of key changes, grouped by domain>

## CI Status

All local CI checks pass:
- [x] Ruff lint & format
- [x] Mypy type check
- [x] Pytest (N tests)
- [x] ESLint & Prettier
- [x] TypeScript (tsc --noEmit)
- [x] Frontend tests (N tests)
- [x] Docker build

## Auto-fixes applied

<List any CI fixes the command auto-applied, so reviewers know what was machine-generated>

## Testing

<How to test these changes — what to look at, what to try>
```

### Confirm and create

```
Create PR?

Title: <title>
Base: main
Head: $BRANCH

<PR body preview>

[y/n/edit]
```

- **y** — `gh pr create --title "<title>" --body "<body>" --base main`
- **n** — Skip PR creation
- **edit** — Let the user modify title and body

---

## CIRCUIT BREAKERS & SAFETY RAILS

### Global attempt limit

If `TOTAL_ATTEMPTS` reaches `MAX_TOTAL_ATTEMPTS` (15), stop all fix loops immediately:

```
🛑 Global fix attempt limit reached (15). Stopping auto-fix.

Checks still failing:
- <list>

Manual intervention needed. All fixes applied so far are in your working tree.
```

### Regression detection

Within each fix loop, track specific error IDs / test names. If a fix introduces a NEW failure that wasn't in the previous iteration:

```
⚠️  Regression detected: fixing <X> broke <Y>.
Reverting last fix attempt and stopping this phase.
```

Use `git stash` or manual revert to undo the regressing change before continuing.

### Stale loop detection

If the same errors appear in 2 consecutive attempts with zero improvement:

```
⚠️  No progress on <check>. Same N errors for 2 consecutive attempts. Stopping.
```

Move to the next phase. Don't waste attempts on stuck errors.

### Never auto-fix these

Some "failures" should not be auto-fixed because the fix requires human judgment:

- **Security warnings** from lint (e.g., `S101 assert used`, `S603 subprocess call`) — flag, don't fix
- **Deprecation warnings** that require architectural decisions — flag, don't fix
- **Tests that test business logic correctness** — if unclear whether the test or source is correct, flag and ask
- **Changes to public API contracts** (route signatures, response schemas) — flag and ask
- **Deletion of any test file or test function** — NEVER do this

---

## ADAPTING TO THE CI CONFIGURATION

This command should adapt to whatever it discovers, not assume a fixed toolchain. Follow these rules:

### Tool discovery priority

1. **GitHub Actions workflows** — Read `.github/workflows/*.yml` to understand what CI actually runs. Match local checks to CI checks.
2. **Package scripts** — Check `package.json` scripts and `pyproject.toml` scripts for project-specific run commands.
3. **Config files** — Fall back to detecting config files (ruff.toml, eslint.config.js, etc.) and running tools directly.

### If a tool is configured but not installed

```bash
# Python tools
pip install ruff black mypy 2>/dev/null  # or use the project's requirements
cd backend && pip install -e ".[dev]" 2>/dev/null  # or however dev deps are installed

# Frontend tools
cd frontend && npm install 2>/dev/null  # or yarn/pnpm
```

Install missing tools before running them. If installation fails, skip that check and note it.

### If CI runs checks differently than standard

Read the GitHub Actions workflow and replicate the exact commands. For example:

- If CI runs `ruff check --select E,W,F` (not all rules), use the same flags locally
- If CI runs `pytest -x --timeout=60`, use the same flags
- If CI runs `tsc --project tsconfig.build.json`, use the same tsconfig
- If CI sets specific environment variables, set them locally

**The goal is local CI parity, not generic linting.**

---

## OUTPUT

### During execution

Print clear progress markers:

```
🔍 Phase 0: Preflight... done
🐍 Phase 1: Python lint & format
   ├─ Ruff check: 3 errors → auto-fix → ✅ clean (1 attempt)
   ├─ Ruff format: 2 files reformatted → ✅ clean
   ├─ Mypy: 5 errors → fix → 2 errors → fix → ✅ clean (3 attempts)
🧪 Phase 2: Python tests
   ├─ pytest: 47 passed, 2 failed → fix → 49 passed ✅ (2 attempts)
⚛️  Phase 3: Frontend lint & format
   ├─ ESLint: ✅ clean (0 fixes needed)
   ├─ Prettier: 4 files reformatted → ✅ clean
   ├─ TypeScript: ✅ clean
🧪 Phase 4: Frontend tests
   ├─ vitest: 23 passed ✅
🐳 Phase 5: Docker build
   ├─ Build: ✅ success
📊 Phase 6: Summary — ALL CHECKS PASS
💾 Phase 7: Commit — awaiting confirmation
🚀 Phase 8: Push — awaiting confirmation
📝 Phase 9: PR — awaiting confirmation
```

### If not all checks pass

After the summary, list each remaining failure with:
- The exact error message
- The file and line number
- Why auto-fix couldn't resolve it
- Suggested manual fix approach

---

## WHAT NOT TO DO

- **Never force-push without explicit user confirmation** — even on feature branches
- **Never commit to main/master** — if on main, ask to create a feature branch first
- **Never delete tests** to make CI pass
- **Never add blanket `# type: ignore` or `@ts-ignore` or `eslint-disable`** — only ignore specific error codes with a comment explaining why
- **Never modify lockfiles (package-lock.json, poetry.lock)** unless a dependency change requires it — lockfile churn creates noisy diffs
- **Never run `npm audit fix` or `pip-audit --fix`** — dependency updates are a separate concern
- **Never modify CI workflow files** (.github/workflows/) — this command runs CI locally, it doesn't change CI
- **Never `git add` files that are in `.gitignore`** — check before staging
- **Never push to a remote that's not `origin`** — unless the user explicitly asks