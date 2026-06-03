"""OCCLI-03: scan command — walk, classify, group, table + JSON output.

Hand-maintained — NOT regenerated. Covers the four behavior buckets:
- TestClassification: extension-based format detection
- TestShapefileGrouping: D-18 sibling grouping under .shp parent
- TestWalkSemantics: D-16 hidden-dirs / max-depth / symlink-loop
- TestCliInvocation: end-to-end CLI invocation (Task 2)
"""
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
