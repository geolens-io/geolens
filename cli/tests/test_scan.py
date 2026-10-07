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

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("points.fgb", "flatgeobuf"),
            ("tour.kml", "kml"),
            ("tour.kmz", "kmz"),
        ],
    )
    def test_single_file_vector_primaries(
        self, tmp_path, name: str, expected: str
    ) -> None:
        """Tier-1 formats classify on extension alone — no sidecars, no peek."""
        (tmp_path / name).write_bytes(b"\x00")
        items = {i.path.name: i for i in _scan.walk(tmp_path)}
        assert items[name].format == expected
        assert items[name].ingest is True


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


class TestGeojsonSnifferBoundedRead:
    """PERF-008: the .json sniffer reads only a bounded prefix, never the whole file."""

    def test_does_not_read_entire_file(self, tmp_path: Path, monkeypatch) -> None:
        # A "large" GeoJSON: small valid header followed by megabytes of filler.
        big = tmp_path / "big.json"
        header = b'{"type":"FeatureCollection","features":['
        with big.open("wb") as fh:
            fh.write(header)
            fh.write(b"0" * (5 * 1024 * 1024))  # 5 MB of filler
            fh.write(b"]}")

        read_sizes: list[int | None] = []
        real_open = Path.open

        def tracking_open(self, *args, **kwargs):  # noqa: ANN001
            fh = real_open(self, *args, **kwargs)
            real_read = fh.read

            def tracking_read(size=-1):  # noqa: ANN001
                read_sizes.append(size)
                return real_read(size)

            fh.read = tracking_read  # type: ignore[method-assign]
            return fh

        monkeypatch.setattr(Path, "open", tracking_open)

        assert _scan._looks_like_geojson(big, peek_bytes=1024) is True
        # The read must be bounded by peek_bytes — never an unbounded read(-1).
        assert read_sizes, "expected at least one bounded read"
        assert all(s == 1024 for s in read_sizes), read_sizes

    def test_still_classifies_correctly(self, tmp_path: Path) -> None:
        gj = tmp_path / "small.json"
        gj.write_text('{"type":"FeatureCollection","features":[]}')
        assert _scan._looks_like_geojson(gj) is True

        plain = tmp_path / "plain.json"
        plain.write_text('{"foo": 1, "bar": 2}')
        assert _scan._looks_like_geojson(plain) is False


class TestIndependentDatasetsSharingABasename:
    def test_geojson_and_gpkg_beside_a_shapefile_are_listed(self, tmp_path) -> None:
        for name in ("cities.shp", "cities.shx", "cities.dbf", "cities.prj"):
            (tmp_path / name).write_bytes(b"x")
        (tmp_path / "cities.geojson").write_text('{"type":"FeatureCollection"}')
        (tmp_path / "cities.gpkg").write_bytes(b"SQLite format 3\x00")

        items = {i.path.name: i for i in _scan.walk(tmp_path)}

        assert set(items) == {"cities.shp", "cities.geojson", "cities.gpkg"}
        assert items["cities.shp"].ingest is True
        assert {p.name for p in items["cities.shp"].sidecar_files} == {
            "cities.shx",
            "cities.dbf",
            "cities.prj",
        }
        assert items["cities.geojson"].format == "geojson"
        assert items["cities.gpkg"].format == "geopackage"

    def test_include_exts_without_shp_still_lists_the_geojson(self, tmp_path) -> None:
        for name in ("cities.shp", "cities.shx", "cities.dbf"):
            (tmp_path / name).write_bytes(b"x")
        (tmp_path / "cities.geojson").write_text('{"type":"FeatureCollection"}')

        items = list(_scan.walk(tmp_path, include_exts={".geojson"}))

        assert [i.path.name for i in items] == ["cities.geojson"]


class TestRasterAuxSidecar:
    def test_aux_xml_is_a_sidecar_not_an_unsupported_file(self, tmp_path) -> None:
        (tmp_path / "dem.tif").write_bytes(b"II*\x00")
        (tmp_path / "dem.tif.aux.xml").write_text("<PAMDataset/>")

        items = list(_scan.walk(tmp_path))

        assert [(i.path.name, i.format) for i in items] == [
            ("dem.tif", "cog-candidate")
        ]


class TestJsonDetection:
    def _scan_one(self, tmp_path, text: str):
        (tmp_path / "x.json").write_text(text)
        (item,) = _scan.walk(tmp_path)
        return item

    def test_type_after_a_long_leading_member_is_still_geojson(self, tmp_path) -> None:
        pad = "a" * 5000
        item = self._scan_one(
            tmp_path, '{"name":"%s","type":"FeatureCollection","features":[]}' % pad
        )
        assert item.format == "geojson" and item.ingest is True

    def test_malformed_json_is_not_ingestable(self, tmp_path) -> None:
        item = self._scan_one(tmp_path, '{"type": "FeatureCollection", "features": [')
        assert item.ingest is False

    def test_non_geojson_type_is_not_ingestable(self, tmp_path) -> None:
        item = self._scan_one(tmp_path, '{"type": "config", "foo": 1}')
        assert item.ingest is False

    def test_oversized_file_is_judged_from_its_prefix(self, tmp_path) -> None:
        path = tmp_path / "big.json"
        path.write_text('{"type":"FeatureCollection","features":[' + "1," * 100)
        assert _scan._looks_like_geojson(path, peek_bytes=64) is True
        path.write_text('{"foo":' + "1," * 100)
        assert _scan._looks_like_geojson(path, peek_bytes=64) is False


class TestJsonDetectionEdgeCases:
    def test_deeply_nested_json_is_unsupported_not_a_crash(self, tmp_path) -> None:
        path = tmp_path / "deep.json"
        path.write_text("[" * 100_000 + "]" * 100_000)
        assert _scan._looks_like_geojson(path) is False

    @pytest.mark.parametrize(
        "text",
        [
            '{"payload":{"type":"Feature","x":1},"pad":"' + "a" * 200,
            '{"note":"\\"type\\": \\"Feature\\"","pad":"' + "a" * 200,
            '{"items":[{"type":"Feature"}],"pad":"' + "a" * 200,
        ],
    )
    def test_nested_or_quoted_type_in_a_truncated_file_is_not_geojson(
        self, tmp_path, text
    ) -> None:
        path = tmp_path / "wrapper.json"
        path.write_text(text)
        assert _scan._looks_like_geojson(path, peek_bytes=64) is False

    def test_root_type_after_other_members_in_a_truncated_file_is_geojson(
        self, tmp_path
    ) -> None:
        path = tmp_path / "big.json"
        path.write_text(
            '{"name":"a {brace}","crs":{"type":"name"},"type":"Feature","pad":"'
            + "a" * 200
        )
        assert _scan._looks_like_geojson(path, peek_bytes=96) is True

    def test_escaped_key_and_value_in_a_truncated_file_still_match(
        self, tmp_path
    ) -> None:
        path = tmp_path / "escaped.json"
        path.write_text(
            '{"ty\\u0070e":"Feature\\u0043ollection","pad":"' + "a" * 200
        )
        assert _scan._looks_like_geojson(path, peek_bytes=96) is True

    def test_large_root_geometry_is_geojson_like_a_small_one(self, tmp_path) -> None:
        path = tmp_path / "poly.json"
        path.write_text('{"type":"Polygon","coordinates":[[' + "[0,0]," * 100 + "[0,0]]]}")
        assert _scan._looks_like_geojson(path, peek_bytes=64) is True
        assert _scan._looks_like_geojson(path) is True


class TestScanRobustness:
    def test_unrecognised_shapefile_sidecars_stay_grouped(self, tmp_path) -> None:
        for name in ("roads.shp", "roads.shx", "roads.dbf", "roads.qpj"):
            (tmp_path / name).write_bytes(b"x")

        items = list(_scan.walk(tmp_path))

        assert [i.path.name for i in items] == ["roads.shp"]
        assert "roads.qpj" in {p.name for p in items[0].sidecar_files}

    def test_prefix_cut_inside_a_string_of_escaped_quotes_is_fast(
        self, tmp_path
    ) -> None:
        import time

        path = tmp_path / "evil.json"
        path.write_bytes(b'{"a":"' + b'\\"' * 200_000 + b'"}')
        start = time.monotonic()
        assert _scan._looks_like_geojson(path, peek_bytes=64 * 1024) is False
        assert time.monotonic() - start < 2

    def test_repeated_root_type_uses_the_last_value_like_a_full_parse(
        self, tmp_path
    ) -> None:
        path = tmp_path / "dup.json"
        path.write_text('{"type":"Feature","type":"config","pad":"' + "a" * 200)
        assert _scan._looks_like_geojson(path, peek_bytes=96) is False
        path.write_text('{"type":"config","type":"Feature","pad":"' + "a" * 200)
        assert _scan._looks_like_geojson(path, peek_bytes=96) is True

    def test_prefix_ending_on_a_dangling_backslash_is_fast(self, tmp_path) -> None:
        import time

        path = tmp_path / "evil2.json"
        path.write_bytes(b'{"a":"' + b'\\"' * 200_000 + b"\\" + b'x"}')
        start = time.monotonic()
        assert _scan._looks_like_geojson(path, peek_bytes=len(b'{"a":"') + 400_000 + 1) is False
        assert time.monotonic() - start < 2
