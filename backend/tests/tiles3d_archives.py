"""Build 3D Tiles tileset archives for the upload tests."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

REGION = [-1.3197, 0.6988, -1.3196, 0.6989, 0.0, 88.0]


def tileset_json(
    *,
    version: object = "1.1",
    volume: dict | None = None,
    geometric_error: object = 70.0,
    extra: dict | None = None,
) -> bytes:
    root: dict = {"boundingVolume": volume or {"region": REGION}, "refine": "ADD"}
    if geometric_error is not None:
        root["geometricError"] = geometric_error
    return json.dumps(
        {
            "asset": {"version": version},
            "geometricError": 500.0,
            "root": root,
            **(extra or {}),
        }
    ).encode()


def zip_bytes(
    entries: list[tuple[str | zipfile.ZipInfo, bytes]],
    *,
    compression: int = zipfile.ZIP_DEFLATED,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return buffer.getvalue()


def build_zip(
    path: Path,
    entries: list[tuple[str | zipfile.ZipInfo, bytes]],
    *,
    compression: int = zipfile.ZIP_DEFLATED,
) -> str:
    path.write_bytes(zip_bytes(entries, compression=compression))
    return str(path)


def tileset_zip(path: Path, *more: tuple[str | zipfile.ZipInfo, bytes], **json_kw):
    return build_zip(
        path,
        [("tileset.json", tileset_json(**json_kw)), ("0/0.glb", b"glb"), *more],
    )
