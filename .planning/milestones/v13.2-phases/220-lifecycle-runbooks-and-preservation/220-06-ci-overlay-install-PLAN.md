---
phase: 220-lifecycle-runbooks-and-preservation
plan: 06
type: execute
wave: 2
depends_on:
  - 220-04-lifecycle-test
files_modified:
  - .github/workflows/ci.yml
autonomous: true
requirements:
  - LIFECYCLE-04

must_haves:
  truths:
    - "CI workflow checks out `geolens-enterprise` (private repo) before the backend test job runs (per D-06)"
    - "CI installs the enterprise overlay via `uv add --editable ./geolens-enterprise` so e002_add_saml_columns is applied during the backend test job"
    - "CI gates the cross-repo checkout behind `secrets.GEOLENS_ENTERPRISE_TOKEN != ''` so fork PRs see SKIPPED, not FAILED (per RESEARCH.md Claude's Discretion option (a) + Pitfall 6)"
    - "When the overlay is unavailable (fork PR), pytest runs with `-m 'not perf and not lifecycle'` so the lifecycle marker is cleanly deselected"
    - "When the overlay is available (push to main / project-member PR), pytest runs with `-m 'not perf'` (lifecycle marker is included)"
  artifacts:
    - path: ".github/workflows/ci.yml"
      provides: "Cross-repo private-repo checkout + enterprise overlay install + fork-PR gating + conditional pytest invocation (LIFECYCLE-04 CI side)"
      contains:
        - "geolens-enterprise"
        - "GEOLENS_ENTERPRISE_TOKEN"
        - "uv add --editable"
        - "not lifecycle"
  key_links:
    - from: ".github/workflows/ci.yml backend-test job"
      to: "geolens-enterprise repository"
      via: "actions/checkout@v4 with repository + token"
      pattern: "repository: ishiland/geolens-enterprise"
    - from: ".github/workflows/ci.yml backend-test job"
      to: "backend/tests/test_lifecycle.py (Plan 04 output)"
      via: "uv run pytest -m 'not perf' (lifecycle included when overlay installed)"
      pattern: "not perf"
---

<objective>
Amend `.github/workflows/ci.yml` `backend-test` job to install the `geolens-enterprise` overlay before pytest runs, so `e002_add_saml_columns` is applied to the test DB and the lifecycle test from Plan 04 (`backend/tests/test_lifecycle.py`) can seed real SAML data. Implements D-06 + LIFECYCLE-04's CI execution criterion.

Purpose: The lifecycle test exists in core (Plan 04 / D-05) but its seed phase requires the enterprise overlay's columns. CI must install the overlay for the test to be exercisable. Fork-PR gating is the planner's chosen approach (Claude's Discretion option (a) per RESEARCH.md): skip cleanly when secrets are unavailable, surface "skipped" in fork-PR runs rather than "failed."

Output: Modified `.github/workflows/ci.yml` `backend-test` job — adds two new steps before the existing "Install Python dependencies" step + amends the existing "Run tests with coverage" step to a conditional invocation.

This plan depends on Plan 04 because the CI is amended to RUN the lifecycle test that Plan 04 creates. If the test does not exist when CI runs, the marker collection produces zero tests (silent miss). Wave 2 ensures the test exists before CI is wired to invoke it.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/STATE.md
@.planning/phases/220-lifecycle-runbooks-and-preservation/220-CONTEXT.md
@.planning/phases/220-lifecycle-runbooks-and-preservation/220-RESEARCH.md
@.planning/phases/220-lifecycle-runbooks-and-preservation/220-PATTERNS.md
@.planning/phases/220-lifecycle-runbooks-and-preservation/220-VALIDATION.md
@.github/workflows/ci.yml

<existing_job_anchor>
Current `backend-test` job is at .github/workflows/ci.yml:219-312. Verbatim from `<context>` reads of the file:

- Line 239: `- uses: actions/checkout@v4` (single existing checkout step, no `path:` parameter, defaults to `$GITHUB_WORKSPACE`).
- Line 241-263: PostgreSQL setup (Docker container).
- Line 265-269: `astral-sh/setup-uv@v6`.
- Line 271-273: `actions/setup-python@v5` (python-version 3.13).
- Line 275-276: `apt-get install gdal-bin`.
- Line 278-279: `Install Python dependencies` — `uv sync --locked --dev`.
- Line 281-298: DB schema setup.
- Line 300-301: `Run migrations` — `uv run alembic upgrade head`.
- Line 303-304: `Run tests with coverage` — `uv run pytest -v --tb=short -m 'not perf' --cov=app --cov-report=term-missing --cov-report=html:htmlcov --cov-report=xml:coverage.xml --cov-fail-under=58.5`.
- Line 306-312: `Upload backend coverage report` (untouched).

Working directory for run steps: `backend` (set at job-level `defaults.run.working-directory: backend`).
</existing_job_anchor>

<path_strategy>
Per PATTERNS.md "Path-restructure caveat": prefer the SMALLER DIFF.

Two valid path strategies:
- **Strategy A (smaller diff — RECOMMENDED):** leave the first `actions/checkout@v4` at line 239 unchanged (no `path:` — checkout defaults to `$GITHUB_WORKSPACE`). The SECOND checkout uses `path: geolens-enterprise`, which lands at `$GITHUB_WORKSPACE/geolens-enterprise`. The backend's `uv add --editable` references the overlay as `../geolens-enterprise` (from `working-directory: backend` that means `$GITHUB_WORKSPACE/geolens-enterprise` — relative path resolution: from `$GITHUB_WORKSPACE/backend`, `../geolens-enterprise` is `$GITHUB_WORKSPACE/geolens-enterprise`. ✓).
- **Strategy B (larger diff):** rewrite the first checkout to `path: geolens` and reference `../../geolens-enterprise` from backend. Forces working-directory updates throughout the job.

USE STRATEGY A. It avoids touching every working-directory reference.
</path_strategy>

<secret_naming>
Per CONTEXT.md Claude's Discretion + RESEARCH.md A1: secret name is `GEOLENS_ENTERPRISE_TOKEN`. The user is the GitHub repo owner; they will need to add this secret in repo settings before merging this CI change. The plan execution does NOT add the secret (Claude can't); the plan's runbook output documents that the user must add it.
</secret_naming>

<fork_pr_gating>
Per RESEARCH.md Pitfall 6 + Claude's Discretion option (a): use `if: ${{ secrets.GEOLENS_ENTERPRISE_TOKEN != '' }}` on the second checkout. When the secret is unavailable (fork PRs), the value is empty, the step is skipped, and the rest of the job continues with `OVERLAY_INSTALLED=0` → pytest runs `-m 'not perf and not lifecycle'`. No "failed" status surfaces.

NB on GH Actions evaluation: `secrets.X` returns an empty string when the secret is not set OR when the workflow is triggered from a fork PR (security model). The `if: ${{ secrets.X != '' }}` idiom evaluates correctly in both contexts.
</fork_pr_gating>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Amend .github/workflows/ci.yml backend-test job — add cross-repo checkout, enterprise install, conditional pytest invocation</name>
  <files>.github/workflows/ci.yml</files>
  <read_first>
    - .github/workflows/ci.yml (current state of the entire `backend-test` job at lines 219-312 — verify line numbers haven't shifted from PATTERNS.md's analysis; if they have, apply the same logical edit at the new line numbers)
    - .planning/phases/220-lifecycle-runbooks-and-preservation/220-CONTEXT.md (D-06 binding; Claude's Discretion option (a) for fork-PR gating)
    - .planning/phases/220-lifecycle-runbooks-and-preservation/220-RESEARCH.md (Pattern 3 — sketch yaml; Pitfall 6 — fork-PR gating; A1 — secret name; A7 — `secrets.X != ''` semantics)
    - .planning/phases/220-lifecycle-runbooks-and-preservation/220-PATTERNS.md (lines 370-465 — exact yaml shape + path-restructure caveat + step ordering)
    - .planning/phases/220-lifecycle-runbooks-and-preservation/220-VALIDATION.md (LIFECYCLE-04 CI integration check block)
  </read_first>
  <action>
Amend the `backend-test` job in `.github/workflows/ci.yml`. Make these THREE coordinated changes; do not modify any other job.

**Change 1 — Insert new "Checkout geolens-enterprise" step** immediately after the existing single `actions/checkout@v4` step (currently at line 239) and before the "Start PostgreSQL with PostGIS + pgvector" step (currently at line 241). Step contents:

```yaml
      - name: Checkout geolens-enterprise (skip on fork PRs without secret)
        if: ${{ secrets.GEOLENS_ENTERPRISE_TOKEN != '' }}
        uses: actions/checkout@v4
        with:
          repository: ishiland/geolens-enterprise
          token: ${{ secrets.GEOLENS_ENTERPRISE_TOKEN }}
          path: geolens-enterprise
```

Notes:
- The `if:` gate uses `secrets.GEOLENS_ENTERPRISE_TOKEN != ''` (per RESEARCH.md A7 + Pitfall 6). When the secret is absent (fork PRs, missing-config), the step is skipped cleanly and downstream `if: OVERLAY_INSTALLED == '1'` logic deselects the lifecycle marker.
- `repository: ishiland/geolens-enterprise` — the user's private overlay repo. If the user later transfers the repo to a different org/owner, this string changes; the test runtime/secrets do not.
- `path: geolens-enterprise` lands the checkout at `$GITHUB_WORKSPACE/geolens-enterprise`. Since job-level `defaults.run.working-directory: backend`, run-steps reference the overlay as `../geolens-enterprise` (Strategy A from `<path_strategy>`).
- `path: geolens-enterprise` does NOT alter the FIRST checkout's path; the existing `actions/checkout@v4` at line 239 stays unchanged (no `path:` added). Strategy A keeps the diff small.

**Change 2 — Insert new "Install enterprise overlay (if available)" step** immediately after the existing "Install Python dependencies" step (currently at line 278-279, the `uv sync --locked --dev` step) and BEFORE the "Set up database extensions, roles, and schemas" step (currently at line 281). Step contents:

```yaml
      - name: Install enterprise overlay (if available)
        run: |
          if [ -d "../geolens-enterprise" ] && [ -f "../geolens-enterprise/pyproject.toml" ]; then
            uv add --editable ../geolens-enterprise
            echo "OVERLAY_INSTALLED=1" >> $GITHUB_ENV
            echo "geolens-enterprise installed; lifecycle marker will be collected"
          else
            echo "OVERLAY_INSTALLED=0" >> $GITHUB_ENV
            echo "geolens-enterprise not available (fork PR or missing GEOLENS_ENTERPRISE_TOKEN secret) — lifecycle marker deselected"
          fi
```

Notes:
- The job's `defaults.run.working-directory: backend` is in effect, so `../geolens-enterprise` resolves to `$GITHUB_WORKSPACE/geolens-enterprise` (where the second checkout landed).
- The detection is `-d` + `-f pyproject.toml` (mirrors backend/scripts/api-entrypoint.sh:46-58 — same conditional shape) — robust to half-finished checkouts.
- `OVERLAY_INSTALLED` is exported via `$GITHUB_ENV` so the conditional pytest step (Change 3) can read it.
- This step runs unconditionally; when the overlay is absent, it sets `OVERLAY_INSTALLED=0` and emits a clear log line so OSS contributors aren't confused by why their fork PR's lifecycle test is skipped.

**Change 3 — Replace the existing "Run tests with coverage" step** (currently at line 303-304):

BEFORE (existing):
```yaml
      - name: Run tests with coverage
        run: uv run pytest -v --tb=short -m 'not perf' --cov=app --cov-report=term-missing --cov-report=html:htmlcov --cov-report=xml:coverage.xml --cov-fail-under=58.5
```

AFTER (replace with):
```yaml
      - name: Run tests with coverage
        run: |
          if [ "${OVERLAY_INSTALLED:-0}" = "1" ]; then
            echo "Running pytest with lifecycle marker INCLUDED (overlay installed)"
            uv run pytest -v --tb=short -m 'not perf' --cov=app --cov-report=term-missing --cov-report=html:htmlcov --cov-report=xml:coverage.xml --cov-fail-under=58.5
          else
            echo "Running pytest with lifecycle marker DESELECTED (overlay unavailable on fork PR)"
            uv run pytest -v --tb=short -m 'not perf and not lifecycle' --cov=app --cov-report=term-missing --cov-report=html:htmlcov --cov-report=xml:coverage.xml --cov-fail-under=58.5
          fi
```

Notes:
- The non-overlay branch deselects `lifecycle` so fork PRs don't try to seed enterprise data they can't access.
- Both branches preserve the existing coverage flags exactly (`--cov=app --cov-report=...` block) so the coverage gate stays at `--cov-fail-under=58.5`.
- `${OVERLAY_INSTALLED:-0}` defaults to "0" if the env var is unset (defense-in-depth in case Change 2 is somehow skipped).

**DO NOT** modify any of these:
- The `frontend-lint`, `frontend-test`, or any other job in ci.yml.
- The `Start PostgreSQL with PostGIS + pgvector` step.
- The `astral-sh/setup-uv@v6`, `actions/setup-python@v5`, or `apt-get gdal-bin` steps.
- The `Set up database extensions, roles, and schemas` step.
- The `Run migrations` step (`uv run alembic upgrade head` — alembic auto-discovers the enterprise migration head when the overlay is installed because the enterprise package's entry point is `geolens.migrations`; see backend/tests/conftest.py:113-176 multi-head discovery).
- The `Upload backend coverage report` step.
- The first `actions/checkout@v4` step at line 239 (no `path:` parameter added — Strategy A).

**Step-ordering recap (pre-edit → post-edit):**

```
[ pre-edit ]                          [ post-edit ]
checkout                              checkout
                                      checkout geolens-enterprise (NEW; gated)
postgres setup                        postgres setup
setup-uv                              setup-uv
setup-python                          setup-python
apt-get gdal                          apt-get gdal
uv sync --locked --dev                uv sync --locked --dev
                                      install enterprise overlay (NEW; conditional)
db extensions                         db extensions
alembic upgrade head                  alembic upgrade head
pytest                                pytest (CONDITIONAL on OVERLAY_INSTALLED)
upload coverage                       upload coverage
```

**User-side prerequisite (DOCUMENT IN SUMMARY.md, do NOT block on this):**
The user (Ian / repo owner) must add the GitHub Actions secret `GEOLENS_ENTERPRISE_TOKEN` (a fine-grained PAT with `content:read` on `ishiland/geolens-enterprise`, ~1-year expiry) before this PR's CI run will exercise the lifecycle test. Without the secret, the workflow cleanly skips the lifecycle marker — no failure. With the secret, the lifecycle test runs as part of the normal pytest invocation. Surface this as user_setup in the SUMMARY.md.
  </action>
  <verify>
    <automated>
# 1. Cross-repo checkout step present and gated
grep -q 'repository: ishiland/geolens-enterprise' .github/workflows/ci.yml && \
grep -q 'GEOLENS_ENTERPRISE_TOKEN' .github/workflows/ci.yml && \
grep -q "secrets.GEOLENS_ENTERPRISE_TOKEN != ''" .github/workflows/ci.yml && \
# 2. Overlay install step present
grep -q 'uv add --editable ../geolens-enterprise' .github/workflows/ci.yml && \
grep -q 'OVERLAY_INSTALLED' .github/workflows/ci.yml && \
# 3. Conditional pytest invocation
grep -q "not perf and not lifecycle" .github/workflows/ci.yml && \
grep -q "not perf'" .github/workflows/ci.yml && \
# 4. Workflow YAML still parses (single-line YAML lint via python)
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && \
# 5. Diff scope: amended job only — no global rewrite
[ "$(git diff --numstat .github/workflows/ci.yml | awk '{print $1+$2}')" -lt 60 ]
    </automated>
  </verify>
  <acceptance_criteria>
    - `.github/workflows/ci.yml` contains the literal string `repository: ishiland/geolens-enterprise`.
    - `.github/workflows/ci.yml` contains the literal string `GEOLENS_ENTERPRISE_TOKEN` at least twice (the `if:` gate + the `token:` parameter).
    - `.github/workflows/ci.yml` contains the literal string `secrets.GEOLENS_ENTERPRISE_TOKEN != ''` (the fork-PR gating idiom).
    - `.github/workflows/ci.yml` contains the literal string `uv add --editable ../geolens-enterprise`.
    - `.github/workflows/ci.yml` contains the literal string `OVERLAY_INSTALLED` at least three times (set in install step, read in pytest step, plus the export `>> $GITHUB_ENV`).
    - `.github/workflows/ci.yml` contains both pytest invocations: `not perf` (overlay-installed branch) AND `not perf and not lifecycle` (fork-PR branch).
    - `.github/workflows/ci.yml` parses as valid YAML (`python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"` exits 0).
    - `git diff --numstat .github/workflows/ci.yml` shows fewer than 60 added+removed lines (proves targeted amendment of one job, not a workflow rewrite).
    - The first `actions/checkout@v4` step (originally at line 239) is unchanged — no `path:` parameter added (Strategy A).
    - The `Upload backend coverage report` step is unchanged (still at the end of the job).
    - No other job in ci.yml (frontend-lint, frontend-test, etc.) is modified.
  </acceptance_criteria>
  <done>backend-test job amended with cross-repo checkout (gated), conditional overlay install, and conditional pytest invocation. Workflow remains valid YAML. Fork PRs see lifecycle marker SKIPPED (clean), main / project-member PRs run lifecycle marker INCLUDED. LIFECYCLE-04's CI execution criterion is satisfied (subject to the user adding the GEOLENS_ENTERPRISE_TOKEN secret in repo settings).</done>
</task>

</tasks>

<verification>
- All 8 grep + YAML-validity assertions pass.
- Diff scope < 60 lines confirms targeted amendment.
- Manual visual diff: only the `backend-test` job is modified; no other job touched.
- After the user adds `GEOLENS_ENTERPRISE_TOKEN` to repo secrets, push to main runs the lifecycle test in CI; before they add it, fork-PR CI shows lifecycle skipped without failure.
</verification>

<success_criteria>
- LIFECYCLE-04 CI side satisfied: `pytest -m lifecycle` runs in CI when the overlay is available; cleanly skips on fork PRs.
- D-06 honored: CI installs `geolens-enterprise` before backend test job.
- Claude's Discretion option (a) honored: fork-PR gating via `secrets.X != ''`, no failure for OSS contributors.
- Pitfall 6 honored: secret-availability check, not a hardcoded `if: github.event_name == 'push'` (which would also work but is less explicit).
</success_criteria>

<output>
After completion, create `.planning/phases/220-lifecycle-runbooks-and-preservation/220-06-SUMMARY.md` capturing:
- Lines amended (with before/after counts).
- The user_setup prerequisite (`GEOLENS_ENTERPRISE_TOKEN` repo secret) — explicitly call out that the user must add this for CI to exercise the lifecycle marker on push to main.
- YAML lint result.
- Confirmation that no other job was touched.

Surface user_setup as:
```yaml
user_setup:
  - service: github_actions
    why: "CI lifecycle test requires private-repo checkout"
    env_vars:
      - name: GEOLENS_ENTERPRISE_TOKEN
        source: "GitHub → Settings → Developer settings → Personal access tokens (fine-grained); scope content:read on ishiland/geolens-enterprise"
    dashboard_config:
      - task: "Add GEOLENS_ENTERPRISE_TOKEN as a repository secret"
        location: "GitHub repo Settings → Secrets and variables → Actions → New repository secret"
```
</output>
