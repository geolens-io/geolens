"""VRT XML rewrite: migrate stored /vsis3/ or /vsiaz/ paths to logical relative paths.

One-pass rewrite: strips the VSI prefix + bucket/container from each
SourceFilename and writes relativeToVRT="1" with the path expressed relative
to the VRT's own directory. GDAL resolves a relative path against that
directory, so the full logical key would produce a nonexistent double path
(``rasters/abc/rasters/abc/...``); the path is computed with
``posixpath.relpath(logical_key, posixpath.dirname(vrt_storage_key))`` and the
caller must supply ``vrt_storage_key``.

VRT-of-VRT sources are treated like any raster source (the regex strips the
VSI prefix regardless of extension); a migration must iterate all stored .vrt
assets in ``catalog.vrt_source_links`` position order.

Idempotent: an already-relative SourceFilename is left unchanged, so a second
pass writes nothing.

Lint allowlist: this file matches /vsis3/ and /vsiaz/ only to strip them; no
VSI prefix is ever constructed here (that's resolve_open_path's job).
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
# This file is on the VSI seam-lint allowlist (test_stor_vsi_seam_lint.py).
_VSI_STRIP_RE = re.compile(r"^(?:/vsis3/[^/]+/|/vsiaz/[^/]+/)(.+)$")


def rewrite_vrt_sources(
    vrt_path: Path,
    *,
    vrt_storage_key: str,
    dry_run: bool = False,
) -> list[str]:
    """Rewrite SourceFilename nodes in-place to use relativeToVRT="1" paths.

    For each node matching a provider-specific VSI prefix (including nested
    VRT-of-VRT SimpleSource blocks): strips the prefix to the logical key,
    computes the path relative to the VRT's own directory
    (``posixpath.relpath(logical_key, posixpath.dirname(vrt_storage_key))``),
    and sets ``relativeToVRT="1"``.

    ``dry_run=True`` returns the change list without writing; otherwise it
    writes only if changes were found.

    Ordering contract for tasks_vrt.py: this must run after metadata
    extraction and quicklook generation, because the in-flight tmp .vrt those
    read must still hold concrete, resolvable VSI paths. Only the stored copy
    is rewritten to logical keys.

    Args:
        vrt_path: Path to the .vrt file to rewrite (in-place when not dry_run).
        vrt_storage_key: The storage key at which the VRT will be/is stored.
        dry_run: If True, return changes without writing. Default: False.

    Returns:
        List of audit strings, one per changed node: ``"{old_path} -> {new_path}"``.
    """
    tree: ElementTree = parse(str(vrt_path))
    root = tree.getroot()
    changes: list[str] = []

    # The VRT's directory within the bucket/container, e.g.
    # "rasters/abc/sha/source.vrt" -> "rasters/abc/sha".
    vrt_dir = posixpath.dirname(vrt_storage_key)

    for node in root.iter("SourceFilename"):
        src = node.text or ""
        m = _VSI_STRIP_RE.match(src)
        if m:
            logical = m.group(1)
            # What GDAL resolves at open time when relativeToVRT="1".
            relative = posixpath.relpath(logical, vrt_dir)
            changes.append(f"{src} -> {relative}")
            node.text = relative
            node.set("relativeToVRT", "1")

    if changes and not dry_run:
        tree.write(str(vrt_path), encoding="utf-8", xml_declaration=True)

    return changes
