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

from types import SimpleNamespace

import httpx
import pytest
import rasterio.crs

from app.modules.catalog.sources import cog_info
from app.modules.catalog.sources.cog_info import fetch_cog_info, reconcile_epsg

pytestmark = pytest.mark.anyio

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
# rather than a round 10. The PIXELS are still 10 m — hypot(8.66, 5.0) — which
# is the whole point of the #1375 review finding. An axis-aligned file returns
# the same shape with both shear terms exactly 0, where element 0 IS the
# resolution.
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
    stats: dict | None = None,
    stats_status: int = 200,
    stac_item: dict | None = _TITILER_STAC_ITEM,
    stac_status: int = 200,
) -> None:
    """Route the three COG-endpoint requests fetch_cog_info makes to one table.

    fetch_cog_info builds its own ``httpx.AsyncClient`` directly rather than
    through a factory seam (Titiler is an internal trusted service, not a
    caller-controlled origin), so the module's ``httpx`` is swapped for one
    whose client answers from this table. Every other client, such as the
    origin probe's, stays real.
    """

    def _handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/cog/statistics" in url:
            if stats_status != 200:
                return httpx.Response(stats_status, json=None)
            return httpx.Response(stats_status, json=stats if stats is not None else {})
        if "/cog/stac" in url:
            return httpx.Response(stac_status, json=stac_item)
        return httpx.Response(200, json=info)

    def _factory(*args, **kwargs) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(_handler))

    monkeypatch.setattr(
        "app.modules.catalog.sources.cog_info.httpx",
        SimpleNamespace(AsyncClient=_factory, Timeout=httpx.Timeout),
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
        """The remote probe stores WKT2 (``PROJCRS[``), not rasterio's default WKT1."""
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


# Valid WKT, as Titiler reports a CRS PROJ cannot match to an authority code.
_UTM_21N_WKT = rasterio.crs.CRS.from_epsg(32621).to_wkt()

# The CRS84 forms a probe may report. The first is what the pinned Titiler
# sends (rio-tiler writes version 0 for an authority with no version); the
# rest are the forms parse_crs_uri would otherwise map to EPSG:4326.
_CRS84_FORMS = [
    "http://www.opengis.net/def/crs/OGC/0/CRS84",
    "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
    "http://www.opengis.net/def/crs/OGC/1.3/CRS84/",
    "https://www.opengis.net/def/crs/OGC/1.3/CRS84",
    "https://www.opengis.net/def/crs/OGC/1.3/CRS84/",
    "urn:ogc:def:crs:OGC:1.3:CRS84",
]
_CRS84_URI = _CRS84_FORMS[0]
# What main stored for each: its own call on the reported string, which gives
# PROJ's CRS84, longitude first.
_MAIN_CRS84_WKT = {
    form: rasterio.crs.CRS.from_user_input(form).to_wkt(version="WKT2_2019")
    for form in _CRS84_FORMS
}


@pytest.fixture
def crs_text_parses(monkeypatch) -> list[str]:
    """Swap rasterio's CRS for one that refuses CRS text, recording each attempt.

    The one text it accepts is the probe's own CRS84 constant.
    """
    real = rasterio.crs.CRS
    attempts: list[str] = []

    def _refuse(name: str):
        def _parse(*args, **kwargs):
            if name == "from_user_input" and args == (cog_info._CRS84_URI,):
                return real.from_user_input(*args)
            attempts.append(name)
            raise AssertionError(f"CRS text parsed through {name}")

        return staticmethod(_parse)

    class _EpsgOnlyCRS:
        from_epsg = staticmethod(real.from_epsg)
        from_user_input = _refuse("from_user_input")
        from_wkt = _refuse("from_wkt")
        from_string = _refuse("from_string")

    monkeypatch.setattr(rasterio.crs, "CRS", _EpsgOnlyCRS)
    return attempts


class TestAuthorityCrsOnly:
    @pytest.mark.parametrize(
        ("crs", "epsg"),
        [
            ("EPSG:32621", 32621),
            ("http://www.opengis.net/def/crs/EPSG/0/32621", 32621),
            ("urn:ogc:def:crs:EPSG::32621", 32621),
        ],
    )
    async def test_an_epsg_reference_builds_the_wkt_from_the_registry(
        self, monkeypatch, crs_text_parses, crs, epsg
    ) -> None:
        """An EPSG reference yields its code and the registry's WKT2."""
        _install(monkeypatch, {**_TITILER_INFO, "crs": crs})
        result = await fetch_cog_info("https://origin.test/scene.tif")

        assert result is not None
        assert result["epsg"] == epsg
        assert result["crs_wkt"] == rasterio.crs.CRS.from_epsg(epsg).to_wkt(
            version="WKT2_2019"
        )
        assert (
            result["crs_is_geographic"],
            result["crs_has_degree_unit"],
            result["crs_metres_per_unit"],
        ) == (False, False, 1.0)
        assert crs_text_parses == []

    @pytest.mark.parametrize(
        "crs",
        [
            _UTM_21N_WKT,
            "http://www.opengis.net/def/crs/ESRI/0/102100",
            "EPSG:999999999",
        ],
        ids=["wkt", "esri-uri", "unknown-code"],
    )
    async def test_any_other_crs_is_unidentified_without_parsing_it(
        self, monkeypatch, crs_text_parses, crs
    ) -> None:
        """WKT, another authority or a code PROJ lacks is reported, not dropped."""
        _install(monkeypatch, {**_TITILER_INFO, "crs": crs})
        result = await fetch_cog_info("https://origin.test/scene.tif")

        assert result is not None
        assert (result["crs_wkt"], result["epsg"]) == (None, None)
        assert result["crs_unidentified"] is True
        assert reconcile_epsg(result, 32621) is None
        assert crs_text_parses == []

    @pytest.mark.parametrize("crs", _CRS84_FORMS)
    async def test_crs84_stays_crs84(self, monkeypatch, crs_text_parses, crs) -> None:
        """CRS84 is not EPSG:4326: it is longitude first, and has no EPSG code."""
        _install(monkeypatch, {**_TITILER_INFO, "crs": crs})
        result = await fetch_cog_info("https://origin.test/scene.tif")

        assert result is not None
        assert result["crs_wkt"] == _MAIN_CRS84_WKT[crs]
        assert result["epsg"] is None
        assert (
            result["crs_is_geographic"],
            result["crs_has_degree_unit"],
            result["crs_metres_per_unit"],
        ) == (True, True, None)
        assert "crs_unidentified" not in result
        assert reconcile_epsg(result, 4326) is None
        assert crs_text_parses == []

    @pytest.mark.parametrize(
        "crs", ["EPSG:4326", "EPSG:32618", "EPSG:2263", "EPSG:4807", _CRS84_FORMS[0]]
    )
    async def test_the_registry_facts_match_the_probe_childs(
        self, monkeypatch, crs
    ) -> None:
        """A remote row's facts equal what ingest's probe child says of its text."""
        from app.processing.raster import probe

        _install(monkeypatch, {**_TITILER_INFO, "crs": crs})
        result = await fetch_cog_info("https://origin.test/scene.tif")

        assert result is not None
        assert {
            key: result[key]
            for key in (
                "crs_is_geographic",
                "crs_has_degree_unit",
                "crs_metres_per_unit",
            )
        } == probe.crs_facts(result["crs_wkt"])

    async def test_no_reported_crs_still_takes_the_declared_code(
        self, monkeypatch
    ) -> None:
        """Titiler naming no CRS is the one case the declaration may fill."""
        info = {k: v for k, v in _TITILER_INFO.items() if k != "crs"}
        _install(monkeypatch, info)
        result = await fetch_cog_info("https://origin.test/scene.tif")

        assert result is not None
        assert "crs_unidentified" not in result
        assert reconcile_epsg(result, 32621) == 32621


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
        """The proving case. This item's raster is rotated 30° with 10 m
        pixels, so its bounding envelope is wider than its footprint and a
        figure derived from ``/cog/info``'s ``bounds`` would overstate the
        resolution. 10.0 is also what ``raster/cog.py`` stores for a local
        upload of the same file — both paths run these six numbers through
        ``pixel_size_from_affine``."""
        _install(monkeypatch, _TITILER_INFO)
        result = await fetch_cog_info("https://origin.test/scene.tif")
        assert result is not None
        assert result["res_x"] == pytest.approx(10.0)
        assert result["res_y"] == pytest.approx(10.0)

    async def test_a_rotated_resolution_is_the_pixel_vector_not_its_x_component(
        self, monkeypatch
    ) -> None:
        """fix(#1375 review): the finding this file exists to keep fixed.

        Element 0 of this fixture's affine is 8.66 — the x-COMPONENT of a
        pixel vector whose length is 10. Reading the resolution off elements
        0 and 4 understates a 30°-rotated raster by 13%, and that number
        reaches the UI and STAC's ``gsd``. The assertion is written as the
        contrast so a regression to ``abs(a)`` fails here rather than
        silently shipping the smaller number."""
        _install(monkeypatch, _TITILER_INFO)
        result = await fetch_cog_info("https://origin.test/scene.tif")
        assert result is not None
        element_0 = _TITILER_STAC_ITEM["properties"]["proj:transform"][0]
        assert element_0 == pytest.approx(8.660254037844387)
        assert result["res_x"] != pytest.approx(element_0)
        assert result["res_x"] == pytest.approx(10.0)

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


class TestBandStatistics:
    async def test_band_info_stays_in_band_order_past_nine_bands(
        self, monkeypatch
    ) -> None:
        stats = {
            f"b{n}": {"min": float(n), "max": float(n) + 1, "mean": float(n) + 0.5}
            for n in range(1, 12)
        }
        _install(monkeypatch, {**_TITILER_INFO, "count": 11}, stats=stats)
        result = await fetch_cog_info("https://origin.test/scene.tif")
        assert result is not None
        assert [entry["min"] for entry in result["band_info"]] == [
            float(n) for n in range(1, 12)
        ]

    async def test_a_non_numeric_b_key_does_not_drop_the_numbered_bands(
        self, monkeypatch
    ) -> None:
        stats = {
            f"b{n}": {"min": float(n), "max": float(n) + 1, "mean": float(n) + 0.5}
            for n in range(1, 4)
        }
        stats["blue"] = {"min": -1.0, "max": -1.0, "mean": -1.0}
        _install(monkeypatch, {**_TITILER_INFO, "count": 3}, stats=stats)
        result = await fetch_cog_info("https://origin.test/scene.tif")
        assert result is not None
        assert [entry["min"] for entry in result["band_info"]] == [1.0, 2.0, 3.0]


class TestNodata:
    async def test_a_nodata_type_stores_its_value(self, monkeypatch) -> None:
        info = {**_TITILER_INFO, "nodata_type": "Nodata", "nodata_value": 0.0}
        _install(monkeypatch, info)
        result = await fetch_cog_info("https://origin.test/scene.tif")
        assert result is not None
        assert result["nodata"] == 0.0

    @pytest.mark.parametrize("nodata_type", ["Mask", "Alpha", "None"])
    async def test_a_non_scalar_nodata_type_stores_none(
        self, monkeypatch, nodata_type
    ) -> None:
        info = {**_TITILER_INFO, "nodata_type": nodata_type, "nodata_value": None}
        _install(monkeypatch, info)
        result = await fetch_cog_info("https://origin.test/scene.tif")
        assert result is not None
        assert result["nodata"] is None


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
