---
phase: 216-geolens-cli-mvp
plan: 05
subsystem: cli
tags: [cli, export, stac, raster, occli-05, occli-06, wave-3, tdd]
dependency_graph:
  requires:
    - cli/geolens_cli (Plans 01-02 — main.py, AppState.sdk(), Formatter,
      _sdk_helpers, config.atomic_write_text)
    - sdks/python/geolens_sdk (Phase 215 — datasets/get_single_dataset +
      stac/get_item_stac binders)
  provides:
    - geolens_cli.export_stac — fetch_record_type, is_raster,
      fetch_stac_item, render_stac_json, write_stac_to_file,
      vector_rejection_message
    - working `geolens export stac <id>` command with -o FILE atomic
      write and --compact single-line modes
    - cli/tests/test_export_stac.py — 20 unit tests
  affects:
    - Plan 06 (round-trip + CI + docs) — round-trip will exercise the
      vector-rejection branch end-to-end (raster fixture skip per
      RESEARCH Open Question 3); docs/cli.md export-stac section lands
      there; OCCLI-06 grep gate inherits export_stac.py invariant proof
tech-stack:
  added: []
  patterns:
    - "SDK pass-through with pre-flight type guard (D-25 + D-26) —
      GET /datasets/{id} first, then GET /stac/items/{id} only on raster"
    - "Atomic file write with mode 0o644 via config.atomic_write_text
      (D-27, RESEARCH Pattern 4) — STAC payloads aren't secrets but the
      tempfile + os.replace dance prevents half-written files on Ctrl+C"
    - "Sorted-keys + indent=2 + trailing-newline JSON for diff stability
      (D-27, mirrors backend/scripts/dump_openapi.py:29-31)"
    - "Compact JSON via json.dumps(separators=(',', ':')) for jq /
      curl --data pipelines (D-27)"
    - "typer.echo(..., nl=False) for stdout — preserves --compact's
      no-trailing-newline contract and bypasses rich's line-wrapping
      on long single-line JSON"
    - "Defensive record_type field-name lookup (record_type → type →
      dataset_type) — survives a future OpenAPI rename"
    - "404 sentinel via 'not_found' string return — keeps the
      caller's branching readable without raising-and-rescuing"
key-files:
  created:
    - cli/geolens_cli/export_stac.py
    - cli/tests/test_export_stac.py
    - .planning/phases/216-geolens-cli-mvp/216-05-SUMMARY.md
  modified:
    - cli/geolens_cli/main.py
key-decisions:
  - "DatasetResponse.record_type confirmed: snake_case `record_type: str
    | Unset`, default 'vector_dataset'. Other documented values:
    'raster_dataset', 'vrt_dataset', 'table', 'map', 'service',
    'collection'. The is_raster() helper matches the lower-cased prefix
    'raster' so 'raster_dataset', 'RasterDataset', 'vrt_dataset' (NOT
    matched — VRTs are out of scope per D-26), and bare 'raster' all
    behave correctly."
  - "get_item_stac return shape: SDK's _parse_response declares the 200
    body as `Any` (the OpenAPI schema is a free-form dict). resp.parsed
    is therefore the STAC dict directly — no .to_dict() needed.
    fetch_stac_item still includes a defensive shape ladder (None →
    json.loads(content); has .to_dict() → call it; isinstance dict →
    return as-is) so a future SDK regen that wraps the body in a
    typed model doesn't silently break the command."
  - "Atomic file mode: 0o644 (NOT 0o600 like credentials.toml). STAC
    payloads are not secrets per D-27 + threat model T-216-08; the
    backend strips signed-URL credentials before emitting STAC items."
  - "404 sentinel: fetch_record_type returns the literal string
    'not_found' for HTTP 404 instead of raising. This keeps the
    caller's branching flat (`if record_type == 'not_found': ...
    if not is_raster(...): ...`) and matches the same pattern Plan 04
    uses for resolve_dataset_id."
  - "typer.echo(..., nl=False) on stdout: render_stac_json owns the
    trailing-newline policy (pretty has one, compact does not). echo
    with nl=False prevents Typer from adding a second newline that
    would corrupt jq pipelines."
  - "Test bug fix during GREEN: test_compact_single_line originally
    asserted `{\"a\":1,\"b\":2}` for input `{\"b\": 1, \"a\": 2}` —
    but sorted keys preserve VALUES, not swap them. Corrected to
    `{\"a\":2,\"b\":1}`."
requirements-completed:
  - OCCLI-05
metrics:
  duration_seconds: 240
  duration_human: "4m"
  completed_date: "2026-04-27"
  tasks_completed: 2
  tests_passing: 112
  tests_added: 20
  files_created: 3
  files_modified: 1
---

# Phase 216 Plan 05: export-stac-command Summary

## One-liner

Implemented `geolens export stac <dataset-id>` as a thin SDK pass-through
with a raster-only pre-flight guard, atomic file output, and `--compact`
mode for jq pipelines — closing OCCLI-05 with 20 new unit tests and the
OCCLI-06 invariant intact.

## What shipped

### `cli/geolens_cli/export_stac.py` (NEW)

Module surface (six exports, all pure functions over a passed-in SDK
client, no global state):

| Symbol | Purpose |
| --- | --- |
| `fetch_record_type(client, dataset_id) -> str` | D-26 pre-flight: GET /datasets/{id}; returns `"not_found"` on 404, the dataset's `record_type` string otherwise. Other non-200 statuses route through `unwrap()` for the standard auth/server/generic exit-code mapping. |
| `is_raster(record_type) -> bool` | Defensive raster classifier. Lower-cases input then checks `.startswith("raster")` — accepts `raster_dataset`, `RasterDataset`, `raster`, etc. Rejects empty, `vector_dataset`, `collection`, `unknown`. |
| `fetch_stac_item(client, dataset_id) -> dict` | D-25 SDK pass-through: GET /stac/items/{id}, unwrap with expected=200, return the STAC dict. Defensive shape ladder (None → json-load content; has `.to_dict()` → call it; dict → return) for forward-compat. |
| `render_stac_json(item, *, compact) -> str` | D-27 formatter. Default: pretty (indent=2, sorted keys, trailing newline) for diff stability. Compact: single-line with `(',', ':')` separators, no trailing newline. |
| `write_stac_to_file(item, path, *, compact) -> None` | D-27 atomic write via `config.atomic_write_text(...)` at mode 0o644. Tempfile + os.replace prevents half-written files on Ctrl+C. |
| `vector_rejection_message(record_type) -> str` | D-26 user-facing rejection text: `"STAC export is supported for raster datasets only — got record_type=<type>"`. |

### `cli/geolens_cli/main.py` (MODIFIED)

Replaced the Plan 01 stub on `export_app.command("stac")` with the real
command body:

1. **Pre-flight** — `fetch_record_type` → branch:
   - `"not_found"` → `state.output.error("Dataset not found: ...")`,
     exit 1 (`EXIT_GENERIC`).
   - non-raster → `state.output.error(vector_rejection_message(...))`,
     exit 2 (`EXIT_USAGE`).
2. **Fetch** — `fetch_stac_item(sdk.client, dataset_id)`.
3. **Emit**:
   - `-o FILE` → `write_stac_to_file(...)` + `state.output.success(...)`.
   - default → `typer.echo(render_stac_json(...), nl=False)` so the
     newline policy is owned by the renderer (pretty has one, compact
     has none).

Imports added: `from . import export_stac as _export_stac`, `EXIT_USAGE`.

### `cli/tests/test_export_stac.py` (NEW)

20 unit tests across 5 classes (1 skip on Windows for the POSIX-only
file-mode assertion):

| Class | Tests | Coverage |
| --- | --- | --- |
| `TestRenderStacJson` | 4 | pretty (indent=2, sorted keys); compact (single-line); pretty trailing newline; compact no trailing newline |
| `TestIsRaster` | 7 (parametrized) | raster_dataset, RasterDataset, raster (True); vector_dataset, collection, "", unknown (False) |
| `TestVectorRejectionMessage` | 1 | message contains "raster" + the offending record_type |
| `TestWriteStacToFile` | 3 | mode 0o644 (POSIX skip on Windows); pretty content round-trip; compact content round-trip |
| `TestExportStacCli` | 5 | raster pass-through to stdout; vector rejection exit 2; not-found exit 1; -o atomic file write; --compact single-line |

All 5 CLI tests use the shared `runner` / `tmp_xdg_home` / `mock_keyring`
fixtures from `cli/tests/conftest.py` plus an inline `_seed_login` helper
(mirrors Plan 04's pattern).

## Confirmed shapes (RESEARCH follow-up)

The plan's `<output>` block asked for two empirical confirmations:

1. **`record_type` field name in DatasetResponse**: confirmed as
   `record_type` (snake_case `str | Unset`, default `'vector_dataset'`).
   See `sdks/python/geolens_sdk/models/dataset_response.py:67-70`.
2. **`get_item_stac` return shape**: the SDK's `_parse_response`
   declares the 200 body as `Any` (literal: `response_200 =
   response.json()`). `resp.parsed` is the STAC dict directly — no
   `.to_dict()` call needed. The defensive shape ladder in
   `fetch_stac_item` covers a future SDK regen that wraps it in a
   typed model.

## OCCLI-06 invariant proof

```
$ rg -E '^(import|from) (httpx|requests)' cli/geolens_cli/
(no matches)
```

Zero direct httpx/requests imports across the entire `geolens_cli`
package. All HTTP traffic flows through the generated SDK functions.

## Verification results

| Gate | Command | Result |
| --- | --- | --- |
| Plan-05 test slice | `cd cli && .venv/bin/python -m pytest tests/test_export_stac.py` | 20/20 PASS |
| Full CLI suite | `cd cli && .venv/bin/python -m pytest -v` | 112/112 PASS |
| OCCLI-06 grep gate | `! rg -E '^(import\|from) (httpx\|requests)' cli/geolens_cli/` | clean |
| Module surface sanity | `.venv/bin/python -c "from geolens_cli.export_stac import ..."` | OK |
| Pretty/compact rendering | inline `<verify>` blocks | OK |
| `geolens export stac --help` | rendered cleanly with two flags + arg | OK |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test assertion expected wrong sorted-keys output**

- **Found during:** Task 1 GREEN
- **Issue:** `test_compact_single_line` asserted
  `render_stac_json({"b": 1, "a": 2}, compact=True) == '{"a":1,"b":2}'`,
  but `json.dumps(..., sort_keys=True)` sorts KEYS, it doesn't swap
  VALUES. The actual (correct) output is `{"a":2,"b":1}` (key `a` with
  value `2`, key `b` with value `1`).
- **Fix:** Updated the expected value to `{"a":2,"b":1}` and added a
  comment explaining the sort semantics. The plan's `<verify>` block
  had the same incorrect assertion (line 277), so this is a transcription
  bug carried from the plan into the test.
- **Files modified:** `cli/tests/test_export_stac.py:59`
- **Commit:** `111f1b9b` (folded into the Task 1 GREEN commit)

### No other deviations

- No architectural changes (Rule 4) needed.
- No missing functionality (Rule 2) found — pre-flight + atomic write +
  defensive shape handling were all in the plan.
- No blocking issues (Rule 3) hit. The CLI's existing `.venv` already
  had `geolens_sdk` linked (the package is sourced from
  `sdks/python/geolens_sdk/` via the workspace setup), so tests ran
  cleanly via `.venv/bin/python -m pytest` (`uv run` would re-resolve
  and fail because `geolens-sdk` isn't published to PyPI yet — same
  pattern Plans 02-04 used).

### Authentication gates

None. No interactive auth was required during execution; all tests use
mocked `fetch_record_type` / `fetch_stac_item` so the SDK never actually
issues HTTP requests.

## TDD Gate Compliance

| Gate | Commit | Behavior |
| --- | --- | --- |
| RED | `3bd1dc41 test(216-05): add failing tests for export_stac module + CLI command` | 20 tests fail with `ImportError: No module named 'geolens_cli.export_stac'` |
| GREEN (Task 1) | `111f1b9b feat(216-05): implement export_stac.py — vector guard + STAC fetch + atomic write` | 15 of 20 pass (the 5 CLI tests still fail because main.py is unwired) |
| GREEN (Task 2) | `8b0344ab feat(216-05): wire export stac command + retire Plan 01 stub` | 20/20 pass; full CLI suite 112/112 |

No REFACTOR commit — the implementation matched the plan's `<action>`
template closely enough that no follow-up cleanup was warranted.

## Self-Check: PASSED

- `cli/geolens_cli/export_stac.py` — FOUND
- `cli/tests/test_export_stac.py` — FOUND
- `cli/geolens_cli/main.py` — FOUND (modified)
- Commit `3bd1dc41` (RED) — FOUND in git log
- Commit `111f1b9b` (Task 1 GREEN) — FOUND in git log
- Commit `8b0344ab` (Task 2 GREEN) — FOUND in git log
- All 20 export_stac tests pass; full CLI suite 112/112
- OCCLI-06 grep gate clean
