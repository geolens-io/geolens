# Phase 227: saml-test-fixture-tmp-path - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-02
**Phase:** 227-saml-test-fixture-tmp-path
**Mode:** `--auto --chain` (Claude auto-selected recommended option per gray area; no interactive prompts)
**Areas discussed:** Fixture file disposition, Docstring "CI fallback" resolution, tmp_path scope and wiring, CI safety guard, Pre-work / sequencing

---

## Fixture file disposition

| Option | Description | Selected |
|--------|-------------|----------|
| Rename to `.xml.b64.template` | Keep committed files as immutable templates; tests fall back to them when generator unavailable | ✓ |
| Remove committed fixtures entirely | Generator must always run; tests skip/fail if pysaml2 missing | |

**Rationale:** Success criterion #3 explicitly offers the rename option; it preserves the docstring's deliberate Phase-217 "CI fallback when pysaml2 unavailable" intent and gives a deterministic baseline for minimal CI containers, fork-PR contexts, and any env where pysaml2/xmlsec1 isn't installed. Files are small (~2-4 KB each) — disk cost negligible.

---

## Docstring "CI fallback" resolution

| Option | Description | Selected |
|--------|-------------|----------|
| Restore the fallback for real | Wire `_load_fixture_b64` so it actually reads `.xml.b64.template` files when no regenerated copy exists | ✓ |
| Delete the docstring claim | Remove the comment; rely on hard pysaml2 dependency | |

**Rationale:** Today's docstring says tests fall back to committed fixtures, but the autouse silently swallows `subprocess.CalledProcessError` and tests then read whatever broken state the generator left in-place — the claim is factually wrong today. Restoring the fallback (D-03 + D-07) makes the comment match reality and gives a real safety net.

---

## tmp_path scope and wiring

| Option | Description | Selected |
|--------|-------------|----------|
| `tmp_path_factory.mktemp("saml_responses")` (session-scoped) | Idiomatic pytest, automatic cleanup, session-scoped | ✓ |
| Custom `tempfile.mkdtemp` + manual cleanup | Hand-rolled temp dir with `yield` + `shutil.rmtree` | |

**Rationale:** `tmp_path_factory` is pytest's built-in mechanism for session-scoped temp dirs; no manual cleanup bookkeeping; matches today's `scope="session"` declaration naturally.

| Option | Description | Selected |
|--------|-------------|----------|
| Refactor `generate_fixtures.main()` to accept `output_dir` param | Generator-level injection; CLI mode preserved via default | ✓ |
| Module-level `FIXTURE_DIR` swap inside autouse | Reassign module global at fixture init; tests read global | |
| Generator stays unchanged, autouse copies files post-gen | Generate to HERE, immediately copy out + restore HEAD | |

**Rationale:** Function-parameter injection is the cleanest API; preserves manual `cd backend && uv run python tests/fixtures/saml/generate_fixtures.py` usage via `output_dir is None → HERE` default. Module-global mutation is action-at-a-distance; copy-then-restore re-introduces the mutation problem we're solving.

| Option | Description | Selected |
|--------|-------------|----------|
| In-process call via `from tests.fixtures.saml.generate_fixtures import main` | Faster, typed Path arg, no subprocess swallow | ✓ |
| Keep `subprocess.run([sys.executable, ...])` | Process isolation; matches current code | |

**Rationale:** In-process call is faster (~100-300ms saved per session), accepts `Path` directly without arg-string parsing, and removes the exception swallow that hides generator failures.

| Option | Description | Selected |
|--------|-------------|----------|
| Session-scoped `saml_response_dir` request-fixture | Tests opt in by parameter | ✓ |
| Session-scoped autouse | Today's pattern; runs even for non-SAML test runs | |

**Rationale:** Request-by-parameter is the more common pytest pattern, makes the dependency explicit, and avoids running the generator when filtered pytest invocations don't touch SAML tests.

---

## CI safety guard

| Option | Description | Selected |
|--------|-------------|----------|
| CI step: `git diff --quiet -- tests/fixtures/saml/` after pytest | One step in `backend-test` job; loud failure pointing at phase 227 | ✓ |
| Pre-commit hook only | Local-only enforcement; misses CI | |
| Both pre-commit + CI | Belt-and-braces | |

**Rationale:** CI is the authoritative enforcement layer (success criterion #1 mandates this). Pre-commit doesn't catch the regression because mutation only happens at pytest-time and most contributors don't run the full backend suite locally before committing. CI-only is sufficient.

---

## Pre-work / sequencing

| Option | Description | Selected |
|--------|-------------|----------|
| Restore the 5 dirty files to HEAD before refactor | `git checkout` first, then `git mv` to `.template` | ✓ |
| `git mv` directly (carrying working-tree mutations) | One commit; rename + content change conflated | |

**Rationale:** Restore-then-rename produces a pure rename in `git log --follow`; conflating rename with content change pollutes the diff and obscures intent.

---

## Claude's Discretion

- Whether `saml_response_dir` lives in `test_saml_overlay.py` (recommended) or `backend/tests/conftest.py`.
- Exact phrasing of CI error message; whether to `cat` failing fixture diffs in the failure output.
- `print(file=sys.stderr)` vs `pytest.warns(UserWarning)` for the "generator unavailable" diagnostic (D-05 recommends `print`).
- Commit granularity for the 5-step suggested ordering (D-10) — planner may collapse steps 3+4 if tests-stay-green per commit is preferred.

## Deferred Ideas

- Pre-commit hook for fixture mutations (CI alone is enough; revisit if class of bug recurs).
- `argparse` CLI flag for `output_dir` in `generate_fixtures.py` (function-only signature is sufficient).
- Cert/key (`idp_cert.pem` / `idp_key.pem`) rotation (separate ops task; 36500-day validity).
- Generic `test_no_fixture_mutation_in_pytest` architecture guard (only one known case today; revisit on second instance).
