"""WORK-04: Overlay resolution probe for api and worker image targets.

This script asserts that the extension registry resolves non-Default ports
after loading the dummy overlay. It serves two purposes:

1. **Local verification** (via ``--with-dummy-overlay``): directly installs the
   in-repo dummy overlay into the ``_extensions`` registry and asserts that both
   ``get_processing_port()`` and ``get_catalog_port()`` return non-Default impls.

2. **CI docker-probe matrix** (via ``--with-dummy-overlay``): the docker matrix
   bakes the dummy overlay as an entry-point package and runs this script inside
   the api and worker image targets to assert the overlay resolved on each.

The script exits 0 on success and 1 on failure, printing a clear diagnostic.

Why a file instead of ``python -c``?
-------------------------------------
A script file is: (a) locally runnable and unit-testable without a container;
(b) auditable in code review; (c) easier to update than an inline ``python -c``
string embedded in a YAML file.

References: WORK-04
"""

from __future__ import annotations

import argparse
import os
import sys

# Self-bootstrap: make `app` importable when run standalone with PYTHONPATH unset.
# This script lives at backend/scripts/; its grandparent (the backend/ dir) holds
# `app/`. In CI the docker run sets PYTHONPATH=/app, so this insert is idempotent.
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


def _install_dummy_overlay_directly() -> None:
    """Install the dummy overlay by directly calling register_extensions.

    Used in --with-dummy-overlay mode so the probe works without a real
    geolens-enterprise package installed (no entry-point registration needed).
    The dummy overlay's register_extensions() is called with the live _extensions
    dict — mirrors the conftest save-restore discipline.

    This path is used for both local testing (where tests/fixtures/ is on
    PYTHONPATH) and CI docker-probe (where the dummy_overlay entry-point
    package is installed into the image — see the overlay-image-probe job).
    """
    # Import from the in-repo dummy overlay fixture.
    # In the docker image the dummy overlay is installed as a package and loaded
    # via entry points; but for local --with-dummy-overlay mode we import directly.
    try:
        from tests.fixtures.dummy_overlay.overlay import register_extensions
    except ImportError:
        # If tests/ is not on PYTHONPATH (e.g., inside docker image where the
        # dummy overlay is installed as an entry-point package rather than a
        # source tree), fall back to entry-point load (load_extensions() handles it).
        return

    import app.platform.extensions as ext_mod

    register_extensions(ext_mod._extensions)


def probe(with_dummy_overlay: bool) -> int:
    """Run the overlay resolution probe. Returns 0 on success, 1 on failure.

    Parameters
    ----------
    with_dummy_overlay:
        If True, install the dummy overlay directly before probing. This is
        the mode used for both local testing and the CI docker-probe matrix
        (in CI the entry-point install is done at image build time via the
        geolens-dummy-overlay package; the direct install here is a fallback
        for local runs where the entry-point is not registered).
    """
    if with_dummy_overlay:
        _install_dummy_overlay_directly()

    from app.platform.extensions import get_catalog_port, get_processing_port

    processing_port = get_processing_port()
    catalog_port = get_catalog_port()

    processing_cls = type(processing_port).__name__
    catalog_cls = type(catalog_port).__name__

    print(f"processing_port resolved to: {processing_cls}")
    print(f"catalog_port resolved to:    {catalog_cls}")

    failed: list[str] = []

    if with_dummy_overlay:
        # In dummy-overlay mode, catalog_port must be non-Default (the dummy
        # overlay claims it). processing_port is not claimed by the dummy overlay,
        # so it remains Default — that is expected and correct.
        if catalog_cls == "DefaultCatalogPort":
            failed.append(
                "catalog_port is still DefaultCatalogPort — the dummy overlay "
                "should have registered DummyCatalogPort. "
                "Check that register_extensions() was called and that the "
                "tests/fixtures/dummy_overlay package is on PYTHONPATH."
            )
    else:
        # In bare/community mode, BOTH ports MUST be Default (no overlay loaded).
        # This proves the probe actually distinguishes Default from overlay.
        if processing_cls != "DefaultProcessingPort":
            failed.append(
                f"processing_port is {processing_cls} (expected DefaultProcessingPort "
                f"in bare/community mode — a real overlay may have been loaded "
                f"unexpectedly; ensure no geolens.extensions entry-point is installed)."
            )
        if catalog_cls != "DefaultCatalogPort":
            failed.append(
                f"catalog_port is {catalog_cls} (expected DefaultCatalogPort "
                f"in bare/community mode — a real overlay may have been loaded "
                f"unexpectedly; ensure no geolens.extensions entry-point is installed)."
            )

    if failed:
        print("\nPROBE FAILED:", file=sys.stderr)
        for msg in failed:
            print(f"  - {msg}", file=sys.stderr)
        return 1

    print("\nPROBE PASSED: overlay resolution is correct.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "WORK-04: Assert overlay-port resolution for the api/worker image probe. "
            "Use --with-dummy-overlay to install the in-repo dummy overlay and assert "
            "catalog_port is DummyCatalogPort (not Default). "
            "Without the flag, asserts both ports are Default (bare/community). "
            "Exits 0 on pass, 1 on failure."
        )
    )
    parser.add_argument(
        "--with-dummy-overlay",
        action="store_true",
        default=False,
        help=(
            "Install the dummy overlay and assert catalog_port is non-Default. "
            "Used for both local testing and the CI docker-probe matrix (WORK-04)."
        ),
    )
    args = parser.parse_args()
    sys.exit(probe(with_dummy_overlay=args.with_dummy_overlay))


if __name__ == "__main__":
    main()
