---
phase: 1080
depth: quick
status: findings_found
findings:
  critical: 0
  warning: 0
  info: 1
generated: 2026-05-21
files_reviewed:
  - backend/app/processing/ingest/tasks_common.py
  - backend/app/core/config.py
  - backend/tests/test_config.py
fixes_applied: 2026-05-21
---

# Phase 1080: Code Review Report

**Reviewed:** 2026-05-21
**Depth:** quick (comment-only + 1-line production code + 2 test assertion updates)
**Files Reviewed:** 3
**Status:** findings_found

## Summary

Phase 1080 delivered two targeted hygiene fixes: TD-01 (same-line `# broad:` justifications on two `except Exception:` clauses in `_job_phase_session`) and TD-07 (`database_connect_args` now sets `connect_args["ssl"] = False` on the `disable` branch). Both fixes are structurally correct and the VERIFICATION.md confirms all three success criteria passed.

Two warnings surfaced during review: one is a latent gap in the layering guard itself (an unjustified broad-except at `tasks_common.py:1030` that the test cannot see due to a macOS `git grep -E` / `\s` metaclass blind spot), and one is a test quality issue in `test_verify_full_returns_ssl_context_with_verify` that tests the wrong mode. One info item: the `database_connect_args` `else` branch silently accepts any unrecognised `ssl_mode` string by building an SSLContext with default verify settings — a hardening note worth tracking.

---

## Warnings

### WR-01: Unjustified broad-except at `tasks_common.py:1030` escapes the layering guard

**File:** `backend/app/processing/ingest/tasks_common.py:1030`

**Issue:** `except Exception as first_exc:` at line 1030 has no `# broad:` or `# noqa: BLE001` justification comment — it is an unjustified broad-except by the Phase 276 CODE-08 rule. The layering test (`test_no_unjustified_broad_except_sites`) does NOT catch this because it uses `git grep -E` with the regex `except Exception(\s+as\s+\w+)?:`, and on macOS (Apple Git 2.50.1) `git grep -E` does not treat `\s` as a whitespace character class (it treats it as a literal `s`). The pattern therefore never matches any `except Exception as <name>:` line — only the bare `except Exception:` form matches. The layering test passes, but the guard has a macOS-specific blind spot that was pre-existing before this phase and is now confirmed by this commit leaving line 1030 uncovered.

Confirmation:
```
git grep -E "except Exception(\s+as\s+\w+)?:" -- backend/app/processing/ingest/tasks_common.py
# returns ONLY lines 232 and 238 — does NOT return line 1030

git grep -P "except Exception(\s+as\s+\w+)?:" -- backend/app/processing/ingest/tasks_common.py
# returns lines 232, 238, 403, 419, 514, 652, AND 1030 — the Perl regex finds it
```

The catch at line 1030 is probably intentional (it filters for lock-timeout errors and re-raises anything else), but it lacks justification and, if the layering test were ever run on Linux (where `git grep -E` respects `\s`), it would immediately fail.

**Fix:**
1. Add a `# broad:` justification to line 1030:
   ```python
   except Exception as first_exc:  # broad: catch any swap failure to inspect for lock-timeout before re-raising
   ```
2. Fix the layering test regex to use `-P` (Perl-compatible) instead of `-E`, or replace `\s+` with `[ \t]+` in the extended-regex form so it is portable:
   ```python
   # In test_layering.py — change the grep argument from:
   r"except Exception(\s+as\s+\w+)?:"
   # to:
   r"except Exception([ \t]+as[ \t]+\w+)?:"
   ```
   This makes the guard work correctly on both macOS and Linux.

---

### WR-02: `test_verify_full_returns_ssl_context_with_verify` does not test `verify-full` connect_args

**File:** `backend/tests/test_config.py:171-183`

**Issue:** The test is named `test_verify_full_returns_ssl_context_with_verify` and is supposed to pin the `verify-full` branch of `database_connect_args`. However, after constructing a `verify-full` settings object (line 175-178), the test does NOT call `s.database_connect_args` — it constructs a second `require`-mode settings object (`s2`) and asserts on that instead. The comment on line 179 says "verify-full with invalid cert path will raise on connect_args access", but this is not tested either (no `pytest.raises` block). The actual `verify-full` branch in the property (the `else:` arm without `ssl_ctx.check_hostname = False`) is therefore untested by the test that claims to cover it.

This is a pre-existing issue in the test file but was not regressed by this phase's edit to `test_disable_returns_ssl_false`. Phase 1080 Plan 02 was asked to leave `test_verify_full_returns_ssl_context_with_verify` "exactly as it is" — and it did — but the existing test was already broken in this way.

**Fix:**
```python
def test_verify_full_returns_ssl_context_with_verify(self):
    import ssl

    s = _make_settings(database_ssl_mode="verify-full")
    args = s.database_connect_args
    assert isinstance(args["ssl"], ssl.SSLContext)
    # verify-full does NOT set check_hostname=False or CERT_NONE — defaults apply
    assert args["ssl"].check_hostname is True
```
(The `cafile` parameter can be omitted if `create_default_context()` succeeds without one; if the test environment requires a valid CA, use `database_ssl_ca_cert=None` which is the current default.)

---

## Info

### IN-01: `database_connect_args` `else` branch silently accepts unrecognised ssl_mode strings

**File:** `backend/app/core/config.py:312-319`

**Issue:** After the restructure, the `else` arm runs for any `database_ssl_mode` value that is neither `"disable"` nor `"prefer"` — including typos like `"requir"` or unknown future values. In those cases, `ssl.create_default_context()` is called and `ssl_ctx.check_hostname`/`verify_mode` are left at defaults (i.e., full verification), which is the safe direction, but the misconfiguration is silently accepted rather than rejected. This was true before the restructure too, so it is not a regression introduced by this phase.

**Fix (optional, post-v1018):** Add an else-guard after the SSLContext block:
```python
else:
    import ssl
    ssl_ctx = ssl.create_default_context(cafile=self.database_ssl_ca_cert)
    if self.database_ssl_mode == "require":
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
    elif self.database_ssl_mode != "verify-full":
        raise ValueError(
            f"Unknown database_ssl_mode {self.database_ssl_mode!r}. "
            "Expected one of: disable, prefer, require, verify-full."
        )
    connect_args["ssl"] = ssl_ctx
```

---

## Per-Check Rationale (hygiene patch gate)

| Check | Result |
|-------|--------|
| **TD-01 wording:** both `# broad:` comments at lines 232/238 use identical text describing caller-yielded blocks that must roll back before re-raising to avoid pool leak. Wording is accurate — both sites are the same async context-manager boundary. | PASS |
| **TD-01 coverage:** line 1030 is an additional unjustified broad-except in the same file that the layering test cannot see on macOS due to `git grep -E` / `\s` metaclass blind spot. Pre-existing gap, but confirmed present post-phase. | WR-01 |
| **TD-07 `disable` branch:** `connect_args["ssl"] = False` at `config.py:309`. Literal Python `False`, not string. Correct. | PASS |
| **TD-07 `prefer` branch:** `connect_args["ssl"] = "prefer"` at line 311. Unchanged. Correct. | PASS |
| **TD-07 `require` branch:** SSLContext with `check_hostname=False` + `CERT_NONE` at lines 317-318. Unchanged. Correct. | PASS |
| **TD-07 `verify-full` branch:** SSLContext with default `check_hostname`/`verify_mode` (the `else` arm without the `require` override). Unchanged. Correct. | PASS |
| **TD-07 external pooler:** `statement_cache_size: 0` appended AFTER ssl block at line 322, regardless of mode. Correct. | PASS |
| **TD-07 sibling properties:** `procrastinate_conninfo` (line 380) and `ogr_connection_string` (line 416) both still gate `sslmode` on `!= "disable"` / not-in-disable-prefer — unchanged from pre-phase. Correct. | PASS |
| **TD-07 field default:** `database_ssl_mode: str = "prefer"` at line 113. Unchanged. Correct. | PASS |
| **Test `test_disable_returns_ssl_false`:** asserts `== {"ssl": False}` (literal `False`). Correct. | PASS |
| **Test `test_enabled_with_ssl_disable`:** asserts `== {"statement_cache_size": 0, "ssl": False}`. Correct. | PASS |
| **Test `test_prefer_returns_ssl_prefer`:** unchanged, asserts `== {"ssl": "prefer"}`. Correct. | PASS |
| **Test `test_require_returns_ssl_context`:** unchanged, asserts `isinstance(ctx, ssl.SSLContext)` and `check_hostname is False`. Correct. | PASS |
| **Test `test_verify_full_returns_ssl_context_with_verify`:** unchanged, but the test body does not actually exercise the `verify-full` branch. Pre-existing defect. | WR-02 |
| **No skip-marks:** `grep pytest.mark.skip` across all three files returns zero. | PASS |
| **Old bug-asserting test gone:** `grep 'database_connect_args == {}'` returns 0. Correct. | PASS |

---

## Fixes Applied (2026-05-21)

Both warnings fixed in-session. 1 Info finding (IN-01) deferred to v1019 per scope rules.

### WR-01 fix — commit `4f9160cf`

**Files modified:**
- `backend/app/processing/ingest/tasks_common.py` line 1030: added `# broad: catch any swap failure to inspect for lock-timeout before re-raising` justification comment
- `backend/tests/test_layering.py` lines 1574-1575: changed grep regex from `r"except Exception(\s+as\s+\w+)?:"` to `r"except Exception([ \t]+as[ \t]+\w+)?:"` (portable ERE, works on macOS Apple Git and GNU grep)

**Verification:**
- `uv run pytest backend/tests/test_layering.py::test_no_unjustified_broad_except_sites -x`: 1 passed
- `uv run pytest backend/tests/test_layering.py -x`: 23 passed
- `git grep -E` old regex does NOT match line 1030 (macOS blind spot confirmed)
- `echo 'except Exception as first_exc: ...' | grep -E 'except Exception([ \t]+as[ \t]+\w+)?:'` exits 0 (portable regex matches correctly)
- Line 1030 has `# broad:` comment — excluded from violations by the test filter

### WR-02 fix — commit `200b829a`

**Files modified:**
- `backend/tests/test_config.py` lines 171-183: replaced body that discarded the verify-full settings object and asserted on a require-mode object instead; now calls `.database_connect_args` on the verify-full settings object (using `certifi.where()` for a valid cafile, required by the Settings fail-fast validator) and asserts `check_hostname is True` and `verify_mode == ssl.CERT_REQUIRED`

**Verification:**
- `uv run pytest backend/tests/test_config.py::TestDatabaseConnectArgs -x`: 4 passed (all branches covered)
- `uv run pytest backend/tests/test_config.py -x`: 58 passed (no regressions)
- `grep -c "database_connect_args" backend/tests/test_config.py` = 9 (verify-full test now actually calls the property)

---

_Reviewed: 2026-05-21_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: quick_
_Fixed: 2026-05-21_
_Fixer: Claude (gsd-code-fixer)_
