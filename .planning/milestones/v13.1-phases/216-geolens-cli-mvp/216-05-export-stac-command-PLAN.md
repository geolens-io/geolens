---
phase: 216-geolens-cli-mvp
plan: 05
type: execute
wave: 3
depends_on: [02]
files_modified:
  - cli/geolens_cli/export_stac.py
  - cli/geolens_cli/main.py
  - cli/tests/test_export_stac.py
files_read:
  - cli/geolens_cli/auth.py
  - cli/geolens_cli/config.py
  - cli/geolens_cli/_sdk_helpers.py
  - sdks/python/geolens_sdk/api/datasets/get_single_dataset_datasets_dataset_id_get.py
  - sdks/python/geolens_sdk/api/stac/get_item_stac_items_item_id_get.py
  - backend/scripts/dump_openapi.py
autonomous: true
requirements:
  - OCCLI-05
must_haves:
  decisions_covered:
    - "D-25: Source endpoint GET /stac/items/{dataset_id} via SDK get_item_stac_items_item_id_get (thin pass-through; backend already emits STAC 1.1)"
    - "D-26: Vector/collection guard — pre-flight GET /datasets/{id} record_type check; non-raster → exit 2 with clear message"
    - "D-27: Output — pretty-printed JSON to stdout default; -o FILE atomic tempfile+os.replace; --compact for jq pipelines"
    - "D-28: No client-side STAC validation — backend already produces conformant STAC 1.1 (avoid pystac dep)"
  truths:
    - "`geolens export stac <dataset-id>` calls GET /stac/items/{dataset_id} via the SDK and prints valid STAC 1.1 JSON to stdout (pretty-printed, 2-space indent, sorted keys)"
    - "Pre-flight check: CLI calls GET /datasets/{id} first; if `record_type` is not raster, prints 'STAC export is supported for raster datasets only — got record_type=<type>' and exits with EXIT_USAGE (2) per D-26"
    - "`-o FILE` / `--output FILE` writes to the file atomically (tempfile + os.replace) using `config.atomic_write_text` so Ctrl+C cannot leave a half-written file"
    - "`--compact` emits single-line JSON (no whitespace) for piping to jq / curl --data"
    - "Default output is pretty-printed JSON to stdout; STAC payload is forwarded as-is from the backend (no client-side schema validation per D-28)"
    - "On 404 from /stac/items/{id}, exits with EXIT_GENERIC (1) and prints 'Dataset not found: <id>'"
    - "export_stac.py imports zero direct `httpx` or `requests` modules — every HTTP call goes through the SDK"
  artifacts:
    - path: cli/geolens_cli/export_stac.py
      provides: "fetch_record_type(client, dataset_id); fetch_stac_item(client, dataset_id); render_stac_json(item, *, compact); write_stac_to_file(item, path, *, compact)"
    - path: cli/geolens_cli/main.py
      provides: "real `export stac` command body replacing the Plan 01 stub; sub-app registered at the export top level"
    - path: cli/tests/test_export_stac.py
      provides: "raster pass-through test; vector rejection test; -o file atomic write test; --compact test; 404 test"
  key_links:
    - from: "cli/geolens_cli/main.py export_stac"
      to: "geolens_sdk.api.datasets.get_single_dataset_datasets_dataset_id_get"
      via: "AppState.sdk() → call_sdk(get_single_dataset.sync_detailed) → check record_type"
      pattern: "get_single_dataset_datasets_dataset_id_get"
    - from: "cli/geolens_cli/main.py export_stac"
      to: "geolens_sdk.api.stac.get_item_stac_items_item_id_get"
      via: "call_sdk(get_item_stac.sync_detailed) → render JSON"
      pattern: "get_item_stac_items_item_id_get"
    - from: "cli/geolens_cli/export_stac.py write_stac_to_file"
      to: "cli/geolens_cli/config.atomic_write_text"
      via: "tempfile + chmod + os.replace (mode 0644 — STAC files are not secrets)"
      pattern: "atomic_write_text"
---

<objective>
Implement the `geolens export stac <dataset-id>` command — a thin SDK pass-through that fetches a STAC 1.1 item for a raster dataset and writes it to stdout (or a file via `-o`). Closes OCCLI-05.

Purpose: Give end users a one-shot way to export STAC metadata for a raster dataset without hitting the API directly. The CLI is intentionally a pretty-printer — the backend already produces conformant STAC 1.1 (per D-25, D-28). The vector-guard pre-flight (D-26) prevents confusing errors when users try to export STAC for a vector dataset.

Output: Working `geolens export stac <id>` command with stdout, `-o FILE`, and `--compact` modes; mocked unit tests covering pass-through, vector rejection, atomic-write, and 404 handling.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/216-geolens-cli-mvp/216-CONTEXT.md
@.planning/phases/216-geolens-cli-mvp/216-RESEARCH.md
@.planning/phases/216-geolens-cli-mvp/216-PATTERNS.md
@.planning/phases/216-geolens-cli-mvp/216-VALIDATION.md
@.planning/phases/216-geolens-cli-mvp/216-02-auth-and-config-PLAN.md
@backend/scripts/dump_openapi.py

<interfaces>
<!-- Plan 01 / 02 surfaces this plan consumes -->

From cli/geolens_cli/main.py (Plan 02 — AppState):
```python
class AppState:
    output: Formatter
    config: AppConfig
    json_mode: bool
    def active_instance() -> Optional[str]
    def sdk() -> GeolensClient
```

From cli/geolens_cli/_sdk_helpers.py (Plan 01):
```python
unwrap(resp, *, expected: int = 200) -> T
call_sdk(fn, **kwargs) -> Response
EXIT_AUTH=3, EXIT_USAGE=2, EXIT_GENERIC=1, EXIT_SERVER=5
```

From cli/geolens_cli/config.py (Plan 02):
```python
atomic_write_text(path: Path, content: str, *, mode: int = 0o600) -> None
```

<!-- SDK surface this plan calls -->

From geolens_sdk.api.datasets:
```python
from geolens_sdk.api.datasets import get_single_dataset_datasets_dataset_id_get
# Returns Response[Union[DatasetResponse, ProblemDetail]]
# Used for the record_type pre-flight check (D-26)
# Field of interest: parsed.record_type (e.g., "raster_dataset", "vector_dataset")
```

From geolens_sdk.api.stac:
```python
from geolens_sdk.api.stac import get_item_stac_items_item_id_get
# Returns Response[Union[T, ProblemDetail]] — backend emits STAC 1.1 JSON
# The parsed body should be the STAC item dict OR a structured model
```

The executor MUST inspect:
1. sdks/python/geolens_sdk/api/datasets/get_single_dataset_datasets_dataset_id_get.py — confirm function name, status codes, parsed response shape (DatasetResponse model?)
2. sdks/python/geolens_sdk/api/stac/get_item_stac_items_item_id_get.py — confirm function name, status codes, and parsed response model (likely a generated model whose `.to_dict()` returns the STAC dict)
3. sdks/python/geolens_sdk/models/ — find DatasetResponse to confirm `record_type` field name (might be `record_type`, `type`, or `dataset_type`)

The output MUST be the STAC dict — call `.to_dict()` on the parsed model if it's a generated attrs class, or json-load the raw response content if needed.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Implement export_stac.py — vector guard, STAC fetch, render, atomic file write</name>
  <files>cli/geolens_cli/export_stac.py</files>
  <read_first>
    - sdks/python/geolens_sdk/api/datasets/get_single_dataset_datasets_dataset_id_get.py (verify function signature, status codes)
    - sdks/python/geolens_sdk/api/stac/get_item_stac_items_item_id_get.py (verify function signature, status codes, response shape)
    - sdks/python/geolens_sdk/models/ (find DatasetResponse — look for `record_type` field name; if file is auto-generated, the field will be a snake_case attribute)
    - .planning/phases/216-geolens-cli-mvp/216-RESEARCH.md (Pattern 4 atomic_write_text — already in config.py from Plan 02; Pitfall 5 — vector guard with cited operationId)
    - .planning/phases/216-geolens-cli-mvp/216-PATTERNS.md (§`cli/geolens_cli/export_stac.py` — atomic-write + sorted keys + pretty-printed)
    - .planning/phases/216-geolens-cli-mvp/216-CONTEXT.md (D-25, D-26, D-27, D-28 — pass-through, vector guard, output format, no client-side validation)
    - backend/scripts/dump_openapi.py (lines 29-31 — pretty-printed JSON pattern: indent=2, sort_keys=True, trailing newline)
    - cli/geolens_cli/config.py (Plan 02 — atomic_write_text)
  </read_first>
  <behavior>
    - `fetch_record_type(client, dataset_id) -> str` calls `get_single_dataset` and returns the dataset's `record_type` (e.g., "raster_dataset", "vector_dataset"); on 404 returns the literal string "not_found"
    - `is_raster(record_type) -> bool` returns True iff `record_type` starts with "raster" (defensive: backend may use `raster_dataset`, `RasterDataset`, etc.)
    - `fetch_stac_item(client, dataset_id) -> dict` calls `get_item_stac_items_item_id_get`, unwraps with expected=200, and returns the STAC item as a Python dict. If the parsed model has `.to_dict()` (attrs-generated), use it; otherwise json-load `resp.content`
    - `render_stac_json(item: dict, *, compact: bool = False) -> str` returns the formatted JSON: `json.dumps(item, indent=2 if not compact else None, sort_keys=True, separators=(',', ':') if compact else None) + ("\n" if not compact else "")`
    - `write_stac_to_file(item: dict, path: Path, *, compact: bool = False) -> None` calls `atomic_write_text(path, render_stac_json(item, compact=compact), mode=0o644)` — STAC files are not secrets, but atomic write prevents half-written files on Ctrl+C
  </behavior>
  <action>
    Create `cli/geolens_cli/export_stac.py`:
    ```python
    """STAC export — fetch a STAC 1.1 item for a raster dataset and render it.

    Hand-maintained — NOT regenerated. Pure SDK pass-through (D-25, D-28). The
    backend at `backend/app/standards/stac/router.py` already produces
    conformant STAC 1.1; the CLI is a pretty-printer. Vector datasets are
    rejected pre-flight (D-26) so users see a clear message rather than a
    confusing 404 or 422.
    """
    from __future__ import annotations

    import json
    from pathlib import Path
    from typing import Any

    from . import config as _config
    from ._sdk_helpers import EXIT_USAGE, call_sdk, unwrap


    def fetch_record_type(client: Any, dataset_id: str) -> str:
        """Pre-flight check: return the dataset's record_type, or 'not_found' on 404.

        Per D-26: STAC export is raster-only. We GET /datasets/{id} first to
        avoid a confusing error from /stac/items/{id} when the dataset is
        vector-typed.
        """
        from geolens_sdk.api.datasets import get_single_dataset_datasets_dataset_id_get

        resp = call_sdk(
            get_single_dataset_datasets_dataset_id_get.sync_detailed,
            dataset_id=dataset_id,
            client=client,
        )
        sc = int(resp.status_code)
        if sc == 404:
            return "not_found"
        if sc != 200:
            # Let unwrap() translate the error → exit code
            unwrap(resp, expected=200)
        rec = getattr(resp.parsed, "record_type", None)
        if rec is None:
            # Defensive: try alternate field names if the OpenAPI shape changes
            rec = getattr(resp.parsed, "type", None) or getattr(resp.parsed, "dataset_type", None)
        return str(rec) if rec else "unknown"


    def is_raster(record_type: str) -> bool:
        """True iff record_type looks like a raster dataset."""
        if not record_type:
            return False
        return record_type.lower().startswith("raster")


    def fetch_stac_item(client: Any, dataset_id: str) -> dict:
        """Fetch the STAC item dict for a dataset. Caller pre-checks record_type."""
        from geolens_sdk.api.stac import get_item_stac_items_item_id_get

        resp = call_sdk(
            get_item_stac_items_item_id_get.sync_detailed,
            item_id=dataset_id,
            client=client,
        )
        item = unwrap(resp, expected=200)
        # The SDK may return either:
        # (a) a generated attrs model with .to_dict() — call it
        # (b) a raw dict — return as-is
        # (c) None (parsed=None when the schema couldn't be matched) — fall back
        #     to JSON-loading the raw response content
        if item is None:
            return json.loads(resp.content.decode("utf-8"))
        if hasattr(item, "to_dict"):
            return item.to_dict()
        if isinstance(item, dict):
            return item
        # Unknown shape — best-effort serialize via __dict__
        return dict(item.__dict__) if hasattr(item, "__dict__") else json.loads(resp.content.decode("utf-8"))


    def render_stac_json(item: dict, *, compact: bool = False) -> str:
        """Format a STAC dict as JSON.

        Default: pretty-printed (indent=2, sorted keys, trailing newline) for
        diff stability per D-27.
        Compact: single-line JSON for piping to jq / curl --data.
        """
        if compact:
            return json.dumps(item, sort_keys=True, separators=(",", ":"))
        return json.dumps(item, indent=2, sort_keys=True) + "\n"


    def write_stac_to_file(item: dict, path: Path, *, compact: bool = False) -> None:
        """Atomic write of the rendered STAC JSON to `path`.

        Mode 0o644 — STAC files are not secrets. The atomic write prevents
        half-written files on Ctrl+C (per D-27).
        """
        _config.atomic_write_text(path, render_stac_json(item, compact=compact), mode=0o644)


    def vector_rejection_message(record_type: str) -> str:
        return (
            f"STAC export is supported for raster datasets only — got record_type={record_type}"
        )
    ```

    Notes for the executor:
    1. The `record_type` field name might differ in the actual generated `DatasetResponse` model. The defensive lookup chain (`record_type` → `type` → `dataset_type`) handles common variants. After Task 1, run `grep -E "record_type|^    type:|^    dataset_type:" sdks/python/geolens_sdk/models/dataset_response*.py` (or the actual model file) to confirm the field name; pin it explicitly if there's only one.
    2. If the SDK's generated `get_item_stac` function returns a strongly-typed model (e.g., `STACItem`), `.to_dict()` is the right call. If it returns `Any` / `None`, the JSON-load-from-`resp.content` fallback is the safe default.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/cli && uv run python -c "from geolens_cli.export_stac import fetch_record_type, fetch_stac_item, render_stac_json, write_stac_to_file, is_raster, vector_rejection_message; assert is_raster('raster_dataset'); assert is_raster('RasterDataset'); assert not is_raster('vector_dataset'); assert not is_raster(''); print(render_stac_json({'a': 1, 'b': [2, 3]})); print('OK')"</automated>
    <automated>cd /Users/ishiland/Code/geolens/cli && uv run python -c "
from geolens_cli.export_stac import render_stac_json
# Pretty
out = render_stac_json({'b': 1, 'a': 2})
assert out.startswith('{\n'), out
assert out.endswith('\n'), repr(out)
assert '\"a\": 2' in out and '\"b\": 1' in out
# Compact
out_c = render_stac_json({'b': 1, 'a': 2}, compact=True)
assert out_c == '{\"a\":2,\"b\":1}', out_c
print('OK')
"</automated>
    <automated>! grep -rE '^(import|from) (httpx|requests)' /Users/ishiland/Code/geolens/cli/geolens_cli/export_stac.py</automated>
  </verify>
  <acceptance_criteria>
    - cli/geolens_cli/export_stac.py exports `fetch_record_type`, `is_raster`, `fetch_stac_item`, `render_stac_json`, `write_stac_to_file`, `vector_rejection_message`
    - `is_raster("raster_dataset")` returns True; `is_raster("vector_dataset")` returns False; `is_raster("")` returns False
    - `render_stac_json({"b": 1, "a": 2})` returns `'{\n  "a": 1,\n  "b": 2\n}\n'` shape (sorted keys, indent=2, trailing newline)
    - `render_stac_json({...}, compact=True)` returns single-line JSON with `,` and `:` separators (no spaces)
    - `write_stac_to_file` calls `_config.atomic_write_text(...)` with `mode=0o644`
    - Zero `^(import|from) (httpx|requests)` lines in export_stac.py
  </acceptance_criteria>
  <done>export_stac.py module exposes the full pre-flight + fetch + render + atomic-write surface. Sorted-keys + indent=2 + trailing newline produce diff-stable output (D-27). The atomic write uses Plan 02's config helper.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Wire `export stac` command + add unit tests</name>
  <files>cli/geolens_cli/main.py, cli/tests/test_export_stac.py</files>
  <read_first>
    - cli/geolens_cli/main.py (Plan 01/02 — current `export_stac` stub on `export_app`)
    - cli/geolens_cli/export_stac.py (Task 1 — the helpers)
    - .planning/phases/216-geolens-cli-mvp/216-VALIDATION.md (test_export_stac.py expectations: raster pass-through, vector rejected, output file)
    - .planning/phases/216-geolens-cli-mvp/216-CONTEXT.md (D-26 — vector exits 2; D-27 — output flags)
  </read_first>
  <behavior>
    - `geolens export stac <dataset-id>` writes pretty-printed STAC JSON to stdout
    - `-o FILE` / `--output FILE` writes to the file (atomically); also prints a success message to stderr
    - `--compact` emits single-line JSON
    - On vector dataset: prints `vector_rejection_message(record_type)` to stderr and exits with EXIT_USAGE (2)
    - On 404 from /datasets/{id}: prints `Dataset not found: <id>` and exits EXIT_GENERIC (1)
    - In `--json` mode (global flag), the STAC payload is wrapped as `{dataset_id, record_type, stac_item}` — but per D-27 the default is to emit STAC directly; revisit if it conflicts with the global --json flag
  </behavior>
  <action>
    Modify `cli/geolens_cli/main.py` — replace the Plan 01 `export_stac` stub. Update imports near the top to add:
    ```python
    from . import export_stac as _export_stac
    from ._sdk_helpers import EXIT_GENERIC, EXIT_USAGE
    ```

    Replace the export_stac function body:
    ```python
    @export_app.command("stac")
    def export_stac(
        ctx: typer.Context,
        dataset_id: Annotated[str, typer.Argument(help="Dataset id")],
        output: Annotated[Optional[Path], typer.Option("-o", "--output", help="Write STAC JSON to FILE (default: stdout)")] = None,
        compact: Annotated[bool, typer.Option("--compact", help="Single-line JSON for piping")] = False,
    ) -> None:
        """Export STAC 1.1 metadata for a raster dataset."""
        state: AppState = ctx.obj
        sdk = state.sdk()

        # Pre-flight: verify the dataset is a raster
        record_type = _export_stac.fetch_record_type(sdk.client, dataset_id)
        if record_type == "not_found":
            state.output.error(f"Dataset not found: {dataset_id}")
            raise typer.Exit(EXIT_GENERIC)
        if not _export_stac.is_raster(record_type):
            state.output.error(_export_stac.vector_rejection_message(record_type))
            raise typer.Exit(EXIT_USAGE)

        # Fetch the STAC item
        stac_item = _export_stac.fetch_stac_item(sdk.client, dataset_id)

        # Render & emit
        if output is not None:
            _export_stac.write_stac_to_file(stac_item, output, compact=compact)
            state.output.success(f"Wrote STAC item to {output}")
        else:
            # Direct stdout — use typer.echo to avoid rich's line-wrap on long lines
            typer.echo(_export_stac.render_stac_json(stac_item, compact=compact), nl=False)
    ```

    Note: when `output` is None and `--compact` is set, the JSON is emitted with no trailing newline (per `render_stac_json` semantics), so piping into `jq` or `curl --data @-` works without extra newlines breaking parsers. When pretty-printed (default), the trailing newline is present. We use `typer.echo(..., nl=False)` to avoid double-newline.

    Create `cli/tests/test_export_stac.py`:
    ```python
    """OCCLI-05: export stac unit tests with mocked SDK."""
    from __future__ import annotations

    import json
    import os
    import stat
    from http import HTTPStatus
    from pathlib import Path
    from unittest.mock import MagicMock

    import pytest

    from geolens_cli import export_stac as _export_stac
    from geolens_cli.main import app


    SAMPLE_STAC = {
        "type": "Feature",
        "stac_version": "1.1.0",
        "id": "ds-1",
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
        "properties": {"datetime": "2026-04-27T00:00:00Z"},
        "assets": {},
        "links": [],
    }


    class TestRenderStacJson:
        def test_pretty_indent_2_sorted_keys(self) -> None:
            out = _export_stac.render_stac_json({"b": 1, "a": 2})
            assert out.startswith("{\n")
            assert out.endswith("\n")
            # Sorted keys: "a" appears before "b"
            assert out.index('"a":') < out.index('"b":')
            # Indent of 2 spaces
            assert '\n  "a"' in out

        def test_compact_single_line(self) -> None:
            out = _export_stac.render_stac_json({"b": 1, "a": 2}, compact=True)
            assert out == '{"a":1,"b":2}'

        def test_pretty_emits_trailing_newline(self) -> None:
            out = _export_stac.render_stac_json({"a": 1})
            assert out.endswith("\n")

        def test_compact_no_trailing_newline(self) -> None:
            out = _export_stac.render_stac_json({"a": 1}, compact=True)
            assert not out.endswith("\n")


    class TestIsRaster:
        @pytest.mark.parametrize("rt,expected", [
            ("raster_dataset", True),
            ("RasterDataset", True),
            ("raster", True),
            ("vector_dataset", False),
            ("collection", False),
            ("", False),
            ("unknown", False),
        ])
        def test_classification(self, rt, expected) -> None:
            assert _export_stac.is_raster(rt) is expected


    class TestVectorRejectionMessage:
        def test_includes_record_type(self) -> None:
            msg = _export_stac.vector_rejection_message("vector_dataset")
            assert "raster" in msg.lower()
            assert "vector_dataset" in msg


    class TestWriteStacToFile:
        @pytest.mark.skipif(os.name == "nt", reason="POSIX file modes only")
        def test_writes_with_mode_0644(self, tmp_path: Path) -> None:
            target = tmp_path / "out.stac.json"
            _export_stac.write_stac_to_file(SAMPLE_STAC, target)
            actual = stat.S_IMODE(target.stat().st_mode)
            assert actual == 0o644, f"got {oct(actual)}"

        def test_pretty_content(self, tmp_path: Path) -> None:
            target = tmp_path / "out.stac.json"
            _export_stac.write_stac_to_file(SAMPLE_STAC, target)
            text = target.read_text()
            payload = json.loads(text)
            assert payload["id"] == "ds-1"
            assert text.startswith("{\n")
            assert text.endswith("\n")

        def test_compact_content(self, tmp_path: Path) -> None:
            target = tmp_path / "out.stac.json"
            _export_stac.write_stac_to_file(SAMPLE_STAC, target, compact=True)
            text = target.read_text()
            assert "\n" not in text
            json.loads(text)  # must still parse


    class TestExportStacCli:
        @pytest.fixture
        def login_state(self, tmp_xdg_home, mock_keyring):
            from geolens_cli import auth as _auth
            from geolens_cli import config as _config
            instance = "https://x.example.com"
            mock_keyring[("geolens", instance)] = "tok-abc"
            _config.write_default_instance(instance, username="alice")
            return instance

        def test_raster_pass_through_to_stdout(self, runner, login_state, monkeypatch) -> None:
            # Mock fetch_record_type → "raster_dataset"
            monkeypatch.setattr(
                "geolens_cli.export_stac.fetch_record_type",
                lambda c, did: "raster_dataset",
            )
            monkeypatch.setattr(
                "geolens_cli.export_stac.fetch_stac_item",
                lambda c, did: SAMPLE_STAC,
            )
            result = runner.invoke(app, ["export", "stac", "ds-1"])
            assert result.exit_code == 0, result.output
            payload = json.loads(result.output)
            assert payload["id"] == "ds-1"
            assert payload["stac_version"] == "1.1.0"

        def test_vector_rejected_with_exit_2(self, runner, login_state, monkeypatch) -> None:
            monkeypatch.setattr(
                "geolens_cli.export_stac.fetch_record_type",
                lambda c, did: "vector_dataset",
            )
            result = runner.invoke(app, ["export", "stac", "ds-1"])
            assert result.exit_code == 2, result.output
            assert "raster" in (result.output + result.stderr).lower() if hasattr(result, "stderr") else "raster" in result.output.lower()

        def test_not_found_exits_generic(self, runner, login_state, monkeypatch) -> None:
            monkeypatch.setattr(
                "geolens_cli.export_stac.fetch_record_type",
                lambda c, did: "not_found",
            )
            result = runner.invoke(app, ["export", "stac", "missing"])
            assert result.exit_code == 1, result.output
            assert "not found" in result.output.lower()

        def test_output_file_atomic_write(self, runner, login_state, monkeypatch, tmp_path) -> None:
            monkeypatch.setattr(
                "geolens_cli.export_stac.fetch_record_type",
                lambda c, did: "raster_dataset",
            )
            monkeypatch.setattr(
                "geolens_cli.export_stac.fetch_stac_item",
                lambda c, did: SAMPLE_STAC,
            )
            target = tmp_path / "ds-1.stac.json"
            result = runner.invoke(app, ["export", "stac", "ds-1", "-o", str(target)])
            assert result.exit_code == 0, result.output
            assert target.is_file()
            payload = json.loads(target.read_text())
            assert payload["id"] == "ds-1"

        def test_compact_flag_emits_single_line(self, runner, login_state, monkeypatch) -> None:
            monkeypatch.setattr(
                "geolens_cli.export_stac.fetch_record_type",
                lambda c, did: "raster_dataset",
            )
            monkeypatch.setattr(
                "geolens_cli.export_stac.fetch_stac_item",
                lambda c, did: SAMPLE_STAC,
            )
            result = runner.invoke(app, ["export", "stac", "ds-1", "--compact"])
            assert result.exit_code == 0, result.output
            # Compact JSON has no internal newlines
            stripped = result.output.rstrip("\n")
            assert "\n" not in stripped
            json.loads(stripped)
    ```
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/cli && uv run pytest tests/test_export_stac.py -v 2>&1 | tail -40</automated>
    <automated>cd /Users/ishiland/Code/geolens/cli && uv run pytest -v 2>&1 | grep -E "(passed|failed)" | tail -5</automated>
    <automated>! grep -rE '^(import|from) (httpx|requests)' /Users/ishiland/Code/geolens/cli/geolens_cli/export_stac.py</automated>
  </verify>
  <acceptance_criteria>
    - cli/geolens_cli/main.py `export_stac` command body imports `_export_stac` and `EXIT_GENERIC`, `EXIT_USAGE`
    - The command calls `fetch_record_type` → branches on `not_found` (exit 1), non-raster (exit 2), then `fetch_stac_item` → renders/writes
    - test_export_stac.py contains TestRenderStacJson with ≥4 methods (pretty/compact/trailing-newline)
    - test_export_stac.py contains TestIsRaster parametrized over ≥7 cases
    - test_export_stac.py contains TestWriteStacToFile with ≥2 methods (mode + content)
    - test_export_stac.py contains TestExportStacCli with ≥5 methods (raster pass-through, vector rejected, not_found, output file, compact)
    - `cd cli && uv run pytest tests/test_export_stac.py -v` exits 0 with all tests passing (≥ 18 tests; 1 skipped on Windows for mode test)
    - Zero `^(import|from) (httpx|requests)` in export_stac.py
  </acceptance_criteria>
  <done>`geolens export stac <id>` works end-to-end against a mocked SDK. Vector datasets are rejected with a clear message and exit 2. Atomic file write prevents partial files on Ctrl+C. ≥18 unit tests pass. OCCLI-06 invariant intact (no httpx/requests imports in export_stac.py).</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| User-supplied dataset id | Free-text positional argument; backend validates the id format and rejects unknown ids |
| User-supplied output file path | `-o FILE` writes to a path the user chooses; atomic_write_text constrains to mode 0o644 (not 0o600 — STAC payloads aren't secrets) |
| CLI process → backend `/datasets/{id}` | Pre-flight GET; backend re-validates auth + visibility |
| CLI process → backend `/stac/items/{id}` | STAC fetch; backend authoritative for STAC 1.1 conformance |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-216-04 | Tampering | export_stac.py introducing a direct httpx import would break OCCLI-06 | mitigate | Acceptance criterion enforces zero `^(import|from) (httpx|requests)` lines in export_stac.py via grep. The command goes entirely through the SDK. Plan 06 closes the global CI grep gate. |
| T-216-02 | Spoofing / Replay | Stolen access token replayed against `/stac/items/{id}` to exfiltrate raster metadata | mitigate (inherited) | Inherited from Plan 02: 401 refresh-retry once via `try_refresh`; second 401 exits EXIT_AUTH (3). Raster metadata is the user's own data; access control is on the backend. |
| T-216-08 | Information Disclosure | `-o FILE` writing a STAC payload that contains sensitive metadata (e.g., asset URLs with embedded credentials) to a world-readable file | accept | Mode 0o644 means user-readable + group/other-readable. Backend's STAC items contain public metadata + signed URLs (which expire); embedding credentials in STAC items is a backend concern (D-28: backend produces conformant STAC). The CLI is a pretty-printer — secret-scrubbing is server-side. |

**Not Applicable in this plan:**
- T-216-01 (token-at-rest): Not applicable — export-stac does not write credentials; it only reads from `AppState.sdk()` (Plan 02). Plan 02 owns T-216-01.
- T-216-03 (file-content spoof): Not applicable — export-stac is download-only; no file uploads or content-type validation in this plan. Plans 03 (scan) and 04 (publish) own extension/MIME concerns.
- T-216-05 (token-in-shell-history): Not applicable — export-stac has no `--token` flag (auth via prior `geolens login`). Plan 02 owns the flag; Plan 06 docs/cli.md owns the user-facing warning.
</threat_model>

<verification>
- `cd cli && uv run pytest tests/test_export_stac.py -v` exits 0 with all tests passing
- `cd cli && uv run pytest -v` (full unit slice) still green (Plans 01 + 02 + 03 + 04 + 05 tests all pass)
- Grep gate clean: zero `^(import|from) (httpx|requests)` in export_stac.py
- Vector rejection produces EXIT_USAGE (2) per D-26
</verification>

<success_criteria>
- OCCLI-05 closed: `geolens export stac <id>` writes valid pretty-printed STAC 1.1 JSON to stdout (or `-o FILE`); vector rejection works; `--compact` emits single-line JSON
- Atomic write via `_config.atomic_write_text` prevents half-written files on Ctrl+C (D-27)
- OCCLI-06 invariant preserved: zero direct httpx/requests imports in export_stac.py
</success_criteria>

<output>
After completion, create `.planning/phases/216-geolens-cli-mvp/216-05-SUMMARY.md` capturing:
- Confirmed `record_type` field name in DatasetResponse
- Whether `get_item_stac` returns a typed model (calls `.to_dict()`) or raw JSON (json-loads `resp.content`)
- Test count and any deviations from RESEARCH
</output>
