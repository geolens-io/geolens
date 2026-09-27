#!/usr/bin/env python3
"""Package four central Amsterdam 3DBAG tiles with their original hierarchy."""

import hashlib
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

BASE = "https://data.3dbag.nl/v20250903/cesium3dtiles/lod12/"
MANIFEST = "tileset-5-416-576.json"
MANIFEST_SHA256 = "9f9e4b0945838f91e2958988bf885d1cf176cb93ac2ff632d9ceb6e18c38ad1f"
CONTENT_SHA256 = {
    "t/9/428/600.glb": "c5b24bfa462824dd710939402e76a1b1dfd9f03f5bd09937634f0184ddc3fc49",
    "t/9/428/602.glb": "924110aa993185fb32b0c516a492a9529cc207946803ca79c5a2f5aa58cbd217",
    "t/9/430/600.glb": "f302b3d27f7dc510a7797932bb3dc359bf570692e650f6f885d6c155a9bb839e",
    "t/9/430/602.glb": "c08ac01c44e3c5733c45d48f0c524f80fc524f07fb663ed54af86f1510c4179a",
}


def fetch_checked(path: str, expected: str) -> bytes:
    with urllib.request.urlopen(BASE + path, timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"Source checksum changed: {path}")
    return data


def content_uris(tile: dict) -> list[str]:
    uris = []
    if tile.get("content"):
        uris.append(tile["content"]["uri"])
    for child in tile.get("children", []):
        uris.extend(content_uris(child))
    return uris


def zip_entry(archive: zipfile.ZipFile, path: str, data: bytes) -> None:
    info = zipfile.ZipInfo(path, date_time=(2025, 9, 3, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, data)


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} OUTPUT.zip", file=sys.stderr)
        return 2
    output = Path(sys.argv[1])
    if output.exists():
        print(f"Refusing to overwrite {output}", file=sys.stderr)
        return 2

    source = json.loads(fetch_checked(MANIFEST, MANIFEST_SHA256))
    tile = source["root"]
    for child_index in (1, 3, 2):
        tile = tile["children"][child_index]
    uris = content_uris(tile)
    if set(uris) != set(CONTENT_SHA256) or len(uris) != 4:
        raise ValueError("The selected 3DBAG tile hierarchy changed")
    selected = {
        "asset": source["asset"],
        "geometricError": tile["geometricError"],
        "root": tile,
    }
    with zipfile.ZipFile(output, "x") as archive:
        zip_entry(
            archive,
            "tileset.json",
            json.dumps(selected, separators=(",", ":")).encode(),
        )
        for uri in uris:
            data = fetch_checked(uri, CONTENT_SHA256[uri])
            if data[:4] != b"glTF":
                raise ValueError(f"Expected GLB content at {uri}")
            zip_entry(archive, uri, data)
    print(
        f"{output}: {output.stat().st_size} bytes, sha256 {hashlib.sha256(output.read_bytes()).hexdigest()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
