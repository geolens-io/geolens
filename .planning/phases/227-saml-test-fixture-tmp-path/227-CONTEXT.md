# Phase 227: saml-test-fixture-tmp-path - Context

**Gathered:** 2026-05-02
**Status:** Ready for planning
**Mode:** `--auto --chain` (recommended decisions auto-selected)

<domain>
## Phase Boundary

Stop the SAML test fixture autouse from rewriting committed files on every `pytest` run. After this phase:

- The `_regenerate_saml_fixtures` session-autouse fixture in `backend/tests/test_saml_overlay.py:45-79` no longer mutates `backend/tests/fixtures/saml/idp_response_*.xml.b64`. Generator output is routed to a pytest session-scoped `tmp_path` instead.
- The 5 committed fixture files (`idp_response_signed.xml.b64`, `idp_response_expired.xml.b64`, `idp_response_replay.xml.b64`, `idp_response_unsigned.xml.b64`, `idp_response_xsw.xml.b64`) are renamed to `.xml.b64.template` — committed, immutable, never overwritten by tests, used as the deterministic CI fallback when pysaml2/xmlsec1 generation cannot run.
- `backend/tests/fixtures/saml/generate_fixtures.py:main()` accepts an `output_dir: Path | None = None` parameter (default `HERE` to preserve the manual-run-from-CLI invocation `cd backend && uv run python tests/fixtures/saml/generate_fixtures.py`). The autouse fixture passes the session tmp dir.
- A new session-scoped `saml_response_dir` fixture exposes the `Path` containing the per-session SAML responses. The 9 `_load_fixture_b64(...)` callsites in `test_saml_overlay.py` (lines 328, 373, 396, 417, 439, 481, 530, 545, 859) are migrated to take the dir from this fixture.
- `_load_fixture_b64(name)` (currently `test_saml_overlay.py:139-153`) is rewritten to resolve from the per-session dir if a regenerated file exists, else fall back to reading the corresponding `.xml.b64.template` from `FIXTURE_DIR`. This makes the docstring's "CI fallback when pysaml2 unavailable" claim **literally true** (today the comment exists at line 76-78 but the fallback path is broken because it would read just-regenerated-then-failed garbage in-place).
- The 5 currently-dirty files in `git status` (the perpetual `M` rows that triggered this phase) are restored to their HEAD baseline before the rename, so the rename commit is clean (`git mv` preserves history).
- A CI guard asserts `git diff --quiet -- backend/tests/fixtures/saml/` (or equivalent relative path inside the `backend/` working-dir of `.github/workflows/ci.yml` `backend-test` job at `:332-339`) immediately after the pytest run. Failure points operators to phase 227.
- Existing SAML overlay tests (`pytest backend/tests/test_saml_overlay.py -v`) continue to pass — same test bodies, same assertions, same fixture cert/key (`idp_cert.pem` / `idp_key.pem` stay committed and unchanged because they are static and never regenerated).
- Module-level constants `FIXTURE_DIR`, `FIXTURE_CERT_PEM`, `FIXTURE_IDP_ENTITY_ID`, etc. (`test_saml_overlay.py:41-87`) stay as-is. `FIXTURE_DIR` continues to point at `backend/tests/fixtures/saml/` because cert/key/template lookup still happens there. Only the response-XML resolution moves to per-session dirs.

**In scope:** refactor `_regenerate_saml_fixtures` to write to `tmp_path_factory.mktemp(...)`; refactor `generate_fixtures.main()` to accept `output_dir`; rename 5 `idp_response_*.xml.b64` → `.xml.b64.template` (via `git mv`, after restoring the dirty baseline); add `saml_response_dir` session fixture; rewrite `_load_fixture_b64` to read from session dir with template fallback; migrate 9 callsites to take the new fixture; add CI guard `git diff --quiet` step after `pytest` in `.github/workflows/ci.yml` `backend-test` job; update the autouse fixture's docstring to match the new (working) fallback behavior; verify `git status` is clean after a full SAML test run locally.

**Out of scope:** changes to `idp_cert.pem` / `idp_key.pem` (these stay committed, static, untouched); changes to the SAML test bodies themselves (fixture-resolution change only); changes to `backend/tests/conftest.py` or other test files that don't reference these fixtures; any production-code change in `backend/app/modules/auth/oauth/saml/` or the enterprise SAML overlay; adding new SAML test scenarios; switching to a different fixture-generation library; introducing pre-commit hooks (CI guard alone is sufficient — see D-08); migrating other fixture-mutation regressions (none identified — this is the only one); regenerating the static `idp_cert.pem` / `idp_key.pem` (they have a 36500-day validity window per `generate_fixtures.py:296`); changes to `pyproject.toml` / `uv.lock` (no new dependencies).

</domain>

<decisions>
## Implementation Decisions

### Fixture file disposition

- **D-01 — Rename 5 `idp_response_*.xml.b64` files to `.xml.b64.template`** (NOT remove them). Reason: success criterion #3 explicitly offers this path, and keeping committed templates preserves the docstring's "CI fallback when pysaml2 unavailable" intent that was deliberately added in Phase 217. Templates also give a deterministic baseline for envs lacking pysaml2/xmlsec1 (minimal CI containers, tight-locked uv-sync layers, fork-PR contexts where the enterprise overlay isn't installed). The files are small (each ~2-4 KB base64), so the disk cost is negligible.

- **D-02 — Use `git mv` for the rename so history is preserved.** Each `idp_response_*.xml.b64` → `.xml.b64.template` is a rename, not a delete + add. After the rename there is NO parallel `.xml.b64` file in the repo — only `.xml.b64.template`. The autouse fixture writes `.xml.b64` files into `tmp_path` (NOT `.xml.b64.template`) so the fallback resolution can distinguish "fresh from generator" vs "committed template" by file extension.

### Docstring "CI fallback" resolution

- **D-03 — Restore the CI fallback for real.** The current docstring at `test_saml_overlay.py:76-78` claims tests fall back to "the committed fixtures and let individual tests skip/fail loudly" if generation fails — but the today's autouse silently swallows `subprocess.CalledProcessError` (line 75) and tests then read whatever garbage the generator left in-place. Phase 227 wires this for real: `_load_fixture_b64(name)` first checks the per-session `saml_response_dir` for a regenerated file; if absent, it reads `FIXTURE_DIR / f"{name}.template"`. Both paths return valid base64 SAML XML. Update the docstring to describe the new (working) behavior precisely — no more "but they are gitignored from the worktree's perspective" handwave (lines 58-61 of today's docstring), which is factually wrong and was the root-cause comment that rationalized the in-place mutation.

### tmp_path scope and wiring

- **D-04 — Use `tmp_path_factory.mktemp("saml_responses")` (session-scoped).** Idiomatic pytest, automatic cleanup at session end, no manual `tempfile.mkdtemp` + `shutil.rmtree` bookkeeping. `tmp_path_factory` is a pytest built-in session fixture; the autouse takes it as a parameter (which automatically promotes the autouse to session-scoped, matching today's `scope="session"` declaration).

- **D-05 — Refactor `generate_fixtures.main()` to accept `output_dir: Path | None = None`.** When `output_dir is None`, default to `HERE` (`Path(__file__).parent.resolve()`) — this preserves the manual-CLI behavior documented at `generate_fixtures.py:3-9` (`cd backend && uv run python tests/fixtures/saml/generate_fixtures.py`), so a developer rotating the cert can still run the generator standalone and have files land beside the script. The autouse passes the session tmp dir. All 5 `(HERE / "idp_response_*.xml.b64").write_bytes(...)` lines (`generate_fixtures.py:309, 313-316, 321, 326, 331`) and the `shutil.copyfile` at `:313-316` are rewritten to use the function-local `output_dir` variable instead of module-level `HERE`. Also: replace today's `subprocess.run([sys.executable, str(generator)], ...)` invocation in the autouse (`test_saml_overlay.py:69-74`) with a direct in-process call — `from tests.fixtures.saml.generate_fixtures import main as generate_saml_fixtures; generate_saml_fixtures(output_dir=session_dir)`. In-process is faster, lets `output_dir` be passed as a typed `Path` (no string-arg parsing), and removes the `subprocess.CalledProcessError` swallow. Wrap in `try / except (ImportError, OSError) as e:` so the fallback path still triggers cleanly when pysaml2/xmlsec1 is unavailable. Log the exception (e.g. `pytest.warns(...)` or a plain `print` to stderr) so a CI failure is debuggable instead of silent.

- **D-06 — Add a session-scoped `saml_response_dir` fixture in the same file** (or in `backend/tests/conftest.py` if planner deems it shared — but only `test_saml_overlay.py` reads these files today, so co-locating keeps blast radius zero). Signature:
  ```python
  @pytest.fixture(scope="session")
  def saml_response_dir(tmp_path_factory) -> Path:
      session_dir = tmp_path_factory.mktemp("saml_responses")
      try:
          generate_saml_fixtures(output_dir=session_dir)
      except (ImportError, OSError, subprocess.CalledProcessError) as e:
          print(f"[saml-fixtures] generator unavailable ({e}); using committed templates", file=sys.stderr)
      return session_dir
  ```
  This replaces today's `_regenerate_saml_fixtures` autouse. The autouse goes away — `saml_response_dir` is requested by name from the helpers / tests that need it.

- **D-07 — Rewrite `_load_fixture_b64(name)` to take the dir as a parameter.** New signature: `_load_fixture_b64(name: str, response_dir: Path) -> str`. Body:
  ```python
  def _load_fixture_b64(name: str, response_dir: Path) -> str:
      regenerated = response_dir / name
      if regenerated.exists():
          return regenerated.read_text().strip()
      template = FIXTURE_DIR / f"{name}.template"
      return template.read_text().strip()
  ```
  All 9 callsites pass the new dir. Two callsites are inside `@pytest.fixture` functions (`:530, :545` — `_authn_redirect` / similar) and 7 are inside test functions (`:328, :373, :396, :417, :439, :481, :859`). Each grows a `saml_response_dir` parameter. Mechanical change.

### CI safety guard

- **D-08 — Add a `git diff --quiet` step in `.github/workflows/ci.yml` `backend-test` job, immediately after `Run tests with coverage` (`:332-339`).** Step:
  ```yaml
  - name: Verify SAML fixtures unchanged after pytest
    run: |
      if ! git diff --quiet -- tests/fixtures/saml/; then
        echo "::error::SAML fixture files were modified by pytest run -- regression of phase 227 (saml-test-fixture-tmp-path)."
        git diff --stat -- tests/fixtures/saml/
        exit 1
      fi
  ```
  Runs in the `backend/` working-dir (already set by the job's `defaults.run.working-directory`). Failure mode is loud, points to phase 227 by name, and prints the dirty diff so the operator can see exactly which fixtures regressed. NOT a pre-commit hook — pre-commit doesn't catch the regression because today's mutation only happens at pytest-time, and most contributors don't run the full backend suite locally before committing. CI is the right enforcement layer.

### Pre-work / sequencing

- **D-09 — Plan starts by reverting the 5 currently-dirty fixture files** to their HEAD baseline:
  ```bash
  git checkout -- backend/tests/fixtures/saml/idp_response_signed.xml.b64
  git checkout -- backend/tests/fixtures/saml/idp_response_expired.xml.b64
  git checkout -- backend/tests/fixtures/saml/idp_response_replay.xml.b64
  git checkout -- backend/tests/fixtures/saml/idp_response_unsigned.xml.b64
  git checkout -- backend/tests/fixtures/saml/idp_response_xsw.xml.b64
  ```
  This makes the baseline clean before the rename commit. Without this step, the rename commit will include "moved + content-changed" diff for each file (because the working-tree mutations carry over), polluting the diff and obscuring intent. Restore-then-rename gives a pure rename in `git log --follow`.

- **D-10 — Suggested commit ordering** (planner decides exact granularity):
  1. `chore(227): restore SAML fixture baseline before refactor` — `git checkout` the 5 files.
  2. `refactor(227): route generate_fixtures.main() output through output_dir param` — generator-only change; manual CLI still works.
  3. `refactor(227): rename SAML response fixtures to .xml.b64.template` — `git mv` the 5 files; nothing else changes (tests still read the old paths and break — temporarily).
  4. `refactor(227): wire saml_response_dir session fixture and tmp_path autouse` — replace the autouse, add the new fixture, rewrite `_load_fixture_b64`, migrate 9 callsites, update the docstring. Tests green again.
  5. `ci(227): assert SAML fixtures unchanged after pytest` — add the CI guard step.
  Bisect-friendly granularity, each commit reviewable independently. Combine 3+4 if planner prefers a single tests-stay-green commit.

### Claude's Discretion

- Whether `saml_response_dir` lives in `test_saml_overlay.py` or in `backend/tests/conftest.py` — co-locate (zero shared use today) is recommended; planner may move to conftest if the SAML overlay grows additional test files.
- Exact phrasing of the CI step's error message and whether to also `cat` the offending file contents in the failure output (helps debug local reproducer mismatches).
- Whether to use `pytest.warns(UserWarning)` or `print(..., file=sys.stderr)` for the "generator unavailable, falling back to templates" diagnostic. `print` to stderr is simpler and won't trip pytest's warning-filter strictness.
- Whether to also update `backend/tests/fixtures/saml/generate_fixtures.py:5-7`'s docstring CLI invocation to mention `--output-dir` if the planner promotes `output_dir` to a CLI flag (`argparse`). Recommended: keep the function signature only, don't add CLI flags — manual run still works via the default.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope and success criteria
- `.planning/ROADMAP.md` §"Phase 227: saml-test-fixture-tmp-path" — goal, source provenance (v13.3 milestone close 2026-05-01), success criteria (4 items), promotion-from-999.18 history.
- `.planning/REQUIREMENTS.md` §"Phase 227 — TESTFIX-01..03" — bound requirements (TESTFIX-01: tmp_path routing; TESTFIX-02: clean `git status` post-pytest; TESTFIX-03: rename-to-template OR remove + docstring resolution).

### Existing code touched
- `backend/tests/test_saml_overlay.py` — module docstring (`:1-18`), `_regenerate_saml_fixtures` autouse (`:45-79`), `FIXTURE_DIR` constant (`:41`), `_load_fixture_b64` helper (`:139-153`), 9 callsites listed in §domain.
- `backend/tests/fixtures/saml/generate_fixtures.py` — `main()` (`:291-336`), `HERE` constant (`:46`), CLI-invocation docstring (`:3-9`), the 5 `(HERE / "idp_response_*.xml.b64").write_bytes(...)` lines (`:309, 313-316, 321, 326, 331`).
- `backend/tests/fixtures/saml/idp_cert.pem` — STATIC, stays committed, NOT touched by this phase.
- `backend/tests/fixtures/saml/idp_key.pem` — STATIC, stays committed, NOT touched by this phase.
- `backend/tests/fixtures/saml/idp_response_*.xml.b64` (5 files) — renamed to `.xml.b64.template` via `git mv` (after restore from HEAD per D-09).

### CI workflow touched
- `.github/workflows/ci.yml` `backend-test` job (`:219-340`) — new "Verify SAML fixtures unchanged after pytest" step inserted between `:332-339` (`Run tests with coverage`) and `:342-346` (`Upload backend coverage report`).

### Prior phase precedent (Phase 217 baselines)
- `.planning/phases/217-*/` — Phase 217 introduced the SAML test infrastructure originally; its CONTEXT.md decided on the committed-fixtures + autouse-regenerate pattern. Phase 227 corrects the autouse part of that decision without disturbing the cert/key or test bodies. Reading Phase 217's RESEARCH.md S10 ("CI fallback when pysaml2 unavailable") clarifies the original docstring intent.

### No external specs
SAML 2.0 / pysaml2 / xmlsec1 specifics are NOT phase-relevant — fixture content (XML structure, signature semantics) is unchanged. Phase 227 is purely about WHERE the generated files land and HOW tests resolve them.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`tmp_path_factory`** (pytest built-in): the canonical session-scoped temp-dir fixture. Already used elsewhere in the test suite implicitly (via `tmp_path` per-test).
- **`FIXTURE_CERT_PEM`** / **`FIXTURE_DIR`** (`test_saml_overlay.py:41-42`): module-level constants for the static cert/key — preserved as-is. The cert lives at `backend/tests/fixtures/saml/idp_cert.pem` and is read once at module import.
- **`generate_fixtures.main()`** (`generate_fixtures.py:291-336`): already does the heavy lifting — pysaml2 server construction, signed/expired/unsigned/xsw/replay variants, base64 encoding. The phase only needs to parametrize WHERE it writes.
- **5 fixture variant builders** (`_build_signed_response_xml`, `_build_unsigned_response_xml`, `_force_expired`, `_build_xsw_attack_xml`) in `generate_fixtures.py` — unchanged.

### Established Patterns
- **Autouse session fixtures** in `backend/tests/test_saml_overlay.py`: today's `_regenerate_saml_fixtures` is the only autouse in that file. Replacing it with an explicit `saml_response_dir` + parameter-passing follows the more common pytest pattern of fixtures-by-request rather than autouse side-effects.
- **`pytest.fixture(scope="session")`**: used elsewhere in `backend/tests/conftest.py` (e.g., DB-level setup). Same scoping discipline applies here.
- **`Path(__file__).parent` chains** for fixture-dir resolution: standard across the test suite. `FIXTURE_DIR = Path(__file__).parent / "fixtures" / "saml"` matches other test-helper paths.
- **CI step composition**: the `backend-test` job already has multi-step shell scripts (`Set up database extensions, roles, and schemas` at `:312-330`, `Run tests with coverage` at `:332-339`). Adding a 5-line `git diff --quiet` step fits the existing style.

### Integration Points
- **9 callsites** of `_load_fixture_b64(name)` in `test_saml_overlay.py` — each grows a `saml_response_dir` parameter (mechanical edit, no semantic change).
- **The autouse → request-fixture transition**: tests / helpers that do NOT take `saml_response_dir` won't trigger the generator. This is correct (only the SAML tests need it). Today's autouse runs the generator even for non-SAML test invocations of `pytest` filtered to other files — wasteful and unnecessary; the new pattern fixes that incidentally.
- **`subprocess.run` removal**: today's autouse spawns a Python subprocess to call the generator (`:69-74`). The new in-process call (`from tests.fixtures.saml.generate_fixtures import main as generate_saml_fixtures`) eliminates the subprocess and its 100-300ms startup cost. Net per-session speedup, no semantic change.
- **No production code touched.** The phase is scoped entirely to `backend/tests/`, `backend/tests/fixtures/saml/`, and `.github/workflows/ci.yml`.

</code_context>

<specifics>
## Specific Ideas

- **Fixture extension naming:** `.xml.b64.template` (not `.xml.b64.tpl` or `.template.xml.b64`). Reason: phase success criterion #3 names this exact extension verbatim (`.xml.b64.template`).
- **Generator default behavior (CLI mode):** when run as `__main__` (the `if __name__ == "__main__":` block at `:335-336`), `main()` is called with no args, so `output_dir is None` defaults to `HERE` — files land beside the script as today. Manual cert-rotation flow is preserved.
- **Diagnostic output on fallback:** print to `sys.stderr` (not `pytest.warns`) so the message appears in CI logs without tripping `pytest -W error::UserWarning` strictness if the project later adopts that.

</specifics>

<deferred>
## Deferred Ideas

- **Pre-commit hook to catch fixture mutations locally** — discussed but rejected (D-08 rationale): CI is the enforcement layer; pre-commit complexity not worth it for a one-time regression class. If similar fixture-mutation bugs recur in other domains, revisit and add a generic pre-commit hook then.
- **Promoting `output_dir` to a CLI flag in `generate_fixtures.py`** — defer: keep function-signature-only injection. Adding `argparse` is unnecessary for the manual-rotation use case and the autouse passes via Python.
- **Migrating `backend/tests/fixtures/saml/idp_cert.pem` / `idp_key.pem` regeneration to a separate phase** — out of scope. The cert has a 36500-day validity and isn't due for rotation. If/when rotation is needed, that's a separate ops task.
- **Generic fixture-mutation linter / architecture-guard test** (e.g., `test_no_fixture_mutation_in_pytest`) — not warranted yet (this is the only known case). Revisit if a second instance surfaces.

</deferred>

---

*Phase: 227-saml-test-fixture-tmp-path*
*Context gathered: 2026-05-02*
