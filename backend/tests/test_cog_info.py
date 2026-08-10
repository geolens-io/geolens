"""fetch_cog_info's georeferencing extraction (#1334).

Titiler's ``/cog/info`` reply already carries ``crs`` (an OGC CRS URI),
which nothing downstream ever read out of it before this fix. Every other
test in this codebase that touches ``fetch_cog_info`` stubs the function
wholesale (see ``test_stac_refresh_1266.py``'s ``cog_info`` fixture and
``test_stac_import.py``), which would never catch a regression in the
extraction itself — these are unit tests of that extraction, against
Titiler's actual response shape (captured live against a 2.2.1 instance,
see ``cog_info.py``'s ``_georeferencing`` docstring for the exact payload).

fix(#1334 review): ``res_x``/``res_y`` are deliberately NOT derived here —
see ``_georeferencing``'s docstring. A prior version of this file computed
them from ``bounds``/pixel-dimensions and asserted on the result; that
computation is gone, and so are those assertions.
"""

from __future__ import annotations

import httpx
import pytest

from app.modules.catalog.sources.cog_info import fetch_cog_info, reconcile_epsg

pytestmark = pytest.mark.anyio

# Captured before any monkeypatching so the factory below can build a real
# client: it replaces the module's `httpx.AsyncClient` attribute, so a
# factory that referenced `httpx.AsyncClient` itself would recurse into its
# own replacement.
_RealAsyncClient = httpx.AsyncClient

# A Titiler 2.2.1 /cog/info reply, captured live against a real COG: `crs` is
# an OGC CRS URI, and `bounds` is in the dataset's OWN projection (UTM 21N
# metres here) — the magnitude alone rules out WGS84 degrees.
_TITILER_INFO = {
    "bounds": [373185.0, 8019284.949381611, 639014.9492102272, 8286015.0],
    "crs": "http://www.opengis.net/def/crs/EPSG/0/32621",
    "band_metadata": [["b1", {}]],
    "band_descriptions": [["b1", "b1"]],
    "dtype": "uint16",
    "nodata_type": "None",
    "colorinterp": ["gray"],
    "scales": [1.0],
    "offsets": [0.0],
    "driver": "GTiff",
    "count": 1,
    "width": 2658,
    "height": 2667,
    "overviews": [2, 4, 8, 16],
}


def _install(monkeypatch, info: dict, *, stats_status: int = 200) -> None:
    """Route both COG-endpoint requests fetch_cog_info makes to one table.

    fetch_cog_info builds its own ``httpx.AsyncClient`` directly rather than
    through a factory seam (Titiler is an internal trusted service, not a
    caller-controlled origin), so the client class itself is the thing to
    replace.
    """

    def _handler(request: httpx.Request) -> httpx.Response:
        if "/cog/statistics" in str(request.url):
            return httpx.Response(
                stats_status, json={} if stats_status == 200 else None
            )
        return httpx.Response(200, json=info)

    def _factory(*args, **kwargs) -> httpx.AsyncClient:
        kwargs.pop("timeout", None)
        return _RealAsyncClient(transport=httpx.MockTransport(_handler))

    monkeypatch.setattr(
        "app.modules.catalog.sources.cog_info.httpx.AsyncClient", _factory
    )


class TestGeoreferencing:
    async def test_crs_wkt_comes_from_titilers_own_reply(self, monkeypatch) -> None:
        """fix(#1334): the value was retrievable all along — this shows
        fetch_cog_info actually reading it out, not just Titiler having sent
        it."""
        _install(monkeypatch, _TITILER_INFO)
        result = await fetch_cog_info("https://origin.test/scene.tif")
        assert result is not None
        assert result["crs_wkt"] is not None
        assert "32621" in result["crs_wkt"]

    async def test_epsg_comes_from_the_same_parsed_crs_as_the_wkt(
        self, monkeypatch
    ) -> None:
        """fix(#1334 review): both keys have to come off the SAME parsed CRS
        object, or a caller preferring this EPSG over a stale item
        declaration could still end up with an EPSG and a WKT that name
        different projections."""
        _install(monkeypatch, _TITILER_INFO)
        result = await fetch_cog_info("https://origin.test/scene.tif")
        assert result is not None
        assert result["epsg"] == 32621

    async def test_an_unparseable_crs_reports_no_epsg_either(self, monkeypatch) -> None:
        info = {**_TITILER_INFO, "crs": "not a crs identifier"}
        _install(monkeypatch, info)
        result = await fetch_cog_info("https://origin.test/scene.tif")
        assert result is not None
        assert result["epsg"] is None

    async def test_fetch_cog_info_never_reports_a_resolution(self, monkeypatch) -> None:
        """fix(#1334 review): Titiler's /cog/info carries no affine
        transform, so nothing here can tell a rotated remote COG from an
        axis-aligned one — and dividing its bounding envelope by pixel
        dimensions is only correct for the latter. A wrong number that looks
        like a measurement is worse than the blank display it would replace,
        so `res_x`/`res_y` are not derived at all, for any input."""
        _install(monkeypatch, _TITILER_INFO)
        result = await fetch_cog_info("https://origin.test/scene.tif")
        assert result is not None
        assert "res_x" not in result
        assert "res_y" not in result

    async def test_a_missing_crs_degrades_to_none_not_a_raise(
        self, monkeypatch
    ) -> None:
        info = {**_TITILER_INFO, "crs": None}
        _install(monkeypatch, info)
        result = await fetch_cog_info("https://origin.test/scene.tif")
        assert result is not None
        assert result["crs_wkt"] is None

    async def test_an_unparseable_crs_degrades_to_none_not_a_raise(
        self, monkeypatch
    ) -> None:
        info = {**_TITILER_INFO, "crs": "not a crs identifier"}
        _install(monkeypatch, info)
        result = await fetch_cog_info("https://origin.test/scene.tif")
        assert result is not None
        assert result["crs_wkt"] is None


class TestReconcileEpsg:
    """fix(#1334 review, round 3): the two questions this function tells
    apart. "The probe returned no EPSG" and "the probe established no CRS
    at all" look the same from ``epsg is None`` alone, but only one of them
    means the declared value is trustworthy."""

    def test_no_crs_from_the_probe_falls_back_to_declared(self) -> None:
        assert reconcile_epsg({}, 4326) == 4326
        assert reconcile_epsg({"crs_wkt": None, "epsg": None}, 4326) == 4326

    def test_a_probed_crs_wins_even_when_it_disagrees_with_declared(self) -> None:
        probe = {"crs_wkt": 'PROJCS["UTM 21N"]', "epsg": 32621}
        assert reconcile_epsg(probe, 4326) == 32621

    def test_a_probed_crs_with_no_mappable_epsg_stays_unset(self) -> None:
        """The exact case round 3 caught: a real, successfully-probed WKT
        that PROJ cannot map to an authority code must not fall back to the
        item's declared EPSG — that would pair the probed WKT with a
        DECLARED code that may name a different projection, reproducing the
        contradiction this function exists to prevent."""
        probe = {"crs_wkt": 'LOCAL_CS["some custom engineering CRS"]', "epsg": None}
        assert reconcile_epsg(probe, 4326) is None

    def test_no_probe_data_at_all_falls_back_to_declared(self) -> None:
        """An unmoved asset never calls fetch_cog_info; the caller passes an
        empty dict rather than None."""
        assert reconcile_epsg({}, None) is None
