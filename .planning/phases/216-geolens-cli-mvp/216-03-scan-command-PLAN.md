---
phase: 216-geolens-cli-mvp
plan: 03
type: execute
wave: 2
depends_on: [01]
files_modified:
  - cli/geolens_cli/scan.py
  - cli/geolens_cli/main.py
  - cli/tests/test_scan.py
files_read:
  - cli/geolens_cli/output.py
  - cli/geolens_cli/_sdk_helpers.py
  - cli/tests/conftest.py
  - backend/app/processing/ingest/constants.py
autonomous: true
requirements:
  - OCCLI-03
must_haves:
  decisions_covered:
    - "D-15: Extension-based detection only (allowlist subset of server-side puremagic-validated allowlist; CSV deferred unless --csv)"
    - "D-16: Walk semantics — recursive by default, --max-depth N caps recursion, symlink-loop visited-set, hidden files skipped"
    - "D-17: Output schema — rich table by default with --json for JSON array; exit 0 even on all-ingest:no (dry-run, not error)"
    - "D-18: Shapefile sibling-grouping — emit one row per .shp; required-siblings (.dbf/.shx) listed in JSON sidecar_files; missing → ingest:no with reason"
  truths:
    - "`geolens scan <dir>` walks a directory recursively, classifies each file by extension, and prints a table or JSON report"
    - "Vector formats detected: .geojson, .gpkg, .shp (with sibling-grouping for .dbf/.shx/.prj/.cpg)"
    - "Raster formats detected: .tif, .tiff (cog-candidate)"
    - "Shapefile sidecars (.dbf, .shx, .prj, .cpg, .qix, .sbn, .sbx) are grouped under their .shp parent — only one row per dataset"
    - "Missing required shapefile sidecars (.dbf, .shx) → `ingest: no, reason: \"missing required sidecar(s): ...\"`"
    - "`--json` emits a JSON array of `{path, format, ingest, reason, sidecar_files}` objects to stdout"
    - "`--max-depth N` caps recursion at N levels below root"
    - "Hidden directories (`.git`, `__pycache__`, `.venv`, `node_modules`, `.idea`, `.vscode`, dot-prefixed) are skipped by default"
    - "Symlink loops are detected via canonical-path visited-set and do not infinite-recurse"
    - "Scan command exits 0 even when every file is `ingest: no` (it's a dry-run report, not an error per D-17)"
    - "Scan command makes ZERO HTTP calls (pure local I/O — verified structurally; OCCLI-06 inherited from Plan 01 invariant)"
  artifacts:
    - path: cli/geolens_cli/scan.py
      provides: "ScanItem dataclass; walk() generator; format-detection allowlist; shapefile sibling-grouping; symlink-loop guard"
      contains: "ScanItem"
    - path: cli/geolens_cli/main.py
      provides: "real `scan` command body replacing the Plan 01 stub; --json + --max-depth + --include-ext flag wiring"
    - path: cli/tests/test_scan.py
      provides: "table-driven format classification + shapefile grouping + json output + max-depth + symlink loop tests"
  key_links:
    - from: "cli/geolens_cli/main.py scan"
      to: "cli/geolens_cli/scan.py walk()"
      via: "iterate ScanItem and render via Formatter"
      pattern: "scan\\.walk\\("
    - from: "cli/geolens_cli/scan.py allowlist"
      to: "backend/app/processing/ingest/constants.py"
      via: "extension allowlist subset (CONTEXT.md D-15: client allowlist is informational; server is the gate)"
      pattern: "VECTOR_EXTS|RASTER_EXTS"
---

<objective>
Implement the `geolens scan <dir>` command — a pure-local-I/O directory walker that classifies spatial files by extension, groups shapefile sidecars, and prints either a `rich.table.Table` or a JSON array. Closes OCCLI-03.

Purpose: Give end users a fast dry-run inventory before publishing. The scan is intentionally extension-only (no magic-byte verification client-side per D-15) — the server validates content on upload, so client-side spoofing is not a security concern. This command makes zero HTTP calls and therefore inherits OCCLI-06 trivially.

Output: Working `geolens scan <dir>` with table + JSON output, shapefile sibling-grouping, max-depth cap, symlink-loop protection, and ≥10 unit tests.
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
@.planning/phases/216-geolens-cli-mvp/216-01-scaffold-cli-package-PLAN.md

<interfaces>
<!-- Plan 01 surfaces this plan consumes -->

From cli/geolens_cli/output.py (Plan 01):
```python
class Formatter:
    json_mode: bool
    quiet: bool
    is_tty: bool
    success(msg), error(msg), info(msg), debug(msg), json(payload)
```

From cli/geolens_cli/_sdk_helpers.py (Plan 01):
```python
EXIT_OK = 0
EXIT_USAGE = 2
```

From cli/geolens_cli/main.py (Plan 01 / 02 — AppState shape after Plan 02 lands):
```python
@dataclass
class AppState:
    output: Formatter
    config: AppConfig
    json_mode: bool
    # ... (Plan 02 adds active_instance(), sdk())
```

NOTE: This plan can run in parallel with Plan 02 because `scan` does not need
an SDK client — it does pure filesystem I/O. The scan command body uses only
`ctx.obj.output` (always populated by the @app.callback() in main.py).

<!-- Server-side allowlist reference (from CONTEXT.md canonical_refs) -->

backend/app/processing/ingest/constants.py is the canonical extension allowlist on
the server. The CLI's allowlist (D-15) MUST be a subset — never claim ingest:yes
for an extension the server rejects. Read the file and reconcile if any
divergence exists.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Implement scan.py — walk, classify, group shapefile sidecars</name>
  <files>cli/geolens_cli/scan.py</files>
  <read_first>
    - .planning/phases/216-geolens-cli-mvp/216-RESEARCH.md (Example C lines 793-886 verbatim — the full walk/classify/group implementation; Standard Stack discussion of extension allowlist)
    - .planning/phases/216-geolens-cli-mvp/216-PATTERNS.md (§`cli/geolens_cli/scan.py` — "RESEARCH-driven, no in-repo analog")
    - .planning/phases/216-geolens-cli-mvp/216-CONTEXT.md (D-15 — extension allowlist + auxiliary skip list; D-16 — walk semantics, max-depth, hidden dirs, symlink loops; D-17 — output schema; D-18 — shapefile sibling grouping)
    - backend/app/processing/ingest/constants.py (canonical server allowlist — verify CLI is a subset)
  </read_first>
  <behavior>
    - Module exports: `ScanItem` dataclass (fields: `path: Path`, `format: str`, `ingest: bool`, `reason: str = ""`, `sidecar_files: list[Path] | None = None`)
    - Module exports: `walk(root: Path, *, max_depth: int | None = None, include_exts: set[str] | None = None) -> Iterator[ScanItem]`
    - `VECTOR_EXTS = {".geojson", ".gpkg", ".shp"}` (csv excluded for MVP per D-15)
    - `RASTER_EXTS = {".tif", ".tiff"}`
    - `SHAPEFILE_REQUIRED_SIDECARS = {".dbf", ".shx"}` (.prj is recommended-but-optional per gdal/ogr semantics; document in code comment)
    - `SHAPEFILE_OPTIONAL_SIDECARS = {".prj", ".cpg", ".qix", ".sbn", ".sbx"}`
    - `RASTER_OPTIONAL_SIDECARS = {".aux.xml", ".ovr", ".tfw"}`
    - `HIDDEN_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".idea", ".vscode", ".pytest_cache", ".ruff_cache"}`
    - Shapefile sibling-grouping: when a `.shp` is found, only one ScanItem is yielded with `path=<the .shp>` and `sidecar_files=<list of grouped sidecars>`; missing required → ingest=False with reason
    - Walk yields items in deterministic order (sorted by path) for testability
    - Symlink loops via `visited: set[Path]` keyed on canonical (resolved) paths — already-visited paths are skipped
    - `_looks_like_geojson(path)` peek-reads up to 1024 bytes; returns True if the file starts with `{` (after lstrip) and contains `"type"` in the first 200 bytes
  </behavior>
  <action>
    Create `cli/geolens_cli/scan.py` (per RESEARCH Example C lines 793-886 verbatim with the docstring marker added):
    ```python
    """Filesystem scan + format detection — pure local I/O, no HTTP.

    Hand-maintained — NOT regenerated. Detection is extension-only per
    CONTEXT.md D-15; the server re-validates content via puremagic on upload,
    so client-side spoofing is not a security concern. This module makes ZERO
    HTTP calls and therefore inherits OCCLI-06 trivially.

    Allowlist is a subset of backend/app/processing/ingest/constants.py — if
    a future regen of that file adds new types, mirror them here.
    """
    from __future__ import annotations

    from dataclasses import dataclass
    from pathlib import Path
    from typing import Iterator, Optional

    VECTOR_EXTS = {".geojson", ".gpkg", ".shp"}
    RASTER_EXTS = {".tif", ".tiff"}
    SHAPEFILE_REQUIRED_SIDECARS = {".dbf", ".shx"}
    SHAPEFILE_OPTIONAL_SIDECARS = {".prj", ".cpg", ".qix", ".sbn", ".sbx"}
    RASTER_OPTIONAL_SIDECARS = {".aux.xml", ".ovr", ".tfw"}
    HIDDEN_DIRS = {
        ".git", "__pycache__", ".venv", "node_modules",
        ".idea", ".vscode", ".pytest_cache", ".ruff_cache",
    }


    @dataclass
    class ScanItem:
        path: Path
        format: str
        ingest: bool
        reason: str = ""
        sidecar_files: Optional[list[Path]] = None

        def to_dict(self) -> dict:
            return {
                "path": str(self.path),
                "format": self.format,
                "ingest": self.ingest,
                "reason": self.reason,
                "sidecar_files": [str(p) for p in (self.sidecar_files or [])],
            }


    def walk(
        root: Path,
        *,
        max_depth: Optional[int] = None,
        include_exts: Optional[set[str]] = None,
    ) -> Iterator[ScanItem]:
        """Yield one ScanItem per dataset (shapefiles grouped by .shp parent).

        Args:
            root: directory to walk (must be a directory).
            max_depth: cap recursion at this many levels below root (None = unlimited).
            include_exts: if provided, only emit ScanItems for files whose extension
                is in this set. Sidecar files are still grouped, just not emitted as
                their own rows. Exts must include the leading dot.
        """
        visited: set[Path] = set()
        yield from sorted_iter(_walk(root, root, visited, max_depth, include_exts))


    def sorted_iter(items: Iterator[ScanItem]) -> Iterator[ScanItem]:
        """Sort ScanItems by path for deterministic output."""
        return iter(sorted(items, key=lambda s: str(s.path)))


    def _walk(
        root: Path,
        current: Path,
        visited: set[Path],
        max_depth: Optional[int],
        include_exts: Optional[set[str]],
    ) -> Iterator[ScanItem]:
        try:
            canon = current.resolve()
        except OSError:
            return
        if canon in visited:
            return
        visited.add(canon)
        if not current.is_dir():
            return
        if max_depth is not None:
            try:
                rel_parts = current.relative_to(root).parts
            except ValueError:
                rel_parts = ()
            if len(rel_parts) > max_depth:
                return

        try:
            children = sorted(current.iterdir())
        except (PermissionError, OSError):
            return

        files_by_stem: dict[Path, dict[str, Path]] = {}
        for child in children:
            if child.is_dir():
                if child.name in HIDDEN_DIRS or child.name.startswith("."):
                    continue
                yield from _walk(root, child, visited, max_depth, include_exts)
                continue
            if child.name.startswith("."):
                continue
            ext = child.suffix.lower()
            stem_path = child.with_suffix("")
            files_by_stem.setdefault(stem_path, {})[ext] = child

        for stem, exts in files_by_stem.items():
            yield from _classify_group(exts, include_exts)


    def _classify_group(
        exts: dict[str, Path],
        include_exts: Optional[set[str]],
    ) -> Iterator[ScanItem]:
        # Shapefile grouping (D-18): one row for .shp, sidecars listed
        if ".shp" in exts:
            shp = exts[".shp"]
            siblings = [p for ext, p in exts.items() if ext != ".shp"]
            missing = SHAPEFILE_REQUIRED_SIDECARS - set(exts.keys())
            if include_exts is not None and ".shp" not in include_exts:
                return
            if missing:
                yield ScanItem(
                    path=shp,
                    format="shapefile",
                    ingest=False,
                    reason=f"missing required sidecar(s): {', '.join(sorted(missing))}",
                    sidecar_files=siblings,
                )
            else:
                yield ScanItem(path=shp, format="shapefile", ingest=True, sidecar_files=siblings)
            return

        for ext, path in exts.items():
            if include_exts is not None and ext not in include_exts:
                continue
            if ext == ".geojson":
                yield ScanItem(path=path, format="geojson", ingest=True)
            elif ext == ".gpkg":
                yield ScanItem(path=path, format="geopackage", ingest=True)
            elif ext in RASTER_EXTS:
                yield ScanItem(path=path, format="cog-candidate", ingest=True)
            elif ext == ".json":
                if _looks_like_geojson(path):
                    yield ScanItem(path=path, format="geojson", ingest=True)
                else:
                    yield ScanItem(
                        path=path, format="unsupported", ingest=False,
                        reason="json file but not GeoJSON",
                    )
            elif ext in SHAPEFILE_OPTIONAL_SIDECARS or ext in SHAPEFILE_REQUIRED_SIDECARS:
                continue  # only ever yielded grouped under .shp
            elif ext in RASTER_OPTIONAL_SIDECARS:
                continue
            else:
                yield ScanItem(
                    path=path, format="unsupported", ingest=False,
                    reason=f"unknown extension {ext}",
                )


    def _looks_like_geojson(path: Path, *, peek_bytes: int = 1024) -> bool:
        try:
            head = path.read_bytes()[:peek_bytes].lstrip()
            return head.startswith(b"{") and (b'"type"' in head[:200])
        except OSError:
            return False
    ```

    Cross-check against backend/app/processing/ingest/constants.py: read that file and confirm the CLI's `VECTOR_EXTS` and `RASTER_EXTS` are a subset of the server's allowlist. If the server has additional extensions (e.g., `.fgb`, `.parquet`), document the divergence in a `# TODO: backend supports X but CLI MVP excludes per D-15` comment. Do NOT silently expand the CLI allowlist beyond the server's — the server is the authoritative gate.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/cli && uv run python -c "from geolens_cli.scan import ScanItem, walk, VECTOR_EXTS, RASTER_EXTS, SHAPEFILE_REQUIRED_SIDECARS, HIDDEN_DIRS; assert '.shp' in VECTOR_EXTS; assert '.tif' in RASTER_EXTS; assert '.dbf' in SHAPEFILE_REQUIRED_SIDECARS; print('OK')"</automated>
    <automated>cd /Users/ishiland/Code/geolens/cli && uv run python -c "
from pathlib import Path
import tempfile
from geolens_cli.scan import walk
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    (root / 'a.geojson').write_text('{\"type\":\"FeatureCollection\",\"features\":[]}')
    (root / 'b.tif').write_bytes(b'II*\\x00')
    (root / 'notes.txt').write_text('hi')
    items = list(walk(root))
    by_name = {item.path.name: item for item in items}
    assert by_name['a.geojson'].ingest is True and by_name['a.geojson'].format == 'geojson'
    assert by_name['b.tif'].ingest is True and by_name['b.tif'].format == 'cog-candidate'
    assert by_name['notes.txt'].ingest is False
    print('OK')
"</automated>
    <automated>! grep -rE '^(import|from) (httpx|requests|geolens_sdk)' /Users/ishiland/Code/geolens/cli/geolens_cli/scan.py</automated>
  </verify>
  <acceptance_criteria>
    - cli/geolens_cli/scan.py defines `ScanItem` dataclass with fields `path`, `format`, `ingest`, `reason`, `sidecar_files`
    - cli/geolens_cli/scan.py exports `walk(root, *, max_depth=None, include_exts=None)` returning an Iterator[ScanItem]
    - VECTOR_EXTS contains `.geojson`, `.gpkg`, `.shp`
    - RASTER_EXTS contains `.tif`, `.tiff`
    - SHAPEFILE_REQUIRED_SIDECARS equals `{".dbf", ".shx"}`
    - HIDDEN_DIRS contains `.git`, `__pycache__`, `.venv`, `node_modules`
    - `walk` does not import `httpx`, `requests`, or `geolens_sdk` (verified by grep — pure-local-I/O proof)
    - Programmatic test (above) passes: a.geojson + b.tif both `ingest=True`, notes.txt `ingest=False`
  </acceptance_criteria>
  <done>scan.py exposes the full walk + classify + group surface. The scan module has zero SDK or HTTP imports — proof OCCLI-06 holds for this command at the structural level.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Wire scan command + table/JSON output; add comprehensive tests</name>
  <files>cli/geolens_cli/main.py, cli/tests/test_scan.py</files>
  <read_first>
    - cli/geolens_cli/main.py (Plan 01 — current scan stub; Plan 02 may have already updated AppState, but scan does not need .sdk())
    - cli/geolens_cli/scan.py (Task 1 — walk, ScanItem, allowlist)
    - cli/geolens_cli/output.py (Plan 01 — Formatter.json, Formatter.is_tty)
    - .planning/phases/216-geolens-cli-mvp/216-CONTEXT.md (D-17 output schema; D-30 --json global flag; D-32 exit codes)
    - .planning/phases/216-geolens-cli-mvp/216-VALIDATION.md (test_scan.py expectations)
  </read_first>
  <behavior>
    - `geolens scan <dir>` walks the directory and prints a human-readable rich.Table with columns `PATH`, `FORMAT`, `INGEST?`
    - `geolens scan <dir> --json` emits a JSON array of ScanItem.to_dict() to stdout (plain JSON; respects the global --json flag too)
    - `geolens scan <dir> --max-depth 0` only scans the top-level directory (no recursion)
    - `geolens scan <dir> --include-ext .gpkg,.tif` filters to only those extensions
    - Exit code 0 even when every file is `ingest: no` (it's a report, not an error)
    - Exit code 2 when the directory does not exist or is not a directory
    - When stdout is not a TTY (or --json is set), suppress the table; emit JSON or plain text
  </behavior>
  <action>
    Modify `cli/geolens_cli/main.py` — replace the Plan 01 `scan` stub with the real implementation. Keep the existing imports and add:
    ```python
    from pathlib import Path
    from . import scan as _scan
    from rich.table import Table
    ```

    Replace the `scan` function body:
    ```python
    @app.command()
    def scan(
        ctx: typer.Context,
        directory: Annotated[Path, typer.Argument(help="Directory to scan", exists=True, file_okay=False, dir_okay=True, readable=True)],
        max_depth: Annotated[Optional[int], typer.Option("--max-depth", help="Cap recursion at N levels below root", min=0)] = None,
        include_ext: Annotated[
            Optional[str],
            typer.Option("--include-ext", help="Comma-separated extension allowlist, e.g. .gpkg,.tif"),
        ] = None,
        json_local: Annotated[bool, typer.Option("--json", help="Emit JSON array (overrides global --json setting)")] = False,
    ) -> None:
        """Walk a directory and report what would be ingested (no upload)."""
        state: AppState = ctx.obj
        include_exts: Optional[set[str]] = None
        if include_ext:
            include_exts = {e.strip().lower() for e in include_ext.split(",") if e.strip()}
            # Add the leading dot if missing.
            include_exts = {e if e.startswith(".") else f".{e}" for e in include_exts}

        items = list(_scan.walk(directory, max_depth=max_depth, include_exts=include_exts))

        json_mode = state.json_mode or json_local
        if json_mode:
            payload = [item.to_dict() for item in items]
            state.output.json(payload)
            return

        # Human-readable rich Table
        table = Table(title=f"Scan: {directory}")
        table.add_column("PATH", overflow="fold")
        table.add_column("FORMAT")
        table.add_column("INGEST?")
        for item in items:
            ingest_marker = "yes" if item.ingest else "no"
            if not item.ingest and item.reason:
                ingest_marker = f"no ({item.reason})"
            try:
                rel = item.path.relative_to(directory)
            except ValueError:
                rel = item.path
            table.add_row(str(rel), item.format, ingest_marker)

        # Use the Formatter's public stdout console so NO_COLOR / quiet are honored.
        # Direct rich.Console.print is fine for tables — Formatter.success is for messages.
        # Plan 01 exposes `console_stdout` as a public property; do NOT touch the
        # underscored `_stdout` attribute (private to Formatter).
        state.output.console_stdout.print(table)
        if not items:
            state.output.info("(no files found)")
    ```

    Note: `state.output.console_stdout` is the public property added in Plan 01 (output.py Task 2). It returns the underlying `rich.Console` configured with the same NO_COLOR / json_mode toggles as the message helpers. Do not access the private `_stdout` attribute directly — the public property is the contract.

    Create `cli/tests/test_scan.py`:
    ```python
    """OCCLI-03: scan command — walk, classify, group, table + JSON output."""
    from __future__ import annotations

    import json
    from pathlib import Path

    import pytest

    from geolens_cli import scan as _scan
    from geolens_cli.main import app


    @pytest.fixture
    def sample_tree(tmp_path: Path) -> Path:
        """Build a representative directory tree."""
        (tmp_path / "a.geojson").write_text(
            '{"type":"FeatureCollection","features":[]}'
        )
        (tmp_path / "b.tif").write_bytes(b"II*\x00")  # TIFF magic
        (tmp_path / "notes.txt").write_text("hi")
        # Shapefile with all sidecars
        (tmp_path / "cities.shp").write_bytes(b"shp")
        (tmp_path / "cities.dbf").write_bytes(b"dbf")
        (tmp_path / "cities.shx").write_bytes(b"shx")
        (tmp_path / "cities.prj").write_text("WGS84")
        # Shapefile MISSING required .dbf
        (tmp_path / "broken.shp").write_bytes(b"shp")
        (tmp_path / "broken.shx").write_bytes(b"shx")
        # Hidden directory should be skipped
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "secret.geojson").write_text(
            '{"type":"FeatureCollection","features":[]}'
        )
        # Nested directory
        nested = tmp_path / "nested"
        nested.mkdir()
        (nested / "elev.tif").write_bytes(b"II*\x00")
        # JSON file that is not GeoJSON
        (tmp_path / "config.json").write_text('{"foo":1}')
        return tmp_path


    class TestClassification:
        def test_geojson_detected(self, sample_tree) -> None:
            items = {i.path.name: i for i in _scan.walk(sample_tree)}
            assert items["a.geojson"].format == "geojson"
            assert items["a.geojson"].ingest is True

        def test_tiff_detected_as_cog_candidate(self, sample_tree) -> None:
            items = {i.path.name: i for i in _scan.walk(sample_tree)}
            assert items["b.tif"].format == "cog-candidate"
            assert items["b.tif"].ingest is True

        def test_unsupported_extension(self, sample_tree) -> None:
            items = {i.path.name: i for i in _scan.walk(sample_tree)}
            assert items["notes.txt"].format == "unsupported"
            assert items["notes.txt"].ingest is False
            assert "unknown extension" in items["notes.txt"].reason

        def test_non_geojson_json_marked_unsupported(self, sample_tree) -> None:
            items = {i.path.name: i for i in _scan.walk(sample_tree)}
            assert items["config.json"].format == "unsupported"
            assert items["config.json"].ingest is False


    class TestShapefileGrouping:
        def test_complete_shapefile_yields_one_row(self, sample_tree) -> None:
            items = list(_scan.walk(sample_tree))
            shapefiles = [i for i in items if i.format == "shapefile" and i.ingest]
            cities = [i for i in shapefiles if i.path.name == "cities.shp"]
            assert len(cities) == 1
            assert cities[0].sidecar_files is not None
            sidecar_names = {p.name for p in cities[0].sidecar_files}
            assert "cities.dbf" in sidecar_names
            assert "cities.shx" in sidecar_names
            assert "cities.prj" in sidecar_names

        def test_missing_dbf_marks_ingest_false(self, sample_tree) -> None:
            items = list(_scan.walk(sample_tree))
            broken = [i for i in items if i.path.name == "broken.shp"]
            assert len(broken) == 1
            assert broken[0].ingest is False
            assert ".dbf" in broken[0].reason

        def test_dbf_not_emitted_as_separate_row(self, sample_tree) -> None:
            paths = {i.path.name for i in _scan.walk(sample_tree)}
            assert "cities.dbf" not in paths
            assert "cities.shx" not in paths
            assert "cities.prj" not in paths


    class TestWalkSemantics:
        def test_skips_hidden_dirs(self, sample_tree) -> None:
            paths = {str(i.path) for i in _scan.walk(sample_tree)}
            assert not any(".git" in p for p in paths)

        def test_recursive_by_default(self, sample_tree) -> None:
            items = {i.path.name: i for i in _scan.walk(sample_tree)}
            assert "elev.tif" in items

        def test_max_depth_zero_does_not_recurse(self, sample_tree) -> None:
            items = {i.path.name: i for i in _scan.walk(sample_tree, max_depth=0)}
            assert "elev.tif" not in items

        def test_symlink_loop_protected(self, tmp_path: Path) -> None:
            # Create a -> b -> a symlink loop
            a = tmp_path / "a"
            b = tmp_path / "b"
            a.mkdir()
            (a / "data.geojson").write_text('{"type":"FeatureCollection","features":[]}')
            try:
                b.symlink_to(a, target_is_directory=True)
                (a / "loopback").symlink_to(b, target_is_directory=True)
            except (OSError, NotImplementedError):
                pytest.skip("symlinks unavailable on this platform")
            # Should terminate (no infinite recursion)
            items = list(_scan.walk(tmp_path, max_depth=10))
            # At least the GeoJSON is found exactly once
            geojsons = [i for i in items if i.format == "geojson"]
            assert len(geojsons) >= 1


    class TestCliInvocation:
        def test_scan_exits_0_on_dry_run(self, runner, sample_tree) -> None:
            result = runner.invoke(app, ["scan", str(sample_tree)])
            assert result.exit_code == 0, result.output

        def test_scan_exits_0_when_all_unsupported(self, runner, tmp_path) -> None:
            (tmp_path / "x.txt").write_text("hi")
            result = runner.invoke(app, ["scan", str(tmp_path)])
            assert result.exit_code == 0, result.output

        def test_json_output_emits_array(self, runner, sample_tree) -> None:
            result = runner.invoke(app, ["scan", str(sample_tree), "--json"])
            assert result.exit_code == 0, result.output
            payload = json.loads(result.output)
            assert isinstance(payload, list)
            assert len(payload) >= 1
            for item in payload:
                assert "path" in item
                assert "format" in item
                assert "ingest" in item
                assert "reason" in item
                assert "sidecar_files" in item

        def test_json_output_includes_shapefile_sidecars(self, runner, sample_tree) -> None:
            result = runner.invoke(app, ["scan", str(sample_tree), "--json"])
            payload = json.loads(result.output)
            cities = [p for p in payload if p["path"].endswith("cities.shp")]
            assert len(cities) == 1
            assert any("cities.dbf" in s for s in cities[0]["sidecar_files"])

        def test_global_json_flag_works(self, runner, sample_tree) -> None:
            # The global --json before the subcommand should also emit JSON
            result = runner.invoke(app, ["--json", "scan", str(sample_tree)])
            assert result.exit_code == 0, result.output
            json.loads(result.output)  # must parse

        def test_nonexistent_dir_exits_with_usage_error(self, runner, tmp_path) -> None:
            result = runner.invoke(app, ["scan", str(tmp_path / "does-not-exist")])
            assert result.exit_code != 0
    ```
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/cli && uv run pytest tests/test_scan.py -v 2>&1 | tail -40</automated>
    <automated>cd /Users/ishiland/Code/geolens/cli && uv run pytest -v 2>&1 | grep -E "(passed|failed)" | tail -5</automated>
    <automated>cd /Users/ishiland/Code/geolens/cli && uv run python -c "
from typer.testing import CliRunner
from geolens_cli.main import app
import tempfile, json
from pathlib import Path
runner = CliRunner()
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    (root / 'a.geojson').write_text('{\"type\":\"FeatureCollection\",\"features\":[]}')
    result = runner.invoke(app, ['scan', str(root), '--json'])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload[0]['format'] == 'geojson'
    assert payload[0]['ingest'] is True
    print('OK')
"</automated>
    <automated>! grep -rE '^(import|from) (httpx|requests|geolens_sdk)' /Users/ishiland/Code/geolens/cli/geolens_cli/scan.py</automated>
  </verify>
  <acceptance_criteria>
    - cli/geolens_cli/main.py `scan` command body uses `_scan.walk(...)` and accepts `--json`, `--max-depth`, `--include-ext` options
    - `scan` validates the directory argument via Typer's `exists=True, file_okay=False, dir_okay=True`
    - `scan` exits 0 even when all files are `ingest: no` (D-17)
    - `--json` emits a parseable JSON array of `{path, format, ingest, reason, sidecar_files}` per item
    - Test class `TestClassification` with ≥4 methods covering geojson/tiff/unsupported/non-geojson-json
    - Test class `TestShapefileGrouping` with ≥3 methods covering complete/missing-dbf/sidecar-not-emitted-separately
    - Test class `TestWalkSemantics` with ≥4 methods covering hidden dirs / recursion / max-depth / symlink loop
    - Test class `TestCliInvocation` with ≥6 methods covering exit code / json output / global --json / nonexistent dir
    - `cd cli && uv run pytest tests/test_scan.py -v` exits 0 with all tests passing (≥ 17 tests; symlink test may skip on Windows)
    - cli/geolens_cli/scan.py has zero `import httpx`, `import requests`, or `import geolens_sdk` lines (pure local I/O proof)
  </acceptance_criteria>
  <done>`geolens scan <dir>` works in both human and JSON modes, groups shapefiles correctly, caps recursion via --max-depth, skips hidden dirs, and survives symlink loops. ≥17 unit tests pass. Zero HTTP/SDK imports in scan.py — OCCLI-06 inheritance verified structurally.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| User-supplied directory path | The `scan` argument is a positional Path; Typer's `exists=True, dir_okay=True` enforces the path exists and is a directory before the command body runs |
| Filesystem | scan.py reads file extensions and (for `.json`) peek-reads up to 1024 bytes to disambiguate GeoJSON from generic JSON |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-216-03 | Tampering | Client-side extension allowlist could be bypassed by renaming a malicious file to `.geojson` | accept | Per CONTEXT.md D-15: extension allowlist is informational only. The server validates via puremagic on `/ingest/upload`. The CLI's claim of "ingest: yes" is a hint; the server is the security boundary. Any malicious file would be caught server-side before persistence. Documented in scan.py docstring. |
| T-216-03 | Information Disclosure | scan walks user-supplied paths and could traverse into sensitive directories | accept | The user passes the directory explicitly; HIDDEN_DIRS skips common version-control / cache trees. No content is uploaded — scan is read-only and printed locally. |
| T-216-04 | Tampering | scan.py introducing a direct httpx import would silently break OCCLI-06 | mitigate | Acceptance criterion enforces zero `import httpx`/`import requests`/`import geolens_sdk` in scan.py via grep. Plan 06 adds the global CI grep gate across `cli/geolens_cli/`. |

**Not Applicable in this plan:**
- T-216-01 (token-at-rest): Not applicable — scan performs no auth and stores no secrets. Plan 02 owns credential storage.
- T-216-02 (replay): Not applicable — scan makes zero HTTP calls (verified by grep gate); no tokens are sent or replayed.
- T-216-05 (token-in-shell-history): Not applicable — scan has no `--token` flag and does not interact with auth credentials. Plan 02 owns the flag; Plan 06 docs/cli.md owns the user-facing warning.
</threat_model>

<verification>
- `cd cli && uv run pytest tests/test_scan.py -v` exits 0 with ≥17 tests passing
- `cd cli && uv run pytest -v` (full unit slice) still green (Plans 01 + 02 + 03 tests all pass)
- `geolens scan <some-dir> --json | jq .` produces valid JSON with the documented shape
- `grep -rE '^(import|from) (httpx|requests|geolens_sdk)' cli/geolens_cli/scan.py` returns zero matches
</verification>

<success_criteria>
- OCCLI-03 closed: `geolens scan <dir>` walks, classifies, and reports vector + raster files; shapefile sidecars grouped; --json + --max-depth + --include-ext flags work; exit 0 on dry-run regardless of ingest:no count
- scan.py is pure local I/O — zero SDK or HTTP imports, structurally proving OCCLI-06 for this command path
</success_criteria>

<output>
After completion, create `.planning/phases/216-geolens-cli-mvp/216-03-SUMMARY.md` capturing: scan.py public surface, allowlist contents, test count, and confirmation that the CLI allowlist is a subset of `backend/app/processing/ingest/constants.py` (or the documented divergence).
</output>
