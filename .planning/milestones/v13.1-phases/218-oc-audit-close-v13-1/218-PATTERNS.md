# Phase 218: oc-audit-close-v13.1 — Pattern Map

**Mapped:** 2026-04-29
**Files analyzed:** 4 (3 new + 1 modified)
**Analogs found:** 4 / 4

> **Note:** This is a verification/closing-audit phase. **No production code is touched.** The artifacts are markdown documents and two phase-local helper scripts (one Python, one bash). Three of the four files have strong analogs in-tree; one (the deferred-items doc modification) has no prior modification analog because the file is essentially newly tracked.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `docs-internal/audits/oc-separation-audit-v13.1-close.md` (NEW) | doc / audit report | report-generation | `docs-internal/audits/oc-separation-audit-20260426-b.md` | exact (same template — `/oc-audit` skill produces it; this phase only renames + appends) |
| `.planning/phases/218-oc-audit-close-v13-1/verify_close_audit.py` (NEW) | utility / verification script | file-I/O + parse + exit-code | `scripts/sync_sdk_versions.py` | role-match (standalone single-file Python validation script with `sys.exit` on failure; both read repo files, parse, and gate on success) |
| `.planning/phases/218-oc-audit-close-v13-1/preflight.sh` (NEW) | utility / pre-flight script | request-response (filesystem) + exit-code | `scripts/check-env.sh` | role-match (small bash script, `set -euo pipefail`, pass/fail helpers, ERRORS counter, non-zero exit on failure) |
| `docs-internal/audits/oc-separation-deferred-items-20260426.md` (MODIFIED) | doc / tracking table | row-replacement | (none — file has no prior modification commits in tree) | NO ANALOG — see "No Analog Found" below; use the verbatim row text from RESEARCH.md §"Pattern 3" instead |

---

## Pattern Assignments

### `docs-internal/audits/oc-separation-audit-v13.1-close.md` (doc / audit report) — NEW

**Analog:** `docs-internal/audits/oc-separation-audit-20260426-b.md`

**Why this analog:** The `/oc-audit` skill (`.claude/commands/oc-audit.md`) produces output that follows the same 8-section template every run; the source baseline is the same template applied to the v13.0 codebase. The closing audit is structurally identical except for (a) updated grades, (b) populated §8 grade-delta table, and (c) appended `## P1 Residual Triage` section per D-04.

**H1 + Scorecard pattern** (lines 1–17 of analog):
```markdown
# Open-Core Separation Audit — 2026-04-26 (re-run b)

> **Note:** This is a same-day re-run of `oc-separation-audit-20260426.md`. ...

## Scorecard

| Dimension | Grade | Rationale |
|-----------|-------|-----------|
| **Boundary Integrity** | **B** | Frontend audit-log export UI is now gated ... |
| **Seam Quality** | **C** | Same distribution as morning baseline: 3 🟡 Adaptable ... |
| **Inventory Accuracy** | **A−** | 20/21 community features present ... |
| **Deployment Separation** | **A** | Zero blockers ... |
| **Coupling Health** | **C** | Auth bottleneck unchanged ... |
| **OSS Surface Readiness** | **D** | Licensing remains clean Apache-2.0 throughout ... |

**Overall Readiness: B− (2.61 / 4.0)** — unchanged from the morning baseline.
```

**For closing audit:** Edit the H1 to `# Open-Core Separation Audit — v13.1 Close (YYYY-MM-DD)` per RESEARCH.md Pitfall 3. Scorecard cells are produced by the skill — do not hand-edit. Note the analog uses Unicode-minus (`A−` = U+2212) and `**bold**` cells; the parser tolerates both per RESEARCH.md Pattern 1.

**Section heading sequence** (H2 anchors at lines 5, 20, 30, 75, 103, 169, 226, 276, 313, 345 of analog):
```
## Scorecard
## Executive Summary
## 1. Feature Boundary Leakage
## 2. Extension Seam Quality
## 3. Feature Inventory Verification
## 4. Deployment Separation
## 5. Codebase Coupling
## 6. OSS Surface & Licensing
## 7. Prioritized Action Items
## 8. Comparison to Prior Audit
## P1 Residual Triage     ← NEW section appended per D-04 (not in analog)
```

**§8 grade-delta table to populate** (per CONTEXT.md D-03 — exact format mandated):
```markdown
## 8. Comparison to Prior Audit (Source baseline 2026-04-26-b)

| Dimension          | Source (2026-04-26) | v13.1 Close | Δ | Target | Met? |
|--------------------|---------------------|-------------|---|--------|------|
| Boundary Integrity | B                   | A−          | ↑ | A−     | ✓    |
| Seam Quality       | C                   | B           | ↑ | B      | ✓    |
| OSS Surface        | D                   | C           | ↑ | C      | ✓    |

### What Improved
- [terse narrative — bulleted list, mirror analog lines 347–349]

### What Regressed
- [bulleted list, mirror analog lines 350–352]

### What's Unchanged
- [bulleted list, mirror analog lines 353–362]
```

**P1 Residual Triage section to append** (per CONTEXT.md D-04 — exact schema mandated, no analog):
```markdown
## P1 Residual Triage

| # | Finding (audit ref) | File:line | Verdict | Rationale | Follow-up |
|---|---------------------|-----------|---------|-----------|-----------|
| 1 | [audit §N row]      | [file]    | Fix-now | [why]     | Phase 219 |
| 2 | …                   | …         | Demote  | [why P2]  | deferred-items.md row added |
| 3 | …                   | …         | Accept  | [why OOS] | none      |
```

**Failure-banner pattern** (D-07 — only written if any of the three target grades misses; not in analog):
```markdown
## ⚠ MILESTONE CLOSE BLOCKED

The following target grade(s) were not met. Per Phase 218 D-06, the milestone-close gate is held until remediation lands:

- **Boundary Integrity:** [actual] (target ≥ A−)  ← MISS
- ...

Recommendation: file remediation Phase 219 (`oc-audit-remediate-{dimension}`).
This audit doc is committed for visibility; chain control returned to user.
```

---

### `.planning/phases/218-oc-audit-close-v13-1/verify_close_audit.py` (utility / verification script) — NEW

**Analog:** `scripts/sync_sdk_versions.py`

**Why this analog:** The repo has no prior `verify_*.py` or `check_*.py` scripts. `sync_sdk_versions.py` is the closest because it (a) is a single-file standalone Python script under `scripts/`, (b) opens repo files via `pathlib`, (c) parses them with `re`/`json`, (d) writes results to stdout/stderr, (e) calls `sys.exit(1)` on validation failure, and (f) returns from `main()` with `raise SystemExit(main())`. Same shape as the verification gate per RESEARCH.md §"Code Examples".

**Module docstring + imports pattern** (`scripts/sync_sdk_versions.py:1-25`):
```python
"""Sync both SDK package versions to backend/openapi.json info.version.

Idempotent: same input always produces the same output. Run as part of
`make sdks` so the drift gate (`make sdks-check`) catches version drift in
the same diff that catches code drift (CONTEXT.md D-08).

Touches four files:
  - sdks/python/pyproject.toml          ([project] version)
  ...

Usage:
    uv run python scripts/sync_sdk_versions.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
```
Adopt for `verify_close_audit.py`: docstring states purpose + lists files checked + lists exit conditions; `from __future__ import annotations`; stdlib-only imports (`re`, `sys`, `pathlib`).

**Repo-rooted path constants pattern** (`scripts/sync_sdk_versions.py:27-32`):
```python
REPO_ROOT = Path(__file__).resolve().parent.parent
OPENAPI_PATH = REPO_ROOT / "backend" / "openapi.json"
PY_PYPROJECT = REPO_ROOT / "sdks" / "python" / "pyproject.toml"
PY_GEN_CONFIG = REPO_ROOT / "sdks" / "python" / ".openapi-python-client.yaml"
TS_PACKAGE = REPO_ROOT / "sdks" / "typescript" / "package.json"
```
Adopt for `verify_close_audit.py`: top-of-file constants for `CLOSE_PATH` and `DEFERRED_PATH`. Note the script lives at `.planning/phases/218-.../verify_close_audit.py` — depth is 3, so `Path(__file__).resolve().parent.parent.parent.parent` to reach repo root, OR (simpler / what RESEARCH.md uses) construct paths relative to the cwd assumption documented in the docstring (`# Run from repo root`). Prefer the latter to match RESEARCH.md §"Code Examples" verbatim and avoid path-arithmetic bugs.

**Existence + read pattern** (`scripts/sync_sdk_versions.py:35-49`):
```python
def _read_openapi_version() -> str:
    if not OPENAPI_PATH.exists():
        sys.stderr.write(
            f"backend/openapi.json missing at {OPENAPI_PATH}.\n"
            "Run `make openapi` first.\n"
        )
        sys.exit(1)
    spec = json.loads(OPENAPI_PATH.read_text())
    version = spec.get("info", {}).get("version")
    if not version or not isinstance(version, str):
        sys.stderr.write(
            "backend/openapi.json has no info.version string. Cannot sync.\n"
        )
        sys.exit(1)
    return version
```
Adopt for verify_close_audit.py: each Check function tests existence first, then parses, then validates a property, calls `sys.exit(1)` with a specific stderr message on each failure. RESEARCH.md §"Code Examples" already provides the exact failure messages — copy verbatim.

**Main + entry-point pattern** (`scripts/sync_sdk_versions.py:90-136`):
```python
def main() -> int:
    version = _read_openapi_version()
    # ... do the work ...
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```
Adopt for verify_close_audit.py: `main()` returns 0 on PASS; raise SystemExit at module bottom. RESEARCH.md §"Code Examples" uses inline `sys.exit(1)` calls inside helper functions instead of returning; either pattern works — prefer the helper-function approach from `sync_sdk_versions.py` for testability.

**Argparse pattern (optional — for `--strict` flag)** (`scripts/flatten_openapi_defs.py:278-292`):
```python
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Path to source OpenAPI JSON (e.g. backend/openapi.json).",
    )
    args = parser.parse_args()
    ...
```
Use only if the verification script needs CLI flags (e.g. `--allow-banner` to PASS even with the milestone-blocked banner). RESEARCH.md §"Code Examples" doesn't require argparse — keep the script flag-free unless needed.

**Error-handling convention:** Both analogs print failure messages to `sys.stderr` (via `sys.stderr.write(...)`) and exit non-zero; success messages go to `sys.stdout` via `print(...)`. RESEARCH.md §"Code Examples" uses a simpler `def fail(msg): print(f"FAIL: {msg}"); sys.exit(1)` helper that writes to stdout — that's a deliberate departure for human-readable gate output. Pick one convention and apply consistently.

**Reference implementation:** RESEARCH.md §"Code Examples" → "Verification Gate (Python script — paste-able into the plan)" provides a complete ~60-line script. The planner should use that body verbatim and only adopt the docstring/path-constants style from `sync_sdk_versions.py`.

---

### `.planning/phases/218-oc-audit-close-v13-1/preflight.sh` (utility / pre-flight script) — NEW

**Analog:** `scripts/check-env.sh`

**Why this analog:** Closest existing bash script that (a) does pre-flight validation, (b) is small (60 lines), (c) uses `set -euo pipefail`, (d) tracks failures via an `ERRORS` counter, (e) prints `OK:` / `FAIL:` per-check, (f) exits non-zero on any failure, and (g) emits a concluding summary line. Same shape as the Wave 0 evidence checks per RESEARCH.md §"Code Examples".

**Shebang + safety pattern** (`scripts/check-env.sh:1-2`):
```bash
#!/usr/bin/env bash
set -euo pipefail
```
Adopt verbatim. Required for any new bash script in this repo.

**Repo-root resolution pattern** (`scripts/check-env.sh:4-5`):
```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
```
For preflight.sh living at `.planning/phases/218-oc-audit-close-v13-1/preflight.sh`, climb three dirs: `cd "$SCRIPT_DIR/../../.."`. RESEARCH.md §"Code Examples" alternative uses `cd "$(git rev-parse --show-toplevel)"` — that's simpler and idiomatic; pick that one to match the research example.

**Pass/fail helper pattern** (`scripts/check-env.sh:15-25`):
```bash
ERRORS=0

pass() {
    echo "  OK: $*"
}

fail() {
    echo "  FAIL: $*" >&2
    ERRORS=$((ERRORS + 1))
}
```
Adopt for preflight.sh. RESEARCH.md §"Code Examples" inlines the failure as `|| { echo "FAIL: ..."; exit 1; }` — that's stricter (fail-fast on first error, no aggregation). Pick the aggregation approach (check-env.sh) so the user sees ALL pre-flight failures in one run, not just the first.

**Per-check pattern** (`scripts/check-env.sh:27-34`):
```bash
echo "=== Environment Variables ==="
for var in POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB; do
    if [ -n "${!var:-}" ]; then
        pass "$var is set"
    else
        fail "$var is not set"
    fi
done
```
Adapt for preflight.sh evidence checks: `if [ -f path ]; then pass "..."; else fail "..."; fi`. RESEARCH.md §"Code Examples" uses bare `test -f` / `test ! -f` / `test -d` — combine: use `test` for existence checks but wrap in the if/then/else pass/fail helpers from check-env.sh so the output is consistent.

**Final summary + exit pattern** (`scripts/check-env.sh:53-59`):
```bash
echo ""
if [ "$ERRORS" -gt 0 ]; then
    echo "$ERRORS check(s) failed." >&2
    exit 1
fi

echo "All checks passed."
```
Adopt verbatim — matches RESEARCH.md §"Code Examples" closing line `echo "ALL PRE-FLIGHT CHECKS PASS"`.

**Specific evidence checks to wire** (per CONTEXT.md `<code_context>` "Known facts to verify" + RESEARCH.md §"Code Examples"):

```bash
# Working tree clean (post-217 merged)
git status --porcelain | grep -v '^??' && fail "uncommitted changes" || pass "working tree clean"

# Phase 217 evidence
[ -f backend/app/modules/audit/router.py ] && pass "audit router exists" || fail "audit router missing"
grep -q 'require_enterprise' backend/app/modules/audit/router.py && pass "audit-export gate present" || fail "audit-export gate missing"
[ -f backend/app/modules/catalog/authorization.py ] && pass "catalog/authorization.py exists" || fail "..."
[ ! -f backend/app/modules/auth/visibility.py ] && pass "auth/visibility.py removed" || fail "..."
[ -f backend/openapi.json ] && pass "openapi.json present" || fail "..."
[ -d cli ] && pass "cli/ exists" || fail "..."
[ -d sdks/python/geolens_sdk ] && pass "python sdk present" || fail "..."

# Enterprise overlay (sibling repo)
[ -d ~/Code/geolens-enterprise/geolens_enterprise/auth/saml ] && pass "saml overlay present" || fail "..."

# SAML LOGIC (not column scaffolding) absent from core — RESEARCH.md Pitfall 5
HITS=$(rg -i 'class.*Saml|def.*saml' backend/app/ --no-messages | wc -l | tr -d ' ')
[ "$HITS" -eq 0 ] && pass "no SAML logic in backend/app/" || fail "$HITS SAML logic hit(s) in backend/app/"
```

**Critical:** RESEARCH.md Pitfall 5 calls out that a naive `rg -i saml backend/app/` returns 76 hits (column scaffolding, not real logic). The pre-flight regex MUST be `class.*Saml|def.*saml` to look for SAML *implementation*, not metadata strings.

---

### `docs-internal/audits/oc-separation-deferred-items-20260426.md` (doc / tracking table) — MODIFIED

**Analog:** NONE — file has no prior modification commits in tree (verified: `git log -- docs-internal/audits/oc-separation-deferred-items-20260426.md` returns no commits; the file appears to be gitignored or freshly added).

**Substitute pattern source:** RESEARCH.md §"Pattern 3: Six Closure Markers in deferred-items.md" provides the exact six row replacements verbatim with verified line anchors (`docs-internal/audits/oc-separation-deferred-items-20260426.md:9-14`). Use those instead of inferring an analog.

**Six exact substitutions** (apply via Edit tool, six small atomic edits — RESEARCH.md "Don't Hand-Roll" prefers Edit over `sed` for atomicity):

| # | Row anchor (first column substring) | Replace `New phase: ...` cell with |
|---|------|------|
| 1 | `**Auto-generate Python + TS SDKs from snapshotted OpenAPI**` | `Closed by Phase 215 (2026-04-27)` |
| 2 | `` **Ship `geolens` CLI (Apache-2.0)** `` | `Closed by Phase 216 (2026-04-27)` |
| 3 | `` **Refactor `auth/visibility.py` → `catalog/authorization.py`** `` | `Closed by Phase 213 (2026-04-27)` |
| 4 | `` **Extract `IdentityProtocol` in `core/identity.py`** `` | `Closed by Phase 214 (2026-04-27)` |
| 5 | `**Reintroduce SAML auth properly**` | `Closed by Phase 217 (2026-04-29)` |
| 6 | `**Break `core ↔ settings` layering inversion**` | `Closed by Phase 212 (2026-04-27)` |

**Verified raw row text** (from current `docs-internal/audits/oc-separation-deferred-items-20260426.md:9-14`):
```markdown
| **Auto-generate Python + TS SDKs from snapshotted OpenAPI** | §6 / §7 P1 | 3–5 days | Needs SDK tooling decision (openapi-generator vs openapi-typescript-codegen vs custom), publish targets (PyPI, npm), versioning strategy. The OpenAPI snapshot now exists (`backend/openapi.json`) so this is unblocked. | New phase: `sdks-from-openapi` |
| **Ship `geolens` CLI (Apache-2.0)** | §6 / §7 P1 | 1–2 weeks | Largest item in the bucket. Needs scope decision for which commands to ship (`scan`, `publish`, `export stac`, `login`), packaging story, distribution channel. The strategy's adoption wedge. | New phase: `geolens-cli-mvp` |
| **Refactor `auth/visibility.py` → `catalog/authorization.py`** | §5 / §7 P1 | 1–2 days | Touches 23 files (15 inbound visibility imports + 8 deferred-import callers). Mechanical but needs careful test coverage to avoid regressing dataset visibility. | New phase: `catalog-authz-relocate` |
| **Extract `IdentityProtocol` in `core/identity.py`** | §5 / §7 P1 | 3–5 days | Touches 51 `User` import sites across 11 domains. Prerequisite for any clean enterprise auth overlay (SAML, SCIM, multi-org). | New phase: `identity-protocol-extract` |
| **Reintroduce SAML auth properly** | §3 / §7 P1 | 2–3 weeks | Migration `2026_04_08_0001` removed the dead scaffold. Government buyers mandate SAML. Should land as part of an `auth-saml-overlay` enterprise extension, not back into core. | New phase: `auth-saml-enterprise` |
| **Break `core ↔ settings` layering inversion** | §5 (new finding) | 1–2 days | `core/persistent_config.py:30` and `core/public_urls.py:14` import `AppSetting` from `modules/settings`. Either move `AppSetting` to `core/db/models.py` or invert by registering a config provider into core at startup. | New phase: `core-settings-decouple` |
```

**Replacement strategy:** For each of the six rows, use the Edit tool with the entire line as `old_string` and the same line with the final cell substituted as `new_string`. Six edits, no batching, no regex. Each closure marker matches the regex `Closed by Phase \d{3} \(\d{4}-\d{2}-\d{2}\)` so verify_close_audit.py Check 6 finds all six.

---

## Shared Patterns

### Pattern S1: Stdlib-only Python with `from __future__ import annotations`

**Source:** `scripts/sync_sdk_versions.py:20-25`, `scripts/flatten_openapi_defs.py:67-74`
**Apply to:** `verify_close_audit.py`
**Why:** Both existing scripts use stdlib-only (`json`, `re`, `sys`, `pathlib`, `argparse`) with `from __future__ import annotations` at the top. Phase 218's verify script needs no third-party deps either — stick to the convention.

```python
from __future__ import annotations

import re
import sys
from pathlib import Path
```

### Pattern S2: `set -euo pipefail` for new bash scripts

**Source:** `scripts/check-env.sh:1-2`, `scripts/run-baseline.sh:1-2`
**Apply to:** `preflight.sh`
**Why:** Every bash script in `scripts/` uses this trio. `-e` exits on error, `-u` errors on unset variable, `-o pipefail` makes pipe failures propagate. Required for the pre-flight script to fail loudly.

```bash
#!/usr/bin/env bash
set -euo pipefail
```

### Pattern S3: H2 section anchor + table-driven content (for the audit + triage doc)

**Source:** `docs-internal/audits/oc-separation-audit-20260426-b.md` — every numbered section uses `## N. Title` followed by one or more H3 subsections, with findings expressed as markdown tables (3–5 columns). This is the skill template's output convention.
**Apply to:** `oc-separation-audit-v13.1-close.md` — the `## 8. Comparison to Prior Audit` section needs the grade-delta table format (D-03), and the appended `## P1 Residual Triage` section needs the 6-column table format (D-04). Both must use bordered markdown table syntax (`| --- |`) for the verify_close_audit.py regex to match (Check 5: `re.search(r"^\|", ...)`).

### Pattern S4: Commit message convention

**Source:** Recent git log (e.g., `chore(217): mark Phase 217 (auth-saml-enterprise) complete`, `docs(217-05): complete Phase 217 close — SUMMARY + deferred-items`)
**Apply to:** Phase 218 commit
**Format:** `docs(218): close v13.1 open-core audit (Boundary A− / Seam B / OSS C)` per RESEARCH.md System Architecture Diagram. Use `docs(...)` prefix because the only files touched are markdown + helper scripts, not production code. Per global CLAUDE.md: never indicate AI/Bot in the commit message.

---

## No Analog Found

| File | Role | Data Flow | Reason | Substitute |
|------|------|-----------|--------|------------|
| `docs-internal/audits/oc-separation-deferred-items-20260426.md` (modified) | doc / tracking-table modification | row-replacement | The file has zero prior modification commits in `git log`. Most files in `docs-internal/audits/` are untracked; only the v13.0-era files (`builder-audit-20260417.md`, `post-impl-20260425-d.md`, `test-debt-backend-20260425.md`) appear in `git ls-files docs-internal/audits/`. There is no prior `git diff` showing how this kind of update was done. | RESEARCH.md §"Pattern 3" provides the six exact row substitutions with verified line numbers. Use Edit tool with full-line `old_string`/`new_string` pairs (RESEARCH.md "Don't Hand-Roll" prefers Edit over `sed -i` for atomicity + macOS portability). |

**Counterpart note for the other three files:** All three other artifacts (closing audit doc, verify_close_audit.py, preflight.sh) have strong role-match analogs and clear source files. The planner can ground every action in concrete excerpts above without inventing patterns.

---

## Metadata

**Analog search scope:**
- `scripts/` — for Python and bash standalone scripts
- `tools/`, `deployment/` — confirmed absent (no such directories)
- `.planning/phases/**/*.{py,sh}` — confirmed empty (no prior phase has shipped a phase-local helper script)
- `docs-internal/audits/` — for prior audit document templates
- `git log` on `docs-internal/audits/oc-separation-deferred-items-20260426.md` — confirmed zero prior commits

**Files scanned (non-overlapping reads, no re-reads):**
- `.planning/phases/218-oc-audit-close-v13-1/218-CONTEXT.md` (1× full read, 223 lines)
- `.planning/phases/218-oc-audit-close-v13-1/218-RESEARCH.md` (1× full read, 647 lines)
- `scripts/sync_sdk_versions.py` (1× full read, 137 lines — analog for verify script)
- `scripts/flatten_openapi_defs.py` (1× full read, 338 lines — secondary analog for argparse pattern)
- `scripts/check-env.sh` (1× full read, 60 lines — analog for preflight)
- `scripts/run-baseline.sh` (1× full read, 183 lines — secondary analog for set -euo pipefail + multi-step bash)
- `docs-internal/audits/oc-separation-audit-20260426-b.md` (2× targeted reads — lines 1-120 and 300-373; non-overlapping; analog for closing audit doc)
- `docs-internal/audits/oc-separation-deferred-items-20260426.md` (1× partial read, lines 1-40 — confirms verbatim row anchors from RESEARCH.md Pattern 3)
- `.claude/commands/oc-audit.md` (1× grep on H2 anchors only — confirms 8-section template)

**Pattern extraction date:** 2026-04-29
**Phase:** 218 — oc-audit-close-v13.1
