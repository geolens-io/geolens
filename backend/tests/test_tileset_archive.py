"""A tileset archive is checked from its central directory and tileset.json alone."""

from __future__ import annotations

import functools
import io
import json
import math
import os
import stat
import struct
import time
import uuid
import zipfile
import zlib
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from app.core.config import settings
from app.core.upload_errors import UnsafeUploadError
from app.platform.storage.local import LocalStorageProvider
from app.platform.storage.s3 import S3StorageProvider
from app.processing.ingest import tileset as tileset_module
from app.processing.ingest.tileset import (
    MAX_TILESET_JSON_DEPTH,
    inspect_stored_tileset,
    inspect_tileset,
)
from app.processing.ingest.validation import MAX_ARCHIVE_ENTRIES, validate_zip_safety
from tests.tiles3d_archives import (
    REGION,
    build_zip,
    tileset_json,
    tileset_zip,
    zip_bytes,
)


def refused(path: str, **kwargs) -> str:
    with pytest.raises(UnsafeUploadError) as refusal:
        inspect_tileset(path, **kwargs)
    return str(refusal.value)


def entry(name: str, *, mode: int | None = None) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name)
    if mode is not None:
        info.create_system = 3
        info.external_attr = mode << 16
    return info


# --- 1. Zip-slip ---------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "../escape.glb",
        "0/../../escape.glb",
        "/etc/escape.glb",
        "C:/escape.glb",
        "C:escape.glb",
        "0\\..\\escape.glb",
        "0\\tile.glb",
        "./tileset-copy.json",
        "0/./tile.glb",
        "0//tile.glb",
        "0/%2e%2e/tile.glb",
    ],
    ids=[
        "dotdot",
        "nested-dotdot",
        "absolute",
        "drive-letter",
        "drive-relative",
        "backslash-dotdot",
        "backslash",
        "dot-segment",
        "inner-dot-segment",
        "empty-segment",
        "percent",
    ],
)
def test_an_escaping_or_ambiguous_name_is_refused(tmp_path: Path, name: str) -> None:
    """Every entry must name a plain path below the archive root."""
    message = refused(tileset_zip(tmp_path / "t.zip", (name, b"x")))

    assert "entry" in message
    assert name not in message


@pytest.mark.parametrize(
    "name", ["0/frame..2.glb", "0/..hidden.glb", "0/v1../tile.glb"]
)
def test_dots_inside_a_segment_are_accepted(tmp_path: Path, name: str) -> None:
    """Only a whole '..' segment climbs; dots inside a name are fine."""
    result = inspect_tileset(tileset_zip(tmp_path / "t.zip", (name, b"x")))

    assert name in {key for _, key in result.layout.files}


def _with_raw_name(path: Path, placeholder: bytes, raw: bytes) -> str:
    data = path.read_bytes()
    assert data.count(placeholder) == 2 and len(placeholder) == len(raw)
    path.write_bytes(data.replace(placeholder, raw))
    return str(path)


def test_a_nul_in_a_recorded_name_is_refused(tmp_path: Path) -> None:
    """zipfile would cut the name at the NUL; the archive is refused instead."""
    path = tmp_path / "t.zip"
    tileset_zip(path, ("0/aXb.glb", b"x"))

    message = refused(_with_raw_name(path, b"0/aXb.glb", b"0/a\x00b.glb"))

    assert "control character" in message


def test_a_nul_in_the_unicode_path_field_is_refused(tmp_path: Path) -> None:
    """The name zipfile takes from the Unicode Path field is checked too."""
    raw = b"0/tile.glb"
    unicode_name = "0/t\x00ile.glb".encode()
    info = zipfile.ZipInfo("0/tile.glb")
    info.extra = (
        struct.pack("<HHBL", 0x7075, 5 + len(unicode_name), 1, zlib.crc32(raw))
        + unicode_name
    )

    message = refused(tileset_zip(tmp_path / "t.zip", (info, b"x")))

    assert "control character" in message


@pytest.mark.parametrize(
    "names",
    [
        ("tiles/a.glb", "Tiles/A.GLB"),
        ("tiles/caf\u00e9.glb", "tiles/cafe\u0301.glb"),
        ("tiles", "tiles/a.glb"),
        ("Tiles", "tiles/a.glb"),
        ("tiles", "Tiles/"),
    ],
    ids=[
        "case",
        "unicode-form",
        "file-and-folder",
        "file-and-folder-by-case",
        "file-and-folder-entry",
    ],
)
def test_names_that_collide_on_a_case_insensitive_disk_are_refused(
    tmp_path: Path, names: tuple[str, str]
) -> None:
    """Two entries that one case-insensitive path would hold are refused."""
    message = refused(tileset_zip(tmp_path / "t.zip", *((n, b"x") for n in names)))

    assert "overwrite" in message or "both a file and a folder" in message


def test_folders_that_differ_only_by_case_are_accepted(tmp_path: Path) -> None:
    """Two folder spellings merge on such a disk without losing a file."""
    result = inspect_tileset(
        tileset_zip(tmp_path / "t.zip", ("Tiles/a.glb", b"a"), ("tiles/b.glb", b"b"))
    )

    assert {key for _, key in result.layout.files} >= {"Tiles/a.glb", "tiles/b.glb"}


def test_an_overlong_name_is_refused(tmp_path: Path) -> None:
    """A name that cannot become a storage key is refused before any put."""
    message = refused(tileset_zip(tmp_path / "t.zip", ("0/" + "a" * 250, b"x")))

    assert "longer than" in message


# --- 2. Links and specials -----------------------------------------------


@pytest.mark.parametrize(
    "mode",
    [
        stat.S_IFLNK | 0o777,
        stat.S_IFCHR | 0o644,
        stat.S_IFBLK | 0o644,
        stat.S_IFIFO | 0o644,
        stat.S_IFSOCK | 0o644,
        stat.S_IFDIR | 0o755,
    ],
    ids=["symlink", "char-device", "block-device", "fifo", "socket", "dir-mode-file"],
)
def test_a_link_or_special_file_is_refused(tmp_path: Path, mode: int) -> None:
    """An entry whose attributes mark it anything but a plain file is refused."""
    message = refused(
        tileset_zip(tmp_path / "t.zip", (entry("0/link.glb", mode=mode), b"/etc"))
    )

    assert "symbolic link or a special file" in message


def test_a_regular_file_mode_is_accepted(tmp_path: Path) -> None:
    """Unix permission bits on a regular file are fine."""
    result = inspect_tileset(
        tileset_zip(
            tmp_path / "t.zip", (entry("0/1.glb", mode=stat.S_IFREG | 0o644), b"x")
        )
    )

    assert "0/1.glb" in {key for _, key in result.layout.files}


# --- 3. Bombs ------------------------------------------------------------


def test_an_unpacked_total_over_the_cap_is_refused(tmp_path: Path, monkeypatch) -> None:
    """The central directory's total is held to MAX_TILESET_UNPACKED_MB."""
    monkeypatch.setattr(settings, "max_tileset_unpacked_mb", 1)
    path = build_zip(
        tmp_path / "t.zip",
        [("tileset.json", tileset_json()), ("0/big.glb", os.urandom(1024 * 1024))],
        compression=zipfile.ZIP_STORED,
    )

    assert "more than the 1 MB" in refused(path)


def test_an_entry_over_the_compression_ratio_is_refused(tmp_path: Path) -> None:
    """One highly compressed entry is a bomb indicator."""
    path = tileset_zip(tmp_path / "t.zip", ("0/zeros.glb", bytes(2 * 1024 * 1024)))

    assert "times its compressed size" in refused(path)


def test_entries_that_overlap_are_refused(tmp_path: Path) -> None:
    """Entries whose compressed sizes add up to more than the archive are refused."""
    data = zip_bytes(
        [("tileset.json", tileset_json()), ("0/a.glb", b"x" * 64 * 1024)],
        compression=zipfile.ZIP_STORED,
    )
    end = data.rindex(b"PK\x05\x06")
    count, _, size, offset = struct.unpack("<HHII", data[end + 8 : end + 20])
    last = data[data.rindex(b"PK\x01\x02", 0, end) : end]
    aliases = b"".join(last.replace(b"0/a.glb", f"0/{c}.glb".encode()) for c in "bcd")
    directory_end = data[end : end + 8] + struct.pack(
        "<HHII", count + 3, count + 3, size + len(aliases), offset
    )
    path = tmp_path / "t.zip"
    path.write_bytes(data[:end] + aliases + directory_end + data[end + 20 :])

    assert "overlap" in refused(str(path))


def test_too_many_entries_are_refused(tmp_path: Path, monkeypatch) -> None:
    """MAX_TILESET_ENTRIES bounds the count before ZipFile builds an entry each."""
    monkeypatch.setattr(settings, "max_tileset_entries", 50)
    path = tileset_zip(tmp_path / "t.zip", *((f"t/{i}.glb", b"") for i in range(50)))

    assert "the maximum is 50" in refused(path)


def test_a_tileset_may_hold_more_entries_than_a_geospatial_zip(tmp_path: Path) -> None:
    """Past MAX_ARCHIVE_ENTRIES a tileset is accepted and a zip for GDAL is not."""
    path = tileset_zip(
        tmp_path / "t.zip", *((f"t/{i}.glb", b"") for i in range(MAX_ARCHIVE_ENTRIES))
    )

    assert len(inspect_tileset(path).layout.files) == MAX_ARCHIVE_ENTRIES + 2
    with pytest.raises(ValueError, match=f"the maximum is {MAX_ARCHIVE_ENTRIES}"):
        validate_zip_safety(path)


def test_a_tileset_json_over_its_bound_is_refused(tmp_path: Path, monkeypatch) -> None:
    """tileset.json is parsed whole, so its own size is bounded first."""
    monkeypatch.setattr(tileset_module, "MAX_TILESET_JSON_BYTES", 256)
    path = tileset_zip(tmp_path / "t.zip", extra={"pad": "x" * 512})

    assert "larger than" in refused(path)


def _nested(depth: int) -> dict:
    value: object = 0
    for _ in range(depth):
        value = [value]
    return {"nested": value}


def test_json_nested_past_the_depth_bound_is_refused(tmp_path: Path) -> None:
    """Nesting is counted before the JSON is parsed."""
    path = tileset_zip(tmp_path / "t.zip", extra=_nested(MAX_TILESET_JSON_DEPTH + 1))

    assert "nests deeper" in refused(path)


def test_json_nested_within_the_bound_is_accepted(tmp_path: Path) -> None:
    """Brackets inside strings do not count toward the depth."""
    path = tileset_zip(
        tmp_path / "t.zip",
        extra={**_nested(MAX_TILESET_JSON_DEPTH - 2), "text": "[[[[{{{{" * 100},
    )

    assert inspect_tileset(path).facts.version == "1.1"


def test_an_unclosed_string_is_scanned_once_and_refused(tmp_path: Path) -> None:
    """The depth scan stays linear on an unclosed string full of escaped quotes."""
    path = build_zip(
        tmp_path / "t.zip",
        [("tileset.json", b'"' + b'\\"' * 50_000)],
        compression=zipfile.ZIP_STORED,
    )

    started = time.perf_counter()
    message = refused(path)

    assert time.perf_counter() - started < 2
    assert "not valid JSON" in message


# --- 4. Layout -----------------------------------------------------------


def test_a_root_tileset_keeps_every_key(tmp_path: Path) -> None:
    """tileset.json at the root: keys are the entry names."""
    result = inspect_tileset(tileset_zip(tmp_path / "t.zip"))

    assert sorted(key for _, key in result.layout.files) == ["0/0.glb", "tileset.json"]
    assert result.layout.entry_point.filename == "tileset.json"


def test_one_top_level_folder_is_stripped(tmp_path: Path) -> None:
    """tileset.json inside the only top-level folder: the folder is stripped."""
    path = build_zip(
        tmp_path / "t.zip",
        [
            ("campus/", b""),
            ("campus/tileset.json", tileset_json()),
            ("campus/0/0.glb", b"glb"),
        ],
    )

    result = inspect_tileset(path)

    assert sorted(key for _, key in result.layout.files) == ["0/0.glb", "tileset.json"]
    assert result.layout.entry_count == 3


@pytest.mark.parametrize(
    "entries",
    [
        [("a/tileset.json", tileset_json()), ("b/tileset.json", tileset_json())],
        [("a/tileset.json", tileset_json()), ("readme.txt", b"hi")],
    ],
    ids=["two-folders", "folder-and-root-file"],
)
def test_more_than_one_top_level_entry_without_a_root_tileset_is_refused(
    tmp_path: Path, entries
) -> None:
    """Only one top-level folder may be stripped."""
    assert "top-level entries" in refused(build_zip(tmp_path / "t.zip", entries))


@pytest.mark.parametrize(
    "entries",
    [
        [("0/0.glb", b"glb")],
        [("campus/Tileset.json", tileset_json())],
        [("campus/inner/tileset.json", tileset_json())],
        [],
    ],
    ids=["none", "wrong-case", "two-folders-deep", "empty"],
)
def test_an_archive_without_a_reachable_tileset_json_is_refused(
    tmp_path: Path, entries
) -> None:
    """tileset.json must sit at the root or inside the one top-level folder."""
    assert "no tileset.json" in refused(build_zip(tmp_path / "t.zip", entries))


def _finder_zip(path: Path, folder: str) -> str:
    """What Finder's Compress writes for a tileset, inside ``folder`` or not."""
    appledouble = b"\x00\x05\x16\x07" + bytes(28)
    return build_zip(
        path,
        [
            *([(folder, b"")] if folder else []),
            (f"{folder}tileset.json", tileset_json()),
            (f"{folder}0/0.glb", b"glb"),
            (f"{folder}.DS_Store", b"Bud1" + bytes(64)),
            (f"{folder}0/._0.glb", appledouble),
            ("__MACOSX/", b""),
            (f"__MACOSX/{folder}._tileset.json", appledouble),
            (f"__MACOSX/{folder}0/._0.glb", appledouble),
        ],
    )


@pytest.mark.parametrize("folder", ["campus/", ""], ids=["folder", "root"])
def test_finder_metadata_is_never_unpacked(tmp_path: Path, folder: str) -> None:
    """__MACOSX, AppleDouble files and .DS_Store are left out of the tileset."""
    layout = inspect_tileset(_finder_zip(tmp_path / "t.zip", folder)).layout

    assert sorted(key for _, key in layout.files) == ["0/0.glb", "tileset.json"]
    assert layout.unpacked_bytes == len(tileset_json()) + len(b"glb")


@pytest.mark.parametrize(
    "name", ["__MACOSX/../x.glb", "__MACOSX/campus/../../x", "0/../.DS_Store"]
)
def test_finder_metadata_names_are_still_checked(tmp_path: Path, name: str) -> None:
    """A metadata entry is left out only once its name passes every check."""
    assert "'..' path segment" in refused(tileset_zip(tmp_path / "t.zip", (name, b"x")))


def test_a_finder_metadata_link_is_still_refused(tmp_path: Path) -> None:
    """A metadata entry's attributes are checked like any other entry's."""
    link = entry("__MACOSX/._0.glb", mode=stat.S_IFLNK | 0o777)

    assert "symbolic link" in refused(tileset_zip(tmp_path / "t.zip", (link, b"/etc")))


def test_a_file_that_is_not_a_zip_is_refused(tmp_path: Path) -> None:
    """A renamed non-archive is refused as one."""
    path = tmp_path / "t.zip"
    path.write_bytes(b"not a zip at all" * 100)

    assert "not a valid ZIP" in refused(str(path))


# --- 5. Versions ---------------------------------------------------------


@pytest.mark.parametrize("version", ["1.0", "1.1"])
def test_versions_one_and_one_point_one_are_accepted(
    tmp_path: Path, version: str
) -> None:
    """asset.version 1.0 and 1.1 are read into the facts."""
    facts = inspect_tileset(tileset_zip(tmp_path / "t.zip", version=version)).facts

    assert facts.version == version


@pytest.mark.parametrize("version", ["0.0", "2.0", "1.2", 1.0, None, ""])
def test_any_other_version_is_refused(tmp_path: Path, version: object) -> None:
    """Any other value, or a number instead of a string, is refused."""
    assert "asset.version" in refused(tileset_zip(tmp_path / "t.zip", version=version))


@pytest.mark.parametrize(
    "document",
    [b"[1, 2]", b"{not json", b'{"asset": {"version": "1.0"}, "x": NaN}', b"\xff\xfe"],
    ids=["array", "malformed", "nan", "not-utf8"],
)
def test_a_tileset_json_that_is_not_a_json_object_is_refused(
    tmp_path: Path, document: bytes
) -> None:
    """The entry point must be a UTF-8 JSON object with finite numbers."""
    path = build_zip(tmp_path / "t.zip", [("tileset.json", document)])

    assert "tileset.json" in refused(path)


@pytest.mark.parametrize(
    "json_kw",
    [
        {"volume": {"region": [0, 0, 0]}},
        {"volume": {"box": [0] * 11}},
        {"volume": {"sphere": [0, 0, 0, True]}},
        {"volume": {"cylinder": [0] * 6}},
        {"volume": {"region": [0.1, 1.0, 0.2, 0.9, 0, 1]}},
        {"volume": {"region": [4.0, 0.0, 4.1, 0.1, 0, 1]}},
        {"geometric_error": -1},
        {"geometric_error": "70"},
    ],
    ids=[
        "short-region",
        "short-box",
        "bool-in-sphere",
        "no-core-volume",
        "south-north-swapped",
        "longitude-out-of-range",
        "negative-error",
        "string-error",
    ],
)
def test_a_malformed_root_is_refused(tmp_path: Path, json_kw: dict) -> None:
    """The root's bounding volume and geometric error must be well formed."""
    refused(tileset_zip(tmp_path / "t.zip", **json_kw))


# --- 11. Content URIs ----------------------------------------------------


def _with_content(uri: str, *, where: str = "root") -> dict:
    tile = {"boundingVolume": {"sphere": [0, 0, 0, 1]}, "geometricError": 0}
    if where == "root":
        return {"content": {"uri": uri}}
    if where == "child":
        return {"children": [{**tile, "content": {"uri": uri}}]}
    if where == "contents":
        return {"contents": [{"uri": "0/0.glb"}, {"uri": uri}]}
    if where == "legacy-url":
        return {"content": {"url": uri}}
    return {"implicitTiling": {"subtrees": {"uri": uri}}}


def _tileset_with_root(root_extra: dict) -> bytes:
    document = json.loads(tileset_json())
    document["root"].update(root_extra)
    return json.dumps(document).encode()


@pytest.mark.parametrize(
    "uri",
    [
        "https://example.com/0/0.b3dm",
        "data:application/octet-stream;base64,AAAA",
        "/srv/tiles/0.glb",
        "C:/tiles/0.glb",
        "..\\0.glb",
        "../0.glb",
        "0/../../0.glb",
        "%2e%2e/0.glb",
        "0/%2E%2E/%2e%2e/0.glb",
    ],
    ids=[
        "http",
        "data",
        "absolute-path",
        "drive-letter",
        "backslash",
        "dotdot",
        "climbs-out-later",
        "encoded-dotdot",
        "encoded-dotdot-later",
    ],
)
@pytest.mark.parametrize(
    "where", ["root", "child", "contents", "legacy-url", "implicit-subtrees"]
)
def test_content_outside_the_tileset_is_refused(
    tmp_path: Path, uri: str, where: str
) -> None:
    """Every content and subtree URI in the tile tree must stay inside the tileset."""
    path = build_zip(
        tmp_path / "t.zip",
        [("tileset.json", _tileset_with_root(_with_content(uri, where=where)))],
    )

    message = refused(path)

    assert "names content outside the tileset" in message
    assert uri not in message


@pytest.mark.parametrize(
    "uri",
    ["0/0.glb", "0/../0/0.glb", "./0/0.glb", "sub/tileset.json", "0/0.glb?v=2#x"],
)
def test_content_inside_the_tileset_is_accepted(tmp_path: Path, uri: str) -> None:
    """A relative path that stays under tileset.json's folder is fine."""
    path = build_zip(
        tmp_path / "t.zip",
        [("tileset.json", _tileset_with_root(_with_content(uri, where="child")))],
    )

    assert inspect_tileset(path).facts.version == "1.1"


def _external(*uris: str) -> bytes:
    """A tileset whose child tiles name ``uris``."""
    document = json.loads(tileset_json())
    document["root"]["children"] = [{"content": {"uri": uri}} for uri in uris]
    return json.dumps(document).encode()


def _nested_zip(path: Path, *files: tuple[str, bytes]) -> str:
    """tileset.json naming the external tileset sub/tileset.json, plus ``files``."""
    return build_zip(path, [("tileset.json", _external("sub/tileset.json")), *files])


@pytest.mark.parametrize(
    "uri",
    ["https://example.com/0.glb", "../../0.glb", "/srv/0.glb", "..%2F..%2F0.glb"],
    ids=["absolute", "climbs-out", "absolute-path", "encoded-climb"],
)
def test_an_external_tileset_is_held_to_the_same_rules(
    tmp_path: Path, uri: str
) -> None:
    """Content an external tileset names must stay inside the tileset too."""
    path = _nested_zip(tmp_path / "t.zip", ("sub/tileset.json", _external(uri)))

    message = refused(path, external=True)

    assert "sub/tileset.json names content outside the tileset" in message
    assert uri not in message


def test_an_external_tileset_named_in_another_case_is_checked(tmp_path: Path) -> None:
    """A case-insensitive disk would serve it under that name, so it is read."""
    path = build_zip(
        tmp_path / "t.zip",
        [
            ("tileset.json", _external("SUB/TileSet.json")),
            ("sub/tileset.json", _external("https://example.com/0.glb")),
        ],
    )

    message = refused(path, external=True)

    assert "sub/tileset.json names content outside" in message


def test_an_external_tileset_two_levels_down_is_checked(tmp_path: Path) -> None:
    """The walk follows the external tilesets an external tileset names."""
    path = _nested_zip(
        tmp_path / "t.zip",
        ("sub/tileset.json", _external("deeper/tileset.json")),
        ("sub/deeper/tileset.json", _external("../../../0.glb")),
    )

    message = refused(path, external=True)

    assert "sub/deeper/tileset.json names content outside" in message


def test_an_external_tileset_may_name_content_anywhere_inside(tmp_path: Path) -> None:
    """'..' from an external tileset's folder is fine while it stays inside."""
    path = _nested_zip(
        tmp_path / "t.zip",
        ("sub/tileset.json", _external("../0/0.glb", "deeper/t.json", "gone.json")),
        ("sub/deeper/t.json", _external("../../0/0.glb")),
        ("0/0.glb", b"glb"),
    )

    assert inspect_tileset(path, external=True).facts.version == "1.1"


def test_external_tilesets_that_cycle_are_read_once_each(
    tmp_path: Path, monkeypatch
) -> None:
    """Tilesets that name each other end the walk, each read a single time."""
    reads: list[str] = []
    read = tileset_module._read_tileset_json

    def _counted(archive, info, name):
        reads.append(name)
        return read(archive, info, name)

    monkeypatch.setattr(tileset_module, "_read_tileset_json", _counted)
    path = _nested_zip(
        tmp_path / "t.zip",
        ("sub/tileset.json", _external("../other.json", "../tileset.json")),
        ("other.json", _external("sub/tileset.json")),
    )

    inspect_tileset(path, external=True)

    assert sorted(reads) == ["other.json", "sub/tileset.json", "tileset.json"]


@pytest.mark.parametrize(
    ("bound", "value"),
    [("MAX_EXTERNAL_TILESETS", 1), ("MAX_EXTERNAL_TILESET_BYTES", 100)],
    ids=["count", "bytes"],
)
def test_external_tilesets_past_a_cap_are_refused(
    tmp_path: Path, monkeypatch, bound: str, value: int
) -> None:
    """The walk reads a bounded number of files and bytes of JSON."""
    monkeypatch.setattr(tileset_module, bound, value)
    path = build_zip(
        tmp_path / "t.zip",
        [
            ("tileset.json", _external("a.json", "b.json")),
            ("a.json", _external()),
            ("b.json", _external()),
        ],
    )

    assert "more external tilesets than this server reads" in refused(
        path, external=True
    )


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"pad": "x" * 2048}, "is larger than"),
        (_nested(MAX_TILESET_JSON_DEPTH + 1), "nests deeper"),
    ],
    ids=["size", "depth"],
)
def test_an_external_tileset_is_held_to_the_json_bounds(
    tmp_path: Path, monkeypatch, extra: dict, message: str
) -> None:
    """An external tileset is read within tileset.json's size and depth bounds."""
    monkeypatch.setattr(tileset_module, "MAX_TILESET_JSON_BYTES", 1024)
    nested = {**json.loads(_external()), **extra}
    path = _nested_zip(
        tmp_path / "t.zip", ("sub/tileset.json", json.dumps(nested).encode())
    )

    assert f"sub/tileset.json {message}" in refused(path, external=True)


# --- 10. Extent ----------------------------------------------------------


def test_a_region_becomes_the_extent_in_degrees(tmp_path: Path) -> None:
    """Radians convert to degrees without reordering."""
    facts = inspect_tileset(tileset_zip(tmp_path / "t.zip")).facts

    assert facts.bounding_volume == "region"
    assert facts.geometric_error == 70.0
    assert facts.extent_bbox == pytest.approx(
        tuple(math.degrees(v) for v in REGION[:4])
    )


def test_an_antimeridian_region_keeps_west_greater_than_east(tmp_path: Path) -> None:
    """A crossing region reads as the west > east pair, never its complement."""
    region = [math.radians(170), -0.3, math.radians(-170), -0.2, 0, 10]
    facts = inspect_tileset(
        tileset_zip(tmp_path / "t.zip", volume={"region": region})
    ).facts

    west, _, east, _ = facts.extent_bbox
    assert west == pytest.approx(170.0)
    assert east == pytest.approx(-170.0)


def test_a_region_that_rounds_pi_up_is_clamped(tmp_path: Path) -> None:
    """A writer's rounding past pi still reads as the antimeridian."""
    region = [-3.14159265359, -1.5707963268, 3.14159265359, 1.5707963268, 0, 1]
    facts = inspect_tileset(
        tileset_zip(tmp_path / "t.zip", volume={"region": region})
    ).facts

    assert facts.extent_bbox == (-180.0, -90.0, 180.0, 90.0)


@pytest.mark.parametrize(
    ("volume", "kind"),
    [({"box": [0.0] * 12}, "box"), ({"sphere": [0.0, 0.0, 0.0, 10.0]}, "sphere")],
)
def test_a_box_or_sphere_leaves_the_extent_null(
    tmp_path: Path, volume: dict, kind: str
) -> None:
    """Only a region yields an extent; the kind says why there is none."""
    facts = inspect_tileset(tileset_zip(tmp_path / "t.zip", volume=volume)).facts

    assert facts.bounding_volume == kind
    assert facts.extent_bbox is None


def test_a_missing_geometric_error_is_null(tmp_path: Path) -> None:
    """The root's geometricError is optional in what the catalog stores."""
    facts = inspect_tileset(tileset_zip(tmp_path / "t.zip", geometric_error=None)).facts

    assert facts.geometric_error is None


# --- The probe reads only the directory and tileset.json -----------------


@pytest.fixture(params=["local", "s3"])
def storage(request, tmp_path, monkeypatch):
    """The local adapter, or the S3 adapter against a moto bucket."""
    monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path / "staging"))
    (tmp_path / "staging").mkdir()
    if request.param == "local":
        yield LocalStorageProvider(base_dir=str(tmp_path / "store"))
        return
    credential = uuid.uuid4().hex
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, credential)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="tiles3d")
        yield S3StorageProvider(
            bucket="tiles3d",
            region="us-east-1",
            access_key_id=credential,
            secret_access_key=credential,
        )


class _CountingReads:
    def __init__(self, storage) -> None:
        self._storage = storage
        self.bytes_read = 0

    def __getattr__(self, name):
        return getattr(self._storage, name)

    async def get_range(self, key: str, start: int, length: int) -> bytes:
        data = await self._storage.get_range(key, start, length)
        self.bytes_read += len(data)
        return data


async def test_a_stored_archive_is_read_without_downloading_it(
    tmp_path: Path, storage
) -> None:
    """The probe reads the tail, the directory and tileset.json, and agrees with a local read."""
    path = build_zip(
        tmp_path / "t.zip",
        [
            ("campus/tileset.json", tileset_json(version="1.0")),
            *((f"campus/0/{i}.glb", os.urandom(256 * 1024)) for i in range(8)),
        ],
        compression=zipfile.ZIP_STORED,
    )
    await storage.put("staging/job/frozen/t.zip", io.BytesIO(Path(path).read_bytes()))
    counting = _CountingReads(storage)

    stored = await inspect_stored_tileset(counting, "staging/job/frozen/t.zip")
    local = inspect_tileset(path)

    assert stored.facts == local.facts
    assert (
        stored.layout.unpacked_bytes
        == local.layout.unpacked_bytes
        == (8 * 256 * 1024 + len(tileset_json(version="1.0")))
    )
    assert counting.bytes_read < 128 * 1024
    assert not any((tmp_path / "staging").iterdir())


async def test_a_stored_archive_that_fails_a_check_is_refused(
    tmp_path: Path, storage
) -> None:
    """The probe applies the same checks as a local read."""
    path = tileset_zip(tmp_path / "t.zip", ("../escape.glb", b"x"))
    await storage.put("staging/job/frozen/t.zip", io.BytesIO(Path(path).read_bytes()))

    with pytest.raises(UnsafeUploadError, match="below the archive root"):
        await inspect_stored_tileset(storage, "staging/job/frozen/t.zip")


@functools.cache
def _zip64_tileset(extensible: int) -> bytes:
    """A tileset with more entries than a classic end record counts.

    ``extensible`` bytes of ZIP64 extensible data move the ZIP64 end record
    that much further from the end of the file.
    """
    data = zip_bytes(
        [("tileset.json", tileset_json()), *((f"t/{i}", b"") for i in range(0x10000))],
        compression=zipfile.ZIP_STORED,
    )
    record = data.rindex(b"PK\x06\x06")
    (length,) = struct.unpack_from("<Q", data, record + 4)
    return (
        data[: record + 4]
        + struct.pack("<Q", length + extensible)
        + data[record + 12 : record + 56]
        + bytes(extensible)
        + data[record + 56 :]
    )


@pytest.mark.parametrize("extensible", [0, 70_000], ids=["zip64", "extensible-data"])
async def test_a_zip64_end_record_is_found_through_its_locator(
    tmp_path: Path, storage, extensible: int
) -> None:
    """A ZIP64 archive is read wherever its locator puts the end record."""
    data = _zip64_tileset(extensible)
    path = tmp_path / "t.zip"
    path.write_bytes(data)
    await storage.put("staging/job/frozen/t.zip", io.BytesIO(data))

    stored = await inspect_stored_tileset(storage, "staging/job/frozen/t.zip")
    local = inspect_tileset(str(path))

    assert stored.layout.entry_count == local.layout.entry_count == 0x10001
    assert stored.facts == local.facts
