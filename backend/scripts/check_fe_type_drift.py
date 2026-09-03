"""OCG-03: FE/SDK type-drift guard.

Checks that ``frontend/src/types/api.ts`` (hand-written TypeScript interfaces)
is a structural subset of ``backend/openapi.json`` (the canonical backend schema).

Design choices
--------------
- **JSON/property-name level comparison** (not openapi-typescript codegen): reads
  ``components.schemas[*].properties`` from ``openapi.json`` and parses FE interface
  property names via a lightweight regex scan.  This avoids shelling out to
  ``npx openapi-typescript`` on every PR (no unpinned npx supply-chain pull, no
  Node.js runtime requirement in backend CI).  A ``--use-openapi-typescript`` flag
  is reserved for a future upgrade once the tool is pinned as a dev dependency.

- **Structural subset rule**: FE is allowed to have EXTRA properties (view-model
  fields, UI-only state); backend properties missing from the FE mirror are drift.

- **Inheritance-aware**: TypeScript ``extends`` relationships are resolved so
  sub-interfaces inherit parent properties (avoids false positives for
  ``DuplicateMapResponse extends MapResponse``).

- **Scope**: comparison is limited to the MAINTAINED_MODELS allowlist (seeded with
  the five tenant-bound models that will gain a ``tenant_id`` in Phase 1207, plus
  the full overlap set for broader coverage).  New models should be added to the
  allowlist as the API surface grows.

- **Known drift handling**: pre-existing drift that is NOT a regression is recorded
  in the ``KNOWN_DRIFT`` dict with a TODO explaining why.  Known drift causes a
  warning (exit 0), not a failure.  New drift (not in ``KNOWN_DRIFT``) causes a
  failure (exit 1).

Usage::

    cd backend
    PYTHONPATH=. uv run python scripts/check_fe_type_drift.py
    # exit 0 = no new drift; exit 1 = drift found (see output for details)

    PYTHONPATH=. uv run python scripts/check_fe_type_drift.py --check-all
    # Also checks schemas outside the maintained allowlist (informational only)

References: OCG-03, T-1206-08
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths (relative to repo root)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_OPENAPI_JSON = _REPO_ROOT / "backend" / "openapi.json"
_FE_TYPES = _REPO_ROOT / "frontend" / "src" / "types" / "api.ts"

# ---------------------------------------------------------------------------
# Five tenant-bound models (Phase 1207 will add tenant_id to these)
# These are the MINIMUM models to hand-audit before tenancy lands (OCG-03).
# ---------------------------------------------------------------------------

TENANT_BOUND_MODELS: list[str] = [
    "MapResponse",
    "DatasetResponse",
    "EmbedTokenResponse",
    "CollectionResponse",
    "MapLayerResponse",  # 'tiles' surface — vector/raster tile token consumers
]

# ---------------------------------------------------------------------------
# Maintained model allowlist (superset of TENANT_BOUND_MODELS)
# These are the models actively maintained in both FE + BE; new drift here
# signals a real contract break.
# ---------------------------------------------------------------------------

MAINTAINED_MODELS: list[str] = TENANT_BOUND_MODELS + [
    "AdminEmbedTokenResponse",
    "AuditLogResponse",
    "CatalogStatsResponse",
    "ColumnStatsResponse",
    "DatasetListResponse",
    "DatasetResponse",
    "DatasetVersionResponse",
    "DuplicateMapResponse",
    "EmbedTokenCreatedResponse",
    "EmbedTokenResponse",
    "JobStatusResponse",
    "MapLayerDiffRequest",
    "MapLayerInput",
    "MapLayerPatch",
    "MapListResponse",
    "MapResponse",
    "MapSummaryResponse",
    "OGCRecordProperties",
    "RasterBandInfo",
    "RasterMetadata",
    "RegisterResponse",
    "UserResponse",
]

# ---------------------------------------------------------------------------
# Known drift: pre-existing backend-property-missing-in-FE cases.
# These are NOT regressions — they reflect intentional FE omissions or
# backend additions not yet propagated to the hand-written FE mirror.
# TODO: resolve each by either adding the FE field or annotating intent.
# ---------------------------------------------------------------------------

KNOWN_DRIFT: dict[str, list[str]] = {
    # MapLayerDiffRequest.fallback_full_replace: backend field for diff fallback.
    # FE builder always sends a full diff; fallback path not needed in FE yet.
    # TODO: add to FE if incremental diff optimization ships.
    "MapLayerDiffRequest": ["fallback_full_replace"],
    # OGCRecordProperties: many metadata fields added server-side for OGC
    # record API but not mirrored in FE (FE uses its own record shaping).
    # TODO: review and add missing fields when FE record detail is extended.
    "OGCRecordProperties": [
        "constraints",
        "distributions",
        "formats",
        "language",
        "lineage",
        "quality_statement",
        "rights",
        "themes",
        "time",
        # fix(#1805 review round 4): proj:code, proj:shape, and raster:bands
        # ARE declared in frontend/src/types/api.ts (added alongside the
        # backend schema in #1805) -- they show as drift only because this
        # checker's FE parser regex (`^\s+(\w+)\??:`) requires a bare
        # identifier property name and cannot match a quoted, colon-
        # containing key like 'proj:code'?:. Not a real omission; remove
        # once the parser learns to match quoted keys too.
        "proj:code",
        "proj:shape",
        "raster:bands",
    ],
    # RasterMetadata.is_dem: added when DEM support landed; FE checks is_dem
    # on the DatasetResponse wrapper, not on the nested RasterMetadata.
    # TODO: redundant — either add to FE mirror or document the explicit choice.
    "RasterMetadata": ["is_dem"],
    # RegisterResponse name collision: the backend AUTH RegisterResponse
    # ({message, next_step}) shares a name with the FE `RegisterResponse`
    # interface, which actually mirrors the UNRELATED dataset-ingest register
    # response ({dataset_id, title, table_name}). The auth response's real FE
    # mirror is the `SignupResponse` interface, which DOES carry both fields.
    # So message/next_step "missing" here is expected, not real drift.
    # TODO: dedupe by renaming one of the two backend RegisterResponse models.
    "RegisterResponse": ["message", "next_step"],
    # EmbedTokenCreatedResponse / AdminEmbedTokenResponse: FE uses 'extends'
    # inheritance — parent properties are inherited and NOT re-declared.
    # The checker resolves inheritance chains and these have no real drift.
    # These should remain EMPTY — if they gain entries, investigate.
    "EmbedTokenCreatedResponse": [],
    "AdminEmbedTokenResponse": [],
}

# ---------------------------------------------------------------------------
# FE TypeScript parser
# ---------------------------------------------------------------------------


def _parse_fe_interfaces(fe_content: str) -> dict[str, dict]:
    """Parse all ``export interface`` declarations from a .ts file.

    Returns a dict mapping interface_name → {
        'props': set[str],     # property names declared directly
        'extends': str | None, # parent interface name (single inheritance only)
    }.

    Limitations:
    - Handles single-level ``extends`` (the codebase uses single inheritance).
    - Does not resolve generic type parameters.
    - Property scan uses a regex matching ``indent + name + '?'? + ':'`` for all camelCase/snake_case
      direct property declarations (optional and required).
    """
    result: dict[str, dict] = {}

    # Find all interface declarations with optional extends clause
    decl_pattern = re.compile(
        r"export interface (\w+)(?:\s+extends\s+(\w+))?\s*\{",
    )

    for m in decl_pattern.finditer(fe_content):
        iface_name = m.group(1)
        parent_name = m.group(2)  # None if no extends

        # Extract the interface body using brace depth tracking
        start = m.end()
        depth = 1
        pos = start
        while pos < len(fe_content) and depth > 0:
            ch = fe_content[pos]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            pos += 1
        body = fe_content[start : pos - 1]

        # Extract property names (ignores comment lines starting with //)
        prop_pattern = re.compile(r"^\s+(\w+)\??:", re.MULTILINE)
        props = set(prop_pattern.findall(body))

        result[iface_name] = {"props": props, "extends": parent_name}

    return result


def _resolve_fe_props(interfaces: dict[str, dict], iface_name: str) -> set[str] | None:
    """Return the full property set for an interface including inherited props."""
    entry = interfaces.get(iface_name)
    if entry is None:
        return None
    props = set(entry["props"])
    parent = entry.get("extends")
    if parent:
        parent_props = _resolve_fe_props(interfaces, parent)
        if parent_props:
            props |= parent_props
    return props


# ---------------------------------------------------------------------------
# OpenAPI schema parser
# ---------------------------------------------------------------------------


def _load_openapi_schemas(openapi_path: Path) -> dict[str, set[str]]:
    """Load ``components.schemas`` from openapi.json and return name → property set."""
    with openapi_path.open() as f:
        spec = json.load(f)
    schemas = spec.get("components", {}).get("schemas", {})
    return {
        name: set(schema.get("properties", {}).keys())
        for name, schema in schemas.items()
        if schema.get("properties")
    }


# ---------------------------------------------------------------------------
# Drift checker
# ---------------------------------------------------------------------------


class DriftReport:
    """Accumulator for drift findings."""

    def __init__(self) -> None:
        self.new_drift: list[tuple[str, list[str]]] = []
        self.known_drift: list[tuple[str, list[str]]] = []
        self.resolved_known_drift: list[tuple[str, list[str]]] = []
        self.skipped: list[str] = []

    def has_new_drift(self) -> bool:
        return bool(self.new_drift)

    def should_fail(self) -> bool:
        """fix(#1778): a maintained model this checker could not compare at
        all (absent from openapi.json or from the FE mirror) is exactly the
        case the KNOWN_DRIFT allowlist cannot cover — silently skipping it
        let a renamed/removed maintained model pass with zero output.

        fix(#1778 review round 9): a KNOWN_DRIFT entry that has become
        fully resolved (the FE mirror caught up — check_drift() computes
        this into ``resolved_known_drift``) used to only print a
        ``[RESOLVED]`` notice; nothing made the gate itself fail, and
        the only repo invocation of this checker is
        ``test_drift_checker_passes()``, so that notice was just
        captured pytest output nobody had to act on. A resolved entry
        left in KNOWN_DRIFT is a standing license to regress — the
        allowlist should shrink back down as the FE mirror catches up,
        not accumulate stale entries forever. Failing the gate forces
        the entry to actually be removed.
        """
        return (
            bool(self.new_drift)
            or bool(self.skipped)
            or bool(self.resolved_known_drift)
        )


def check_drift(
    model_names: list[str],
    be_schemas: dict[str, set[str]],
    fe_interfaces: dict[str, dict],
) -> DriftReport:
    """Compare backend schema properties against FE interface properties."""
    report = DriftReport()

    for name in model_names:
        be_props = be_schemas.get(name)
        if be_props is None:
            report.skipped.append(f"{name}: not in openapi.json schemas")
            continue

        fe_props = _resolve_fe_props(fe_interfaces, name)
        if fe_props is None:
            report.skipped.append(f"{name}: not found in frontend/src/types/api.ts")
            continue

        missing = sorted(be_props - fe_props)

        # fix(#1778): compute "known drift now resolved" BEFORE the
        # early-continue below. A model with ZERO current drift used to
        # skip this block entirely, so a KNOWN_DRIFT entry for a model the
        # FE mirror had fully caught up on was invisible to this reporter
        # forever — the allowlist entry just sat there as a standing
        # license to regress with no signal telling anyone to remove it.
        known = KNOWN_DRIFT.get(name, [])
        resolved = [p for p in known if p and p not in missing]
        if resolved:
            report.resolved_known_drift.append((name, resolved))

        if not missing:
            continue

        # Partition: known vs new drift
        truly_known = [p for p in missing if p in known]
        new_missing = [p for p in missing if p not in known]

        if truly_known:
            report.known_drift.append((name, truly_known))
        if new_missing:
            report.new_drift.append((name, new_missing))

    return report


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _print_report(report: DriftReport, verbose: bool = False) -> None:
    if report.skipped:
        # fix(#1778): printed unconditionally (not just under --verbose) —
        # this now fails the build (DriftReport.should_fail()), so a
        # skipped, uncomparable maintained model must be visible without
        # needing to know to pass a flag; the pytest wrapper does not.
        print(
            "[FAIL] Maintained models not checkable (absent from openapi.json or api.ts):"
        )
        for s in report.skipped:
            print(f"  - {s}")
        print(
            "  → A renamed/removed model must be updated here and in "
            "MAINTAINED_MODELS, or removed from both."
        )
        print()

    if report.known_drift:
        print("[WARN] Known pre-existing drift (not a regression — see KNOWN_DRIFT):")
        for name, props in report.known_drift:
            print(f"  {name}: missing {props}")
        print(
            "  → These are documented in KNOWN_DRIFT in scripts/check_fe_type_drift.py."
        )
        print("  → Add the field to frontend/src/types/api.ts or update KNOWN_DRIFT.")
        print()

    if report.resolved_known_drift:
        print(
            "[RESOLVED] Previously known drift is now fixed (remove from KNOWN_DRIFT):"
        )
        for name, props in report.resolved_known_drift:
            print(f"  {name}: {props}")
        print()

    if report.new_drift:
        print("[FAIL] NEW drift detected — backend properties missing from FE mirror:")
        for name, props in report.new_drift:
            print(f"  {name}: missing {props}")
        print()
        print(
            "  Fix: add the field to frontend/src/types/api.ts, "
            "OR add it to KNOWN_DRIFT in scripts/check_fe_type_drift.py with a TODO."
        )
        print("  References: OCG-03, T-1206-08")
    elif report.resolved_known_drift:
        print(
            "  Fix: remove the resolved entries named above from KNOWN_DRIFT "
            "in scripts/check_fe_type_drift.py."
        )
    elif not report.known_drift and not report.skipped:
        print("[PASS] No drift detected between backend schemas and FE type mirrors.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--check-all",
        action="store_true",
        help=(
            "Also check schemas outside the maintained allowlist "
            "(informational, does not affect exit code)."
        ),
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print skipped models.",
    )
    parser.add_argument(
        "--openapi",
        type=Path,
        default=_OPENAPI_JSON,
        help="Path to openapi.json (default: backend/openapi.json).",
    )
    parser.add_argument(
        "--fe-types",
        type=Path,
        default=_FE_TYPES,
        help="Path to frontend types file (default: frontend/src/types/api.ts).",
    )
    args = parser.parse_args(argv)

    openapi_path: Path = args.openapi
    fe_types_path: Path = args.fe_types

    if not openapi_path.exists():
        sys.stderr.write(
            f"ERROR: openapi.json not found at {openapi_path}.\n"
            "Run `make openapi` to regenerate it.\n"
        )
        return 1

    if not fe_types_path.exists():
        sys.stderr.write(f"ERROR: FE types file not found at {fe_types_path}.\n")
        return 1

    be_schemas = _load_openapi_schemas(openapi_path)
    fe_content = fe_types_path.read_text()
    fe_interfaces = _parse_fe_interfaces(fe_content)

    # Primary check: maintained allowlist
    report = check_drift(list(set(MAINTAINED_MODELS)), be_schemas, fe_interfaces)
    _print_report(report, verbose=args.verbose)

    if args.check_all:
        all_common = sorted(
            set(fe_interfaces.keys()) & set(be_schemas.keys()) - set(MAINTAINED_MODELS)
        )
        if all_common:
            print(
                f"\n[INFO] Checking {len(all_common)} additional schemas (--check-all):"
            )
            extra_report = check_drift(all_common, be_schemas, fe_interfaces)
            _print_report(extra_report, verbose=args.verbose)

    return 1 if report.should_fail() else 0


if __name__ == "__main__":
    raise SystemExit(main())
