"""CatalogPort contract tests.

Mirrors ``test_processing_port.py``'s conformance shape for the sibling port:
the community default satisfies the Protocol, and a method the Protocol
requires is genuinely required — which is what an ``EXTENSION_API_VERSION``
bump exists to make the loader refuse at boot.
"""

from __future__ import annotations

from app.core.catalog_port import CatalogPort
from app.platform.extensions.defaults import DefaultCatalogPort


def test_default_catalog_port_satisfies_the_contract() -> None:
    assert isinstance(DefaultCatalogPort(), CatalogPort)


def test_a_port_missing_the_narrow_raster_meta_read_does_not_satisfy_the_contract() -> (
    None
):
    """refactor(stac): why EXTENSION_API_VERSION went 5 -> 6.

    ``fetch_raster_meta_bulk_without_vrt`` is a REQUIRED method, not an
    optional one. Every STAC item and item-page response reads raster metadata
    through it — including an empty page — so an overlay that replaces the
    ``catalog_port`` slot without it would answer AttributeError instead of a
    page. The loader has to refuse such an overlay at boot, and the version
    bump is what makes it refuse.

    The overlay that ships today is unaffected either way: it wraps the prior
    implementation as a pure ``__getattr__`` delegate and so inherits the
    method. This test is about the ones that do not.
    """

    class _OverlayPortWithoutIt:
        """Everything the default offers, minus the one method under test."""

        def __init__(self) -> None:
            self._inner = DefaultCatalogPort()

        def __getattr__(self, name):  # type: ignore[no-untyped-def]
            if name == "fetch_raster_meta_bulk_without_vrt":
                raise AttributeError(name)
            return getattr(self._inner, name)

    assert not isinstance(_OverlayPortWithoutIt(), CatalogPort)
