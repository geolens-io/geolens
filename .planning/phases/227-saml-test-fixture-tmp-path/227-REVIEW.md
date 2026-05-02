---
phase: 227-saml-test-fixture-tmp-path
reviewed: 2026-05-01T00:00:00Z
depth: standard
files_reviewed: 3
files_reviewed_list:
  - backend/tests/fixtures/saml/generate_fixtures.py
  - backend/tests/test_saml_overlay.py
  - .github/workflows/ci.yml
findings:
  critical: 0
  warning: 2
  info: 3
  total: 5
status: issues_found
---

# Phase 227: Code Review Report

**Reviewed:** 2026-05-01T00:00:00Z
**Depth:** standard
**Files Reviewed:** 3
**Status:** issues_found

## Summary

The Phase 227 refactor cleanly accomplishes its primary goal: the autouse `subprocess.run` regen has been removed, the in-process generator import works (verified by importing `tests.fixtures.saml.generate_fixtures.main` from a fresh interpreter under `uv run`), all 9 callsites in scope correctly thread `saml_response_dir`, the `_load_fixture_b64` fallback semantic is preserved (`.read_text().strip()`), and the new Wave 0 unit test (`test_load_fixture_b64_falls_back_to_template`) genuinely exercises the fallback branch by passing a fresh empty `tmp_path`. The generator's `target.mkdir(parents=True, exist_ok=True)` runs before any writes; the cert/key pre-flight guard is unchanged; the CI step lives in the right job at the right place.

That said, two real defects are present:

1. **WR-01** — the fixture's `except (ImportError, OSError)` is too narrow: pysaml2/xmlsec1 generation can also raise `RuntimeError` (the generator itself raises one at line 249 of `generate_fixtures.py`) and `subprocess.CalledProcessError` (raised when xmlsec1 is present but exits non-zero — confirmed NOT a subclass of `OSError`). Either of those will propagate up out of `saml_response_dir` and abort the entire pytest session at fixture-setup time, defeating the whole point of the graceful-fallback try/except.
2. **WR-02** — the CI guard step uses `git diff --quiet`, which only flags modifications to *tracked* files. The exact regression most likely to silently re-occur (a future code path writing a fresh `idp_response_*.xml.b64` — without the `.template` suffix — into `tests/fixtures/saml/`) leaves an *untracked* file that `git diff` does not see. `git status --porcelain` would catch it.

Three Info-level nits round out the review.

## Warnings

### WR-01: Fixture exception filter is too narrow — pytest session can still abort

**File:** `backend/tests/test_saml_overlay.py:71-81`

**Issue:** `saml_response_dir` wraps `generate_saml_fixtures(output_dir=session_dir)` in `try/except (ImportError, OSError)`. The intent (per the docstring) is "fall back to committed templates when pysaml2 / xmlsec1 are unavailable." But the generator can raise other exceptions even when both packages are present:

- `generate_fixtures._build_xsw_attack_xml` explicitly raises `RuntimeError("Cannot locate <Assertion> element in signed response")` at `generate_fixtures.py:249` if the regex misses (which is not impossible if pysaml2 changes its serialization prefix).
- xmlsec1, when invoked by pysaml2 and present-but-failing (config error, key/cert mismatch, version skew), raises `subprocess.CalledProcessError` from inside `subprocess.run`. Verified locally: `subprocess.CalledProcessError.__mro__` does not include `OSError` — it inherits directly from `subprocess.SubprocessError → Exception`. So the existing `except (ImportError, OSError)` will **not** catch it.
- Various pysaml2 internal errors (e.g. `saml2.s_utils.UnknownSystemEntity`) also subclass `Exception`, not `OSError`.

Any of these will propagate out of the session-scoped fixture and abort the entire pytest session at collection-time, which is exactly the failure mode the try/except was added to prevent. The graceful "use templates as CI fallback" promise is only honored for the narrow `ImportError` (pysaml2 missing) and `FileNotFoundError`/`PermissionError` (xmlsec1 binary missing) cases.

**Fix:** Broaden the catch to `Exception` (with the existing diagnostic stderr line). The fallback path provably works (the templates are committed, non-empty, and exercised by the existing tests when pysaml2 is unavailable on fork-PR CI), so swallowing any generator failure is strictly safer than aborting the session:

```python
try:
    from tests.fixtures.saml.generate_fixtures import (
        main as generate_saml_fixtures,
    )
    generate_saml_fixtures(output_dir=session_dir)
except Exception as exc:  # noqa: BLE001 - intentional: any generator failure → templates
    print(
        f"[saml-fixtures] generator unavailable ({type(exc).__name__}: {exc}); "
        "using committed templates",
        file=sys.stderr,
    )
return session_dir
```

If a narrower catch is preferred, the minimum addition needed to cover the documented failure modes is:

```python
import subprocess
...
except (ImportError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
```

But that requires re-importing `subprocess` (which the refactor explicitly removed) — `Exception` is the cleaner choice here.

### WR-02: CI fixture-unchanged guard misses untracked file additions

**File:** `.github/workflows/ci.yml:342-349`

**Issue:** The new "Verify SAML fixtures unchanged after pytest" step runs:

```yaml
if ! git diff --quiet -- tests/fixtures/saml/; then
```

`git diff --quiet` only inspects modifications to **tracked** files. The exact regression this guard is meant to prevent — pytest writing fresh `idp_response_*.xml.b64` files (without the `.template` suffix) into `tests/fixtures/saml/` — produces *untracked* files (the `.xml.b64` paths were git-mv'd to `.xml.b64.template` in task 01, and there is no `.gitignore` entry that would suppress them). An untracked write does not register on `git diff` at all, so the guard would silently pass while the regression was active.

Concretely: if a future code change accidentally restored autouse regen-into-FIXTURE_DIR behavior (e.g. a developer wires `_load_fixture_b64` to write back the regenerated bytes for "convenience"), CI would not catch it; the next contributor would just see mysterious `.xml.b64` files cluttering their `git status` after `pytest`.

The committed `.xml.b64.template` files ARE protected by `git diff --quiet` (overwriting them would be a tracked modification), so the guard is not useless — it just guards the less-likely failure mode.

**Fix:** Use `git status --porcelain` (which sees both modified-tracked AND new-untracked) and fail when output is non-empty:

```yaml
- name: Verify SAML fixtures unchanged after pytest
  run: |
    DIRTY=$(git status --porcelain -- tests/fixtures/saml/)
    if [ -n "$DIRTY" ]; then
      echo "::error::SAML fixture dir was modified by pytest run -- regression of phase 227 (saml-test-fixture-tmp-path)."
      echo "$DIRTY"
      git diff -- tests/fixtures/saml/ | head -200
      exit 1
    fi
```

This catches both the tracked-modification case (existing coverage) and the untracked-write case (the more likely regression vector).

## Info

### IN-01: `import tempfile` placed inside `main()` instead of at module top

**File:** `backend/tests/fixtures/saml/generate_fixtures.py:303`

**Issue:** `import tempfile` is the only deferred import in the module — every other import (`base64`, `os`, `re`, `shutil`, `pathlib`, `saml2.*`) is at the top. Deferred imports are usually justified by either (a) avoiding a heavy/optional dependency at import time, or (b) breaking a circular import. Neither applies to `tempfile` (it's stdlib, always available, no circularity). This is a pre-existing style inconsistency, not something Phase 227 introduced — but the refactor touched the surrounding lines, so it's fair game to clean up.

**Fix:** Move `import tempfile` to the top alongside `import shutil`:

```python
import base64
import os
import re
import shutil
import tempfile
from pathlib import Path
```

### IN-02: `tmpdir` from `mkdtemp` is never cleaned up (pre-existing)

**File:** `backend/tests/fixtures/saml/generate_fixtures.py:305`

**Issue:** `tempfile.mkdtemp(prefix="saml_fixture_gen_")` returns a directory that the caller owns; the generator never `shutil.rmtree(tmpdir)`s it. Each call leaves a `/tmp/saml_fixture_gen_XXXX/` directory containing `sp_metadata.xml` behind. Pre-existing, not introduced by Phase 227, but Phase 227 makes the leak more frequent — the autouse regen ran once per pytest session via subprocess (which then tore down its whole process tree, releasing the tmpdir under most OSes' `/tmp` cleanup policies); the new in-process flow runs in the test runner's own process, and the leaked dirs persist for the runner's full lifetime (and beyond, on macOS where `/tmp` is not aggressively reaped).

**Fix:** Wrap the tmpdir handling in `tempfile.TemporaryDirectory()`:

```python
with tempfile.TemporaryDirectory(prefix="saml_fixture_gen_") as tmpdir_str:
    tmpdir = Path(tmpdir_str)
    sp_meta = _write_sp_metadata(tmpdir)
    server = _make_server(sp_meta)
    # ... rest of main() body indented under the with-block
```

### IN-03: Module docstring's "minimal CI images without xmlsec1" line is now slightly stale

**File:** `backend/tests/test_saml_overlay.py:25-30`

**Issue:** The `saml_response_dir` docstring (line 65-69) and the module docstring (line 25-26) both describe "fork-PR CI without the enterprise overlay, minimal CI images without `xmlsec1`" as the trigger for the template-fallback path. With WR-01's narrow `except (ImportError, OSError)`, the "minimal CI images without xmlsec1" claim is technically only honored when `xmlsec1` is fully absent (FileNotFoundError → OSError). If `xmlsec1` is present-but-broken (CalledProcessError), the docstring promises a fallback that the code does not actually deliver.

**Fix:** Either fix WR-01 (preferred) and the docstring becomes accurate, or weaken the docstring to match the current narrow catch. The former is strictly better.

---

_Reviewed: 2026-05-01T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
