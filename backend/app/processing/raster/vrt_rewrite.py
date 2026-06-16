"""VRT XML rewrite utility: migrate stored /vsis3/ or /vsiaz/ paths to logical relative paths.

Used by:
  - The cross-cloud migration runbook (STOR-04 / Phase 1210).
  - The promote state machine (Phase 1214 hook point — import rewrite_vrt_sources directly).

One-pass rewrite: reads SourceFilename nodes, strips the provider-specific
VSI prefix + bucket/container, and writes relativeToVRT="1" with the path
expressed RELATIVE TO THE VRT FILE'S OWN DIRECTORY within the bucket.

Correct relative-path computation (CR-01 fix):
  If the VRT is stored at  rasters/abc/source.vrt  and the source COG is at
  rasters/abc/source.cog.tif, the relative path is ``source.cog.tif`` (one level,
  same directory).  The previous code wrote the FULL logical key as the relative
  path (e.g. ``rasters/abc/source.cog.tif``), which GDAL resolves relative to the
  VRT's own directory, producing the double-path
  ``rasters/abc/rasters/abc/source.cog.tif`` (nonexistent).

  The fix: after stripping the VSI prefix to obtain the logical key, compute
  posixpath.relpath(logical_key, posixpath.dirname(vrt_storage_key)).  The caller
  must supply vrt_storage_key so this function knows the VRT's own position in the
  bucket/container.

Handles VRT-of-VRT: a SourceFilename pointing to another .vrt file is treated
identically to any raster source — the regex strips the VSI prefix regardless
of the file extension. When migrating a stored VRT collection, the runbook must
iterate ALL stored .vrt assets (using catalog.vrt_source_links position ordering
so nested VRTs are processed in a consistent order).

Running rewrite_vrt_sources twice on the same file is SAFE (idempotent): already-
relative SourceFilename nodes (no VSI prefix) are left unchanged, so the second
pass returns an empty change list and writes nothing.

STOR-05 lint allowlist: this file is explicitly allowed to reference /vsis3/ and
/vsiaz/ because it matches those strings in order to STRIP them. No VSI prefix is
ever CONSTRUCTED here — that is exclusively resolve_open_path's responsibility.
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path
from xml.etree.ElementTree import ElementTree, parse


# VSI prefix patterns to strip — matches the provider-specific prefixes that
# _write_python_vrt and gdalbuildvrt used to bake into stored VRT XML.
# Group 1 captures the logical key (everything after the bucket/container segment).
#
# Patterns covered:
#   /vsis3/{bucket}/logical/key.tif  ->  logical/key.tif
#   /vsiaz/{container}/logical/key.tif -> logical/key.tif
#
# VRT-of-VRT: /vsis3/{bucket}/rasters/2/source.vrt -> rasters/2/source.vrt
#
# NOTE: this regex purposefully matches /vsis3/ and /vsiaz/ literals — this file
# is on the STOR-05 seam-lint allowlist (test_stor_vsi_seam_lint.py).
_VSI_STRIP_RE = re.compile(r"^(?:/vsis3/[^/]+/|/vsiaz/[^/]+/)(.+)$")


def rewrite_vrt_sources(
    vrt_path: Path,
    *,
    vrt_storage_key: str | None = None,
    dry_run: bool = False,
) -> list[str]:
    """Rewrite SourceFilename nodes in-place to use relativeToVRT="1" paths.

    Parses the VRT at ``vrt_path``, iterates ALL SourceFilename nodes (including
    those nested inside VRT-of-VRT SimpleSource blocks), and for each node whose
    text matches a provider-specific VSI prefix pattern:

    - Strips the ``/vsis3/{bucket}/`` or ``/vsiaz/{container}/`` prefix to get
      the logical key (e.g. ``rasters/1/sha/source.cog.tif``)
    - Computes the path RELATIVE TO THE VRT'S OWN DIRECTORY in storage using
      ``posixpath.relpath(logical_key, posixpath.dirname(vrt_storage_key))``
    - Sets ``node.text`` to that relative path (e.g. ``source.cog.tif`` when
      both VRT and COG share the same directory)
    - Sets ``relativeToVRT="1"`` on the node

    When ``vrt_storage_key`` is None the function falls back to using the
    full logical key as the relative path (legacy behaviour, same as before
    the CR-01 fix).  This fallback path only occurs during standalone migration
    scripts that do not know the VRT's storage key; all ingest call sites supply
    ``vrt_storage_key`` explicitly.

    Records each transformation as an ``"{old} -> {new}"`` audit string.

    When ``dry_run=True``: parses the file and returns the change list WITHOUT
    writing anything back to disk (the file's mtime and content are unchanged).

    When ``dry_run=False`` (default): if any changes were found, writes the
    updated tree back to ``vrt_path`` (UTF-8 with XML declaration). If no
    changes were found the file is not touched (idempotent write guard).

    ORDERING CONTRACT (load-bearing for tasks_vrt.py):
    ``rewrite_vrt_sources`` MUST be called AFTER metadata extraction and quicklook
    generation — the in-flight tmp .vrt that feeds ``extract_raster_metadata`` and
    ``generate_quicklook`` must still hold concrete, resolvable VSI paths. Only the
    STORED copy is rewritten to logical keys. See tasks_vrt.py store sites for the
    inline comment that enforces this ordering.

    Args:
        vrt_path: Path to the .vrt file to rewrite (in-place when not dry_run).
        vrt_storage_key: The storage key at which the VRT will be/is stored
            (e.g. ``"rasters/{id}/{sha}/source.vrt"``).  Used to compute the
            correct relative path for each SourceFilename.  When None, the full
            logical key is used as-is (legacy fallback).
        dry_run:  If True, return changes without writing. Default: False.

    Returns:
        List of audit strings, one per changed node: ``"{old_path} -> {new_path}"``.
        Empty list if no nodes matched (file is already provider-agnostic).
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
