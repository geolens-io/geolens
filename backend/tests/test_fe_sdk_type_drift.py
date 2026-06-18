"""OCG-03: FE/SDK type-drift guard — pytest wrapper + tenant-model hand-audit.

This module provides two layers of protection against FE/backend type drift:

1. **Checker invocation test** (``test_drift_checker_passes``): invokes
   ``scripts/check_fe_type_drift.py`` via its ``main()`` function and asserts
   exit 0 (no NEW drift found beyond the documented ``KNOWN_DRIFT`` allowlist).
   Pre-existing drift is captured in the allowlist with TODOs, not silently ignored.
   If this test fails, a backend field was added to a maintained model without
   updating the FE mirror or the KNOWN_DRIFT allowlist.

2. **Tenant-bound model hand-audit** (``TestTenantBoundModelAudit``): explicit
   per-model assertions that each of the five models gaining a ``tenant_id``
   in Phase 1207 has its critical backend properties covered by its FE mirror.
   These assertions provide a hard gate that Phase 1207 must remain green through.

The five tenant-bound models (Phase 1207 will add tenant_id to each):

- **maps** → ``MapResponse`` (also covers ``MapLayerResponse``)
- **datasets** → ``DatasetResponse``
- **embed_tokens** → ``EmbedTokenResponse``
- **tiles** → ``MapLayerResponse`` (vector/raster tile consumers)
- **collections** → ``CollectionResponse``

References: OCG-03, T-1206-08
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Shared helpers (mirrored from check_fe_type_drift to avoid circular deps)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_OPENAPI_JSON = _REPO_ROOT / "backend" / "openapi.json"
_FE_TYPES = _REPO_ROOT / "frontend" / "src" / "types" / "api.ts"


def _load_fe_interfaces() -> dict[str, dict]:
    """Parse all export interface declarations from the FE types file."""
    content = _FE_TYPES.read_text()
    result: dict[str, dict] = {}
    decl_pattern = re.compile(r"export interface (\w+)(?:\s+extends\s+(\w+))?\s*\{")
    for m in decl_pattern.finditer(content):
        iface_name = m.group(1)
        parent_name = m.group(2)
        start = m.end()
        depth = 1
        pos = start
        while pos < len(content) and depth > 0:
            ch = content[pos]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            pos += 1
        body = content[start : pos - 1]
        prop_pattern = re.compile(r"^\s+(\w+)\??:", re.MULTILINE)
        props = set(prop_pattern.findall(body))
        result[iface_name] = {"props": props, "extends": parent_name}
    return result


def _resolve_fe_props(interfaces: dict[str, dict], iface_name: str) -> set[str] | None:
    """Return full property set including inherited props."""
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


def _load_be_schema_props(name: str) -> set[str]:
    """Return property names for a backend schema from openapi.json."""
    with _OPENAPI_JSON.open() as f:
        spec = json.load(f)
    schemas = spec.get("components", {}).get("schemas", {})
    return set(schemas.get(name, {}).get("properties", {}).keys())


# ---------------------------------------------------------------------------
# Task 1: Drift checker passes (no new drift)
# ---------------------------------------------------------------------------


def test_drift_checker_passes():
    """OCG-03: check_fe_type_drift.py exits 0 on the current tree.

    Invokes the checker via its ``main()`` function and asserts no NEW drift
    (i.e. exit 0).  Known/pre-existing drift in the KNOWN_DRIFT allowlist is
    acceptable — it is documented with TODOs, not silently passing.

    If this test fails, a backend field was added to a maintained model without:
    (a) updating frontend/src/types/api.ts with the new field, OR
    (b) documenting the intentional omission in KNOWN_DRIFT in
        backend/scripts/check_fe_type_drift.py.

    References: OCG-03, T-1206-08
    """
    # Import via sys.path manipulation (not a package, just a script)
    import importlib.util

    checker_path = _REPO_ROOT / "backend" / "scripts" / "check_fe_type_drift.py"
    spec = importlib.util.spec_from_file_location("check_fe_type_drift", checker_path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    exit_code = module.main([])
    assert exit_code == 0, (
        "check_fe_type_drift.py reported NEW drift (exit 1). "
        "Either add the missing fields to frontend/src/types/api.ts "
        "or document them in KNOWN_DRIFT. "
        "Run `PYTHONPATH=. uv run python scripts/check_fe_type_drift.py` "
        "for the full diff. References: OCG-03, T-1206-08"
    )


# ---------------------------------------------------------------------------
# Task 2: Tenant-bound model hand-audit (minimum bar before Phase 1207)
# ---------------------------------------------------------------------------


class TestTenantBoundModelAudit:
    """Explicit per-model hand-audit of the five tenant-bound models.

    Each test asserts that a defined set of REQUIRED_CORE properties appears
    in the FE interface for the model.  These are the properties that MUST be
    present in the FE mirror before Phase 1207 adds ``tenant_id``.

    If Phase 1207 adds ``tenant_id`` to a backend schema, the developer MUST
    also update ``frontend/src/types/api.ts`` for the corresponding interface
    and add ``tenant_id`` to its ``REQUIRED_CORE`` set here.

    The allowlisted ``KNOWN_DRIFT`` fields (e.g. ``og_image_url`` for
    ``MapResponse``) are deliberately NOT in the required set — they're
    documented omissions, not contract violations.

    References: OCG-03, T-1206-08
    """

    @pytest.fixture(autouse=True)
    def _load_data(self):
        """Load FE interfaces + openapi.json once per test."""
        self.fe_interfaces = _load_fe_interfaces()

    def _assert_fe_has_props(
        self, be_schema_name: str, fe_iface_name: str, required_props: set[str]
    ) -> None:
        """Assert required_props are present in the FE interface's resolved property set."""
        fe_props = _resolve_fe_props(self.fe_interfaces, fe_iface_name)
        assert fe_props is not None, (
            f"FE interface '{fe_iface_name}' not found in {_FE_TYPES}. "
            f"It must exist and match the backend schema '{be_schema_name}'. "
            "References: OCG-03"
        )
        missing = required_props - fe_props
        assert not missing, (
            f"FE interface '{fe_iface_name}' is missing required properties "
            f"from backend schema '{be_schema_name}': {sorted(missing)}. "
            f"Add these fields to frontend/src/types/api.ts before Phase 1207 "
            "adds tenant_id. References: OCG-03, T-1206-08"
        )

    def test_maps_model_coverage(self):
        """maps → MapResponse: core identity, visibility, audit, ownership fields present.

        Minimum bar: the properties that gate map authorization and will interact
        with tenant_id in Phase 1207 must be in the FE mirror.

        References: OCG-03, T-1206-08
        """
        required = {
            "id",
            "name",
            "description",
            "visibility",
            "created_by",
            "created_at",
            "updated_at",
            "layers",
            "layer_count",
            "basemap_style",
            "basemap_config",
            "terrain_config",
            "thumbnail_url",
            "show_basemap_labels",
            "plugins",
        }
        self._assert_fe_has_props("MapResponse", "MapResponse", required)

    def test_datasets_model_coverage(self):
        """datasets → DatasetResponse: core identity, visibility, type, spatial fields present.

        References: OCG-03, T-1206-08
        """
        required = {
            "id",
            "record_id",
            "title",
            "table_name",
            "visibility",
            "geometry_type",
            "feature_count",
            "srid",
            "column_info",
            "created_by",
            "created_at",
            "updated_at",
            "record_type",
            "record_status",
            "raster",
            "collections",
        }
        self._assert_fe_has_props("DatasetResponse", "DatasetResponse", required)

    def test_embed_tokens_model_coverage(self):
        """embed_tokens → EmbedTokenResponse: all token fields present.

        References: OCG-03, T-1206-08
        """
        required = {
            "id",
            "map_id",
            "name",
            "token_hint",
            "allowed_origins",
            "expires_at",
            "is_active",
            "use_count",
            "last_used_at",
            "created_at",
            "scoped_dataset_ids",
        }
        self._assert_fe_has_props("EmbedTokenResponse", "EmbedTokenResponse", required)

    def test_tiles_model_coverage(self):
        """tiles → MapLayerResponse: core layer identity, dataset ref, style fields present.

        MapLayerResponse is the primary 'tiles' surface — it is the FE type for
        a layer that renders vector/raster tile data and is the model that will
        need tenant awareness when multi-tenant tile access is controlled.

        References: OCG-03, T-1206-08
        """
        required = {
            "id",
            "dataset_id",
            "dataset_name",
            "dataset_geometry_type",
            "dataset_table_name",
            "visible",
            "opacity",
            "sort_order",
            "paint",
            "layout",
            "layer_type",
            "style_config",
            "label_config",
            "popup_config",
        }
        self._assert_fe_has_props("MapLayerResponse", "MapLayerResponse", required)

    def test_collections_model_coverage(self):
        """collections → CollectionResponse: all core collection fields present.

        References: OCG-03, T-1206-08
        """
        required = {
            "id",
            "name",
            "description",
            "created_by",
            "created_at",
            "updated_at",
            "dataset_count",
            "extent_bbox",
            "temporal_start",
            "temporal_end",
        }
        self._assert_fe_has_props("CollectionResponse", "CollectionResponse", required)

    def test_all_five_tenant_models_have_fe_mirrors(self):
        """All five tenant-bound models must have corresponding FE interfaces.

        This is the structural check: if any of the five models is removed
        from frontend/src/types/api.ts (e.g. renamed), this test fails before
        Phase 1207 can add tenant_id to a FE-mirror-less model.

        References: OCG-03, T-1206-08
        """
        # maps + tiles share MapResponse / MapLayerResponse
        # datasets → DatasetResponse
        # embed_tokens → EmbedTokenResponse
        # collections → CollectionResponse
        five_tenant_models = {
            "MapResponse",  # maps
            "MapLayerResponse",  # tiles
            "DatasetResponse",  # datasets
            "EmbedTokenResponse",  # embed_tokens
            "CollectionResponse",  # collections
        }
        missing_mirrors = {
            name
            for name in five_tenant_models
            if _resolve_fe_props(self.fe_interfaces, name) is None
        }
        assert not missing_mirrors, (
            f"The following tenant-bound models have NO FE interface mirror: "
            f"{sorted(missing_mirrors)}. "
            "These must be added to frontend/src/types/api.ts before Phase 1207 "
            "adds tenant_id. References: OCG-03, T-1206-08"
        )
