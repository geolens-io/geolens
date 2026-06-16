"""BUG-003: Enterprise overlay startup check — loud failure when requested but inactive.

If ``GEOLENS_EDITION=enterprise`` is set but no overlay extensions are loaded
(e.g. because the overlay cannot be installed under read_only rootfs), the
app must fail LOUDLY instead of silently booting as community edition.

RED phase: these tests exercise the not-yet-implemented
``check_enterprise_overlay_requested`` helper.
"""

from __future__ import annotations

import inspect
from unittest.mock import patch

import pytest


def _reset_edition():
    import app.core.edition as ed_mod

    ed_mod._info = None


@pytest.fixture(autouse=True)
def _clean_edition():
    _reset_edition()
    yield
    _reset_edition()


class TestEnterpriseOverlayStartupCheck:
    """check_enterprise_overlay_requested raises when enterprise explicitly
    requested but no overlay loaded."""

    def test_raises_when_enterprise_requested_and_no_extensions(self):
        """GEOLENS_EDITION=enterprise + zero loaded extensions → RuntimeError."""
        from app.core.edition import check_enterprise_overlay_requested

        with patch.dict("os.environ", {"GEOLENS_EDITION": "enterprise"}):
            with pytest.raises(RuntimeError, match="enterprise"):
                check_enterprise_overlay_requested(loaded_extensions=[])

    def test_raises_when_enterprise_requested_case_insensitive(self):
        """GEOLENS_EDITION=Enterprise (capitalised) still triggers the check."""
        from app.core.edition import check_enterprise_overlay_requested

        with patch.dict("os.environ", {"GEOLENS_EDITION": "Enterprise"}):
            with pytest.raises(RuntimeError):
                check_enterprise_overlay_requested(loaded_extensions=[])

    def test_silent_when_enterprise_requested_and_overlay_loaded(self):
        """GEOLENS_EDITION=enterprise + overlay extension present → no error."""
        from app.core.edition import check_enterprise_overlay_requested

        with patch.dict("os.environ", {"GEOLENS_EDITION": "enterprise"}):
            # Should not raise — overlay IS loaded
            check_enterprise_overlay_requested(
                loaded_extensions=["some_enterprise_ext"]
            )

    def test_silent_when_no_edition_requested_and_no_extensions(self):
        """Default OSS (no GEOLENS_EDITION set, no extensions) → no error."""
        import os

        from app.core.edition import check_enterprise_overlay_requested

        env = {k: v for k, v in os.environ.items() if k != "GEOLENS_EDITION"}
        with patch.dict("os.environ", env, clear=True):
            check_enterprise_overlay_requested(loaded_extensions=[])

    def test_silent_when_community_explicitly_requested(self):
        """GEOLENS_EDITION=community → no error even with no extensions."""
        from app.core.edition import check_enterprise_overlay_requested

        with patch.dict("os.environ", {"GEOLENS_EDITION": "community"}):
            check_enterprise_overlay_requested(loaded_extensions=[])

    def test_error_message_mentions_overlay_and_build_time_bake(self):
        """RuntimeError message must guide operators toward the build-time bake fix."""
        from app.core.edition import check_enterprise_overlay_requested

        with patch.dict("os.environ", {"GEOLENS_EDITION": "enterprise"}):
            with pytest.raises(RuntimeError) as exc_info:
                check_enterprise_overlay_requested(loaded_extensions=[])

        msg = str(exc_info.value).lower()
        # Must mention the problem and the correct remedy
        assert "enterprise" in msg
        assert any(
            word in msg for word in ("overlay", "extension", "geolens.extensions")
        )


class TestEnterpriseCheckWiredIntoLifespan:
    """Structural regression: check_enterprise_overlay_requested is called from
    the app lifespan so a misconfigured deploy never silently boots OSS.

    WORK-01: the lifespan now delegates to bootstrap() which owns the full
    extension-load + enterprise-check sequence. The lifespan must call
    bootstrap() and bootstrap() must call check_enterprise_overlay_requested().
    """

    def test_check_called_from_lifespan(self):
        """main.py lifespan must call bootstrap() which calls check_enterprise_overlay_requested.

        WORK-01: the lifespan delegates to the shared bootstrap() helper.
        bootstrap() calls check_enterprise_overlay_requested() internally so
        the enterprise loud-failure guarantee (BUG-003) is preserved via the
        call chain: lifespan → bootstrap → check_enterprise_overlay_requested.
        """
        import app.platform.extensions.bootstrap as bootstrap_mod
        from app.api import main as main_module

        # Lifespan must reference bootstrap (WORK-01 drift guard)
        lifespan_src = inspect.getsource(main_module.lifespan)
        assert "bootstrap" in lifespan_src, (
            "BUG-003 / WORK-01: lifespan must call bootstrap() — the shared "
            "extension-load sequence that calls check_enterprise_overlay_requested."
        )

        # bootstrap() itself must call check_enterprise_overlay_requested
        bootstrap_src = inspect.getsource(bootstrap_mod.bootstrap)
        assert "check_enterprise_overlay_requested" in bootstrap_src, (
            "BUG-003: bootstrap() must call check_enterprise_overlay_requested() "
            "so an enterprise-requested-but-inactive deploy fails loudly."
        )
