"""Every file in a tileset archive is read for a URI that leaves the tileset."""

from __future__ import annotations

import json
import struct
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest

from app.core.upload_errors import UnsafeUploadError
from app.processing.ingest import tileset as tileset_module
from app.processing.ingest import tileset_content
from app.processing.ingest.tileset import inspect_tileset
from app.processing.ingest.tileset_content import check_archive_uris
from tests.tiles3d_archives import (
    GLB_BIN,
    GLB_JSON,
    b3dm,
    build_zip,
    cmpt,
    glb,
    gltf_json,
    i3dm,
    subtree,
    tileset_json,
)

DATA_URI = "data:application/octet-stream;base64,AAAA"


def scan(path: str) -> None:
    check_archive_uris(path, inspect_tileset(path).layout)


def refused(path: str) -> str:
    with pytest.raises(UnsafeUploadError) as refusal:
        scan(path)
    return str(refusal.value)


def archive(tmp_path: Path, *files: tuple[str, bytes]) -> str:
    """tileset.json plus ``files``, which it need not name."""
    return build_zip(tmp_path / "t.zip", [("tileset.json", tileset_json()), *files])


def _nested_tileset(**root: object) -> bytes:
    document = json.loads(tileset_json())
    document["root"].update(root)
    return json.dumps(document).encode()


def _buffers(uri: str) -> bytes:
    return gltf_json(buffers=[{"uri": uri, "byteLength": 4}])


def _images(uri: str) -> bytes:
    return gltf_json(images=[{"uri": uri}])


def _gltf_1(field: str, uri: str) -> bytes:
    return json.dumps(
        {"asset": {"version": "1.0"}, field: {"x": {"uri": uri}}}
    ).encode()


def _subtree_json(uri: str) -> bytes:
    return json.dumps({"buffers": [{"uri": uri, "byteLength": 4}]}).encode()


def _last_json_chunk(uri: str) -> bytes:
    """A GLB whose second JSON chunk, the one CesiumJS keeps, names ``uri``."""
    return glb(
        b"",
        chunks=[
            (GLB_JSON, gltf_json() + b"  "),
            (GLB_BIN, bytes(4)),
            (GLB_JSON, _buffers(uri) + b" " * (-len(_buffers(uri)) % 4)),
        ],
    )


# Each carrier makes one file of the archive, one folder down, naming ``uri``,
# and says whether a data: URI is fine there: it is for a schema, buffer,
# image or shader, but inline content or a subtree could name anything.
CARRIERS: dict[str, tuple[Callable[[str], tuple[str, bytes]], bool]] = {
    "external-tileset-content": (
        lambda uri: ("sub/tileset.json", _nested_tileset(content={"uri": uri})),
        False,
    ),
    "external-tileset-schema": (
        lambda uri: ("sub/tileset.json", tileset_json(extra={"schemaUri": uri})),
        True,
    ),
    "external-tileset-metadata-extension": (
        lambda uri: (
            "sub/tileset.json",
            tileset_json(
                extra={"extensions": {"3DTILES_metadata": {"schemaUri": uri}}}
            ),
        ),
        True,
    ),
    "multiple-contents-extension": (
        lambda uri: (
            "sub/tileset.json",
            _nested_tileset(
                extensions={"3DTILES_multiple_contents": {"contents": [{"uri": uri}]}}
            ),
        ),
        False,
    ),
    "implicit-tiling-extension": (
        lambda uri: (
            "sub/tileset.json",
            _nested_tileset(
                extensions={"3DTILES_implicit_tiling": {"subtrees": {"uri": uri}}}
            ),
        ),
        False,
    ),
    "gltf-buffer": (lambda uri: ("0/model.gltf", _buffers(uri)), True),
    "gltf-image": (lambda uri: ("0/model.gltf", _images(uri)), True),
    "gltf-structural-metadata": (
        lambda uri: (
            "0/model.gltf",
            gltf_json(extensions={"EXT_structural_metadata": {"schemaUri": uri}}),
        ),
        True,
    ),
    "gltf-feature-metadata": (
        lambda uri: (
            "0/model.gltf",
            gltf_json(extensions={"EXT_feature_metadata": {"schemaUri": uri}}),
        ),
        True,
    ),
    "gltf-1.0-buffer": (lambda uri: ("0/model.gltf", _gltf_1("buffers", uri)), True),
    "gltf-1.0-image": (lambda uri: ("0/model.gltf", _gltf_1("images", uri)), True),
    "gltf-1.0-shader": (lambda uri: ("0/model.gltf", _gltf_1("shaders", uri)), True),
    "techniques-webgl-shader": (
        lambda uri: (
            "0/model.gltf",
            gltf_json(extensions={"KHR_techniques_webgl": {"shaders": [{"uri": uri}]}}),
        ),
        True,
    ),
    "glb": (lambda uri: ("0/model.glb", glb(_buffers(uri))), True),
    "glb-1": (lambda uri: ("0/model.glb", glb(_buffers(uri), version=1)), True),
    "glb-last-json-chunk": (lambda uri: ("0/model.glb", _last_json_chunk(uri)), True),
    "glb-named-otherwise": (lambda uri: ("0/model.bin", glb(_images(uri))), True),
    "b3dm": (lambda uri: ("0/0.b3dm", b3dm(glb(_images(uri)))), True),
    "b3dm-gltf-json": (lambda uri: ("0/0.b3dm", b3dm(_images(uri))), True),
    "b3dm-legacy-1": (
        lambda uri: ("0/0.b3dm", b3dm(glb(_images(uri)), legacy=1)),
        True,
    ),
    "b3dm-legacy-2": (
        lambda uri: ("0/0.b3dm", b3dm(glb(_images(uri)), legacy=2)),
        True,
    ),
    "i3dm": (lambda uri: ("0/0.i3dm", i3dm(glb(_buffers(uri)))), True),
    "i3dm-gltf-uri": (
        lambda uri: ("0/0.i3dm", i3dm(uri.encode(), gltf_format=0)),
        False,
    ),
    "cmpt": (lambda uri: ("0/0.cmpt", cmpt(b3dm(glb(_buffers(uri))))), True),
    "cmpt-later-tile": (
        lambda uri: (
            "0/0.cmpt",
            cmpt(b3dm(glb(gltf_json())), i3dm(glb(_buffers(uri)))),
        ),
        True,
    ),
    "cmpt-nested": (
        lambda uri: ("0/0.cmpt", cmpt(cmpt(b3dm(glb(_images(uri)))))),
        True,
    ),
    "cmpt-subtree": (lambda uri: ("0/0.cmpt", cmpt(subtree(_subtree_json(uri)))), True),
    "subtree": (lambda uri: ("subtrees/0.subtree", subtree(_subtree_json(uri))), True),
    "subtree-json": (
        lambda uri: (
            "subtrees/0.json",
            json.dumps(
                {"tileAvailability": {"constant": 1}, "buffers": [{"uri": uri}]}
            ).encode(),
        ),
        True,
    ),
}


@pytest.mark.parametrize(
    "uri",
    ["https://example.com/0.bin", "../../0.bin", ":example.com/0.bin"],
    ids=["absolute", "climbs-out", "empty-scheme"],
)
@pytest.mark.parametrize("carrier", CARRIERS)
def test_a_uri_leaving_the_tileset_is_refused_wherever_it_is(
    tmp_path: Path, carrier: str, uri: str
) -> None:
    """Every place a client reads a URI from is held to the tileset.json rule."""
    name, data = CARRIERS[carrier][0](uri)

    message = refused(archive(tmp_path, (name, data)))

    assert f"{name} names content outside the tileset" in message
    assert uri not in message


@pytest.mark.parametrize("carrier", CARRIERS)
def test_a_uri_inside_the_tileset_is_accepted_wherever_it_is(
    tmp_path: Path, carrier: str
) -> None:
    """'..' from a file's folder is fine while it stays inside the tileset."""
    scan(archive(tmp_path, CARRIERS[carrier][0]("../0/0.bin")))


@pytest.mark.parametrize("carrier", CARRIERS)
def test_a_data_uri_is_accepted_where_it_names_nothing_further(
    tmp_path: Path, carrier: str
) -> None:
    """A data: URI is fine for a schema, buffer, image or shader, not for content."""
    make, inline_ok = CARRIERS[carrier]
    path = archive(tmp_path, make(DATA_URI))

    if inline_ok:
        scan(path)
    else:
        assert "names content outside the tileset" in refused(path)


def test_a_file_no_tileset_names_is_checked_too(tmp_path: Path) -> None:
    """Files are read by what they hold, whether or not a tileset names them."""
    path = archive(
        tmp_path, ("unused/tileset.json", _nested_tileset(content={"uri": "/0.glb"}))
    )

    assert "unused/tileset.json names content outside" in refused(path)


@pytest.mark.parametrize(
    "data",
    [
        b'{"buffers": [{"uri": "https://example.com/0.bin"}',
        b"["
        + json.dumps({"buffers": [{"uri": "https://example.com/0.bin"}]}).encode()
        + b"]",
        b'{"buffers": [{"uri": "https://example.com/0.bin"}]}\x00',
        b'{"asset": {"version": "2.0"}}\x89PNG' + bytes(64),
    ],
    ids=["truncated", "not-an-object", "control-byte", "binary"],
)
def test_bytes_a_client_cannot_parse_as_a_json_object_are_skipped(
    tmp_path: Path, data: bytes
) -> None:
    """JSON.parse fails on these, or yields no object, so no URI in them is read."""
    scan(archive(tmp_path, ("0/model.gltf", data), ("0/0.glb", glb(data))))


def test_an_integer_too_long_for_python_does_not_hide_a_document(
    tmp_path: Path,
) -> None:
    """JSON.parse reads any number, so the scan reads past a 5000-digit integer."""
    data = gltf_json(buffers=[{"uri": "https://example.com/0.bin"}])[:-1]
    data += b', "extras": ' + b"1" * 5000 + b"}"

    assert "names content outside" in refused(archive(tmp_path, ("0/m.gltf", data)))


def test_json_nested_too_deeply_to_parse_is_refused(tmp_path: Path) -> None:
    """JSON the scan cannot parse for its depth is refused, not skipped."""
    deep = b'{"extras": ' + b"[" * 2_000_000 + b"]" * 2_000_000 + b"}"
    path = build_zip(
        tmp_path / "t.zip",
        [("tileset.json", tileset_json()), ("0/0.glb", glb(deep))],
        compression=zipfile.ZIP_STORED,
    )

    message = refused(path)

    assert "0/0.glb holds JSON nested too deeply" in message


# --- Hostile headers ------------------------------------------------------


def _past_the_end(uri: str) -> bytes:
    """A b3dm whose tile, GLB and JSON chunk lengths all claim 4 GB."""
    document = _buffers(uri)
    inner = struct.pack("<2I", 0xFFFFFFFF, GLB_JSON) + document
    tile = bytearray(b3dm(struct.pack("<4s2I", b"glTF", 2, 0xFFFFFFFF) + inner))
    struct.pack_into("<I", tile, 8, 0xFFFFFFFF)
    return bytes(tile)


def test_lengths_past_the_end_of_a_file_are_read_to_its_end(tmp_path: Path) -> None:
    """A part that claims more than the file holds is read up to the file's end."""
    outside = archive(tmp_path, ("0/0.b3dm", _past_the_end("https://example.com/0")))
    inside = build_zip(
        tmp_path / "inside.zip",
        [("tileset.json", tileset_json()), ("0/0.b3dm", _past_the_end("0.bin"))],
    )

    assert "0/0.b3dm names content outside" in refused(outside)
    scan(inside)


def test_a_json_chunk_past_the_json_bound_is_refused(
    tmp_path: Path, monkeypatch
) -> None:
    """A JSON chunk that runs to a far end is held to the per-part bound."""
    monkeypatch.setattr(tileset_module, "MAX_TILESET_JSON_BYTES", 1024)
    document = gltf_json(extras="x" * 2048)
    tile = struct.pack("<4s2I", b"glTF", 2, 0xFFFFFFFF)
    tile += struct.pack("<2I", 0xFFFFFFFF, GLB_JSON) + document

    message = refused(archive(tmp_path, ("0/0.glb", tile)))

    assert "0/0.glb holds a JSON or URI part larger than" in message


def test_a_composite_claiming_more_tiles_than_it_holds_stops_at_its_end(
    tmp_path: Path, monkeypatch
) -> None:
    """The walk ends where the file does, however many tiles the header claims."""
    monkeypatch.setattr(tileset_content, "MAX_CONTENT_HEADERS", 10)
    tile = bytearray(cmpt(b3dm(glb(_images("0.png")))))
    struct.pack_into("<I", tile, 12, 0xFFFFFFFF)

    scan(archive(tmp_path, ("0/0.cmpt", bytes(tile))))


@pytest.mark.parametrize("length", [0, 11], ids=["zero", "shorter-than-a-header"])
def test_composite_tiles_that_overlap_are_refused(
    tmp_path: Path, monkeypatch, length: int
) -> None:
    """A tile length that would reread a tile's own header is refused."""
    monkeypatch.setattr(tileset_content, "MAX_CONTENT_HEADERS", 1000)
    inner = bytearray(b"pnts" + bytes(24))
    struct.pack_into("<I", inner, 8, length)
    tile = bytearray(cmpt(bytes(inner)))
    struct.pack_into("<I", tile, 12, 0xFFFFFFFF)

    message = refused(archive(tmp_path, ("0/0.cmpt", bytes(tile))))

    assert "The tile headers in 0/0.cmpt overlap" in message


def test_a_composite_walking_back_over_its_parent_is_refused(tmp_path: Path) -> None:
    """A nested composite that reads past its own length breaks the forward read."""
    child = bytearray(cmpt(b3dm(glb(_images("0.png")))))
    struct.pack_into("<I", child, 8, 16)
    parent = cmpt(bytes(child), b"pnts" + struct.pack("<2I", 1, 28) + bytes(16))

    message = refused(archive(tmp_path, ("0/0.cmpt", parent)))

    assert "The tile headers in 0/0.cmpt overlap" in message


def test_composites_nested_past_the_depth_bound_are_refused(tmp_path: Path) -> None:
    """Composite tiles nest at most MAX_COMPOSITE_DEPTH levels."""
    tile = b3dm(glb(gltf_json()))
    for _ in range(tileset_content.MAX_COMPOSITE_DEPTH):
        tile = cmpt(tile)
    within = archive(tmp_path, ("0/0.cmpt", tile))
    past = build_zip(
        tmp_path / "past.zip",
        [("tileset.json", tileset_json()), ("0/0.cmpt", cmpt(tile))],
    )

    scan(within)
    assert "0/0.cmpt nests composite tiles deeper than" in refused(past)


def test_tile_and_chunk_headers_past_the_budget_are_refused(
    tmp_path: Path, monkeypatch
) -> None:
    """The headers walked across every file share one budget."""
    monkeypatch.setattr(tileset_content, "MAX_CONTENT_HEADERS", 3)
    path = archive(
        tmp_path, ("0/a.glb", glb(gltf_json())), ("0/b.glb", glb(gltf_json()))
    )

    assert "tile and chunk headers" in refused(path)


def test_json_past_the_scan_budget_is_refused(tmp_path: Path, monkeypatch) -> None:
    """The JSON parsed across every file shares one budget."""
    monkeypatch.setattr(tileset_content, "MAX_SCANNED_JSON_BYTES", 2048)
    document = gltf_json(extras="x" * 1024)
    path = archive(tmp_path, ("0/a.gltf", document), ("0/b.gltf", document))

    assert "more JSON than the" in refused(path)
