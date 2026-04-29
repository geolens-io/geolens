---
phase: 216
slug: geolens-cli-mvp
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-27
formalized: 2026-04-29
formalization_note: "Post-hoc paperwork close per v13.1-MILESTONE-AUDIT.md (2026-04-29). 112 CLI unit tests pass (0.54s); 6 round-trip tests pass + 2 documented skips; OCCLI-06 grep gate clean; phase-level 216-VERIFICATION.md confirmed 6/6 ROADMAP SC verified; no coverage gaps surfaced by milestone audit. Original status=draft was paperwork lag, not coverage gap."
---

# Phase 216 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | `pytest` 9.0.3+ (CLI unit tests under `cli/tests/`; integration test under `backend/tests/`) |
| **Config file** | `cli/pyproject.toml` (NEW — `[tool.pytest.ini_options]` with `testpaths = ["tests"]`) + existing `backend/pyproject.toml` for `backend/tests/test_cli_round_trip.py` |
| **Quick run command** | `cd cli && uv run pytest -x` |
| **Full suite command** | `cd cli && uv run pytest -v && cd ../backend && PYTHONPATH=. uv run pytest tests/test_cli_round_trip.py -v` |
| **Estimated runtime** | ~30s unit + ~10–60s round-trip (depends on ASGI vs uvicorn-on-port spike per RESEARCH.md A2) |

---

## Sampling Rate

- **After every task commit:** `cd cli && uv run pytest tests/test_<module>.py -x` — the unit slice for the module being edited (~<5s).
- **After every plan wave:** `cd cli && uv run pytest -v` (full unit suite ~<30s) + `cd backend && PYTHONPATH=. uv run pytest tests/test_cli_round_trip.py -v`.
- **Before `/gsd-verify-work`:** Full suite green AND `make sdks-check` exit 0 AND `cd cli && uv build` succeeds.
- **Max feedback latency:** 30s (unit suite); 90s (full).

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 216-01-* | 01 (scaffold) | 1 | OCCLI-01 | — | Apache-2.0 license file present | unit | `cd cli && uv run pytest tests/test_version.py -x` | ❌ W0 | ⬜ pending |
| 216-02-* | 02 (auth+config) | 2 | OCCLI-02 | T-216-01 (token-at-rest) | credentials.toml mode 0600; keyring service `geolens` | unit | `cd cli && uv run pytest tests/test_auth_keyring.py tests/test_config.py -x` | ❌ W0 | ⬜ pending |
| 216-02-* | 02 (auth+config) | 2 | OCCLI-02 | T-216-02 (replay) | refresh-token retry once on 401, then exit code 3 | integration | `PYTHONPATH=. uv run pytest backend/tests/test_cli_round_trip.py::test_login_round_trip -x` | ❌ W0 | ⬜ pending |
| 216-03-* | 03 (scan) | 2 | OCCLI-03 | — | extension allowlist subset of server allowlist | unit | `cd cli && uv run pytest tests/test_scan.py -x` | ❌ W0 | ⬜ pending |
| 216-03-* | 03 (scan) | 2 | OCCLI-03 | — | shapefile sidecars grouped under `.shp` parent | unit | `cd cli && uv run pytest tests/test_scan.py::test_shapefile_grouping -x` | ❌ W0 | ⬜ pending |
| 216-03-* | 03 (scan) | 2 | OCCLI-03 | — | `--json` emits machine-readable schema | unit | `cd cli && uv run pytest tests/test_scan.py::test_json_output -x` | ❌ W0 | ⬜ pending |
| 216-04-* | 04 (publish) | 3 | OCCLI-04 | T-216-03 (file-content-type spoof) | server-side magic-byte validation respected (no client bypass) | unit | `cd cli && uv run pytest tests/test_publish_unit.py -x` | ❌ W0 | ⬜ pending |
| 216-04-* | 04 (publish) | 3 | OCCLI-04 | — | dataset URL printed to stdout (`https://<instance>/datasets/<id>`) | integration | `PYTHONPATH=. uv run pytest backend/tests/test_cli_round_trip.py::test_publish_geojson_round_trip -x` | ❌ W0 | ⬜ pending |
| 216-04-* | 04 (publish) | 3 | OCCLI-04 | — | progress UI suppressed when stdout not a TTY | unit | `cd cli && uv run pytest tests/test_publish_unit.py::test_progress_suppressed_non_tty -x` | ❌ W0 | ⬜ pending |
| 216-05-* | 05 (export stac) | 3 | OCCLI-05 | — | non-raster dataset → exit code 2 with clear error | unit | `cd cli && uv run pytest tests/test_export_stac.py::test_vector_rejected -x` | ❌ W0 | ⬜ pending |
| 216-05-* | 05 (export stac) | 3 | OCCLI-05 | — | `-o FILE` writes pretty JSON atomically | unit | `cd cli && uv run pytest tests/test_export_stac.py::test_output_file -x` | ❌ W0 | ⬜ pending |
| 216-06-* | 06 (round-trip + CI + docs) | 4 | OCCLI-06 | T-216-04 (HTTP bypass) | zero `import httpx`/`import requests` in `cli/geolens_cli/` | static check | `! grep -rE '^(import\|from) (httpx\|requests)' cli/geolens_cli/` | ❌ W0 | ⬜ pending |
| 216-06-* | 06 (round-trip + CI + docs) | 4 | OCCLI-06 | T-216-04 (HTTP bypass) | `cli/pyproject.toml` declares no `httpx`/`requests` direct deps | static check | `cd cli && uv run python -c "import tomllib;d=tomllib.load(open('pyproject.toml','rb'));deps=d['project']['dependencies'];assert not any('httpx' in dep or 'requests' in dep for dep in deps)"` | ❌ W0 | ⬜ pending |
| 216-06-* | 06 (round-trip + CI + docs) | 4 | (cross) | — | exit-code matrix `0/1/2/3/4/5` correct per scenario | unit | `cd cli && uv run pytest tests/test_exit_codes.py -x` | ❌ W0 | ⬜ pending |
| 216-06-* | 06 (round-trip + CI + docs) | 4 | (cross) | — | round-trip suite hits in-process ASGI app | integration | `PYTHONPATH=. uv run pytest backend/tests/test_cli_round_trip.py -v` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

Threat refs are placeholders; the planner's `<threat_model>` block will replace them with the actual T-216-NN identifiers from each plan's threat model.

---

## Wave 0 Requirements

- [ ] `cli/pyproject.toml` — `[tool.pytest.ini_options] testpaths = ["tests"]`; declared deps include the standard stack (typer, rich, keyring, structlog, geolens-sdk; tomli_w for 3.10 floor or none for 3.11+).
- [ ] `cli/tests/__init__.py` — empty marker.
- [ ] `cli/tests/conftest.py` — shared `runner = CliRunner()` fixture; `tmp_xdg_home` fixture (sets `XDG_CONFIG_HOME` to tmp_path); `mock_keyring` fixture (in-memory dict via monkeypatch).
- [ ] `cli/tests/test_version.py` — covers OCCLI-01 (importlib.metadata version, --version flag prints version).
- [ ] `cli/tests/test_auth_keyring.py` — covers OCCLI-02 (keyring set/get/delete, --no-keyring file fallback path, headless detection).
- [ ] `cli/tests/test_config.py` — covers TOML round-trip + 0600 mode + atomic-write semantics.
- [ ] `cli/tests/test_scan.py` — covers OCCLI-03 (extension classification, shapefile grouping, table + JSON output).
- [ ] `cli/tests/test_publish_unit.py` — covers OCCLI-04 unit slice with mocked SDK (dataset URL format, progress suppression, optional flags).
- [ ] `cli/tests/test_export_stac.py` — covers OCCLI-05 (raster pass-through, vector rejection, -o file atomic write, --compact).
- [ ] `cli/tests/test_exit_codes.py` — exit-code matrix (D-32).
- [ ] `cli/tests/test_output.py` — JSON vs table output formatters; NO_COLOR env var respected.
- [ ] `backend/tests/test_cli_round_trip.py` — integration tests mirroring `backend/tests/test_sdks_round_trip.py` pattern (in-process `httpx.ASGITransport` per RESEARCH.md A2 spike; module-level skip when `cli/` source absent — docker container path).
- [ ] Framework install: `cd cli && uv add --dev pytest`. Round-trip test reuses backend's existing pytest pin.
- [ ] OCCLI-06 static check — add `cli-lint` Makefile recipe + CI step (grep + tomllib assertion).
- [ ] `.github/workflows/ci.yml` — extend with `cli-test` job (mirrors `sdks-check`); add `cli/**` to the paths-filter (NEW filter category).
- [ ] `.github/workflows/publish-cli.yml` — manual `workflow_dispatch` (mirrors `publish-sdks.yml`).
- [ ] `scripts/sync_sdk_versions.py` — extend to write `cli/pyproject.toml` `[project].version`.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `pip install geolens` from PyPI installs Apache-2.0 package | OCCLI-01 | Requires actually publishing to PyPI; first publish is a user action with `PYPI_TOKEN` (per CONTEXT.md D-40 and Phase 215 D-16). | After phase merges, the user runs `Actions → publish-cli.yml → Run workflow` with the version tag, then `pip install geolens` in a clean venv and runs `geolens --version`. Smoke-build with `cd cli && uv build` is automated; the actual PyPI publish is not. |
| OS keyring integration on macOS Keychain / Windows Credential Manager | OCCLI-02 | Cannot fully exercise platform-native keyring backends in CI (Linux has Secret Service / KWallet but macOS/Windows backends require those OSes). | After local dev install, run `geolens login http://localhost:8001` on macOS and Windows respectively; confirm the token appears in Keychain Access (macOS) / Credential Manager (Windows). |
| `--no-keyring` headless-Linux fallback | OCCLI-02 | The auto-fallback warning path is only triggered when dbus is unavailable; CI Linux runners may not have it. | Run `geolens login --no-keyring` on a real headless box; confirm `~/.config/geolens/credentials.toml` is mode 0600. |
| Native progress UI under interactive TTY | OCCLI-04 | `rich.progress` rendering is observable only in real terminals; CI captures non-TTY output (D-21). | Run `geolens publish foo.geojson` interactively against a real instance; confirm 4-stage progress bar renders. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies (every per-task entry above maps to a Wave 0 file or existing infrastructure)
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify (every plan has unit + integration coverage)
- [ ] Wave 0 covers all MISSING references (16 Wave 0 items above)
- [ ] No watch-mode flags (all commands are one-shot `pytest -x`)
- [ ] Feedback latency < 30s (unit) / 90s (full)
- [ ] `nyquist_compliant: true` set in frontmatter (after Wave 0 lands)

**Approval:** pending
