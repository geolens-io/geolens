"""VRT XML rewrite: migrate stored /vsis3/ or /vsiaz/ paths to logical relative paths.

Used by the cross-cloud migration runbook (STOR-04 / Phase 1210) and the
promote state machine (Phase 1214 hook point).

One-pass rewrite: strips the VSI prefix + bucket/container from each
SourceFilename and writes relativeToVRT="1" with the path expressed
RELATIVE TO THE VRT'S OWN DIRECTORY.

CR-01 fix: the old code wrote the FULL logical key as the relative path,
which GDAL resolves relative to the VRT's directory, producing a
nonexistent double path (``rasters/abc/rasters/abc/...``). Fixed via
``posixpath.relpath(logical_key, posixpath.dirname(vrt_storage_key))`` —
the caller must supply ``vrt_storage_key``.

VRT-of-VRT sources are treated like any raster source (the regex strips
the VSI prefix regardless of extension); a migration must iterate ALL
stored .vrt assets in ``catalog.vrt_source_links`` position order.

Idempotent: an already-relative SourceFilename is left unchanged, so a
second pass writes nothing.

STOR-05 lint allowlist: this file matches /vsis3/ and /vsiaz/ only to
STRIP them; no VSI prefix is ever CONSTRUCTED here (that's
resolve_open_path's job).
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path
from xml.etree.ElementTree import ElementTree, parse


# VSI prefix patterns to strip, capturing the logical key (everything after
# the bucket/container segment):
#   /vsis3/{bucket}/logical/key.tif  ->  logical/key.tif
#   /vsiaz/{container}/logical/key.tif -> logical/key.tif
#
# NOTE: this regex purposefully matches /vsis3/ and /vsiaz/ literals — this
# file is on the STOR-05 seam-lint allowlist (test_stor_vsi_seam_lint.py).
_VSI_STRIP_RE = re.compile(r"^(?:/vsis3/[^/]+/|/vsiaz/[^/]+/)(.+)$")


def rewrite_vrt_sources(
    vrt_path: Path,
    *,
    vrt_storage_key: str | None = None,
    dry_run: bool = False,
) -> list[str]:
    """Rewrite SourceFilename nodes in-place to use relativeToVRT="1" paths.

    For each node matching a provider-specific VSI prefix (including nested
    VRT-of-VRT SimpleSource blocks): strips the prefix to the logical key,
    computes the path relative to the VRT's own directory
    (``posixpath.relpath(logical_key, posixpath.dirname(vrt_storage_key))``),
    and sets ``relativeToVRT="1"``. ``vrt_storage_key=None`` falls back to
    the full logical key (legacy, pre-CR-01) — only standalone migration
    scripts hit this; ingest call sites always supply it.

    ``dry_run=True`` returns the change list without writing;
    ``dry_run=False`` (default) writes only if changes were found
    (idempotent write guard).

    ORDERING CONTRACT (load-bearing for tasks_vrt.py): must run AFTER
    metadata extraction and quicklook generation — the in-flight tmp .vrt
    those read must still hold concrete, resolvable VSI paths. Only the
    STORED copy is rewritten to logical keys.

    Args:
        vrt_path: Path to the .vrt file to rewrite (in-place when not dry_run).
        vrt_storage_key: The storage key at which the VRT will be/is stored.
            None uses the full logical key as-is (legacy fallback).
        dry_run: If True, return changes without writing. Default: False.

    Returns:
        List of audit strings, one per changed node: ``"{old_path} -> {new_path}"``.
    """
    tree: ElementTree = parse(str(vrt_path))
    root = tree.getroot()
    changes: list[str] = []

    # Derive the VRT's directory within the bucket/container once (POSIX).
    # e.g. "rasters/abc/sha/source.vrt" -> "rasters/abc/sha"
    vrt_dir: str | None = (
        posixpath.dirname(vrt_storage_key) if vrt_storage_key else None
    )

    for node in root.iter("SourceFilename"):
        src = node.text or ""
        m = _VSI_STRIP_RE.match(src)
        if m:
            logical = m.group(1)
            if vrt_dir is not None:
                # Compute the path of the source file relative to the VRT's
                # own directory in the bucket/container.  This is what GDAL
                # resolves at open-time when relativeToVRT="1".
                relative = posixpath.relpath(logical, vrt_dir)
            else:
                # Legacy fallback: caller did not supply vrt_storage_key.
                relative = logical
            changes.append(f"{src} -> {relative}")
            node.text = relative
            node.set("relativeToVRT", "1")

    if changes and not dry_run:
        tree.write(str(vrt_path), encoding="utf-8", xml_declaration=True)

    return changes
