"""Side-by-side load gate: cloud + enterprise in the CORE venv (CLOUD-01..05 blocker).

This test module is the integration gate that catches failure modes individual
per-plan unit tests miss:

  A. **Side-by-side load (no SLOT conflict):** with enterprise AND cloud
     entry points both present, load_extensions() must succeed with zero
     ExtensionSlotConflictError — the cloud wrappers compose over enterprise
     ports via __slot_inner__ (CLOUD-04, SLOT-01/02).

  B. **Wrap-composes, not widens (security):** an enterprise permission DENIAL
     must still fire THROUGH the cloud wrapper after side-by-side load — the
     wrapper must NOT widen access (T-1211-19).

  C. **Cloud-absent byte-identical (runtime-primary):** with cloud NOT in the
     active overlay/entry-point set (enterprise-only and community-only cases),
     the RUNTIME assertions hold:
       - list_extensions() excludes "cloud"
       - no single-slot key holds a cloud wrapper (no __slot_inner__ set by cloud)
       - get_extension_routers() has no /cloud router
       - app.openapi() has zero /cloud/... paths
     Note: in the dev venv geolens_cloud may be importable (editable-installed
     for the side-by-side tests). That is expected; the RUNTIME overlay-load set
     — not import availability — is the boundary.

  D. **Supplementary (image boundary):** the Dockerfile BAKE-01 INSTALL_OVERLAYS
     ARG defaults to empty (cloud not baked) AND .dockerignore default-denies
     the cloud dir. This is explicitly marked supplementary to the runtime proof.

References: CLOUD-01..05, SLOT-01, SLOT-02, OCG-01, T-1211-18..20, BAKE-01
"""

from __future__ import annotations

import importlib.util
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.platform.extensions.version import EXTENSION_API_VERSION

# ---------------------------------------------------------------------------
# Cloud importability check
# ---------------------------------------------------------------------------

#: True if geolens_cloud is importable in the current venv.
#: The side-by-side tests (A, B, C-wrapper-check) require it.
#: When cloud is NOT installed (clean core venv baseline), these tests skip.
#: Install geolens_cloud editable before running to exercise the gate:
#:   unset VIRTUAL_ENV
#:   uv pip install -e ~/Code/geolens-overlays --python backend/.venv/bin/python
_CLOUD_IMPORTABLE: bool = importlib.util.find_spec("geolens_cloud") is not None

_requires_cloud = pytest.mark.skipif(
    not _CLOUD_IMPORTABLE,
    reason=(
        "geolens_cloud is not installed in the core venv — skipping side-by-side gate. "
        "Install with: unset VIRTUAL_ENV && "
        "uv pip install -e ~/Code/geolens-overlays --python backend/.venv/bin/python"
    ),
)

# ---------------------------------------------------------------------------
# Fixtures — registry isolation (mirrors test_openapi_overlay_boundary.py)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_extension_registry():
    """Isolate the extension registry before and after each test.

    Patches entry_points to empty by default so installed overlays in the
    venv do not bleed into tests that control their own mock entry points.
    Tests that need specific entry points override entry_points inside their
    own patch context.
    """
    import app.platform.extensions as ext_mod

    # Save state
    saved_extensions = dict(ext_mod._extensions)
    saved_routers = list(ext_mod._routers)
    saved_loaded = ext_mod._loaded
    saved_slot_owners = dict(ext_mod._slot_owners)

    ext_mod._extensions.clear()
    ext_mod._routers.clear()
    ext_mod._loaded = False
    ext_mod._slot_owners.clear()

    with patch("app.platform.extensions.entry_points", return_value=[]):
        yield

    # Teardown — restore state
    ext_mod._extensions.clear()
    ext_mod._extensions.update(saved_extensions)
    ext_mod._routers.clear()
    ext_mod._routers.extend(saved_routers)
    ext_mod._loaded = saved_loaded
    ext_mod._slot_owners.clear()
    ext_mod._slot_owners.update(saved_slot_owners)


@pytest.fixture(autouse=True)
def _reset_openapi_schema_cache():
    """Clear FastAPI's cached OpenAPI schema before and after each test."""
    from app.api.main import app

    app.openapi_schema = None
    yield
    app.openapi_schema = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry_point(name: str, loader_fn: object) -> MagicMock:
    """Build a mock entry_points item for a given name + loader callable."""
    ep = MagicMock()
    ep.name = name
    ep.load.return_value = loader_fn
    return ep


def _enterprise_loader(registry: dict) -> None:
    """Simulate enterprise register_extensions: registers permission + identity."""
    # This function-level attribute is what load_extensions reads via getattr().
    # It cannot be set on the function object in-scope so we set it after definition.

    # permission — bare claim (enterprise is first, no prior owner)
    enterprise_perm = MagicMock(name="enterprise_permission")

    async def _check_permission(
        db, user, capability, *, user_roles, permission_matrix=None, resource=None
    ):
        # Deny everything — the denial must fire through the cloud wrapper.
        return False

    enterprise_perm.check_permission = AsyncMock(side_effect=_check_permission)
    enterprise_perm.can_access_dataset = AsyncMock(return_value=False)
    enterprise_perm.filter_visible = MagicMock(return_value=MagicMock())

    registry["permission"] = enterprise_perm
    registry["identity"] = MagicMock(name="enterprise_identity")
    registry["auth"] = MagicMock(name="enterprise_auth")
    registry.setdefault("_routers", [])


_enterprise_loader.EXTENSION_API_VERSION = EXTENSION_API_VERSION  # type: ignore[attr-defined]
_enterprise_loader.EXTENSION_LOAD_PRIORITY = 100  # type: ignore[attr-defined]


def _cloud_loader_factory():
    """Build a cloud loader that reads the registry and wraps existing ports.

    This mirrors what geolens_cloud.register_extensions does: reads the current
    value from the registry via the accessor functions and wraps it with
    __slot_inner__ set.
    """

    def _cloud_loader(registry: dict) -> None:
        from geolens_cloud.ports import CloudPermission, CloudIdentity

        # Wrap permission: read prior from registry (not accessor, to avoid
        # default fallback when called in the middle of load_extensions)
        prior_perm = registry.get("permission")
        if prior_perm is not None:
            registry["permission"] = CloudPermission(inner=prior_perm)

        # Wrap identity
        prior_identity = registry.get("identity")
        if prior_identity is not None:
            registry["identity"] = CloudIdentity(inner=prior_identity)

        # List-slot: routers via setdefault+extend (cloud-owned routers)
        registry.setdefault("_routers", [])

    _cloud_loader.EXTENSION_API_VERSION = EXTENSION_API_VERSION  # type: ignore[attr-defined]
    _cloud_loader.EXTENSION_LOAD_PRIORITY = 200  # type: ignore[attr-defined]
    return _cloud_loader


# ---------------------------------------------------------------------------
# Test A: Side-by-side load — no ExtensionSlotConflictError
# ---------------------------------------------------------------------------


@_requires_cloud
class TestSideBySideLoad:
    """CLOUD-01/04: enterprise + cloud both load without SLOT conflict."""

    @pytest.mark.parametrize("reverse_discovery", [False, True])
    def test_cloud_and_enterprise_load_side_by_side(self, reverse_discovery: bool):
        """load_extensions() with enterprise→cloud entry points must not raise.

        After load:
          - list_extensions() contains both "enterprise" registration keys
            AND the cloud wrappers.
          - _extensions["permission"].__slot_inner__ is the enterprise permission
            instance (cloud wrapped, not clobbered).
          - _extensions["identity"].__slot_inner__ is the enterprise identity
            instance.
          - No ExtensionSlotConflictError raised.

        References: CLOUD-01, CLOUD-04, SLOT-01, SLOT-02
        """
        import app.platform.extensions as ext_mod
        from app.platform.extensions import (
            ExtensionSlotConflictError,
            load_extensions,
        )
        from geolens_cloud.ports import CloudPermission, CloudIdentity

        ent_ep = _make_entry_point("enterprise", _enterprise_loader)
        cloud_ep = _make_entry_point("cloud", _cloud_loader_factory())

        discovered = [ent_ep, cloud_ep]
        if reverse_discovery:
            discovered.reverse()

        with patch(
            "app.platform.extensions.entry_points",
            return_value=discovered,
        ):
            # Must NOT raise ExtensionSlotConflictError
            try:
                load_extensions()
            except ExtensionSlotConflictError as exc:
                pytest.fail(
                    f"ExtensionSlotConflictError raised during enterprise+cloud "
                    f"side-by-side load: {exc}"
                )

        # Cloud wrapper is in place for permission
        assert "permission" in ext_mod._extensions, (
            "permission key must be in _extensions after side-by-side load"
        )
        perm = ext_mod._extensions["permission"]
        assert isinstance(perm, CloudPermission), (
            f"Expected CloudPermission wrapper, got {type(perm)}"
        )

        # __slot_inner__ points to the enterprise instance
        enterprise_perm_instance = perm.__slot_inner__
        assert enterprise_perm_instance is not None, (
            "CloudPermission.__slot_inner__ must not be None after side-by-side load"
        )
        assert not isinstance(enterprise_perm_instance, CloudPermission), (
            "__slot_inner__ must be the enterprise impl, not another CloudPermission"
        )

        # identity wrapped
        assert "identity" in ext_mod._extensions
        ident = ext_mod._extensions["identity"]
        assert isinstance(ident, CloudIdentity), (
            f"Expected CloudIdentity wrapper, got {type(ident)}"
        )
        assert ident.__slot_inner__ is not None
        assert not isinstance(ident.__slot_inner__, CloudIdentity)

    def test_side_by_side_list_extensions_tracks_both(self):
        """After side-by-side load, list_extensions() reflects both overlays' keys."""
        import app.platform.extensions as ext_mod
        from app.platform.extensions import load_extensions

        ent_ep = _make_entry_point("enterprise", _enterprise_loader)
        cloud_ep = _make_entry_point("cloud", _cloud_loader_factory())

        with patch(
            "app.platform.extensions.entry_points",
            return_value=[ent_ep, cloud_ep],
        ):
            load_extensions()

        keys = ext_mod.list_extensions()
        # Both overlays register at minimum permission + identity
        assert "permission" in keys, (
            "permission must appear in list_extensions after side-by-side load"
        )
        assert "identity" in keys, (
            "identity must appear in list_extensions after side-by-side load"
        )
        # auth registered by enterprise
        assert "auth" in keys, (
            "auth must appear in list_extensions after side-by-side load"
        )

    def test_bare_replace_after_enterprise_still_raises_conflict(self):
        """A third overlay that bare-replaces an enterprise-owned slot still raises.

        This proves the SLOT guard is not bypassed by the cloud wrap path — only
        cloud's sanctioned __slot_inner__ wrap passes; an unrelated bare replace
        is still rejected.
        """
        from app.platform.extensions import (
            ExtensionSlotConflictError,
            load_extensions,
        )
        from app.platform.extensions.version import EXTENSION_API_VERSION

        def _bare_replace_loader(registry: dict) -> None:
            registry["permission"] = MagicMock(name="rogue_permission")

        _bare_replace_loader.EXTENSION_API_VERSION = EXTENSION_API_VERSION  # type: ignore[attr-defined]

        ent_ep = _make_entry_point("enterprise", _enterprise_loader)
        cloud_ep = _make_entry_point("cloud", _cloud_loader_factory())
        rogue_ep = _make_entry_point("rogue", _bare_replace_loader)

        with patch(
            "app.platform.extensions.entry_points",
            return_value=[ent_ep, cloud_ep, rogue_ep],
        ):
            with pytest.raises(ExtensionSlotConflictError):
                load_extensions()


# ---------------------------------------------------------------------------
# Test B: Compose-correctness — enterprise denial propagates through cloud wrapper
# ---------------------------------------------------------------------------


@_requires_cloud
class TestWrapComposeSecurity:
    """CLOUD-04 / T-1211-19: enterprise denial must fire through cloud wrapper.

    The cloud wrapper is a pure delegate in Phase 1211. An enterprise permission
    denial must reach the caller unchanged — the wrapper must NOT widen access.
    """

    @pytest.mark.anyio
    async def test_enterprise_denial_fires_through_cloud_permission(self):
        """With side-by-side registry, enterprise denial propagates (T-1211-19).

        1. Load enterprise + cloud entry points.
        2. Extract _extensions["permission"] — the CloudPermission wrapper.
        3. Assert wrapper.__slot_inner__ is the enterprise impl.
        4. Drive check_permission — inner denies → wrapper must deny.

        This is the load-bearing proof: a clobbered permission slot that dropped
        the enterprise impl would here show an ALLOW where there should be a DENY.
        """
        import app.platform.extensions as ext_mod
        from app.platform.extensions import load_extensions

        ent_ep = _make_entry_point("enterprise", _enterprise_loader)
        cloud_ep = _make_entry_point("cloud", _cloud_loader_factory())

        with patch(
            "app.platform.extensions.entry_points",
            return_value=[ent_ep, cloud_ep],
        ):
            load_extensions()

        wrapper = ext_mod._extensions["permission"]

        # Drive a permission check — the enterprise inner denies (returns False)
        result = await wrapper.check_permission(
            db=MagicMock(),
            user=MagicMock(),
            capability="admin",
            user_roles=["viewer"],
            permission_matrix=None,
            resource=None,
        )

        assert result is False, (
            "Enterprise denial must propagate through CloudPermission wrapper. "
            "If this assertion fails, the cloud wrapper is widening access — "
            "the security boundary is broken (T-1211-19)."
        )

    @pytest.mark.anyio
    async def test_enterprise_can_access_dataset_denial_propagates(self):
        """can_access_dataset denial propagates through cloud wrapper."""
        import app.platform.extensions as ext_mod
        from app.platform.extensions import load_extensions

        ent_ep = _make_entry_point("enterprise", _enterprise_loader)
        cloud_ep = _make_entry_point("cloud", _cloud_loader_factory())

        with patch(
            "app.platform.extensions.entry_points",
            return_value=[ent_ep, cloud_ep],
        ):
            load_extensions()

        wrapper = ext_mod._extensions["permission"]

        result = await wrapper.can_access_dataset(
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
            user_roles=["viewer"],
        )

        assert result is False, (
            "Dataset access denial must propagate through CloudPermission wrapper (T-1211-19)"
        )


# ---------------------------------------------------------------------------
# Test C: Cloud-absent byte-identical (runtime-primary)
# ---------------------------------------------------------------------------


@_requires_cloud
class TestCloudAbsentRuntimePrimary:
    """CLOUD-01 / T-1211-20: cloud must be completely absent from the runtime
    when NOT in the loaded overlay set.

    The runtime boundary (not import availability) is what matters. In the dev
    venv geolens_cloud is editable-installed for the side-by-side tests above;
    that is expected and correct. The PROOF is that when cloud is NOT in the
    entry_points set, none of its code appears in the loaded registry or routers.
    """

    def _load_enterprise_only(self):
        """Helper: load enterprise-only entry points and return registry state."""
        import app.platform.extensions as ext_mod
        from app.platform.extensions import load_extensions

        ent_ep = _make_entry_point("enterprise", _enterprise_loader)

        with patch(
            "app.platform.extensions.entry_points",
            return_value=[ent_ep],
        ):
            load_extensions()

        return ext_mod

    def _load_community_only(self):
        """Helper: load empty entry points (community) and return registry state."""
        import app.platform.extensions as ext_mod
        from app.platform.extensions import load_extensions

        with patch(
            "app.platform.extensions.entry_points",
            return_value=[],
        ):
            load_extensions()

        return ext_mod

    def test_enterprise_only_no_cloud_wrapper_in_registry(self):
        """Enterprise-only load: no single-slot key holds a CloudPermission wrapper."""
        from geolens_cloud.ports import (
            CloudPermission,
            CloudIdentity,
            CloudProcessingPort,
            CloudCatalogPort,
        )

        ext_mod = self._load_enterprise_only()

        cloud_wrapper_types = (
            CloudPermission,
            CloudIdentity,
            CloudProcessingPort,
            CloudCatalogPort,
        )

        for key, val in ext_mod._extensions.items():
            assert not isinstance(val, cloud_wrapper_types), (
                f"_extensions['{key}'] is a cloud wrapper ({type(val).__name__}) "
                f"but cloud was NOT in the entry-point set — runtime boundary violated (T-1211-20)"
            )
        # Also confirm: no __slot_inner__ exists that points to cloud code
        for key, val in ext_mod._extensions.items():
            inner = getattr(val, "__slot_inner__", None)
            if inner is not None:
                assert not isinstance(inner, cloud_wrapper_types), (
                    f"_extensions['{key}'].__slot_inner__ is a cloud type — "
                    f"cloud leaked into enterprise-only registry"
                )

    def test_enterprise_only_no_cloud_router(self):
        """Enterprise-only load: get_extension_routers() has no /cloud router."""
        ext_mod = self._load_enterprise_only()

        for router in ext_mod.get_extension_routers():
            prefix = getattr(router, "prefix", "") or ""
            assert not prefix.startswith("/cloud"), (
                f"Router with prefix '{prefix}' appeared in enterprise-only load — "
                f"cloud router must not load without cloud entry point (T-1211-20)"
            )

    def test_enterprise_only_openapi_has_no_cloud_paths(self):
        """Enterprise-only load: app.openapi() has zero /cloud/... paths."""
        from app.api.main import app

        self._load_enterprise_only()

        # Regenerate spec (no lifespan, mirrors dump_openapi.py)
        app.openapi_schema = None
        spec = app.openapi()

        cloud_paths = [p for p in spec.get("paths", {}) if p.startswith("/cloud")]
        assert not cloud_paths, (
            f"Cloud paths found in enterprise-only OpenAPI spec: {cloud_paths}. "
            f"Cloud routes must be absent when cloud is not in the entry-point set (OCG-01 / T-1211-20)"
        )

    def test_community_only_no_cloud_wrapper_in_registry(self):
        """Community-only load (empty entry points): zero cloud wrappers in registry."""
        from geolens_cloud.ports import (
            CloudPermission,
            CloudIdentity,
            CloudProcessingPort,
            CloudCatalogPort,
        )

        ext_mod = self._load_community_only()

        cloud_wrapper_types = (
            CloudPermission,
            CloudIdentity,
            CloudProcessingPort,
            CloudCatalogPort,
        )

        for key, val in ext_mod._extensions.items():
            assert not isinstance(val, cloud_wrapper_types), (
                f"_extensions['{key}'] is a cloud wrapper in community-only load — "
                f"runtime boundary violated (T-1211-20)"
            )

    def test_community_only_no_cloud_router(self):
        """Community-only load: no /cloud routers registered."""
        ext_mod = self._load_community_only()

        for router in ext_mod.get_extension_routers():
            prefix = getattr(router, "prefix", "") or ""
            assert not prefix.startswith("/cloud"), (
                f"Cloud router '{prefix}' appeared in community-only load (T-1211-20)"
            )

    def test_community_only_openapi_has_no_cloud_paths(self):
        """Community-only load: app.openapi() has zero /cloud/... paths."""
        from app.api.main import app

        self._load_community_only()

        app.openapi_schema = None
        spec = app.openapi()

        cloud_paths = [p for p in spec.get("paths", {}) if p.startswith("/cloud")]
        assert not cloud_paths, (
            f"Cloud paths found in community-only OpenAPI spec: {cloud_paths}. "
            f"Cloud must be completely absent without cloud entry point (OCG-01 / T-1211-20)"
        )


# ---------------------------------------------------------------------------
# Test D: Supplementary — image boundary (BAKE-01 Dockerfile + .dockerignore)
# ---------------------------------------------------------------------------


class TestBake01ImageBoundary:
    """BAKE-01 supplementary: Dockerfile + .dockerignore default-exclude /cloud.

    This is SUPPLEMENTARY to the runtime proofs above (Tests C). The image
    boundary check proves the build mechanism is correct — the cloud dir is
    excluded from the OSS build context by default and the INSTALL_OVERLAYS ARG
    defaults to empty so the cloud overlay is never baked without an explicit
    opt-in.

    A failure here is a build-mechanism bug (deploy risk), not a runtime bug —
    the runtime Tests C are the primary proof.

    References: BAKE-01, T-1211-20
    """

    def test_dockerfile_install_overlays_arg_defaults_empty(self):
        """BAKE-01: INSTALL_OVERLAYS ARG must default to empty string (not /cloud).

        The OSS Dockerfile must default-exclude cloud. Cloud inclusion is an
        legacy distributor-owned builds may still pass INSTALL_OVERLAYS, while
        the unmodified public build must keep its default empty.

        Supplementary to runtime cloud-absent proof (Tests C).
        """
        # __file__ = .../geolens/backend/tests/test_cloud_overlay_side_by_side.py
        # parents[0] = .../geolens/backend/tests/
        # parents[1] = .../geolens/backend/
        # parents[2] = .../geolens/   (repo root)
        repo_root = pathlib.Path(__file__).resolve().parents[2]
        dockerfile = repo_root / "Dockerfile"

        assert dockerfile.exists(), (
            "Dockerfile not found at repo root — cannot verify BAKE-01 default-exclusion"
        )

        text = dockerfile.read_text()

        # The ARG must be present with an empty (no-cloud) default
        assert "ARG INSTALL_OVERLAYS=" in text, (
            "BAKE-01: INSTALL_OVERLAYS ARG not found in Dockerfile — "
            "the N-overlay bake mechanism is missing (T-1211-20)"
        )

        # Verify the ARG is declared with an empty default, not with /cloud baked in.
        import re

        # Match: ARG INSTALL_OVERLAYS= (optional whitespace) then end-of-line or newline
        # This captures 'ARG INSTALL_OVERLAYS=' with nothing after (empty default)
        # but NOT 'ARG INSTALL_OVERLAYS=/cloud' or similar.
        empty_default_pattern = re.compile(r"^ARG INSTALL_OVERLAYS=\s*$", re.MULTILINE)
        assert empty_default_pattern.search(text), (
            "BAKE-01: INSTALL_OVERLAYS ARG does not default to empty — "
            "cloud may be baked into the OSS image by default (T-1211-20 SUPPLEMENTARY). "
            "The ARG line should be 'ARG INSTALL_OVERLAYS=' with no value."
        )

    def test_dockerignore_default_denies_cloud_dir(self):
        """BAKE-01: .dockerignore must deny the cloud/ dir by default.

        The OSS build context must not include cloud/ by default. The
        .dockerignore uses a '**' default-deny pattern and requires an
        explicit opt-in allowance for overlay dirs.

        Supplementary to runtime cloud-absent proof (Tests C).
        """
        repo_root = pathlib.Path(__file__).resolve().parents[2]
        dockerignore = repo_root / ".dockerignore"

        assert dockerignore.exists(), (
            ".dockerignore not found at repo root — cannot verify cloud dir exclusion"
        )

        text = dockerignore.read_text()

        # The default-deny '**' must be present
        assert "**" in text, (
            ".dockerignore does not use default-deny '**' pattern — "
            "cloud/ dir may not be excluded from OSS build context (BAKE-01 SUPPLEMENTARY)"
        )

        # The cloud dir must NOT be unconditionally allowed
        # (it must NOT have an uncommented '!cloud/' line)
        import re

        uncommented_cloud_allow = re.compile(r"^!cloud/", re.MULTILINE)
        assert not uncommented_cloud_allow.search(text), (
            "BAKE-01: .dockerignore has an uncommented '!cloud/' allowance — "
            "the cloud dir is in the OSS build context by default (T-1211-20 SUPPLEMENTARY). "
            "The allowance must be commented-out and added only for cloud image builds."
        )
