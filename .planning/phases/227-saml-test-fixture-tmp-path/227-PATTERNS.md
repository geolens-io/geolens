# Phase 227: saml-test-fixture-tmp-path - Pattern Map

**Mapped:** 2026-05-02
**Files analyzed:** 9 (1 test file modify, 1 generator modify, 5 fixture renames, 1 CI workflow modify, 1 new test in same file)
**Analogs found:** 7 / 9 (the 5 fixture renames are pure `git mv` mechanics — no analog needed)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/tests/test_saml_overlay.py` (modify autouse → request fixture; rewrite helper; migrate 9 callsites) | test (pytest fixture + helper) | file-I/O | `backend/tests/conftest.py:34-36` (`anyio_backend` session fixture) AND today's `_regenerate_saml_fixtures` autouse at `backend/tests/test_saml_overlay.py:45-79` (the thing being replaced — copy *structure*, not behavior) | role-match (no in-repo `tmp_path_factory` user yet — RESEARCH.md confirms this phase is the first) |
| `backend/tests/fixtures/saml/generate_fixtures.py` (add `output_dir: Path \| None = None` param to `main()`) | utility (script) | file-I/O | self — existing `main()` at `backend/tests/fixtures/saml/generate_fixtures.py:291-336` already does the heavy lifting; we only re-target writes from `HERE` to a parameter-supplied `target` | self-reference (only one fixture-generator script in repo; no peer to copy from) |
| `backend/tests/fixtures/saml/idp_response_signed.xml.b64` → `.xml.b64.template` | fixture asset | n/a (rename) | n/a — pure `git mv` mechanics | n/a |
| `backend/tests/fixtures/saml/idp_response_expired.xml.b64` → `.xml.b64.template` | fixture asset | n/a (rename) | n/a | n/a |
| `backend/tests/fixtures/saml/idp_response_replay.xml.b64` → `.xml.b64.template` | fixture asset | n/a (rename) | n/a | n/a |
| `backend/tests/fixtures/saml/idp_response_unsigned.xml.b64` → `.xml.b64.template` | fixture asset | n/a (rename) | n/a | n/a |
| `backend/tests/fixtures/saml/idp_response_xsw.xml.b64` → `.xml.b64.template` | fixture asset | n/a (rename) | n/a | n/a |
| `.github/workflows/ci.yml` (insert "Verify SAML fixtures unchanged after pytest" step) | CI config | command-execution | `.github/workflows/ci.yml:310-327` (`Set up database extensions, roles, and schemas` — multi-line shell run-step inside `backend-test` job) AND `:329-330` (`Run migrations` — short single-purpose run-step) | exact (same job, same `working-directory: backend` default, same shell-step shape) |
| `test_load_fixture_b64_falls_back_to_template` (NEW unit test in `backend/tests/test_saml_overlay.py`, Wave 0) | test (unit) | file-I/O | RESEARCH.md §"Wave 0 Gaps" prescribes the test directly; analog is any small `def test_*` in `backend/tests/test_saml_overlay.py` that uses `tmp_path` (e.g., none currently use `tmp_path` — pattern is generic pytest unit-test) | role-match |

## Pattern Assignments

### `backend/tests/test_saml_overlay.py` — `saml_response_dir` session fixture (NEW, replaces `_regenerate_saml_fixtures`)

**Analog:** `backend/tests/conftest.py:34-36` (session fixture shape) + `backend/tests/test_saml_overlay.py:45-79` (the autouse being replaced — strip the autouse + subprocess, keep the try/except diagnostic intent).

**Existing session-scoped fixture pattern** (`backend/tests/conftest.py:34-36`):
```python
@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"
```

**Today's autouse to delete** (`backend/tests/test_saml_overlay.py:45-79` — DO NOT preserve `autouse=True`, DO NOT preserve `subprocess.run`, DO NOT preserve the misleading "gitignored from the worktree's perspective" docstring):
```python
@pytest.fixture(scope="session", autouse=True)
def _regenerate_saml_fixtures():
    ...
    subprocess.run(
        [sys.executable, str(generator)],
        check=True,
        capture_output=True,
        cwd=Path(__file__).parent.parent,  # backend/
    )
    ...
    yield
```

**Replacement pattern** (per CONTEXT.md D-06 + RESEARCH.md §Pattern 1, prescribed verbatim):
```python
@pytest.fixture(scope="session")
def saml_response_dir(tmp_path_factory) -> Path:
    """Session-scoped dir holding generated SAML XML responses (Phase 227)."""
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

**Key transitions** (autouse → request fixture):
- Drop `autouse=True` — fixture only runs when a test/helper requests it by name.
- Drop `subprocess.run` — direct in-process import + call (typed `Path` arg, real `ImportError`/`OSError`).
- `except` tuple: `(ImportError, OSError)` is sufficient; `subprocess.CalledProcessError` no longer reachable (RESEARCH.md Anti-Patterns: keep it only as forward-compat noise if planner insists).
- Diagnostic: `print(..., file=sys.stderr)` (not `pytest.warns`) per CONTEXT.md `<specifics>`.

---

### `backend/tests/test_saml_overlay.py` — `_load_fixture_b64` helper rewrite

**Analog:** the existing helper at `backend/tests/test_saml_overlay.py:139-153` itself (signature change + body rewrite, not full replacement).

**Today** (`:139-153`):
```python
def _load_fixture_b64(name: str) -> str:
    """Read a base64-encoded SAML fixture and return the base64 string itself.
    ...
    """
    return (FIXTURE_DIR / name).read_text().strip()
```

**Replacement** (per CONTEXT.md D-07 + RESEARCH.md §"Refactored `_load_fixture_b64`"):
```python
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

**9 callsite migration** (lines 328, 373, 396, 417, 439, 481, 530, 545, 859 — verified in CONTEXT.md A4): each callsite gains `response_dir=saml_response_dir` arg AND each enclosing function/fixture grows a `saml_response_dir` parameter (Pitfall 5: 8 signature edits cover 9 callsites because `:530` and `:545` share a function).

---

### `backend/tests/fixtures/saml/generate_fixtures.py` — `main()` accepts `output_dir`

**Analog:** the existing `main()` at `backend/tests/fixtures/saml/generate_fixtures.py:291-336` itself (parameterize, don't replace).

**Today** (`:291, :309-331`):
```python
def main() -> None:
    if not CERT_PEM.exists() or not KEY_PEM.exists():
        raise SystemExit(...)
    import tempfile
    tmpdir = Path(tempfile.mkdtemp(prefix="saml_fixture_gen_"))
    sp_meta = _write_sp_metadata(tmpdir)
    server = _make_server(sp_meta)

    signed_xml = _build_signed_response_xml(server)
    signed_b64 = _b64(signed_xml)
    (HERE / "idp_response_signed.xml.b64").write_bytes(signed_b64)         # :309
    shutil.copyfile(
        HERE / "idp_response_signed.xml.b64",                              # :313-316
        HERE / "idp_response_replay.xml.b64",
    )
    expired_xml = _force_expired(signed_xml)
    (HERE / "idp_response_expired.xml.b64").write_bytes(_b64(expired_xml)) # :321
    unsigned_xml = _build_unsigned_response_xml(server)
    (HERE / "idp_response_unsigned.xml.b64").write_bytes(_b64(unsigned_xml))  # :326
    xsw_xml = _build_xsw_attack_xml(signed_xml)
    (HERE / "idp_response_xsw.xml.b64").write_bytes(_b64(xsw_xml))         # :331


if __name__ == "__main__":
    main()  # :335-336 — manual CLI invocation
```

**Replacement** (per CONTEXT.md D-05 + RESEARCH.md §"Refactored generator main() signature"):
```python
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
    main()  # output_dir=None → target = HERE; manual CLI behavior preserved.
```

**Mechanical changes:** 5 `(HERE / "...")` → `(target / "...")` substitutions at the lines listed above + `shutil.copyfile` at `:313-316`. No new imports, no CLI flag, no signature change at call site `if __name__ == "__main__":` (Pitfall: do NOT add `argparse` — Claude's Discretion in CONTEXT.md says no).

**Module docstring touch-up** (`generate_fixtures.py:11-22`): no change required, but RESEARCH.md §"Runtime State Inventory" notes the docstring also references the old filenames — leaving as-is is fine because the manual-CLI default still produces files at those paths beside the script.

---

### `.github/workflows/ci.yml` — "Verify SAML fixtures unchanged after pytest" step

**Analog:** `.github/workflows/ci.yml:310-327` (`Set up database extensions, roles, and schemas`) — multi-line shell `run:` step inside the same `backend-test` job, inheriting `defaults.run.working-directory: backend` (set at `:224-226`).

**Existing peer step** (`.github/workflows/ci.yml:329-330`, single-line `run:`):
```yaml
      - name: Run migrations
        run: uv run alembic upgrade head
```

**Existing peer step** (`.github/workflows/ci.yml:310-327`, multi-line `run:`):
```yaml
      - name: Set up database extensions, roles, and schemas
        run: |
          PGPASSWORD=geolens_test psql -h localhost -U geolens -d geolens_test -c "
            CREATE EXTENSION IF NOT EXISTS postgis;
            ...
          "
```

**Insertion point:** between `:332-340` (`Run tests with coverage`) and `:342-348` (`Upload backend coverage report`). The `if: always()` on the upload step means the new guard runs on the success path only (which is what we want — no point asserting clean fixtures if pytest itself already failed; the regression won't fire on test failure regardless).

**New step** (per CONTEXT.md D-08 + RESEARCH.md §"CI guard step"):
```yaml
      - name: Verify SAML fixtures unchanged after pytest
        run: |
          if ! git diff --quiet -- tests/fixtures/saml/; then
            echo "::error::SAML fixture files were modified by pytest run -- regression of phase 227 (saml-test-fixture-tmp-path)."
            git diff --stat -- tests/fixtures/saml/
            git diff -- tests/fixtures/saml/ | head -200
            exit 1
          fi
```

**Critical pathspec note** (Pitfall 1): pathspec is **`tests/fixtures/saml/`** (relative to `backend/`), NOT `backend/tests/fixtures/saml/`. The job-level `working-directory: backend` default makes the step's CWD `backend/`, so a repo-root-relative path matches nothing. Verify the working-directory default at `.github/workflows/ci.yml:224-226` before writing the step.

---

### `test_load_fixture_b64_falls_back_to_template` (NEW Wave 0 unit test in `backend/tests/test_saml_overlay.py`)

**Analog:** generic pytest unit test using `tmp_path` (function-scoped). RESEARCH.md §"Wave 0 Gaps" prescribes ~10 lines.

**Pattern** (from RESEARCH.md §Wave 0 Gaps verbatim intent):
```python
def test_load_fixture_b64_falls_back_to_template(tmp_path):
    """When the per-session dir has no regenerated file, _load_fixture_b64
    must read from FIXTURE_DIR / f'{name}.template' instead. Phase 227 D-03.
    """
    # tmp_path is empty -> regenerated.exists() is False -> template branch
    result = _load_fixture_b64("idp_response_signed.xml.b64", tmp_path)
    assert result  # non-empty base64 string
    # Defensive: confirm we actually hit the template, not a stale write
    assert (FIXTURE_DIR / "idp_response_signed.xml.b64.template").exists()
```

Place adjacent to other helper-level tests in `test_saml_overlay.py` (no specific home — top of the test section is fine).

---

## Shared Patterns

### Path resolution from test files
**Source:** `backend/tests/test_saml_overlay.py:41` (existing constant, unchanged):
```python
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "saml"
```
**Apply to:** template-fallback resolution in `_load_fixture_b64`. `FIXTURE_DIR` stays as-is — it now holds `idp_cert.pem`, `idp_key.pem`, AND the 5 `.xml.b64.template` files.

### Cross-package test imports (PYTHONPATH=. + namespace packages)
**Source:** existing 10+ `from tests.factories import ...` usages across `backend/tests/`; verified at RESEARCH.md Pitfall 7.
**Apply to:** `from tests.fixtures.saml.generate_fixtures import main as generate_saml_fixtures` inside `saml_response_dir`. Works because `backend/tests/__init__.py` exists; `fixtures/__init__.py` and `fixtures/saml/__init__.py` are intentionally absent (PEP 420 implicit namespace packages — DO NOT add `__init__.py` files).

### CI step composition
**Source:** `.github/workflows/ci.yml:310-330` peer steps in the same `backend-test` job.
**Apply to:** the new "Verify SAML fixtures unchanged" step. Same indentation, same `run: |` heredoc style, no `working-directory:` override (inherit job-level `backend`), no `if:` condition (run unconditionally on success path).

### git mv discipline
**Source:** D-09 + Pitfall 4 — restore the 5 dirty files via `git checkout --` BEFORE running `git mv`, so the rename commit shows pure `R100` in `git log --summary` (no rename + content-edit pollution).
**Apply to:** all 5 fixture renames. Sequence is fixed:
```bash
git checkout -- backend/tests/fixtures/saml/idp_response_signed.xml.b64
git checkout -- backend/tests/fixtures/saml/idp_response_expired.xml.b64
git checkout -- backend/tests/fixtures/saml/idp_response_replay.xml.b64
git checkout -- backend/tests/fixtures/saml/idp_response_unsigned.xml.b64
git checkout -- backend/tests/fixtures/saml/idp_response_xsw.xml.b64
# verify clean:
git status -- backend/tests/fixtures/saml/   # must be empty
# then rename:
git mv backend/tests/fixtures/saml/idp_response_signed.xml.b64    backend/tests/fixtures/saml/idp_response_signed.xml.b64.template
git mv backend/tests/fixtures/saml/idp_response_expired.xml.b64   backend/tests/fixtures/saml/idp_response_expired.xml.b64.template
git mv backend/tests/fixtures/saml/idp_response_replay.xml.b64    backend/tests/fixtures/saml/idp_response_replay.xml.b64.template
git mv backend/tests/fixtures/saml/idp_response_unsigned.xml.b64  backend/tests/fixtures/saml/idp_response_unsigned.xml.b64.template
git mv backend/tests/fixtures/saml/idp_response_xsw.xml.b64       backend/tests/fixtures/saml/idp_response_xsw.xml.b64.template
```

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `saml_response_dir` fixture (`tmp_path_factory` user) | test fixture | file-I/O | RESEARCH.md confirms phase 227 is the FIRST `tmp_path_factory` user in this repo. No in-codebase precedent — pattern is taken from pytest docs (`https://docs.pytest.org/en/stable/reference/reference.html#tmp-path-factory`) and prescribed verbatim by RESEARCH.md §Pattern 1. |
| `output_dir` parameter on `generate_fixtures.main()` | utility (script) | file-I/O | `generate_fixtures.py` is the only fixture-generator script in `backend/tests/fixtures/`. Pattern is self-referential — parameterize the existing `HERE` writes. RESEARCH.md §Pattern 2 prescribes the shape. |

## Metadata

**Analog search scope:**
- `backend/tests/conftest.py` — session-scoped fixture shape
- `backend/tests/test_saml_overlay.py:1-170` — module top + autouse + helper (the in-place subjects)
- `backend/tests/fixtures/saml/generate_fixtures.py:1-50, :285-336` — generator imports + `main()` (the in-place subject)
- `backend/tests/fixtures/` (full listing) — only Python file is `generate_fixtures.py`
- `.github/workflows/ci.yml:219-348` — `backend-test` job (peer steps)
- `grep -rn "tmp_path_factory" backend/tests/` — zero results (confirms first-user status)

**Files scanned:** 5 (3 read in-line, 2 listed via shell)

**Pattern extraction date:** 2026-05-02

---

## PATTERN MAPPING COMPLETE

**Phase:** 227 - saml-test-fixture-tmp-path
**Files classified:** 9
**Analogs found:** 7 / 9 (5 fixture renames are pure `git mv` mechanics — no analog needed)

### Coverage
- Files with exact analog: 1 (CI step — same job, same shape)
- Files with role-match / self-reference analog: 6 (test fixture pattern, helper rewrite, generator parameterization, CI step composition, new unit test, plus 5 renames sharing the `git mv` discipline)
- Files with no in-repo analog: 2 (`saml_response_dir` is first `tmp_path_factory` user; `output_dir` parameter is unique to the only generator script)

### Key Patterns Identified
- **Session-scoped request fixture replaces autouse + subprocess** — `tmp_path_factory.mktemp("saml_responses")` + in-process `from tests.fixtures.saml.generate_fixtures import main` + `try/except (ImportError, OSError)` + stderr diagnostic. Verbatim from RESEARCH.md §Pattern 1.
- **Optional output-dir with HERE default** — `def main(output_dir: Path | None = None)` keeps manual CLI invocation working (`HERE` default) while letting tests pass a tmp dir. Mechanical 5 substitutions (`HERE` → `target`).
- **Template-fallback resolution** — `_load_fixture_b64(name, response_dir)` tries `response_dir / name` first, falls back to `FIXTURE_DIR / f"{name}.template"`. Realizes the docstring intent that was broken since Phase 217.
- **CI guard via `git diff --quiet`** — single shell step inside `backend-test` job, pathspec relative to `backend/` (NOT repo root) because of job-level `working-directory: backend`. Loud failure with phase-227 reference + diff stat + truncated diff.
- **Restore-before-rename discipline** — `git checkout --` 5 dirty files BEFORE `git mv`, so the rename commit is pure (R100 in git log).

### File Created
`/Users/ishiland/Code/geolens/.planning/phases/227-saml-test-fixture-tmp-path/227-PATTERNS.md`

### Ready for Planning
Pattern mapping complete. Planner can now reference analog patterns in PLAN.md files. Notable: phase 227 introduces `tmp_path_factory` to the codebase for the first time — the planner should cite pytest docs (RESEARCH.md §Pattern 1) rather than expect an in-repo precedent for that specific API.
