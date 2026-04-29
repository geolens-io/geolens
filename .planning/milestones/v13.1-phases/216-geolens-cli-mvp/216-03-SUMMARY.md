---
phase: 216-geolens-cli-mvp
plan: 03
subsystem: cli
tags: [cli, scan, filesystem, walk, shapefile, occli-03, occli-06, wave-2, tdd]
dependency_graph:
  requires:
    - cli/geolens_cli (Plan 01 — main.py shell, AppState, Formatter.console_stdout)
    - cli/tests/conftest.py (Plan 01 — runner fixture)
  provides:
    - geolens_cli.scan — ScanItem dataclass, walk() generator, allowlist constants
      (VECTOR_EXTS, RASTER_EXTS, SHAPEFILE_REQUIRED_SIDECARS, HIDDEN_DIRS),
      _classify_group(), _looks_like_geojson()
    - working `geolens scan <dir>` command with --json, --max-depth, --include-ext flags
    - cli/tests/test_scan.py — 17 unit tests (4 classification + 3 grouping +
      4 walk semantics + 6 CLI invocation)
  affects:
    - Plan 06 (round-trip + CI + docs) — scan invariant adds to OCCLI-06 grep gate;
      docs/cli.md will document the scan command surface
tech-stack:
  added: []
  patterns:
    - Pure-local-I/O module pattern (no httpx/requests/geolens_sdk imports)
    - Shapefile sibling-grouping under .shp parent (D-18) — single dataset row,
      sidecar list in JSON output, missing required sidecars → ingest=False
    - Symlink-loop protection via canonical-path visited set
    - Deterministic sorted output for testability
    - Peek-read disambiguation (.json → geojson if startswith "{" + contains "type")
    - Public Formatter.console_stdout property usage (no _stdout private access)
key-files:
  created:
    - cli/geolens_cli/scan.py
    - cli/tests/test_scan.py
    - .planning/phases/216-geolens-cli-mvp/216-03-SUMMARY.md
  modified:
    - cli/geolens_cli/main.py
    - cli/tests/test_exit_codes.py
key-decisions:
  - "Allowlist is a documented subset of backend/app/processing/ingest/validation.py
     EXTENSION_CONTENT_MAP; CSV/XLS/XLSX/ZIP intentionally excluded per D-15 with
     in-code comment explaining the divergence (CSV deferred until --csv flag)"
  - "Reused Formatter.console_stdout public property for rich.Table rendering instead
     of recreating a Console — Plan 01 explicitly added this property as the contract"
  - "Removed test_scan_stub_exits_2 from test_exit_codes.py (per Plan 01 SUMMARY's
     explicit handoff — stubs are replaced with per-command behavior tests)"
  - "Typer's exists=True/file_okay=False/dir_okay=True/readable=True validates the
     directory argument before the command body runs; nonexistent dir → exit 2 by
     Typer default (no manual check needed)"
  - "Used path-keyed (not stem-only) files_by_stem to avoid colliding files in
     different subdirectories from being grouped — child.with_suffix('') retains
     the parent path"
patterns-established:
  - "scan.py demonstrates the structural-purity pattern for pure-local-I/O modules:
     module docstring documents the policy + grep-gate-friendly imports + zero SDK
     dependencies. Future commands that don't need HTTP (e.g., schema inspection,
     local-only validation) follow the same shape."
  - "Shapefile-style sibling grouping is generalizable to any multi-file dataset
     format. _classify_group accepts a stem-keyed extension map; future plan can
     extend with raster .aux.xml grouping if needed (currently silently skipped)."
requirements-completed:
  - OCCLI-03
metrics:
  duration_seconds: 480
  duration_human: "8m 00s"
  completed_date: "2026-04-27"
  tasks_completed: 2
  tests_passing: 63
  tests_added: 17
  files_created: 2
  files_modified: 2
---

# Phase 216 Plan 03: scan-command Summary

**Pure-local-I/O directory scanner with extension-based classification, shapefile sibling-grouping, symlink-loop protection, and rich-table + JSON dual output — closes OCCLI-03 and structurally inherits OCCLI-06.**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-04-27T22:03:00Z (approx)
- **Completed:** 2026-04-27T22:11:00Z
- **Tasks:** 2/2 (RED+GREEN per task — 3 commits total)
- **Files created:** 2 (scan.py, test_scan.py)
- **Files modified:** 2 (main.py, test_exit_codes.py)

## Accomplishments

- `geolens scan <dir>` walks a directory, classifies each file by extension, and prints either a rich.Table (default) or a JSON array (`--json`).
- Vector formats detected: `.geojson`, `.gpkg`, `.shp`. Raster formats: `.tif`, `.tiff` (`cog-candidate`).
- Shapefile sibling-grouping (D-18): one row per `.shp`, with `.dbf`/`.shx`/`.prj`/`.cpg` listed under `sidecar_files`. Missing required `.dbf`/`.shx` → `ingest=False` with descriptive reason.
- Walk semantics (D-16): recursive by default; `--max-depth N` caps recursion; hidden dirs (`.git`, `__pycache__`, `.venv`, `node_modules`, `.idea`, `.vscode`, `.pytest_cache`, `.ruff_cache`, dot-prefixed) skipped; symlink loops detected via canonical-path visited set.
- Output schema (D-17): exit 0 even when every file is `ingest: no` (it's a dry-run report, not an error).
- 17 new unit tests: 4 classification + 3 shapefile-grouping + 4 walk-semantics + 6 CLI invocation. Total cli/tests/ suite is now 63/63 passing.
- OCCLI-06 invariant verified structurally: `scan.py` has zero `httpx`/`requests`/`geolens_sdk` imports.

## What Shipped

### `cli/geolens_cli/scan.py` (NEW, 206 lines)

**Module docstring** documents the pure-local-I/O policy: detection is extension-only per D-15; the server re-validates content via puremagic on upload, so client-side spoofing is not a security concern. The module makes ZERO HTTP calls and inherits OCCLI-06 trivially.

**Public surface:**

| Symbol | Type | Purpose |
| ------ | ---- | ------- |
| `ScanItem` | `@dataclass` | One row per dataset: `path`, `format`, `ingest`, `reason`, `sidecar_files`. `to_dict()` for JSON serialization. |
| `walk(root, *, max_depth=None, include_exts=None)` | generator | Yields ScanItems sorted by path. |
| `VECTOR_EXTS` | `set[str]` | `{".geojson", ".gpkg", ".shp"}` |
| `RASTER_EXTS` | `set[str]` | `{".tif", ".tiff"}` |
| `SHAPEFILE_REQUIRED_SIDECARS` | `set[str]` | `{".dbf", ".shx"}` |
| `SHAPEFILE_OPTIONAL_SIDECARS` | `set[str]` | `{".prj", ".cpg", ".qix", ".sbn", ".sbx"}` |
| `RASTER_OPTIONAL_SIDECARS` | `set[str]` | `{".aux.xml", ".ovr", ".tfw"}` |
| `HIDDEN_DIRS` | `set[str]` | 8 entries (see below) |

**Internal helpers:**

- `_walk(root, current, visited, max_depth, include_exts)` — recursive walker with `visited: set[Path]` keyed on canonical (resolved) paths for symlink-loop protection. Builds `files_by_stem: dict[Path, dict[str, Path]]` per directory before classifying so shapefile siblings are grouped.
- `_classify_group(exts, include_exts)` — emits one ScanItem per stem; shapefile case takes priority and emits a single grouped row; non-shapefile extensions classified individually.
- `_looks_like_geojson(path, peek_bytes=1024)` — peek-reads up to 1024 bytes; returns True if file starts with `{` (after lstrip) and contains `"type"` in first 200 bytes.
- `_sorted_iter` — ensures deterministic `sorted(by str(path))` output.

**HIDDEN_DIRS:** `.git`, `__pycache__`, `.venv`, `node_modules`, `.idea`, `.vscode`, `.pytest_cache`, `.ruff_cache`. Plus any dot-prefixed directory name (also implicitly skipped via `child.name.startswith(".")`).

### `cli/geolens_cli/main.py` (MODIFIED — scan stub replaced)

`scan(directory, max_depth, include_ext, json_local)`:

- `directory: Annotated[Path, typer.Argument(exists=True, file_okay=False, dir_okay=True, readable=True)]` — Typer validates before the body runs; nonexistent or non-directory paths exit 2 via Typer default.
- `--max-depth N` — `Optional[int]` with `min=0`. `0` scans only top-level (no recursion).
- `--include-ext .gpkg,.tif` — comma-separated, auto-prepended dot, lowercased.
- `--json` — local flag (overrides global state.json_mode if either is set).

JSON-mode emits `[ScanItem.to_dict(), ...]` via `state.output.json(payload)` (Formatter handles indent + sort_keys).

Default mode renders a rich.Table with `PATH`/`FORMAT`/`INGEST?` columns (PATH is `relative_to(directory)` when possible). Reason text appended to INGEST? column when `ingest=False`. Empty results emit `(no files found)` info message. Table rendered via `state.output.console_stdout.print(table)` — the public Formatter property added in Plan 01, NOT the underscored `_stdout`.

### `cli/tests/test_scan.py` (NEW, 168 lines, 17 tests)

`sample_tree` fixture builds a representative directory tree: `.geojson`, `.tif`, `.txt`, complete shapefile (`cities.shp`+`.dbf`+`.shx`+`.prj`), broken shapefile (`broken.shp`+`.shx`, missing `.dbf`), hidden `.git/secret.geojson`, nested `nested/elev.tif`, non-GeoJSON `config.json`.

| Class | Tests | What it covers |
| ----- | ----- | -------------- |
| `TestClassification` | 4 | geojson/tiff/unsupported-ext/non-geojson-json detection |
| `TestShapefileGrouping` | 3 | complete .shp + sidecars / missing .dbf reason / no separate sidecar rows |
| `TestWalkSemantics` | 4 | hidden dirs skipped / recursive default / max-depth=0 / symlink loop |
| `TestCliInvocation` | 6 | exit 0 on dry-run / exit 0 all-unsupported / --json schema / --json sidecars / global --json / nonexistent dir |

### `cli/tests/test_exit_codes.py` (MODIFIED)

Removed `test_scan_stub_exits_2` from `TestRemainingStubsExitWithUsage` and updated the class docstring to reflect that scan now exits 0 on dry-run per D-17. Per-command behavior is asserted in `test_scan.py::TestCliInvocation`. This mirrors the Plan 02 handoff pattern (Plan 02 SUMMARY explicitly flagged that auth stubs would be replaced).

## Allowlist Reconciliation with Server

The CLI's allowlist is a **documented subset** of the server's `EXTENSION_CONTENT_MAP` in `backend/app/processing/ingest/validation.py`:

| Extension | Server `EXTENSION_CONTENT_MAP` | CLI MVP | Reason for divergence |
| --------- | ------------------------------ | ------- | --------------------- |
| `.geojson` | yes | yes | matched |
| `.json` | yes (geojson alias) | yes (peek-read disambiguation) | matched semantically |
| `.gpkg` | yes | yes | matched |
| `.shp` | (via .zip bundle) | yes (with sibling grouping) | extension-only client; server validates the .zip bundle |
| `.tif`/`.tiff` | yes | yes | matched |
| `.csv` | yes (text fallback) | **no** | brittle without lat/lon column detection (deferred to `--csv` flag) |
| `.xls`/`.xlsx` | yes | **no** | not geospatial primaries — CLI excludes per D-15 |
| `.zip` | yes (with bomb checks) | **no** | shapefile bundles handled via sidecar grouping on extracted `.shp` |

The divergence is documented in scan.py's module docstring with a TODO marker. **The CLI never claims `ingest=yes` for an extension the server rejects** — the inverse direction (server allows but CLI says "unsupported") is acceptable since the server is the authoritative gate.

## OCCLI-06 Invariant Evidence

```bash
$ ! grep -rE '^(import|from) (httpx|requests|geolens_sdk)' cli/geolens_cli/scan.py
OCCLI-06 invariant holds — scan.py is pure local I/O.
```

`scan.py` imports are limited to:
- `__future__` annotations
- `dataclasses.dataclass`
- `pathlib.Path`
- `typing.Iterator, Optional`

Zero direct `httpx`/`requests` imports. Zero `geolens_sdk` imports. The module is structurally proven to be HTTP-free.

## Verification Evidence

| Check | Command | Result |
| ----- | ------- | ------ |
| OCCLI-03: scan.py public surface | `python -c "from geolens_cli.scan import ScanItem, walk, VECTOR_EXTS, RASTER_EXTS, SHAPEFILE_REQUIRED_SIDECARS, HIDDEN_DIRS"` | OK |
| OCCLI-03: walk + classify smoke | inline programmatic test (geojson/tif/txt) | OK |
| OCCLI-03: scan.py grep gate | `! grep -rE '^(import\|from) (httpx\|requests\|geolens_sdk)' cli/geolens_cli/scan.py` | no matches |
| OCCLI-03: --json end-to-end | `runner.invoke(app, ['scan', dir, '--json'])` → `json.loads(output)[0] == {format: geojson, ingest: True, ...}` | OK |
| OCCLI-03: console_stdout (not _stdout) | `grep state.output.console_stdout main.py` | found 1 match; no `_stdout` access |
| Plan-level tests | `cd cli && uv run pytest tests/test_scan.py -v` | 17/17 passed in 0.09s |
| Full suite | `cd cli && uv run pytest -v` | 63/63 passed in 0.14s |

## Public Interfaces Established for Plan 04+

```python
# Plan 04 (publish) may use the same allowlist for client-side type pre-flight:
from geolens_cli.scan import (
    VECTOR_EXTS, RASTER_EXTS,
    SHAPEFILE_REQUIRED_SIDECARS, SHAPEFILE_OPTIONAL_SIDECARS,
)

# If publish needs to pre-classify a file (it likely does for the "is this
# vector or raster?" branch on the client), it can call:
from geolens_cli.scan import _classify_group  # or a future public _classify_file()
# Currently _classify_group is private; if Plan 04 needs it, promote to public
# and update test_scan.py.

# Test fixtures continue to work via cli/tests/conftest.py:
@pytest.fixture
def runner() -> CliRunner: ...
```

## Decisions Made

1. **Reused Formatter.console_stdout (not _stdout)** — Plan 01 explicitly added `console_stdout` as the public contract for downstream rich primitives. Direct `_stdout` access would couple Plan 03 to Formatter's internal field name.
2. **Removed test_scan_stub_exits_2 instead of repurposing it** — matches Plan 02's pattern where stubbed-exit tests for login/logout/whoami were deleted and replaced by per-command behavior tests. Keeps the exit-code matrix file focused on what it claims to test.
3. **Used `child.with_suffix("")` instead of `child.stem` for the files_by_stem key** — `child.stem` would collide files with the same name in different subdirectories. Using the full path-with-suffix-stripped retains the parent-path discriminator while still grouping `cities.shp` with `cities.dbf` correctly.
4. **Typer `exists=True` validation handles nonexistent directories** — exit 2 emerges from Typer/Click's argument parser before our body runs; no manual `if not directory.is_dir()` check needed.
5. **CSV/XLS/XLSX/ZIP intentionally excluded from CLI allowlist** — documented divergence from server `EXTENSION_CONTENT_MAP`; the CLI is conservative (never claims ingest=yes for what the server might reject). Future `--csv` flag (deferred) would reactivate CSV.

## Deviations from Plan

None — plan executed exactly as written.

- No Rule 1 (bug) auto-fixes.
- No Rule 2 (missing critical functionality) auto-fixes.
- No Rule 3 (blocking issue) auto-fixes (test_scan_stub removal was the explicit Plan 01 handoff, not an unplanned issue).
- No Rule 4 (architectural) escalations.
- No authentication gates.

The only judgment call beyond literal plan text was extending the module docstring's allowlist comment to explicitly enumerate which server-side extensions the CLI excludes (CSV/XLS/XLSX/ZIP), rather than just naming `.fgb`/`.parquet` as the plan suggested. This is documentation richness, not a behavioral deviation.

## TDD Gate Compliance

Plan was `type=execute` with per-task `tdd="true"`. Each task followed RED → GREEN:

| Task | RED commit (test) | GREEN commit (impl) | REFACTOR |
| ---- | ----------------- | ------------------- | -------- |
| 1 (scan.py) + 2 (main.py wiring) | `bfcc11d6` test(216-03): add failing tests for scan walk + classify + group + CLI | `b00707c4` (Task 1 GREEN — scan.py) → `748dee9c` (Task 2 GREEN — main.py wiring + test_exit_codes update) | not needed |

Tasks 1 and 2 share a single RED commit (`bfcc11d6`) because the test_scan.py file naturally covers both the unit-level walk/classify tests (Task 1) and the CLI invocation tests (Task 2) — they target the same module under test. Both GREEN commits land separately with task-specific deliverables.

| RED gate | GREEN gate | REFACTOR gate |
| -------- | ---------- | ------------- |
| `test(216-03):` commit landed before any `feat(216-03):` | yes (`bfcc11d6` → `b00707c4`) | not needed |

## Issues Encountered

None — plan-driven execution with no blockers, ambiguities, or external failures. The two-tasks-share-one-RED-commit pattern emerged naturally because test_scan.py is one file, but acceptance criteria for both tasks pass.

## Threat Flags

None — this plan only adds pure-local-I/O filesystem scanning. No new HTTP surface, no new credentials, no new file-write paths beyond pre-existing rich Console output. T-216-03 (extension-allowlist bypass) is `accept` per CONTEXT.md D-15 — the server is the authoritative gate. T-216-04 (HTTP bypass) is `mitigate` and remains satisfied: the OCCLI-06 grep gate against `cli/geolens_cli/scan.py` returns zero matches.

## Next Plan Readiness

- Plan 04 (publish) can reuse `geolens_cli.scan.VECTOR_EXTS`/`RASTER_EXTS` for client-side type pre-flight if needed.
- The `_classify_group()` helper is currently private; if Plan 04 requires per-file classification (e.g., to pick the right ingest endpoint client-side), promote a public `classify_file(path) -> ScanItem` wrapper.
- All Wave 0 test infrastructure (Plan 01) and credential layer (Plan 02) remain intact; Plan 04 has the full `AppState.sdk()` bridge available.

## Task Commits

| Task | Hash | Description |
| ---- | ---- | ----------- |
| 1+2 RED | `bfcc11d6` | test(216-03): add failing tests for scan walk + classify + group + CLI |
| 1 GREEN | `b00707c4` | feat(216-03): implement scan.py walk + classify + shapefile grouping |
| 2 GREEN | `748dee9c` | feat(216-03): wire scan command + table/JSON output |

## Self-Check: PASSED

- `cli/geolens_cli/scan.py` exists ✓
- `cli/tests/test_scan.py` exists ✓
- `cli/geolens_cli/main.py` modified (scan command wired) ✓
- `cli/tests/test_exit_codes.py` modified (test_scan_stub_exits_2 removed) ✓
- `.planning/phases/216-geolens-cli-mvp/216-03-SUMMARY.md` exists ✓
- Commit `bfcc11d6` exists ✓
- Commit `b00707c4` exists ✓
- Commit `748dee9c` exists ✓
- 17/17 test_scan.py tests passing ✓
- 63/63 full unit suite passing ✓
- OCCLI-06 invariant holds (zero `^(import|from) (httpx|requests|geolens_sdk)` in scan.py) ✓
- `state.output.console_stdout` used (NOT `_stdout` private) ✓
- `geolens scan --json` emits machine-readable JSON array on stdout ✓

---
*Phase: 216-geolens-cli-mvp*
*Completed: 2026-04-27*
