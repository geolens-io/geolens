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
    the app lifespan so a misconfigured deploy never silently boots OSS."""

    def test_check_called_from_lifespan(self):
        """main.py lifespan source must reference check_enterprise_overlay_requested."""
        from app.api import main as main_module

        lifespan_src = inspect.getsource(main_module.lifespan)
        assert "check_enterprise_overlay_requested" in lifespan_src, (
            "BUG-003: lifespan must call check_enterprise_overlay_requested() "
            "after load_extensions() so an enterprise-requested-but-inactive "
            "deploy fails loudly instead of silently running OSS."
        )
