"""Detector for unscoped finding markers in ``backend/app`` documentation.

Stdlib only and importable without ``app.core.config``, so the pre-commit
hook runs ``main()`` directly. AGENTS.md > Inline review-comment convention.
"""

from __future__ import annotations

import ast
import io
import re
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

# A coded finding id (`SEC-002`, `T-1214-17`, `PERF-N5`, `IA-P0-01`). The
# numeric tail excludes `AUTO-GENERATED` and a `^[A-Z]+$` regex; the uppercase
# segments exclude GHSA ids and `X-Esri-Authorization`.
MARKER_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-[A-Z]?[0-9]+[A-Z0-9]*\b")

# An agent or tool name used as a comment tag. No general shape covers this
# half, so it is a denylist and says so.
AGENT_TAG_RE = re.compile(r"(?i)\b(ponytail)\s*:")

# What makes a marker scoped: an issue or PR number a reader can look up.
# Two digits minimum, so `Pitfall #5` and a `#1f2937` colour do not count.
ANCHOR_RE = re.compile(r"#\d{2,6}\b|\bGH-\d{2,6}\b|\bCVE-\d{4}-\d{4,7}\b")

# Tokens carrying the marker SHAPE that name a published standard, so they
# resolve for any reader. A literal list, not a prefix family: `ISO-8601` is
# vocabulary and `ISO-01` is a finding id, and no `ISO-` rule separates them.
TECHNICAL_VOCABULARY = frozenset(
    {
        # Encodings, hashes, curves, coordinate reference systems.
        "AES-128",
        "AES-256",
        "EPSG-3857",
        "EPSG-4326",
        "IEEE-754",
        "ISO-3166-1",
        "ISO-639-1",
        "ISO-8601",
        "NAMEDATALEN-1",
        "P-256",
        "P-384",
        "SHA-1",
        "SHA-256",
        "SHA-384",
        "SHA-512",
        "UTF-7",
        "UTF-8",
        "UTF-16",
        "UTF-32",
        "WGS-84",
        # NIST SP 800-53 control ids, cited in the audit-sink and config-export
        # prose. `AU-5` is the one present; the rest are its immediate family.
        "AC-3",
        "AU-5",
        "AU-9",
        "CM-6",
        "IA-5",
        "SC-8",
        "SI-4",
        # Arithmetic, not an id: "keys 0..N-1", "commit N-1 renames".
        "N-1",
    }
)


class MarkerScanError(RuntimeError):
    """A source file the detector could not read. Always names the file."""


@dataclass(frozen=True)
class Unit:
    """One run of comment lines, or one docstring, with its first line number."""

    kind: str
    lineno: int
    text: str


@dataclass(frozen=True)
class Hit:
    """A documentation line carrying finding markers with no anchor near it."""

    module: str
    lineno: int
    kind: str
    markers: tuple[str, ...]

    def describe(self) -> str:
        return (
            f"{self.module}:{self.lineno} ({self.kind}) "
            f"{', '.join(self.markers)} — no #issue anchor"
        )


# How far from a marker an anchor may sit and still scope it. AGENTS.md caps
# an inline review comment at three lines, so an anchor leading (or trailing)
# its own block reaches its markers and a long docstring's does not.
ANCHOR_WINDOW = 2


def _comment_units(source: str, module: str) -> list[Unit]:
    """Group comment tokens into runs of consecutive lines."""
    units: list[Unit] = []
    run: list[tokenize.TokenInfo] = []

    def flush() -> None:
        if run:
            units.append(
                Unit("comment", run[0].start[0], "\n".join(t.string for t in run))
            )
            run.clear()

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
        raise MarkerScanError(f"{module}: could not tokenize: {exc}") from exc
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        if run and token.start[0] != run[-1].start[0] + 1:
            flush()
        run.append(token)
    flush()
    return units


def _docstring_units(source: str, module: str) -> list[Unit]:
    """Every bare string expression statement, docstring or attribute doc."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise MarkerScanError(f"{module}: could not parse: {exc}") from exc
    units: list[Unit] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Expr):
            continue
        value = node.value
        if isinstance(value, ast.JoinedStr):
            # An f-string statement has no static text to read. No site in
            # app/ has one; report rather than skip if that ever changes.
            raise MarkerScanError(
                f"{module}:{node.lineno}: f-string expression statement is not readable"
            )
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            units.append(Unit("docstring", node.lineno, value.value))
    return units


def iter_units(source: str, module: str) -> list[Unit]:
    """All documentation units in one module, comments and docstrings alike."""
    return _comment_units(source, module) + _docstring_units(source, module)


def markers_in(text: str) -> tuple[str, ...]:
    """Finding markers in one unit, vocabulary removed, sorted and deduped."""
    found = {t for t in MARKER_RE.findall(text) if t not in TECHNICAL_VOCABULARY}
    found.update(m.group(1) for m in AGENT_TAG_RE.finditer(text))
    return tuple(sorted(found))


def scan_module(module: str, source: str) -> list[Hit]:
    """Unanchored marker-bearing lines in one module's documentation."""
    hits = []
    for unit in iter_units(source, module):
        lines = unit.text.splitlines()
        anchored = [ANCHOR_RE.search(line) is not None for line in lines]
        for offset, line in enumerate(lines):
            markers = markers_in(line)
            if not markers:
                continue
            low = max(0, offset - ANCHOR_WINDOW)
            high = offset + ANCHOR_WINDOW + 1
            if any(anchored[low:high]):
                continue
            hits.append(Hit(module, unit.lineno + offset, unit.kind, markers))
    return hits


def scan_tree(app_root: Path = APP_ROOT) -> tuple[list[Hit], int, int]:
    """Scan every module under ``app_root``. Returns (hits, modules, units)."""
    hits: list[Hit] = []
    modules = 0
    units = 0
    for path in sorted(app_root.rglob("*.py")):
        module = path.relative_to(app_root).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise MarkerScanError(f"{module}: could not read: {exc}") from exc
        modules += 1
        units += len(iter_units(source, module))
        hits.extend(scan_module(module, source))
    return hits, modules, units


# Floors, so a collapsed glob or a moved APP_ROOT fails loudly instead of
# reporting zero findings and passing (#1552). `main` carries 431 modules and
# 9602 units.
MIN_SCANNED_MODULES = 350
MIN_SCANNED_UNITS = 7000

# The unanchored markers already on main, counted per MARKER and frozen per
# module, EXACT in both directions. Residual: swapping one id for another on a
# line already counted still passes; catching that needs a per-module multiset.
UNANCHORED_MARKER_DEBT: dict[str, int] = {
    "api/main.py": 31,
    "api/middleware/body_limit.py": 8,
    "api/middleware/logging.py": 2,
    "api/middleware/security.py": 7,
    "api/middleware/tenant_context.py": 7,
    "core/catalog_port.py": 1,
    "core/config.py": 30,
    "core/crs_uri.py": 10,
    "core/db/rls.py": 6,
    "core/db/schema_skew.py": 3,
    "core/db/session.py": 2,
    "core/db/tenant_schema.py": 3,
    "core/db/tenant_session.py": 7,
    "core/edition.py": 6,
    "core/identity.py": 3,
    "core/logging_config.py": 4,
    "core/permissions.py": 2,
    "core/persistent_config.py": 15,
    "core/processing_port.py": 16,
    "core/public_urls.py": 10,
    "core/raster_bands.py": 1,
    "core/runtime/staging.py": 2,
    "core/service_tokens.py": 2,
    "core/tenancy.py": 1,
    "modules/admin/backfill_jobs.py": 1,
    "modules/admin/router.py": 15,
    "modules/admin/schemas.py": 4,
    "modules/admin/service.py": 12,
    "modules/audit/events.py": 1,
    "modules/audit/models.py": 2,
    "modules/audit/router.py": 5,
    "modules/audit/schemas.py": 3,
    "modules/audit/service.py": 8,
    "modules/auth/cookies.py": 1,
    "modules/auth/dependencies.py": 5,
    "modules/auth/domain_policy.py": 5,
    "modules/auth/domain_validation.py": 7,
    "modules/auth/models.py": 10,
    "modules/auth/oauth/encryption.py": 1,
    "modules/auth/oauth/router.py": 19,
    "modules/auth/oauth/schemas.py": 11,
    "modules/auth/oauth/service.py": 33,
    "modules/auth/password_policy.py": 1,
    "modules/auth/permissions.py": 2,
    "modules/auth/router.py": 77,
    "modules/auth/schemas.py": 9,
    "modules/auth/service.py": 8,
    "modules/auth/verification.py": 4,
    "modules/auth/verification_email.py": 2,
    "modules/catalog/authorization.py": 1,
    "modules/catalog/collections/models.py": 3,
    "modules/catalog/collections/router.py": 3,
    "modules/catalog/datasets/api/router.py": 3,
    "modules/catalog/datasets/api/router_data.py": 4,
    "modules/catalog/datasets/api/router_export.py": 14,
    "modules/catalog/datasets/api/router_health.py": 2,
    "modules/catalog/datasets/api/router_metadata.py": 2,
    "modules/catalog/datasets/api/router_refresh.py": 2,
    "modules/catalog/datasets/api/router_reupload.py": 11,
    "modules/catalog/datasets/domain/_sql_safety.py": 1,
    "modules/catalog/datasets/domain/models.py": 10,
    "modules/catalog/datasets/domain/schemas.py": 6,
    "modules/catalog/datasets/domain/service.py": 1,
    "modules/catalog/datasets/domain/service_create.py": 1,
    "modules/catalog/datasets/domain/service_relationships.py": 4,
    "modules/catalog/datasets/domain/source_freshness.py": 4,
    "modules/catalog/features/service.py": 3,
    "modules/catalog/maps/_router_helpers.py": 2,
    "modules/catalog/maps/filter_grammar.py": 2,
    "modules/catalog/maps/models.py": 6,
    "modules/catalog/maps/router.py": 11,
    "modules/catalog/maps/router_assets.py": 2,
    "modules/catalog/maps/router_sharing.py": 4,
    "modules/catalog/maps/schemas.py": 15,
    "modules/catalog/maps/service_crud.py": 4,
    "modules/catalog/maps/service_diff.py": 2,
    "modules/catalog/maps/service_public.py": 13,
    "modules/catalog/maps/service_shared.py": 1,
    "modules/catalog/maps/sprites.py": 2,
    "modules/catalog/maps/style_json.py": 5,
    "modules/catalog/search/cache.py": 2,
    "modules/catalog/search/router.py": 10,
    "modules/catalog/search/schemas.py": 1,
    "modules/catalog/search/service_filters.py": 1,
    "modules/catalog/search/service_records.py": 2,
    "modules/catalog/search/service_semantic.py": 2,
    "modules/catalog/sources/adapters/ogcapi.py": 5,
    "modules/catalog/sources/adapters/stac.py": 4,
    "modules/catalog/sources/adapters/wfs.py": 4,
    "modules/catalog/sources/classify.py": 8,
    "modules/catalog/sources/cog_info.py": 1,
    "modules/catalog/sources/origin_probe.py": 3,
    "modules/catalog/sources/preview.py": 3,
    "modules/catalog/sources/probe.py": 11,
    "modules/catalog/sources/router.py": 3,
    "modules/catalog/sources/schemas.py": 1,
    "modules/catalog/sources/stac_resolve_asset_gate.py": 1,
    "modules/catalog/sources/stac_resolve_taxonomy.py": 1,
    "modules/catalog/validation/service.py": 4,
    "modules/embed_tokens/admin_router.py": 5,
    "modules/embed_tokens/models.py": 2,
    "modules/embed_tokens/public_router.py": 1,
    "modules/embed_tokens/router.py": 2,
    "modules/embed_tokens/service.py": 18,
    "modules/embed_tokens/sharing.py": 2,
    "modules/quota/schemas.py": 1,
    "modules/quota/service.py": 7,
    "modules/settings/router.py": 36,
    "modules/settings/router_public.py": 3,
    "modules/settings/schemas.py": 8,
    "modules/tenancy/models.py": 1,
    "observability/health/service.py": 4,
    "platform/assets/urls.py": 7,
    "platform/audit.py": 2,
    "platform/cache/provider.py": 3,
    "platform/cache/tile_cache.py": 7,
    "platform/config_ops/router.py": 2,
    "platform/config_ops/service.py": 1,
    "platform/dataset_origin.py": 4,
    "platform/extensions/__init__.py": 42,
    "platform/extensions/bootstrap.py": 22,
    "platform/extensions/defaults_ai_anthropic.py": 3,
    "platform/extensions/defaults_ai_openai.py": 10,
    "platform/extensions/defaults_catalog_port.py": 1,
    "platform/extensions/defaults_extensions.py": 11,
    "platform/extensions/defaults_processing_port.py": 9,
    "platform/extensions/entitlement.py": 3,
    "platform/extensions/protocols.py": 27,
    "platform/extensions/version.py": 3,
    "platform/jobs/defer_guard.py": 1,
    "platform/jobs/heartbeat.py": 2,
    "platform/jobs/models.py": 4,
    "platform/jobs/router.py": 6,
    "platform/jobs/schemas.py": 7,
    "platform/jobs/sweep.py": 1,
    "platform/jobs/worker.py": 6,
    "platform/notifications/__init__.py": 7,
    "platform/notifications/env_sink.py": 6,
    "platform/notifications/events.py": 9,
    "platform/notifications/smtp_channel.py": 6,
    "platform/notifications/webhook_channel.py": 8,
    "platform/refresh/credentials.py": 2,
    "platform/refresh/models.py": 3,
    "platform/refresh/service.py": 3,
    "platform/sandbox/executor.py": 3,
    "platform/security.py": 9,
    "platform/service_auth.py": 1,
    "platform/storage/azure.py": 2,
    "platform/storage/local.py": 6,
    "platform/storage/provider.py": 6,
    "platform/storage/titiler_url.py": 8,
    "processing/ai/chat_actions.py": 7,
    "processing/ai/chat_constants.py": 1,
    "processing/ai/chat_dataset.py": 1,
    "processing/ai/chat_geojson.py": 1,
    "processing/ai/chat_service.py": 2,
    "processing/ai/chat_styles.py": 1,
    "processing/ai/chat_validation.py": 2,
    "processing/ai/constants.py": 1,
    "processing/ai/llm_loop.py": 10,
    "processing/ai/metadata_service.py": 2,
    "processing/ai/probe.py": 1,
    "processing/ai/router.py": 2,
    "processing/ai/service.py": 1,
    "processing/ai/sql_generator.py": 6,
    "processing/ai/streaming.py": 5,
    "processing/analysis/provenance.py": 2,
    "processing/analysis/tasks.py": 2,
    "processing/embeddings/helpers.py": 3,
    "processing/embeddings/service.py": 7,
    "processing/export/router.py": 5,
    "processing/export/service.py": 3,
    "processing/export/where_validator.py": 4,
    "processing/ingest/layer_guard.py": 1,
    "processing/ingest/manifest_schemas.py": 2,
    "processing/ingest/manifest_service.py": 4,
    "processing/ingest/manifest_sources.py": 1,
    "processing/ingest/metadata_attributes.py": 2,
    "processing/ingest/metadata_extent.py": 10,
    "processing/ingest/metadata_geometry.py": 5,
    "processing/ingest/metadata_mercator.py": 3,
    "processing/ingest/metadata_projection.py": 6,
    "processing/ingest/metadata_sql.py": 1,
    "processing/ingest/ogr.py": 20,
    "processing/ingest/presigned.py": 2,
    "processing/ingest/router.py": 19,
    "processing/ingest/schemas.py": 1,
    "processing/ingest/service.py": 20,
    "processing/ingest/tasks_common.py": 47,
    "processing/ingest/tasks_postgis_refresh.py": 2,
    "processing/ingest/tasks_raster.py": 37,
    "processing/ingest/tasks_raster_common.py": 6,
    "processing/ingest/tasks_raster_replace.py": 4,
    "processing/ingest/tasks_reupload.py": 7,
    "processing/ingest/tasks_stac_refresh.py": 4,
    "processing/ingest/tasks_vector.py": 36,
    "processing/ingest/tasks_vrt.py": 7,
    "processing/ingest/url_fetch.py": 1,
    "processing/ingest/validation.py": 3,
    "processing/ingest/warnings.py": 2,
    "processing/raster/cog.py": 2,
    "processing/raster/models.py": 2,
    "processing/raster/queries.py": 1,
    "processing/raster/validation.py": 7,
    "processing/raster/vrt.py": 5,
    "processing/raster/vrt_rewrite.py": 5,
    "processing/tiles/pool.py": 6,
    "processing/tiles/router.py": 26,
    "processing/tiles/service.py": 16,
    "processing/tiles/signing.py": 5,
    "processing/vector/quicklook.py": 2,
    "standards/ogc/errors.py": 2,
    "standards/ogc/router.py": 16,
    "standards/stac/router.py": 11,
}


def _debt(hits: list[Hit]) -> int:
    """One marker is one unit of debt; two on a line are two."""
    return sum(len(hit.markers) for hit in hits)


def check(app_root: Path = APP_ROOT) -> list[str]:
    """Every way the tree violates the gate, as printable lines."""
    hits, modules, units = scan_tree(app_root)
    problems: list[str] = []

    if modules < MIN_SCANNED_MODULES:
        problems.append(
            f"scanned {modules} modules under {app_root}, floor is "
            f"{MIN_SCANNED_MODULES} — the scan is not seeing the tree"
        )
    if units < MIN_SCANNED_UNITS:
        problems.append(
            f"read {units} comment/docstring units, floor is {MIN_SCANNED_UNITS}"
            " — the scan is not seeing the documentation"
        )

    by_module: dict[str, list[Hit]] = {}
    for hit in hits:
        by_module.setdefault(hit.module, []).append(hit)

    for module, module_hits in sorted(by_module.items()):
        allowed = UNANCHORED_MARKER_DEBT.get(module, 0)
        if _debt(module_hits) <= allowed:
            continue
        problems.append(
            f"{module}: {_debt(module_hits)} unanchored finding markers, "
            f"{allowed} recorded. Anchor the new one as `fix(#N): <invariant>`, "
            "drop the tag and let the sentence stand, or — if it names a "
            "published standard — add it to TECHNICAL_VOCABULARY:"
        )
        problems.extend(f"    {hit.describe()}" for hit in module_hits)

    for module, allowed in sorted(UNANCHORED_MARKER_DEBT.items()):
        found = _debt(by_module.get(module, []))
        if found < allowed:
            problems.append(
                f"{module}: {found} unanchored finding markers, {allowed} "
                f"recorded. Lower the UNANCHORED_MARKER_DEBT entry to {found}"
                " (or delete it) in backend/tests/finding_markers.py."
            )

    return problems


def main() -> int:
    """Print every violation and return 1, or return 0 on a clean tree."""
    problems = check()
    if not problems:
        return 0
    print("FAIL: unscoped finding markers in backend/app comments or docstrings")
    for line in problems:
        print(f"  {line}")
    print("  See AGENTS.md > Inline review-comment convention.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
