"""fetch_cog_info's georeferencing extraction (#1334).

Titiler's ``/cog/info`` reply already carries ``crs`` (an OGC CRS URI),
which nothing downstream ever read out of it before this fix. Every other
test in this codebase that touches ``fetch_cog_info`` stubs the function
wholesale (see ``test_stac_refresh_1266.py``'s ``cog_info`` fixture and
``test_stac_import.py``), which would never catch a regression in the
extraction itself — these are unit tests of that extraction, against
Titiler's actual response shape (captured live against a 2.2.1 instance,
see ``cog_info.py``'s ``_georeferencing`` docstring for the exact payload).

fix(#1334 review): ``res_x``/``res_y`` are still not derived from
``/cog/info`` — a prior version of this file computed them from
``bounds``/pixel-dimensions and asserted on the result, and that computation
is gone. fix(#1375): they come instead from ``/cog/stac``'s
``proj:transform``, an endpoint that publishes the real affine, so
``TestGeotransform`` below asserts on measured numbers rather than on their
absence.
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

# A Titiler 2.2.1 /cog/stac reply, trimmed to what _geotransform reads. The
# affine is a real 30°-rotated one, captured from the pinned image against a
# synthetic rotated COG with 10 m pixels: element 0 is cos(30°)*10 and the
# shear terms are sin(30°)*10, which is why the numbers below are 8.66/5.0
# rather than a round 10. An axis-aligned file returns the same shape with
# both shear terms exactly 0.
_TITILER_STAC_ITEM = {
    "type": "Feature",
    "stac_version": "1.1.0",
    "id": "scene",
    "properties": {
        "proj:epsg": 32621,
        "proj:shape": [2667, 2658],
        "proj:transform": [
            8.660254037844387,
            -4.999999999999999,
            373185.0,
            4.999999999999999,
            -8.660254037844387,
            8286015.0,
            0.0,
            0.0,
            1.0,
        ],
    },
    "assets": {"data": {"href": "https://origin.test/scene.tif"}},
}

_AXIS_ALIGNED_TRANSFORM = [100.0, 0.0, 373185.0, 0.0, -100.0, 8286015.0, 0.0, 0.0, 1.0]


def _install(
    monkeypatch,
    info: dict,
    *,
    stats_status: int = 200,
    stac_item: dict | None = _TITILER_STAC_ITEM,
    stac_status: int = 200,
) -> None:
    """Route the three COG-endpoint requests fetch_cog_info makes to one table.

    fetch_cog_info builds its own ``httpx.AsyncClient`` directly rather than
    through a factory seam (Titiler is an internal trusted service, not a
    caller-controlled origin), so the client class itself is the thing to
    replace.
    """

    def _handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/cog/statistics" in url:
            return httpx.Response(
                stats_status, json={} if stats_status == 200 else None
            )
        if "/cog/stac" in url:
            return httpx.Response(stac_status, json=stac_item)
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

    async def test_crs_wkt_is_serialized_as_wkt2(self, monkeypatch) -> None:
        """fix(#1376): this value reaches ``RasterAsset.crs_wkt``, which
        ``to_stac_properties()`` publishes as ``proj:wkt2``. rasterio's
        default export is WKT1_GDAL, so the version has to be asked for —
        and the root keyword is the whole difference a strict consumer sees
        (``PROJCS[`` vs ``PROJCRS[``)."""
        _install(monkeypatch, _TITILER_INFO)
        result = await fetch_cog_info("https://origin.test/scene.tif")
        assert result is not None
        assert result["crs_wkt"].startswith("PROJCRS[")

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


class TestGeotransform:
    """fix(#1375): the resolution pair and the rotation flag, from
    ``/cog/stac``'s ``proj:transform``.

    ``/cog/info`` still carries no transform — that is why #1334 refused to
    divide its bounding envelope by pixel dimensions, and why the numbers
    come from a second endpoint rather than a smarter reading of the first.
    """

    async def test_resolution_comes_from_the_affine_not_the_envelope(
        self, monkeypatch
    ) -> None:
        """The proving case. This item's raster is rotated 30°, so its
        bounding envelope is much wider than its footprint: deriving from
        ``/cog/info``'s ``bounds`` would report ~100 m where the affine says
        the pixels are 8.66 m on the transform's own axes — the same number
        ``raster/cog.py`` stores for a local upload of the same file."""
        _install(monkeypatch, _TITILER_INFO)
        result = await fetch_cog_info("https://origin.test/scene.tif")
        assert result is not None
        assert result["res_x"] == pytest.approx(8.660254037844387)
        assert result["res_y"] == pytest.approx(8.660254037844387)

    async def test_a_rotated_transform_sets_is_rotated(self, monkeypatch) -> None:
        """The flag the local path sets from ``transform.b``/``transform.d``
        and that a remote row could never answer before — it defaulted to
        the column's ``false``, asserting axis-alignment with no evidence."""
        _install(monkeypatch, _TITILER_INFO)
        result = await fetch_cog_info("https://origin.test/scene.tif")
        assert result is not None
        assert result["is_rotated"] is True

    async def test_an_axis_aligned_transform_clears_is_rotated(
        self, monkeypatch
    ) -> None:
        item = {
            **_TITILER_STAC_ITEM,
            "properties": {
                **_TITILER_STAC_ITEM["properties"],
                "proj:transform": _AXIS_ALIGNED_TRANSFORM,
            },
        }
        _install(monkeypatch, _TITILER_INFO, stac_item=item)
        result = await fetch_cog_info("https://origin.test/scene.tif")
        assert result is not None
        assert result["is_rotated"] is False
        assert result["res_x"] == pytest.approx(100.0)
        assert result["res_y"] == pytest.approx(100.0)

    async def test_resolution_is_positive_for_a_north_up_transform(
        self, monkeypatch
    ) -> None:
        """``transform.e`` is negative for the usual north-up raster; the
        stored resolution is a magnitude, matching ``abs(src.transform.e)``
        on the local path."""
        _install(
            monkeypatch,
            _TITILER_INFO,
            stac_item={
                **_TITILER_STAC_ITEM,
                "properties": {
                    **_TITILER_STAC_ITEM["properties"],
                    "proj:transform": _AXIS_ALIGNED_TRANSFORM,
                },
            },
        )
        result = await fetch_cog_info("https://origin.test/scene.tif")
        assert result is not None
        assert result["res_y"] > 0

    @pytest.mark.parametrize(
        "properties",
        [
            {},
            {"proj:transform": None},
            {"proj:transform": [10.0, 0.0, 1.0]},
            {"proj:transform": "10,0,1,0,-10,2"},
            {"proj:transform": [10.0, 0.0, 1.0, 0.0, "not a number", 2.0]},
        ],
        ids=["absent", "null", "too-short", "not-a-list", "unparseable-member"],
    )
    async def test_a_transform_it_cannot_read_leaves_the_keys_absent(
        self, monkeypatch, properties
    ) -> None:
        """Absent, not None. The two callers write these straight onto the
        row, so a None would assert "measured, and there is no value" where
        an absent key leaves the column as it was."""
        _install(
            monkeypatch,
            _TITILER_INFO,
            stac_item={**_TITILER_STAC_ITEM, "properties": properties},
        )
        result = await fetch_cog_info("https://origin.test/scene.tif")
        assert result is not None
        assert "res_x" not in result
        assert "res_y" not in result
        assert "is_rotated" not in result

    async def test_a_failing_stac_endpoint_does_not_fail_the_probe(
        self, monkeypatch
    ) -> None:
        """Same contract as the optional statistics call: the rest of the
        probe is still worth having."""
        _install(monkeypatch, _TITILER_INFO, stac_item=None, stac_status=500)
        result = await fetch_cog_info("https://origin.test/scene.tif")
        assert result is not None
        assert result["crs_wkt"] is not None
        assert "res_x" not in result


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
