---
phase: 216-geolens-cli-mvp
verified: 2026-04-27T23:30:00Z
status: human_needed
score: 6/6 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Manual PyPI publish via .github/workflows/publish-cli.yml"
    expected: "`pip install geolens` from PyPI succeeds; `geolens --version` runs"
    why_human: "First-publish is a deferred user action per CONTEXT D-40 (requires PYPI_TOKEN secret + claiming the `geolens` PyPI name)"
  - test: "Verify keyring backend works on macOS (Keychain) and Windows (Credential Manager)"
    expected: "`geolens login --token <jwt>` writes to and reads from the OS-native keyring; cross-session persistence works"
    why_human: "Tests use a monkey-patched in-memory keyring; real OS-native backends require interactive verification on each platform"
  - test: "Interactive `geolens publish <file>` against a live GeoLens instance"
    expected: "rich.Progress UI displays 4 stages (Uploading → Previewing → Committing → Resolving) on a real TTY"
    why_human: "CliRunner output is non-TTY; progress UI rendering quality requires interactive observation"
  - test: "Refresh-token retry flow against a live backend"
    expected: "On a 401, CLI silently refreshes once; on second 401 prints 'Session expired'"
    why_human: "Time-based JWT expiry requires a real backend with a configured short-lived access token"
---

# Phase 216: geolens-cli-mvp Verification Report

**Phase Goal:** An end user can install the Apache-2.0 `geolens` CLI from PyPI, log into any GeoLens instance, scan a directory of spatial data, publish a dataset, and export STAC metadata — without writing a line of HTTP code or touching the GeoLens UI.
**Verified:** 2026-04-27T23:30:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| #   | Truth (SC) | Status | Evidence |
| --- | ---------- | ------ | -------- |
| 1 | SC#1 — `geolens` CLI distributed as Apache-2.0 PyPI package; `geolens --version` works | VERIFIED | `cli/pyproject.toml` declares `name="geolens"`, `license={text="Apache-2.0"}`; `cli/LICENSE` is byte-identical to `sdks/python/LICENSE` (190 lines, `diff` exit 0); `cli/geolens_cli/__init__.py` exposes `__version__` via `importlib.metadata.version("geolens")` with `PackageNotFoundError` fallback; `uv run geolens --version` prints `geolens 1.0.0`; `uv build` produces wheel + sdist (27,657 + 32,750 bytes) |
| 2 | SC#2 — `geolens login` keyring + `--no-keyring` fallback | VERIFIED | `cli/geolens_cli/auth.py` imports `keyring` + `keyring.errors.KeyringError`; `SERVICE = "geolens"`; `store_bearer_token/store_api_key/store_refresh_token` all use `keyring.set_password` with `KeyringError` auto-fallback to `credentials.toml` (mode 0600); `--no-keyring` flag wired in `main.py:123`; `tests/test_auth_keyring.py` (12 tests) + `tests/test_config.py` (15 tests) all pass |
| 3 | SC#3 — `geolens scan <dir>` dry-run report | VERIFIED | `cli/geolens_cli/scan.py` (206 lines) defines `walk()` generator + `ScanItem` dataclass + allowlist constants; `geolens scan --help` lists `--max-depth`, `--include-ext`, `--json`; `tests/test_scan.py` (17 tests) covers classification + shapefile grouping + symlink-loop + max-depth + JSON output; pure-local-I/O proven by zero `httpx`/`requests`/`geolens_sdk` imports |
| 4 | SC#4 — `geolens publish <file>` 3-step flow + dataset URL | VERIFIED | `cli/geolens_cli/publish.py` defines `upload_file` (multipart workaround via `client.get_httpx_client()`), `build_commit_request`, `resolve_dataset_id` (job_id→dataset_id poll), `construct_dataset_url` (canonical `<instance>/datasets/<id>` or fallback `?job_id=<id>`); `main.py publish` wires upload → preview → commit; `tests/test_publish_unit.py` (30 tests) covers the full flow including 400/409 duplicate handling and progress UI suppression |
| 5 | SC#5 — `geolens export stac <id>` writes STAC 1.1 + vector rejected exit 2 | VERIFIED | `cli/geolens_cli/export_stac.py` defines `fetch_record_type` (pre-flight) + `is_raster` + `fetch_stac_item` (calls `get_item_stac_items_item_id_get`) + `render_stac_json` + `write_stac_to_file` (uses `config.atomic_write_text` mode 0o644); main.py `export_stac` exits `EXIT_USAGE` (2) for non-raster; `tests/test_export_stac.py` (20 tests) including raster pass-through, vector rejection (exit 2), -o file atomic write, --compact |
| 6 | SC#6 — Zero direct HTTP imports in CLI source | VERIFIED | `grep -rE '^(import\|from) (httpx\|requests)' cli/geolens_cli/` returns zero matches; `cli/pyproject.toml` `[project].dependencies` has no httpx/requests entries (only typer, rich, keyring, tomli_w, platformdirs, structlog, geolens-sdk); multipart workaround uses `client.get_httpx_client()` which is the SDK-owned httpx instance; CI gate enforces both checks via `.github/workflows/ci.yml cli-test` job (lines 184-209) |

**Score:** 6/6 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `cli/pyproject.toml` | Apache-2.0 manifest, no httpx/requests, console-script | VERIFIED | name="geolens", license={text="Apache-2.0"}, requires-python=">=3.11", `[project.scripts] geolens = "geolens_cli.main:app"`, deps locked, no httpx/requests |
| `cli/LICENSE` | Apache-2.0 byte-identical to sdks/python/LICENSE | VERIFIED | 190 lines, `diff` exit 0 |
| `cli/README.md` | PyPI-facing quickstart | VERIFIED | Contains "geolens (CLI)", "Apache-2.0", "pip install geolens", "docs/cli.md" |
| `cli/geolens_cli/__init__.py` | `__version__` via importlib.metadata | VERIFIED | uses `importlib.metadata.version("geolens")` with PackageNotFoundError fallback to "0.0.0+dev" |
| `cli/geolens_cli/main.py` | Typer app + AppState + 6 commands wired | VERIFIED | All 6 commands (login/logout/whoami/scan/publish/export-stac) implemented; AppState.sdk() lazy property; @app.callback() with --json/-v/-q/--instance/--version |
| `cli/geolens_cli/output.py` | Formatter (rich + JSON) + EXIT_* indirectly | VERIFIED | Formatter dataclass with success/error/json/info/debug/console_stdout; NO_COLOR honored |
| `cli/geolens_cli/_sdk_helpers.py` | unwrap + call_sdk + EXIT_* constants | VERIFIED | EXIT_OK=0, EXIT_GENERIC=1, EXIT_USAGE=2, EXIT_AUTH=3, EXIT_NETWORK=4, EXIT_SERVER=5; httpx imported lazily for exception types only |
| `cli/geolens_cli/config.py` | XDG paths + atomic_write_text + AppConfig | VERIFIED | platformdirs.user_config_dir("geolens", appauthor=False); atomic_write_text uses tempfile.mkstemp + os.replace; mode 0o600 default |
| `cli/geolens_cli/auth.py` | keyring + file fallback + try_refresh | VERIFIED | SERVICE="geolens"; BearerToken/ApiKey frozen dataclasses; store/load/delete/try_refresh with KeyringError auto-fallback |
| `cli/geolens_cli/scan.py` | walk + ScanItem + allowlist | VERIFIED | VECTOR_EXTS, RASTER_EXTS, SHAPEFILE_REQUIRED_SIDECARS, HIDDEN_DIRS; symlink-loop guard; pure local I/O |
| `cli/geolens_cli/publish.py` | multipart workaround + 3-step flow helpers | VERIFIED | upload_file uses `client.get_httpx_client()`; UPLOAD_OK_STATUS=201, PREVIEW_OK_STATUS=200, COMMIT_OK_STATUS=202; resolve_dataset_id polls /jobs/{id}; is_duplicate_commit_response handles 400+409 |
| `cli/geolens_cli/export_stac.py` | fetch_record_type + fetch_stac_item + render | VERIFIED | calls `get_item_stac_items_item_id_get`; atomic write via config.atomic_write_text mode 0o644; pretty (indent=2, sorted keys, trailing \n) and compact modes |
| `cli/tests/conftest.py` + 7 test files | Wave 0 fixtures + per-module tests | VERIFIED | conftest with runner/tmp_xdg_home/mock_keyring; 112 unit tests pass in 0.54s |
| `backend/tests/test_cli_round_trip.py` | Round-trip integration | VERIFIED | 364 lines; uvicorn-on-free-port pattern (Option C); 8 tests, 6 pass + 2 documented skips |
| `scripts/sync_sdk_versions.py` | Extended with CLI_PYPROJECT | VERIFIED | `CLI_PYPROJECT` constant added; `_replace_pyproject_version` source-aware; idempotent (`make sdks-check` exit 0) |
| `.github/workflows/ci.yml` | cli-test job + OCCLI-06 grep gate | VERIFIED | Lines 153-217: cli-test job with checkout → setup-uv → install → grep gate (no httpx/requests imports) → tomllib gate (no httpx/requests deps) → CLI unit tests → CLI round-trip |
| `.github/workflows/publish-cli.yml` | workflow_dispatch publish | VERIFIED | 49 lines; `on.workflow_dispatch` only with `dry_run` boolean input; `working-directory: cli`; `UV_PUBLISH_TOKEN: ${{ secrets.PYPI_TOKEN }}` |
| `docs/cli.md` | ≥200 lines user docs | VERIFIED | 248 lines; 12 H2 sections (Installation, Quickstart, Commands, Auth Modes, Configuration, Lockstep Version Policy, Drift Gate, Publishing, Known Rough Edges, Troubleshooting, Exit Codes, References) |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| `cli/pyproject.toml` | `geolens_cli.main:app` | `[project.scripts]` | WIRED | `geolens = "geolens_cli.main:app"` declared; `uv run geolens --version` works |
| `cli/geolens_cli/__init__.py` | `cli/pyproject.toml` | `importlib.metadata.version` | WIRED | Version "1.0.0" reported by `geolens --version` |
| `cli/geolens_cli/main.py login` | SDK auth | `login_auth_login_post.sync_detailed` | WIRED | Imported in main.py:152; called via call_sdk |
| `cli/geolens_cli/auth.py` | OS keyring | `keyring.set_password` | WIRED | Direct calls in store_bearer_token/store_api_key/store_refresh_token |
| `cli/geolens_cli/main.py whoami` | SDK auth | `me_auth_me_get.sync_detailed` | WIRED | Imported main.py:196; called via call_sdk; refresh-retry on 401 |
| `cli/geolens_cli/auth.py` | SDK refresh | `refresh_auth_refresh_post` | WIRED | Imported in try_refresh; rotates refresh token on success |
| `cli/geolens_cli/main.py scan` | scan.walk | `_scan.walk(directory, max_depth, include_exts)` | WIRED | main.py:263 |
| `cli/geolens_cli/main.py publish` | upload/preview/commit SDK | `upload_file` + `_preview.sync_detailed` + `_commit.sync_detailed` | WIRED | main.py:381, 391, 397 |
| `cli/geolens_cli/publish.py upload_file` | SDK httpx | `client.get_httpx_client()` | WIRED | publish.py:127 — confirms multipart workaround uses SDK-owned httpx |
| `cli/geolens_cli/main.py export_stac` | SDK datasets + stac | `get_single_dataset_datasets_dataset_id_get` + `get_item_stac_items_item_id_get` | WIRED | export_stac.py:37-39, 92 |
| `cli/geolens_cli/export_stac.py write_stac_to_file` | atomic write | `_config.atomic_write_text(mode=0o644)` | WIRED | export_stac.py:130-134 |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| `geolens --version` exits 0 | `cd cli && uv run --no-sync geolens --version` | `geolens 1.0.0` | PASS |
| `geolens --help` lists 6 commands | `cd cli && uv run --no-sync geolens --help` | login, logout, whoami, scan, publish, export listed | PASS |
| `geolens login --help` lists --no-keyring | `cd cli && uv run --no-sync geolens login --help` | `--no-keyring` flag visible | PASS |
| `geolens scan --help` lists --json/--max-depth/--include-ext | `cd cli && uv run --no-sync geolens scan --help` | All 3 flags listed | PASS |
| `geolens export stac --help` shows -o + --compact | `cd cli && uv run --no-sync geolens export stac --help` | `-o`/`--output` and `--compact` listed | PASS |
| `geolens publish --help` shows --wait/--no-wait + 3-step description | `cd cli && uv run --no-sync geolens publish --help` | Flags + "3-step ingest flow" described | PASS |
| Full unit test suite | `cd cli && uv run --no-sync pytest -v` | 112 passed in 0.54s | PASS |
| Round-trip test suite | `cd backend && uv run pytest tests/test_cli_round_trip.py -v` | 6 passed, 2 skipped (documented) | PASS |
| `make sdks-check` (drift gate) | `make sdks-check` | exit 0 | PASS |
| `cd cli && uv build` (wheel + sdist) | `cd cli && uv build` | dist/geolens-1.0.0-py3-none-any.whl + .tar.gz built | PASS |
| OCCLI-06 grep gate | `grep -rE '^(import\|from) (httpx\|requests)' cli/geolens_cli/` | 0 matches | PASS |
| OCCLI-06 dep-list gate | tomllib check on cli/pyproject.toml | no httpx/requests in deps | PASS |
| LICENSE byte-identity | `diff cli/LICENSE sdks/python/LICENSE` | exit 0 | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| OCCLI-01 | 216-01 + 216-06 | Apache-2.0 PyPI package | SATISFIED | pyproject.toml + LICENSE + wheel build + publish-cli.yml workflow_dispatch |
| OCCLI-02 | 216-02 | keyring + headless fallback | SATISFIED | auth.py + 12 keyring tests pass; --no-keyring writes credentials.toml mode 0600 |
| OCCLI-03 | 216-03 | scan command | SATISFIED | scan.py + 17 tests pass; vector + raster + shapefile grouping verified |
| OCCLI-04 | 216-04 | publish command | SATISFIED | publish.py + 30 tests pass; multipart workaround + duplicate handling + dataset URL |
| OCCLI-05 | 216-05 | export stac command | SATISFIED | export_stac.py + 20 tests pass; vector rejection exit 2; -o atomic write |
| OCCLI-06 | 216-01 + 216-06 | No direct HTTP imports | SATISFIED | Grep gate clean; tomllib gate clean; CI cli-test job enforces both |

All 6 OCCLI requirements marked `[x]` in REQUIREMENTS.md (verified at lines 40-45). REQUIREMENTS.md status table (lines 131-136) lists all six as Complete. ROADMAP.md line 19 marks Phase 216 as `[x] **Phase 216: geolens-cli-mvp** ... (completed 2026-04-27)`.

### Anti-Patterns Found

None of consequence. Spot-checked the seven main `geolens_cli/*.py` source files:

- No `TODO:` / `FIXME:` / `XXX:` / `HACK:` markers indicating incomplete work (only documented `TODO(OCCLI-deferred)` comments for the explicit `--tags` and `--collection` flag deferrals from Plan 04 Q2/Q5, which are documented in the SUMMARY).
- No empty implementations (`return null`, `=> {}`, etc.).
- No console.log-only command bodies.
- The `--tags` and `--collection` flags ARE accepted but deferred via debug log + TODO comment — this is **documented intentional deviation** captured in the Plan 04 SUMMARY and DECISION-LOG.md (Q2 + Q5). Acceptable per CONTEXT D-15 / D-22 / D-24 (MVP scope).

### Human Verification Required

Four items require human testing because they cannot be programmatically verified:

1. **PyPI publish (D-40 deferred user action)**
   - **Test:** Run `gh workflow run publish-cli.yml -f dry_run=true`, then `dry_run=false` after PYPI_TOKEN is set
   - **Expected:** `pip install geolens` from PyPI succeeds; `geolens --version` runs from a fresh venv
   - **Why human:** First publish requires PYPI_TOKEN secret + claiming the `geolens` PyPI name (per CONTEXT D-40)

2. **OS-native keyring backends (macOS Keychain, Windows Credential Manager, Linux Secret Service)**
   - **Test:** On each platform, run `geolens login <url> --token <jwt>` then `geolens whoami` in a new shell session
   - **Expected:** Token persists across sessions; OS keychain UI shows a `geolens` entry
   - **Why human:** Tests use a monkey-patched in-memory keyring; real OS-native backends require interactive verification per platform

3. **Interactive progress UI rendering**
   - **Test:** Run `geolens publish <large-file>.geojson` against a live instance from a real terminal
   - **Expected:** rich.Progress UI displays 4 stages (Uploading → Previewing → Committing → Resolving) with spinner animation
   - **Why human:** CliRunner output is non-TTY by design; Progress UI rendering quality requires interactive observation

4. **Refresh-token retry against live backend**
   - **Test:** With a short-lived JWT, run `geolens whoami`; wait until expiration; run again
   - **Expected:** First post-expiry call silently refreshes; second 401 (after refresh fails) prints "Session expired"
   - **Why human:** Time-based JWT expiry requires a real backend with configured short-lived access tokens

### Gaps Summary

No blocking gaps. All 6 ROADMAP success criteria are verified through code inspection, unit tests (112 pass), round-trip integration tests (6 pass + 2 documented skips), and infrastructure verification (CI job + publish workflow + version-sync extension + 248-line user docs).

The four human-verification items above represent the boundary of programmatic verification:
- PyPI publish is a deferred user action (D-40) tracked in CONTEXT.md and the publish-cli.yml runbook in docs/cli.md.
- OS-native keyring + interactive TTY + time-based refresh are real-world phenomena tests cannot simulate without staging a live deployment.

These are **expected** human-verification items per the verification request notes; the prompt explicitly identifies "PyPI install of `geolens` is a deferred user action (D-40 — manual workflow_dispatch trigger required). Treat that as `human_needed`, not `gaps_found`. Same for macOS/Windows keyring backends and interactive progress UI rendering."

Phase goal is achieved. Status `human_needed` reflects deferred user actions, not implementation gaps.

---

_Verified: 2026-04-27T23:30:00Z_
_Verifier: Claude (gsd-verifier)_
