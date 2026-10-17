"""FE/SDK type-drift guard — pytest wrapper + tenant-model hand-audit.

This module provides two layers of protection against FE/backend type drift:

1. **Checker invocation test** (``test_drift_checker_passes``): invokes
   ``scripts/check_fe_type_drift.py`` via its ``main()`` function and asserts
   exit 0 (no NEW drift found beyond the documented ``KNOWN_DRIFT`` allowlist).
   Pre-existing drift is captured in the allowlist with TODOs, not silently ignored.
   If this test fails, a backend field was added to a maintained model without
   updating the FE mirror or the KNOWN_DRIFT allowlist.

2. **Tenant-bound model hand-audit** (``TestTenantBoundModelAudit``): explicit
   per-model assertions that each of the five models gaining a ``tenant_id``
   has its critical backend properties covered by its FE mirror.
   These assertions provide a hard gate that must stay green when tenant_id lands.

The five tenant-bound models (each will gain tenant_id):

- **maps** → ``MapResponse`` (also covers ``MapLayerResponse``)
- **datasets** → ``DatasetResponse``
- **embed_tokens** → ``EmbedTokenResponse``
- **tiles** → ``MapLayerResponse`` (vector/raster tile consumers)
- **collections** → ``CollectionResponse``
"""

from __future__ import annotations


import pytest

from tests.repo_paths import repo_root

# ---------------------------------------------------------------------------
# Shared helpers (mirrored from check_fe_type_drift to avoid circular deps)
# ---------------------------------------------------------------------------

_REPO_ROOT = repo_root(__file__)
_OPENAPI_JSON = _REPO_ROOT / "backend" / "openapi.json"
_FE_TYPES = _REPO_ROOT / "frontend" / "src" / "types" / "api.ts"


def _load_checker_module():
    import importlib.util

    checker_path = _REPO_ROOT / "backend" / "scripts" / "check_fe_type_drift.py"
    spec = importlib.util.spec_from_file_location("check_fe_type_drift", checker_path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _load_fe_interfaces() -> dict[str, dict]:
    """Parse the exported API types (interfaces and generated aliases)."""
    return _load_checker_module()._parse_fe_interfaces(_FE_TYPES.read_text())


def _load_be_schemas() -> dict[str, set[str]]:
    return _load_checker_module()._load_openapi_schemas(_OPENAPI_JSON)


def _resolve_fe_props(interfaces: dict[str, dict], iface_name: str) -> set[str] | None:
    """Return full property set including inherited and generated props."""
    return _load_checker_module()._resolve_fe_props(
        interfaces, iface_name, _load_be_schemas()
    )


# ---------------------------------------------------------------------------
# Drift checker passes (no new drift)
# ---------------------------------------------------------------------------


def test_drift_checker_passes():
    """check_fe_type_drift.py exits 0 on the current tree.

    Invokes the checker via its ``main()`` function and asserts no NEW drift
    (i.e. exit 0).  Known/pre-existing drift in the KNOWN_DRIFT allowlist is
    acceptable — it is documented with TODOs, not silently passing.

    If this test fails, a backend field was added to a maintained model without:
    (a) updating frontend/src/types/api.ts with the new field, OR
    (b) documenting the intentional omission in KNOWN_DRIFT in
        backend/scripts/check_fe_type_drift.py.
    """
    module = _load_checker_module()

    exit_code = module.main([])
    assert exit_code == 0, (
        "check_fe_type_drift.py reported NEW drift (exit 1). "
        "Either add the missing fields to frontend/src/types/api.ts "
        "or document them in KNOWN_DRIFT. "
        "Run `PYTHONPATH=. uv run python scripts/check_fe_type_drift.py` "
        "for the full diff. References: OCG-03, T-1206-08"
    )


class TestResolvedKnownDriftIsReportedEvenAtZeroDrift:
    """check_drift() must compute "known drift now resolved" even for a model
    with zero CURRENT drift: otherwise a KNOWN_DRIFT entry for a model whose
    FE mirror has fully caught up is invisible to the reporter forever — the
    stale allowlist entry sits there as a standing license to regress with no
    signal telling anyone to remove it."""

    def test_a_fully_resolved_known_drift_entry_is_reported(self) -> None:
        module = _load_checker_module()

        be_schemas = {"Widget": {"a", "b"}}
        fe_interfaces = {"Widget": {"props": {"a", "b"}, "extends": None}}
        original_known_drift = module.KNOWN_DRIFT
        module.KNOWN_DRIFT = {"Widget": ["b"]}
        try:
            report = module.check_drift(["Widget"], be_schemas, fe_interfaces)
        finally:
            module.KNOWN_DRIFT = original_known_drift

        assert report.resolved_known_drift == [("Widget", ["b"])]
        assert report.new_drift == []
        assert report.known_drift == []

    def test_a_resolved_known_drift_entry_fails_the_gate(self) -> None:
        """check_drift() computed
        resolved_known_drift, but should_fail() ignored it -- the only
        repo invocation of this checker is test_drift_checker_passes(),
        so the [RESOLVED] notice was just captured pytest output nobody
        had to act on. A resolved entry left in KNOWN_DRIFT is a
        standing license to regress; the gate must fail until the
        entry is actually removed."""
        module = _load_checker_module()

        be_schemas = {"Widget": {"a", "b"}}
        fe_interfaces = {"Widget": {"props": {"a", "b"}, "extends": None}}
        original_known_drift = module.KNOWN_DRIFT
        module.KNOWN_DRIFT = {"Widget": ["b"]}
        try:
            report = module.check_drift(["Widget"], be_schemas, fe_interfaces)
        finally:
            module.KNOWN_DRIFT = original_known_drift

        assert report.resolved_known_drift == [("Widget", ["b"])]
        assert report.should_fail() is True

    def test_stale_allowlist_entries_are_gone(self) -> None:
        """The three now-stale entries this finding named must stay gone —
        pins the KNOWN_DRIFT cleanup so a revert doesn't quietly slide
        back in."""
        module = _load_checker_module()

        assert "MapResponse" not in module.KNOWN_DRIFT
        assert "DuplicateMapResponse" not in module.KNOWN_DRIFT
        assert "JobStatusResponse" not in module.KNOWN_DRIFT


class TestSkippedMaintainedModelFailsTheBuild:
    """report.skipped (a maintained model absent from
    openapi.json or the FE mirror — e.g. renamed on either side) must affect
    the exit code, or a renamed MAINTAINED_MODELS entry silently drops out of
    comparison with zero output and exit 0."""

    def test_should_fail_is_true_when_a_model_is_skipped(self) -> None:
        module = _load_checker_module()

        report = module.DriftReport()
        report.skipped.append("GhostModel: not in openapi.json schemas")

        assert report.should_fail() is True

    def test_should_fail_is_false_with_no_drift_and_nothing_skipped(self) -> None:
        module = _load_checker_module()

        assert module.DriftReport().should_fail() is False

    def test_check_drift_skips_a_model_absent_from_openapi(self) -> None:
        module = _load_checker_module()

        report = module.check_drift(["GhostModel"], be_schemas={}, fe_interfaces={})

        assert report.skipped == ["GhostModel: not in openapi.json schemas"]
        assert report.should_fail() is True


class TestGeneratedTypeForms:
    """api.ts declares most response types as aliases of the generated schema
    types, so the checker reads those forms as well as hand-written
    interfaces."""

    def test_an_alias_of_the_same_schema_is_a_drift_free_mirror(self) -> None:
        module = _load_checker_module()
        fe = module._parse_fe_interfaces(
            "export type Widget = components['schemas']['Widget'];\n"
        )

        report = module.check_drift(["Widget"], {"Widget": {"a", "b"}}, fe)

        assert report.new_drift == []
        assert report.skipped == []
        assert report.should_fail() is False

    def test_an_omit_that_redeclares_every_omitted_field_is_a_mirror(self) -> None:
        module = _load_checker_module()
        fe = module._parse_fe_interfaces(
            "export type Widget = Omit<\n"
            "  components['schemas']['Widget'],\n"
            "  'a' | 'b'\n"
            "> & {\n"
            "  a: 'x' | 'y';\n"
            "  b?: { nested: string } | null;\n"
            "};\n"
        )

        report = module.check_drift(["Widget"], {"Widget": {"a", "b", "c"}}, fe)

        assert report.should_fail() is False

    def test_an_omit_list_with_a_leading_pipe_is_parsed(self) -> None:
        module = _load_checker_module()
        fe = module._parse_fe_interfaces(
            "export type Widget = Omit<\n"
            "  components['schemas']['Widget'],\n"
            "  | 'a'\n"
            "  | 'b'\n"
            "> & {\n"
            "  a: string;\n"
            "  b?: string;\n"
            "};\n"
        )

        assert fe["Widget"]["omitted"] == {"a", "b"}
        assert (
            module.check_drift(["Widget"], {"Widget": {"a", "b"}}, fe).new_drift == []
        )

    def test_an_omitted_field_that_is_not_redeclared_is_drift(self) -> None:
        module = _load_checker_module()
        fe = module._parse_fe_interfaces(
            "export type Widget = Omit<\n"
            "  components['schemas']['Widget'],\n"
            "  'a' | 'b'\n"
            "> & {\n"
            "  a: string;\n"
            "};\n"
        )

        report = module.check_drift(["Widget"], {"Widget": {"a", "b", "c"}}, fe)

        assert report.new_drift == [("Widget", ["b"])]
        assert report.should_fail() is True

    def test_a_nested_key_does_not_redeclare_an_omitted_field(self) -> None:
        module = _load_checker_module()
        fe = module._parse_fe_interfaces(
            "export type Widget = Omit<components['schemas']['Widget'], 'a' | 'b'> & {\n"
            "  a: { b: string };\n"
            "};\n"
        )

        report = module.check_drift(["Widget"], {"Widget": {"a", "b"}}, fe)

        assert report.new_drift == [("Widget", ["b"])]

    def test_an_alias_of_a_differently_named_schema_is_drift(self) -> None:
        module = _load_checker_module()
        fe = module._parse_fe_interfaces(
            "export type Widget = components['schemas']['Gadget'];\n"
        )

        report = module.check_drift(["Widget"], {"Widget": {"a"}, "Gadget": {"a"}}, fe)

        assert report.new_drift == [("Widget", ["aliases schema Gadget"])]
        assert report.should_fail() is True

    def test_a_mismatched_alias_is_no_mirror_for_the_tenant_audit(self) -> None:
        module = _load_checker_module()
        fe = module._parse_fe_interfaces(
            "export type Widget = components['schemas']['Gadget'];\n"
        )

        props = module._resolve_fe_props(fe, "Widget", {"Gadget": {"a"}})

        assert props is None


# ---------------------------------------------------------------------------
# Tenant-bound model hand-audit
# ---------------------------------------------------------------------------


class TestTenantBoundModelAudit:
    """Explicit per-model hand-audit of the five tenant-bound models.

    Each test asserts that a defined set of REQUIRED_CORE properties appears
    in the FE interface for the model.  These are the properties that MUST be
    present in the FE mirror before ``tenant_id`` is added.

    If a change adds ``tenant_id`` to a backend schema, the developer MUST
    also update ``frontend/src/types/api.ts`` for the corresponding interface
    and add ``tenant_id`` to its ``REQUIRED_CORE`` set here.

    The allowlisted ``KNOWN_DRIFT`` fields (e.g. ``og_image_url`` for
    ``MapResponse``) are deliberately NOT in the required set — they're
    documented omissions, not contract violations.
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
        with tenant_id must be in the FE mirror.
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
        """Datasets → DatasetResponse: core identity, visibility, type, spatial fields present."""
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
        """embed_tokens → EmbedTokenResponse: all token fields present."""
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
        """Collections → CollectionResponse: all core collection fields present."""
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
        tenant_id can be added to a FE-mirror-less model.
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
