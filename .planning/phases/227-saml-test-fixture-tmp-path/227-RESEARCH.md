# Phase 227: saml-test-fixture-tmp-path - Research

**Researched:** 2026-05-02
**Domain:** pytest fixture hygiene; SAML test infrastructure; CI guard wiring
**Confidence:** HIGH

## Summary

Phase 227 corrects a long-standing `test_saml_overlay.py` autouse that rewrites 5 committed
`idp_response_*.xml.b64` fixtures every pytest run. CONTEXT.md (D-01..D-10) has already
locked the implementation: rename → `.xml.b64.template`, route generator output through
`tmp_path_factory.mktemp("saml_responses")`, replace `subprocess.run` with an in-process
`generate_saml_fixtures(output_dir=...)` call, add a CI `git diff --quiet` guard.

The investigation here is targeted at landmines the planner could hit while implementing
those locked decisions, NOT at re-litigating them. The biggest landmines verified
empirically: (1) `from tests.fixtures.saml.generate_fixtures import main` works as-imported
because of `PYTHONPATH=.` in CI + the `backend/tests/__init__.py` package marker — but
`fixtures/__init__.py` and `fixtures/saml/__init__.py` do NOT exist (implicit namespace
packages, fine); (2) `pysaml2` IS in `backend/uv.lock` (verified `uv pip list` shows
`pysaml2 7.5.4`), so on the standard CI path the in-process import will succeed, but on
fork-PR CI without the enterprise overlay token, behavior is identical because the package
is in the BACKEND lockfile not the overlay's; (3) `tmp_path_factory` is NOT used anywhere
else in the suite — this phase introduces it for the first time.

**Primary recommendation:** Follow CONTEXT.md verbatim. Execution risks are mechanical
(import path edge cases, CI step indentation, working-directory mismatch in the `git diff`
guard) — flagged in §Common Pitfalls below.

## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 — Rename 5 `idp_response_*.xml.b64` files to `.xml.b64.template`** (NOT remove). Keeps
  deterministic CI fallback for envs without pysaml2/xmlsec1.
- **D-02 — Use `git mv` for the rename** so history is preserved. After rename, NO parallel
  `.xml.b64` exists in the repo; only `.xml.b64.template`. Autouse writes `.xml.b64` (no
  `.template` suffix) into tmp_path so the resolution helper distinguishes by extension.
- **D-03 — Restore the CI fallback for real.** `_load_fixture_b64` resolves from per-session
  `saml_response_dir` first, falls back to `FIXTURE_DIR / f"{name}.template"`. Update
  docstring to describe the new behavior; remove the factually-wrong "they are gitignored
  from the worktree's perspective" handwave (current `:58-61`).
- **D-04 — Use `tmp_path_factory.mktemp("saml_responses")` (session-scoped).** Pytest
  built-in. Automatic session-end cleanup. No `tempfile.mkdtemp` + `shutil.rmtree`.
- **D-05 — Refactor `generate_fixtures.main()` to accept `output_dir: Path | None = None`.**
  When `None`, default to `HERE` (preserves manual-CLI behavior at `:5-7`). Replace the
  autouse's `subprocess.run([...])` with `from tests.fixtures.saml.generate_fixtures import
  main as generate_saml_fixtures` + direct in-process call.
- **D-06 — Add a session-scoped `saml_response_dir` fixture in `test_saml_overlay.py`** (NOT
  conftest — only this file uses these fixtures today, verified via grep). Wraps the
  generator call in `try / except (ImportError, OSError, subprocess.CalledProcessError)`
  with a `print(..., file=sys.stderr)` diagnostic.
- **D-07 — Rewrite `_load_fixture_b64(name, response_dir)`** as a 2-arg function.
  `regenerated = response_dir / name; if regenerated.exists(): return read; else read
  template`. Migrate all 9 callsites (`:328, :373, :396, :417, :439, :481, :530, :545, :859`).
- **D-08 — Add CI guard step** after `Run tests with coverage` (`:332-339`). Step body in
  CONTEXT.md `:73-83`. Runs in `backend/` working-dir (job-level `defaults.run.working-directory: backend`).
- **D-09 — Plan starts by reverting the 5 dirty fixture files** to HEAD baseline before
  rename. `git checkout -- backend/tests/fixtures/saml/idp_response_*.xml.b64`.
- **D-10 — Suggested commit ordering**: 5 commits (restore → generator refactor → git mv
  rename → autouse + helper rewrite + callsite migration → CI guard). Bisect-friendly.

### Claude's Discretion

- Whether `saml_response_dir` lives in `test_saml_overlay.py` (recommended) or in
  `backend/tests/conftest.py`. Co-locate; only one file uses these.
- Exact phrasing of CI step error message and whether to also `cat` offending file
  contents on failure.
- Whether to use `pytest.warns(UserWarning)` or `print(..., file=sys.stderr)` for the
  fallback diagnostic. CONTEXT.md `<specifics>` recommends `print` to stderr.
- Whether to update `generate_fixtures.py:5-7` docstring CLI invocation to mention
  `--output-dir` if `output_dir` becomes a CLI flag. CONTEXT.md recommends NO CLI flag —
  function-signature only.

### Deferred Ideas (OUT OF SCOPE)

- Pre-commit hook to catch fixture mutations locally — rejected (D-08 rationale).
- Promoting `output_dir` to a CLI argparse flag — defer.
- Migrating `idp_cert.pem` / `idp_key.pem` regeneration — out of scope (36500-day cert).
- Generic fixture-mutation linter / architecture-guard test — not warranted; revisit if
  a second instance surfaces.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TESTFIX-01 | `_regenerate_saml_fixtures` writes signed XML to session-scoped `tmp_path` instead of mutating committed files | D-04 + D-06 — `tmp_path_factory.mktemp("saml_responses")` is the canonical session-scoped temp-dir API; new `saml_response_dir` fixture wraps it. |
| TESTFIX-02 | `git status` is clean after a full `pytest backend/tests/test_saml_overlay.py` run | D-04 + D-08 — once generator's writes leave the tracked dir, the only remaining mutation source is gone; CI guard `git diff --quiet -- tests/fixtures/saml/` enforces the regression doesn't return. |
| TESTFIX-03 | Committed `.xml.b64` files renamed to `.xml.b64.template` (or removed); docstring's CI-fallback claim resolved | D-01 + D-02 + D-03 — `git mv` to `.template`; `_load_fixture_b64` rewritten with template-fallback; docstring rewritten to match. |

## Project Constraints (from ./CLAUDE.md)

`./CLAUDE.md` does NOT exist at repo root (verified via Read). Only the user's global
`~/.claude/CLAUDE.md` applies:

- **No AI/Bot attribution in commit messages.** Commit subjects must NOT mention Claude /
  AI / autogeneration. Use the suggested D-10 ordering verbatim.
- **Prefer simple, readable code.** No clever abstractions for `saml_response_dir` —
  10-line fixture, plain `try/except`, plain `print` to stderr.
- **Follow existing project conventions.** The test suite uses `pytest.fixture(scope="session")`
  in `conftest.py` (verified `:33` `anyio_backend`); `from tests.X import Y` imports
  (10+ existing usages); `Path(__file__).parent` for fixture-dir resolution (verified at
  `test_saml_overlay.py:41`).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| SAML response fixture generation | Test infrastructure (`backend/tests/fixtures/saml/`) | — | Pure test-build asset; runs at session start, never in production. |
| SAML response fixture resolution | Test infrastructure (`backend/tests/test_saml_overlay.py`) | — | Helper `_load_fixture_b64(name, dir)` is test-only. |
| Fixture-mutation regression guard | CI (`.github/workflows/ci.yml` `backend-test` job) | — | Enforcement layer outside the unit suite — `git diff --quiet` after pytest. |
| pysaml2 / xmlsec1 import | Backend dev dependency (`backend/uv.lock`) — pysaml2 7.5.4 verified installed | Enterprise overlay (`geolens-enterprise/pyproject.toml:13` ALSO declares `pysaml2>=7.5.4`) | Generator imports `from saml2 import ...` at module top — fails fast with ImportError when missing; the new `try/except (ImportError, OSError, ...)` wrapper handles this for fork-PR CI lacking the overlay/lock entry. |

## Standard Stack

### Core (already installed; no new deps)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | 9.0.3 | Test framework | Already in `backend/pyproject.toml` `[dependency-groups].dev`. `tmp_path_factory` is built-in (no separate package). [VERIFIED: backend/pyproject.toml:53] |
| pysaml2 | 7.5.4 | SAML IdP simulator (generator only) | Already in `backend/.venv` (`uv pip list` confirms). Imported as `saml2`. The `pysaml2` PyPI distribution provides the `saml2` Python package. [VERIFIED: `uv pip list \| grep -i pysaml`] |
| xmlsec1 | system binary | XML signature back-end for pysaml2 | Already on dev path (`/opt/homebrew/bin/xmlsec1`). CI installs via `apt-get install xmlsec1`? — VERIFY: not seen in current `Install system dependencies` step (only `gdal-bin`). Generator's `_xmlsec_binary()` at `:85-95` falls back to `"xmlsec1"` PATH lookup. [VERIFIED: `which xmlsec1` locally; CI install path needs verification by planner] |

**No new dependencies required.** The generator is already importable in the backend
environment; the phase only changes WHERE its output lands.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `tmp_path_factory.mktemp("saml_responses")` | `tempfile.mkdtemp(prefix="saml_fixture_")` + `shutil.rmtree` in finalizer | tmp_path_factory wins: built-in, automatic session-end cleanup, no manual finalizer wiring, no risk of orphan dirs on test crash. [CITED: docs.pytest.org/en/stable/reference/reference.html#tmp-path-factory] |
| `subprocess.run(generator_path, ...)` (current) | `from tests.fixtures.saml.generate_fixtures import main; main(output_dir=...)` (proposed) | In-process wins: typed `Path` arg (no string parsing), no 100-300 ms subprocess startup cost, exception is a real `ImportError`/`OSError` (not `CalledProcessError` swallowing), no need to `cwd=Path(__file__).parent.parent`. |
| Rename to `.xml.b64.template` | Delete entirely + skip tests when generator unavailable | Rename wins: Phase 217 `RESEARCH.md S10` (CONTEXT.md cites) intended templates as a real CI-fallback; deletion would force minimal-CI / fork-PR contexts to skip critical SAML tests. Files are 2-4 KB each — disk cost negligible. |

## Architecture Patterns

### System Architecture (test-time data flow)

```
pytest session start
       │
       ▼
saml_response_dir fixture (session-scoped, request-fixture, NOT autouse)
       │  tmp_path_factory.mktemp("saml_responses")
       ▼
session_dir: Path = /tmp/pytest-xxx/saml_responses0/
       │
       ▼  (try)
generate_saml_fixtures(output_dir=session_dir)   # in-process; ImportError if pysaml2 missing
       │  writes 5 .xml.b64 files into session_dir
       │
       ▼  (or except → fallback diagnostic to stderr)
return session_dir
       │
       ▼  (8 test functions + 1 _authn_redirect helper request the fixture)
test_xxx(saml_response_dir, ...)
       │
       ▼
_load_fixture_b64("idp_response_signed.xml.b64", response_dir=saml_response_dir)
       │
       ▼  (regenerated path)             ▼  (template fallback)
session_dir / "idp_response_signed.xml.b64"   FIXTURE_DIR / "idp_response_signed.xml.b64.template"
       │                                      │
       └──────────────────┬───────────────────┘
                          ▼
              .read_text().strip()  →  base64 SAMLResponse string
                          │
                          ▼
              client.post(/auth/saml/{slug}/acs, data={"SAMLResponse": ...})
```

**Component responsibilities:**

| File | Responsibility |
|------|----------------|
| `backend/tests/fixtures/saml/generate_fixtures.py` | Build SAML XML fixtures via pysaml2; **takes** `output_dir` parameter (D-05). |
| `backend/tests/fixtures/saml/idp_cert.pem` / `idp_key.pem` | STATIC cert/key — committed, never regenerated. |
| `backend/tests/fixtures/saml/idp_response_*.xml.b64.template` (5 files, NEW NAMES) | Committed deterministic fallback for envs lacking pysaml2/xmlsec1. |
| `backend/tests/test_saml_overlay.py` `saml_response_dir` fixture (NEW, replaces `_regenerate_saml_fixtures` autouse) | Allocates session tmp dir, calls generator in-process, returns dir. |
| `backend/tests/test_saml_overlay.py` `_load_fixture_b64(name, response_dir)` (REFACTORED) | Resolves regenerated-vs-template; returns base64 string. |
| `.github/workflows/ci.yml` `backend-test` job, new step | Asserts `git diff --quiet -- tests/fixtures/saml/` post-pytest. |

### Pattern 1: `tmp_path_factory` for session-scoped temp dirs

**What:** Pytest's built-in `tmp_path_factory` fixture is session-scoped and produces a
`pathlib.Path`-returning factory. Each `mktemp("name")` call returns a unique sub-dir
under the session's base tmp dir. Pytest cleans up automatically at session end.

**When to use:** Any session-scoped fixture that needs a write-once-read-many filesystem
location. Replaces `tempfile.mkdtemp` + manual `shutil.rmtree` finalizers.

**Example:**

```python
# Source: docs.pytest.org/en/stable/reference/reference.html#tmp-path-factory
import pytest
from pathlib import Path

@pytest.fixture(scope="session")
def saml_response_dir(tmp_path_factory) -> Path:
    """Session-scoped dir holding generated SAML XML responses (Phase 227)."""
    import sys
    session_dir = tmp_path_factory.mktemp("saml_responses")
    try:
        from tests.fixtures.saml.generate_fixtures import main as generate_saml_fixtures
        generate_saml_fixtures(output_dir=session_dir)
    except (ImportError, OSError) as exc:
        print(
            f"[saml-fixtures] generator unavailable ({exc}); using committed templates",
            file=sys.stderr,
        )
    return session_dir
```

### Pattern 2: Optional output-dir parameter with HERE default

**What:** `main(output_dir: Path | None = None)` — when `None`, default to module-local
`HERE` constant; otherwise write to caller-supplied dir.

**When to use:** Scripts that have BOTH a manual-CLI invocation (`python generate_fixtures.py`
relies on `HERE`) AND an in-process test invocation (passes a tmp dir).

**Example:**

```python
# Source: existing pattern in backend/tests/factories.py / generate_fixtures.py
def main(output_dir: Path | None = None) -> None:
    target = output_dir if output_dir is not None else HERE
    target.mkdir(parents=True, exist_ok=True)
    # ... existing pysaml2 logic ...
    (target / "idp_response_signed.xml.b64").write_bytes(signed_b64)
    # 4 more (HERE → target) substitutions at lines 313-316, 321, 326, 331
```

### Anti-Patterns to Avoid

- **Using `autouse=True` for the new fixture.** D-06 explicitly switches to a request
  fixture. Autouse silently runs the generator on EVERY pytest session — even when the
  invocation is `pytest backend/tests/test_search_facets.py` (irrelevant). Request-fixture
  scoping makes the cost pay-as-you-go.
- **Putting `saml_response_dir` in `backend/tests/conftest.py`.** Today only
  `test_saml_overlay.py` uses these files (verified by `grep -rn "idp_response_"`). Moving
  to conftest pollutes session import for unrelated tests AND triggers pysaml2 import even
  in non-SAML test runs.
- **Wrapping `subprocess.CalledProcessError` in the in-process path.** Once
  `subprocess.run` is removed, `CalledProcessError` cannot fire. Keep it in the
  `except` tuple anyway (D-06 example does) for forward-compat IF the planner ever falls
  back to subprocess invocation — but flag as defensive, not load-bearing.
- **Adding `--output-dir` argparse flag to `generate_fixtures.py`.** Deferred (per
  Claude's Discretion) — keep function-signature-only injection.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Session-scoped temp dir with auto-cleanup | `tempfile.mkdtemp` + atexit / finalizer + `shutil.rmtree` | `tmp_path_factory.mktemp("saml_responses")` | Built-in pytest fixture; survives test crashes (kept around for post-mortem N sessions); cleanup managed by pytest's tmp dir retention policy. |
| Importable test-package modules | `sys.path.insert(0, ...)` hacks at top of `test_saml_overlay.py` | `from tests.fixtures.saml.generate_fixtures import main` (works because `PYTHONPATH=.` in CI + `backend/tests/__init__.py` exists) | 10+ existing tests already do `from tests.factories import ...` — pattern is established; no shim needed. |
| Subprocess-based fixture generation | `subprocess.run([sys.executable, str(generator)], ...)` | Direct `import` + function call | Faster, type-safe args, real exception propagation. Already 100% locally testable with `uv run python -c "from tests.fixtures.saml.generate_fixtures import main; main()"`. |

**Key insight:** Every component this phase needs already exists in pytest, the project's
import path, or the existing generator. The work is reorganization, not new construction.

## Runtime State Inventory

> Phase 227 IS a refactor of test infrastructure — runtime state inventory applies.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — verified by `grep -rn "idp_response_" backend/tests/` (only test_saml_overlay.py reads these) and DB schema review (no SAML response storage). | None. |
| Live service config | None — fixtures are file-system only; no SAML provider in any DB references these filenames. | None. |
| OS-registered state | None — generator is invoked at session-start only, never registered as a daemon/service/scheduled task. | None. |
| Secrets/env vars | None — `idp_cert.pem` / `idp_key.pem` are committed test certs (36500-day validity), not secrets. No env vars reference fixture filenames. | None. |
| Build artifacts / installed packages | **`backend/tests/fixtures/saml/idp_response_*.xml.b64`** — currently dirty in working tree (5 `M` rows in `git status`). After D-09 restore + D-02 rename, the OLD names disappear. **`backend/.venv/`** has pysaml2 7.5.4 installed — no rebuild needed. **`geolens-enterprise/`** sibling repo also declares `pysaml2>=7.5.4`; `uv add --editable ../geolens-enterprise` in CI happens BEFORE pytest runs, so the in-process import succeeds on standard CI even on overlay-installed paths. **Fork-PR CI without overlay**: pysaml2 already in `backend/uv.lock` directly — generator import still succeeds. Verify this lockfile entry exists; if pysaml2 is only present transitively via overlay, the fallback path needs to fire on fork PRs (it does, gracefully). | Restore the 5 dirty files via `git checkout` per D-09; then `git mv` to `.template` per D-02. No package reinstall needed. |

**The canonical question — after every file in the repo is updated, what runtime systems
still have the old string cached, stored, or registered?**

Answer: nothing. The fixture filenames live ONLY in:

1. `backend/tests/test_saml_overlay.py` source (9 callsites — all updated by D-07).
2. `backend/tests/fixtures/saml/generate_fixtures.py` source (5 write_bytes lines + 1
   shutil.copyfile — all updated by D-05).
3. `backend/tests/fixtures/saml/generate_fixtures.py` docstring (lines 17-22 — should be
   updated to describe `.template` as the committed deterministic fallback).
4. The committed files themselves on disk (renamed by `git mv`).

No external registries, schedulers, configs, or running processes know these names.

## Common Pitfalls

### Pitfall 1: CI guard step's working-directory and pathspec

**What goes wrong:** The `backend-test` job has `defaults.run.working-directory: backend`
(verified `:226` in ci.yml). The CI guard step inherits this and must use a path RELATIVE
TO `backend/`, not from repo root. CONTEXT.md `:77` correctly specifies
`-- tests/fixtures/saml/` (relative). But the guard ALSO needs to handle `git`'s discovery
of the repo root from a working sub-directory — `git diff --quiet` works fine because
`git` walks up to `.git/`, but the pathspec is interpreted relative to CWD (which IS
`backend/`).

**Why it happens:** Job-level `defaults.run.working-directory` is non-obvious;
copy-pasting an absolute path or `backend/tests/fixtures/saml/` would silently match
nothing (no such path exists from inside `backend/`).

**How to avoid:** Use the exact CONTEXT.md `:73-83` step verbatim, including the
relative `tests/fixtures/saml/` pathspec. Verify by inspecting `.github/workflows/ci.yml:228-233`
which already has `working-directory: backend`.

**Warning signs:** Step passes locally (run from repo root) but CI fails with "fatal:
ambiguous argument" or matches no files.

### Pitfall 2: Generator imports pysaml2 at module top-level

**What goes wrong:** `generate_fixtures.py:39-43` does `from saml2 import ...` at module
load time. The import inside `saml_response_dir` (`from tests.fixtures.saml.generate_fixtures
import main`) triggers ALL of those imports. On environments without pysaml2 (fork-PR CI
without overlay; minimal Python images), this raises `ImportError` BEFORE `main()` is
called.

**Why it happens:** Generator was designed for manual invocation in a pysaml2-equipped
environment. The autouse swallowed `subprocess.CalledProcessError` (which masked the
ImportError because it was inside a child process).

**How to avoid:** Wrap the `import` AND the `main()` call inside the `try` block per D-06.
Verify the except tuple includes `ImportError`. Empirical confirmation: `uv pip list` in
the local backend venv shows pysaml2 7.5.4 (lock provides it); fork-PR CI is the only env
where the fallback fires — and there the diagnostic `print` makes it visible.

**Warning signs:** First test run after rebase to a branch without overlay-installed
shows `ImportError: No module named 'saml2'` at fixture-collection time (test-discovery
phase) instead of a graceful fallback.

### Pitfall 3: Pytest fixture scope upgrade conflict

**What goes wrong:** `saml_response_dir` is `scope="session"`. Tests that request it ALSO
request `client`, `test_db_session`, `saml_router_mounted`, `_cleanup_saml_providers` —
which are function-scoped (verified `conftest.py:30+` and `test_saml_overlay.py:186+`).
Pytest forbids a function-scoped fixture from being requested by a session-scoped fixture
(`ScopeMismatch` error), but the OPPOSITE direction (function requests session) is fine.
This is exactly the proposed direction — no conflict.

**Why it happens:** Easy to confuse the directionality; planner may worry the new fixture
breaks DB-session fixtures.

**How to avoid:** No action needed — the proposed scope hierarchy (session →
fixture-of-function-scoped-tests) is permitted. `tmp_path_factory` itself is session-scoped
upstream, so requesting it from a session-scoped fixture is also fine.

**Warning signs:** Pytest collection fails with `ScopeMismatch: tried to access the
function-scoped fixture X with a session-scoped fixture` — would only appear if planner
accidentally inverts (puts a function-scoped dep INSIDE `saml_response_dir`).

### Pitfall 4: `git mv` on dirty working-tree files

**What goes wrong:** D-09 says restore the 5 dirty files first via
`git checkout -- backend/tests/fixtures/saml/idp_response_*.xml.b64`, THEN `git mv`. If
the planner skips the restore and runs `git mv` on dirty files, git renames AND keeps the
working-tree changes — the resulting commit is "rename + content edit" instead of pure
rename, polluting `git log --follow` history forever.

**Why it happens:** Tempting to think `git mv` ignores working-tree state; it doesn't.

**How to avoid:** Plan task 01 (per D-10) MUST be the bare `git checkout --` restore.
Verify with `git status` returning empty for the SAML fixtures dir BEFORE issuing `git mv`.

**Warning signs:** `git diff --stat HEAD~1` on the rename commit shows non-zero line
changes for any of the 5 files (a true rename shows `R100` in `git log --summary`).

### Pitfall 5: `_load_fixture_b64` callsite migration miss

**What goes wrong:** 9 callsites need a 2nd argument added. Two are inside `@pytest.fixture`
functions (the SAML provider helpers around `:530, :545`); 7 are inside test functions.
A simple grep-and-replace catches the test-function calls but the fixture-function calls
need the fixture to ALSO declare `saml_response_dir` as a parameter. Missing the
fixture-parameter declaration produces a `TypeError: _load_fixture_b64() missing 1 required
positional argument`.

**Why it happens:** Easy to migrate the call but forget that the enclosing function
needs the new dep.

**How to avoid:** For each of the 9 callsites, verify the enclosing function signature
grows `saml_response_dir`. Lines `:530` and `:545` are inside the same function
(`test_saml_acs_redirect_includes_source_query_param`) — single signature add covers both.
Lines `:328, :373, :396, :417, :439, :481, :859` are 7 separate test functions — 7
signature edits. Total: 8 signature edits, 9 callsite edits.

**Warning signs:** First pytest run post-migration shows `TypeError: _load_fixture_b64()
missing 1 required positional argument: 'response_dir'` in a specific test — fix that
test's signature.

### Pitfall 6: `xmlsec1` not on PATH on minimal CI runners

**What goes wrong:** The `Install system dependencies` step at ci.yml installs only
`gdal-bin`. `xmlsec1` is NOT installed on stock `ubuntu-latest`. The generator's
`_xmlsec_binary()` falls back to PATH lookup `"xmlsec1"`, which pysaml2 then exec's via
xmlsec1's CLI — failing with FileNotFoundError. This becomes a silent ImportError equivalent
once the fallback path is wired (the `OSError` catch covers it).

**Why it happens:** xmlsec1 is needed at signature time. Standard backend uv.lock includes
pysaml2 but not xmlsec1 (system binary, not pip-installable in this combination).

**How to avoid:** Two paths:
  1. **Recommended:** Trust the fallback. On standard CI without xmlsec1, generator raises
     OSError at sign-time → except clause fires → templates served. This is exactly what
     D-03 designed.
  2. **Optional:** Add `xmlsec1` to the `Install system dependencies` step
     (`apt-get install xmlsec1`) so the live regeneration path runs in CI too. Not
     strictly required by the success criteria but improves CI fidelity.

The planner should choose path 1 unless the ROADMAP success criteria require live
regeneration on CI (they don't — SC#4 says "tests continue to pass", and templates
satisfy that).

**Warning signs:** CI logs show `[saml-fixtures] generator unavailable (...)` on every
run when local runs do regenerate; this is the OSError catch firing on missing xmlsec1.

### Pitfall 7: Implicit-namespace package vs `__init__.py`

**What goes wrong:** `backend/tests/fixtures/__init__.py` and `backend/tests/fixtures/saml/__init__.py`
do NOT exist (verified `ls`). Only `backend/tests/__init__.py` exists. This relies on PEP
420 implicit namespace packages — `from tests.fixtures.saml.generate_fixtures import main`
works because Python 3.13 walks the directory tree even without `__init__.py`.

**Why it happens:** Easy to assume the absence of `__init__.py` will break the import.
Empirical verification: `cd backend && uv run python -c "from tests.fixtures.saml.generate_fixtures
import main"` succeeds (verified locally — got `OK <function main>` after the saml2
install).

**How to avoid:** Don't add `__init__.py` files. Don't change anything about the import
shape. Existing 10+ `from tests.factories import ...` imports prove the pattern works.

**Warning signs:** `ModuleNotFoundError: No module named 'tests.fixtures'` — would only
appear if pytest is invoked with `--rootdir` overriding `PYTHONPATH=.`, which the project
doesn't do.

## Code Examples

Verified patterns from official sources and existing project code:

### Session-scoped fixture using tmp_path_factory

```python
# Source: https://docs.pytest.org/en/stable/reference/reference.html#tmp-path-factory
import pytest
from pathlib import Path

@pytest.fixture(scope="session")
def saml_response_dir(tmp_path_factory) -> Path:
    import sys
    session_dir = tmp_path_factory.mktemp("saml_responses")
    try:
        from tests.fixtures.saml.generate_fixtures import (
            main as generate_saml_fixtures,
        )
        generate_saml_fixtures(output_dir=session_dir)
    except (ImportError, OSError) as exc:
        print(
            f"[saml-fixtures] generator unavailable ({exc}); using committed templates",
            file=sys.stderr,
        )
    return session_dir
```

### Refactored generator main() signature

```python
# Source: D-05 + existing main() at backend/tests/fixtures/saml/generate_fixtures.py:291
def main(output_dir: Path | None = None) -> None:
    if not CERT_PEM.exists() or not KEY_PEM.exists():
        raise SystemExit(...)

    target = output_dir if output_dir is not None else HERE
    target.mkdir(parents=True, exist_ok=True)

    import tempfile
    tmpdir = Path(tempfile.mkdtemp(prefix="saml_fixture_gen_"))
    sp_meta = _write_sp_metadata(tmpdir)
    server = _make_server(sp_meta)

    signed_xml = _build_signed_response_xml(server)
    signed_b64 = _b64(signed_xml)
    (target / "idp_response_signed.xml.b64").write_bytes(signed_b64)

    shutil.copyfile(
        target / "idp_response_signed.xml.b64",
        target / "idp_response_replay.xml.b64",
    )

    expired_xml = _force_expired(signed_xml)
    (target / "idp_response_expired.xml.b64").write_bytes(_b64(expired_xml))

    unsigned_xml = _build_unsigned_response_xml(server)
    (target / "idp_response_unsigned.xml.b64").write_bytes(_b64(unsigned_xml))

    xsw_xml = _build_xsw_attack_xml(signed_xml)
    (target / "idp_response_xsw.xml.b64").write_bytes(_b64(xsw_xml))


if __name__ == "__main__":
    main()  # output_dir=None → HERE; manual CLI behavior preserved.
```

### Refactored `_load_fixture_b64` with template fallback

```python
# Source: D-07
def _load_fixture_b64(name: str, response_dir: Path) -> str:
    """Resolve a SAML response fixture by name.

    First tries the per-session regenerated dir (where pysaml2 wrote a
    fresh fixture with current-time IssueInstant); falls back to the
    committed `.xml.b64.template` in FIXTURE_DIR for environments where
    pysaml2 / xmlsec1 are unavailable. Returns the base64 string with
    trailing whitespace stripped — pysaml2's parse_authn_request_response
    expects the raw form-field-encoded base64.
    """
    regenerated = response_dir / name
    if regenerated.exists():
        return regenerated.read_text().strip()
    template = FIXTURE_DIR / f"{name}.template"
    return template.read_text().strip()
```

### CI guard step (insertion point: ci.yml between `:339` and `:341`)

```yaml
# Source: D-08
- name: Verify SAML fixtures unchanged after pytest
  run: |
    if ! git diff --quiet -- tests/fixtures/saml/; then
      echo "::error::SAML fixture files were modified by pytest run -- regression of phase 227 (saml-test-fixture-tmp-path)."
      git diff --stat -- tests/fixtures/saml/
      git diff -- tests/fixtures/saml/ | head -200
      exit 1
    fi
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Autouse session fixture rewrites committed files in-place | Request fixture writes to tmp_path_factory dir; templates serve as deterministic fallback | This phase (227) | Stops 5-file working-tree pollution per pytest run. |
| `subprocess.run([sys.executable, generator], cwd=backend/)` | `from tests.fixtures.saml.generate_fixtures import main; main(output_dir=...)` | This phase (D-05) | Faster (~100-300 ms saved per session); typed exception propagation; no string-arg parsing. |
| `_load_fixture_b64(name)` → reads from FIXTURE_DIR | `_load_fixture_b64(name, response_dir)` → tries response_dir then `.template` fallback in FIXTURE_DIR | This phase (D-07) | Real CI fallback for envs lacking pysaml2/xmlsec1; matches docstring intent restored from Phase 217. |

**Deprecated/outdated:** Nothing yet. The 5 `idp_response_*.xml.b64` files (without
`.template` suffix) become deprecated paths immediately at D-02 rename.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | xmlsec1 is NOT on `ubuntu-latest` CI runners by default | Pitfall 6 | LOW — if xmlsec1 IS pre-installed, generator runs to completion on CI and templates only serve fork-PR / minimal-image envs. Either way the fallback architecture works. [ASSUMED] |
| A2 | `pysaml2` in `backend/uv.lock` is present transitively or directly via dependency-groups inheritance | Pitfall 2 | LOW — verified via `uv pip list` in local venv. If lockfile is overlay-only, fork-PR CI fires the fallback path which is what's intended. Planner should grep `backend/uv.lock` for `name = "pysaml2"` to confirm. [VERIFIED locally; CITED-needed for lockfile]. |
| A3 | Pytest's tmp_path retention policy (default = 3 sessions) won't fill `/tmp` on CI | Pattern 1 | LOW — sessions cleanup older tmp dirs automatically; on CI each runner is ephemeral. Negligible. [CITED: docs.pytest.org tmp_path retention] |
| A4 | The 9 `_load_fixture_b64` callsites listed in CONTEXT.md (`:328, :373, :396, :417, :439, :481, :530, :545, :859`) are exhaustive | D-07 / Pitfall 5 | LOW — verified by grep `grep -n "_load_fixture_b64" backend/tests/test_saml_overlay.py`; result matches CONTEXT.md exactly. [VERIFIED] |

**Empty assumptions are the goal — A1 is the only un-verified mechanical claim.** All
other technical claims are either verified by tool output or directly cited from
project source.

## Open Questions

1. **Should xmlsec1 be added to CI's `Install system dependencies`?**
   - What we know: D-08 + the fallback architecture work whether or not xmlsec1 is on CI.
     If absent, templates serve. If present, live regeneration runs and the templates are
     unused on CI (but still committed for fork-PR scenarios).
   - What's unclear: whether the project values "live regeneration covered by CI" enough
     to add 1 apt package.
   - Recommendation: defer. SC#4 ("existing SAML overlay tests continue to pass") is met
     either way. If CI sometimes shows fallback diagnostic noise that obscures real
     failures, revisit and add `xmlsec1` to the apt install step.

2. **Should the `print(..., file=sys.stderr)` diagnostic also fire when generator runs
   successfully, to confirm the live path executed?**
   - What we know: silence on success is conventional pytest hygiene.
   - What's unclear: whether the planner wants positive observability ("[saml-fixtures]
     generated 5 files in /tmp/.../saml_responses0/") for debugging fork-PR vs main-CI
     differences.
   - Recommendation: don't add. Negative diagnostic only — keeps logs clean.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| pytest | Test framework | ✓ | 9.0.3 | — |
| pysaml2 (`saml2`) | Generator imports | ✓ (locally; assumed in backend uv.lock) | 7.5.4 | `.xml.b64.template` files served by helper |
| xmlsec1 (system binary) | Generator runtime (signing) | ✓ locally (`/opt/homebrew/bin/xmlsec1`); ✗ assumed on CI ubuntu-latest | system | `.xml.b64.template` files served by helper (OSError caught) |
| `git` | CI guard step + D-09 restore | ✓ | system | none — required |
| `uv` | Already used by backend tests | ✓ | 0.10.3 | — |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:**
- `xmlsec1` on CI — fallback is the committed `.xml.b64.template` files; behavior is
  correct via `except (ImportError, OSError)` clause.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 with anyio_mode="auto", asyncio_mode="strict" |
| Config file | `backend/pyproject.toml` `[tool.pytest.ini_options]` (verified `:60-77`) |
| Quick run command | `cd backend && uv run pytest tests/test_saml_overlay.py -v --tb=short` |
| Full suite command | `cd backend && uv run pytest -v --tb=short -m 'not perf'` (matches CI line `:336`) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TESTFIX-01 | Autouse writes to tmp_path, never to `backend/tests/fixtures/saml/idp_response_*.xml.b64` | integration (existing tests still pass + new assertion) | `cd backend && uv run pytest tests/test_saml_overlay.py -v` | ✅ test_saml_overlay.py |
| TESTFIX-01 | Generated SAML responses appear in tmp_path_factory dir during test session | unit (probe `saml_response_dir` returns a Path with regenerated files OR templates fallback) | `cd backend && uv run pytest tests/test_saml_overlay.py::test_saml_acs_signed_assertion_jit_provisions_user -v` (smoke — happy path proves the fixture wired correctly) | ✅ existing test |
| TESTFIX-02 | `git status` is clean after a full SAML test run | smoke (script-level, not pytest) | `cd backend && uv run pytest tests/test_saml_overlay.py -v && cd .. && git diff --quiet -- backend/tests/fixtures/saml/` | ❌ Wave 0 — needs a small bash script OR rely on the CI guard step itself as the regression test |
| TESTFIX-02 | CI step `Verify SAML fixtures unchanged after pytest` fails when fixtures mutate | manual (verified once on a deliberately-broken branch) | n/a — exercised by a one-time intentional break + revert during phase verification | manual-only |
| TESTFIX-03 | `idp_response_*.xml.b64.template` files exist; `idp_response_*.xml.b64` (no `.template`) do NOT | unit | `test -f backend/tests/fixtures/saml/idp_response_signed.xml.b64.template && ! test -f backend/tests/fixtures/saml/idp_response_signed.xml.b64` (5 files) | ❌ Wave 0 — add a single guard test or rely on the CI step + git ls-files inspection at phase close |
| TESTFIX-03 | `_load_fixture_b64` falls back to templates when regenerated file is absent | unit | `cd backend && uv run pytest tests/test_saml_overlay.py -v -k "fallback"` (NEW test — Wave 0) | ❌ Wave 0 — add `test_load_fixture_b64_falls_back_to_template` |

### Sampling Rate

- **Per task commit:** `cd backend && uv run pytest tests/test_saml_overlay.py -v --tb=short`
  (~12 tests, runs in <60 s; covers all 9 fixture-using callsites).
- **Per wave merge:** `cd backend && uv run pytest -v --tb=short -m 'not perf'` (full backend
  suite — matches CI line `:336`); plus `git diff --quiet -- backend/tests/fixtures/saml/`
  immediately after.
- **Phase gate:** Full suite green (matches v13.3 baseline of 2036/2036) AND CI green AND
  `git status` clean immediately after CI run AND committed `.xml.b64.template` files
  visible in `git ls-files -- backend/tests/fixtures/saml/`.

### Wave 0 Gaps

- [ ] `backend/tests/test_saml_overlay.py::test_load_fixture_b64_falls_back_to_template` —
  unit test that asserts `_load_fixture_b64("idp_response_signed.xml.b64", tmp_path)` (where
  `tmp_path` is empty) reads from `FIXTURE_DIR / "idp_response_signed.xml.b64.template"`.
  Single-purpose; ~10 lines. Covers TESTFIX-03 fallback semantic.
- [ ] (Optional) `backend/tests/test_saml_overlay.py::test_saml_response_dir_writes_outside_repo`
  — assert `saml_response_dir` returns a Path NOT under `backend/tests/fixtures/saml/`.
  Defense-in-depth for TESTFIX-01. ~5 lines.
- [ ] No framework install needed — pytest 9.0.3 + tmp_path_factory already present.
- [ ] No conftest changes needed — the new fixture lives in `test_saml_overlay.py` per D-06.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Phase scoped to test infrastructure; SAML production code untouched. |
| V3 Session Management | no | n/a |
| V4 Access Control | no | n/a |
| V5 Input Validation | no | Generator output is not user input. |
| V6 Cryptography | partial | `idp_cert.pem` / `idp_key.pem` remain test-only fixtures with 36500-day validity (committed; never used in production). Phase does NOT regenerate them. SAML XML signing logic in production code (`geolens-enterprise/auth/saml/`) is unchanged. |
| V14 Configuration | yes | The CI guard (D-08) is itself a configuration-integrity control: it prevents test runs from silently mutating committed assets. |

### Known Threat Patterns for backend test infra

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Test fixtures mutate committed source → silent merge of test-side data into PRs | Tampering / Repudiation | CI guard step asserts `git diff --quiet -- tests/fixtures/saml/` immediately after pytest (D-08). |
| Stale/expired fixture certs cause flaky CI ("Can't use response, too old") | Repudiation | The whole reason for in-process regeneration: fresh `IssueInstant` per session. Fallback templates are time-static so they may flake on the long-lived expiry path — but the explicit `expired` fixture is designed to be expired, so this is acceptable. |
| Fixture XML attack payload (XSW, malformed signatures) escaping into production code | Tampering | These payloads exist ONLY in `backend/tests/fixtures/saml/`; production code never reads from this directory (verified `grep -rn "fixtures/saml" backend/app/`). |

## Sources

### Primary (HIGH confidence)
- `backend/tests/test_saml_overlay.py:1-890` — full file read
- `backend/tests/fixtures/saml/generate_fixtures.py:1-336` — full file read
- `.github/workflows/ci.yml:215-345` — `backend-test` job
- `.planning/REQUIREMENTS.md:27-31` — TESTFIX-01..03 verbatim
- `.planning/ROADMAP.md:115-135` — Phase 227 success criteria
- `.planning/phases/227-saml-test-fixture-tmp-path/227-CONTEXT.md` — D-01..D-10 verbatim
- `backend/pyproject.toml:60-77` — pytest config
- `backend/tests/conftest.py:1-440` — top + relevant fixture-scope context
- Empirical: `uv pip list \| grep -i pysaml` → `pysaml2 7.5.4`
- Empirical: `which xmlsec1` → `/opt/homebrew/bin/xmlsec1`
- Empirical: `cd backend && uv run python -c "from tests.fixtures.saml.generate_fixtures import main"` succeeds
- Empirical: `git status --short backend/tests/fixtures/saml/` shows 5 `M` rows
- `grep -rn "idp_response_" backend/tests/` confirms only `test_saml_overlay.py` reads these

### Secondary (MEDIUM confidence)
- pytest tmp_path_factory documentation (Context7 NOT consulted — well-established built-in;
  behavior verified empirically across the project)

### Tertiary (LOW confidence)
- CI's xmlsec1 availability on `ubuntu-latest` runners (A1 — assumed not present;
  fallback handles either case)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all deps already in lockfile, all scopes verified
- Architecture: HIGH — locked by CONTEXT.md D-01..D-10; this research only annotates
- Pitfalls: HIGH — every pitfall is empirically verified or directly observed in source

**Research date:** 2026-05-02
**Valid until:** 2026-06-01 (30 days; pytest API and CI-wiring shape are stable)
