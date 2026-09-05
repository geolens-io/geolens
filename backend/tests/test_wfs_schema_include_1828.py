"""fix(#1828): a credentialed WFS whose DescribeFeatureType schema includes a
location on another origin is refused before GDAL is handed the source.

The WFS driver resolves every ``xs:include`` of the schema it is given, with
the credential header attached, before any GetFeature. No GDAL option turns
that off, so `_check_wfs` reads the DescribeFeatureType the driver reads for
the layer a door is about to open, on the submitted origin, and refuses the
first include the driver would fetch from another origin or open as a path.
Both spawn points refuse a credentialed WFS that names no layer before GDAL
starts, so GDAL never opens every layer on the credential's behalf.
The import path and the GetFeature schema download are not refused: the
vector envs pin both off (`test_gdal_env.py`), and a real schema imports GML
from another origin.

Every credential value is generated per test, so an assertion that a value
never reached a host cannot pass by coincidence.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.service_tokens import CredentialMethod, ServiceCredential
from app.modules.catalog.sources import preview as preview_mod
from app.platform import security
from app.platform.service_endpoints import (
    CrossOriginEndpointError,
    EndpointCheckFailedError,
    assert_endpoints_stay_on_origin,
)

pytestmark = pytest.mark.anyio

_SVC_ORIGIN = "https://service.example"
_SVC_WFS = f"{_SVC_ORIGIN}/geoserver/wfs"
_FOREIGN = "https://collector.example"
_XS = "http://www.w3.org/2001/XMLSchema"
_LAYER = "topp:parcels"


def _value() -> str:
    return uuid.uuid4().hex


def _capabilities(names: list[str], *, version: str | None = "2.0.0") -> str:
    """A WFS capabilities document advertising *names*, on this origin."""
    version_attr = "" if version is None else f' version="{version}"'
    types = "".join(
        f"<FeatureType><Name>{name}</Name><Title>{name}</Title></FeatureType>"
        for name in names
    )
    return f"""<?xml version="1.0"?>
<WFS_Capabilities{version_attr}
    xmlns="http://www.opengis.net/wfs/2.0"
    xmlns:ows="http://www.opengis.net/ows/1.1"
    xmlns:xlink="http://www.w3.org/1999/xlink">
  <ows:OperationsMetadata>
    <ows:Operation name="DescribeFeatureType"><ows:DCP><ows:HTTP>
      <ows:Get xlink:href="{_SVC_WFS}"/></ows:HTTP></ows:DCP></ows:Operation>
    <ows:Operation name="GetFeature"><ows:DCP><ows:HTTP>
      <ows:Get xlink:href="{_SVC_WFS}"/></ows:HTTP></ows:DCP></ows:Operation>
  </ows:OperationsMetadata>
  <FeatureTypeList>{types}</FeatureTypeList>
</WFS_Capabilities>"""


def _schema(
    names: list[str] | None = None,
    *,
    include: str | None = None,
    extra: str = "",
) -> str:
    """A DescribeFeatureType answer declaring *names*, with the ordinary
    off-origin GML import every real schema carries."""
    declared = "".join(
        f'<xs:element name="{n.split(":", 1)[-1]}" type="topp:{n.split(":", 1)[-1]}Type"'
        ' substitutionGroup="gml:AbstractFeature"/>'
        for n in names or [_LAYER]
    )
    included = "" if include is None else f'<xs:include schemaLocation="{include}"/>'
    return f"""<?xml version="1.0"?>
<xs:schema xmlns:xs="{_XS}" xmlns:gml="http://www.opengis.net/gml/3.2"
    xmlns:topp="http://example.test/topp"
    targetNamespace="http://example.test/topp" elementFormDefault="qualified">
  <xs:import namespace="http://www.opengis.net/gml/3.2"
      schemaLocation="http://schemas.opengis.net/gml/3.2.1/gml.xsd"/>
  {included}{extra}
  {declared}
</xs:schema>"""


def _exception_report() -> str:
    return """<?xml version="1.0"?>
<ows:ExceptionReport xmlns:ows="http://www.opengis.net/ows/1.1" version="2.0.0">
  <ows:Exception exceptionCode="InvalidParameterValue" locator="typeName">
    <ows:ExceptionText>unknown type</ows:ExceptionText>
  </ows:Exception>
</ows:ExceptionReport>"""


def _as_stream(response: httpx.Response, *, chunk: int = 64) -> httpx.Response:
    """A double that streams, so the bounded read under test really runs."""
    if not response.is_stream_consumed:
        return response
    raw = response.content

    async def _chunks():
        for start in range(0, len(raw), chunk):
            yield raw[start : start + chunk]

    return httpx.Response(
        response.status_code, headers=response.headers, content=_chunks()
    )


def _params(request: httpx.Request) -> dict[str, str]:
    return {key.lower(): value for key, value in request.url.params.items()}


def _wfs(capabilities: str, describe, *, files: dict[str, str] | None = None):
    """A WFS double. ``describe(names)`` answers a DescribeFeatureType for the
    comma-separated ``TYPENAME`` it received, as text or as a response; any
    other path is looked up in ``files``."""

    def handle(request: httpx.Request) -> httpx.Response:
        params = _params(request)
        operation = params.get("request", "").lower()
        if operation == "getcapabilities":
            return httpx.Response(200, text=capabilities)
        if operation == "describefeaturetype":
            answer = describe(params.get("typename", "").split(","))
            if isinstance(answer, httpx.Response):
                return answer
            return httpx.Response(200, text=answer)
        if files is not None and request.url.path in files:
            return httpx.Response(200, text=files[request.url.path])
        return httpx.Response(404)

    return handle


def _transport(monkeypatch, handler) -> list[httpx.Request]:
    recorded: list[httpx.Request] = []

    def _handle(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return _as_stream(handler(request))

    monkeypatch.setattr(
        security, "make_safe_transport", lambda: httpx.MockTransport(_handle)
    )
    monkeypatch.setattr(security, "validate_url_for_ssrf", AsyncMock())
    monkeypatch.setattr(
        "app.platform.service_endpoints.validate_url_for_ssrf", AsyncMock()
    )
    return recorded


async def _check(
    monkeypatch,
    handler,
    *,
    url: str = _SVC_WFS,
    collection: str | None = _LAYER,
) -> tuple[list[httpx.Request], str]:
    """Run the credentialed check for a named layer, the shape the preview and
    worker doors open under; ``collection=None`` is the capabilities-only
    probe check. Returns the recorded requests and the credential value."""
    recorded = _transport(monkeypatch, handler)
    value = _value()
    await assert_endpoints_stay_on_origin(
        url,
        service_format="wfs",
        credential_line=f"X-Api-Key: {value}",
        collection=collection,
        deadline=None,
    )
    return recorded, value


async def _refused(
    monkeypatch, handler, error: type[Exception], *, collection: str | None = _LAYER
):
    recorded = _transport(monkeypatch, handler)
    with pytest.raises(error) as raised:
        await assert_endpoints_stay_on_origin(
            _SVC_WFS,
            service_format="wfs",
            credential_line=f"X-Api-Key: {_value()}",
            collection=collection,
            deadline=None,
        )
    return recorded, raised.value


def _described(recorded: list[httpx.Request]) -> list[list[str]]:
    """The type names of every DescribeFeatureType request, in order."""
    return [
        _params(request)["typename"].split(",")
        for request in recorded
        if _params(request).get("request") == "DescribeFeatureType"
    ]


def _hosts(recorded: list[httpx.Request]) -> set[str]:
    return {request.url.host for request in recorded}


class TestAnIncludeOffTheOriginIsRefused:
    uses_the_real_endpoint_check = True

    async def test_an_absolute_include_on_another_origin_is_refused_naming_it(
        self, monkeypatch
    ) -> None:
        handler = _wfs(
            _capabilities([_LAYER]),
            lambda names: _schema(names, include=f"{_FOREIGN}/inc.xsd"),
        )
        recorded = _transport(monkeypatch, handler)
        value = _value()

        with pytest.raises(CrossOriginEndpointError) as raised:
            await assert_endpoints_stay_on_origin(
                _SVC_WFS,
                service_format="wfs",
                credential_line=f"X-Api-Key: {value}",
                collection=_LAYER,
                deadline=None,
            )

        assert raised.value.code == "cross_origin_endpoint"
        assert raised.value.field == "url"
        assert raised.value.origin == _FOREIGN
        assert value not in str(raised.value)
        # The check itself read the schema on the submitted origin and nothing
        # else: the other origin was never contacted.
        assert _hosts(recorded) == {"service.example"}
        assert _described(recorded) == [[_LAYER]]

    async def test_every_read_carries_the_credential_to_the_submitted_origin_only(
        self, monkeypatch
    ) -> None:
        handler = _wfs(
            _capabilities([_LAYER]),
            lambda names: _schema(names, include=f"{_SVC_ORIGIN}/inc.xsd"),
            files={"/inc.xsd": _schema()},
        )

        recorded, value = await _check(monkeypatch, handler)

        assert [request.url.path for request in recorded] == [
            "/geoserver/wfs",
            "/geoserver/wfs",
            "/inc.xsd",
        ]
        for request in recorded:
            assert request.url.host == "service.example"
            assert request.headers["X-Api-Key"] == value

    @pytest.mark.parametrize(
        "spelling",
        [
            f'<xs:INCLUDE SCHEMALOCATION="{_FOREIGN}/inc.xsd"/>',
            f'<xs:include xs:schemaLocation="{_FOREIGN}/inc.xsd"/>',
            f"<xs:include><xs:schemaLocation>{_FOREIGN}/inc.xsd"
            "</xs:schemaLocation></xs:include>",
        ],
        ids=["upper_cased", "prefixed_attribute", "child_element"],
    )
    async def test_the_spellings_the_driver_reads_are_all_read(
        self, monkeypatch, spelling
    ) -> None:
        """GDAL matches the element and the attribute case-insensitively, after
        stripping any namespace prefix, and `CPLGetXMLValue` also answers a
        text-only child element by that name."""
        handler = _wfs(
            _capabilities([_LAYER]), lambda names: _schema(names, extra=spelling)
        )

        _recorded, error = await _refused(
            monkeypatch, handler, CrossOriginEndpointError
        )

        assert error.origin == _FOREIGN

    async def test_an_include_under_redefine_is_refused_as_a_superset(
        self, monkeypatch
    ) -> None:
        """The driver resolves only the direct children of the schema element.
        The walk covers the whole tree, which refuses a shape no real schema
        has rather than reasoning about which nesting the driver skips."""
        nested = (
            f'<xs:redefine schemaLocation="local.xsd">'
            f'<xs:include schemaLocation="{_FOREIGN}/inc.xsd"/></xs:redefine>'
        )
        handler = _wfs(
            _capabilities([_LAYER]), lambda names: _schema(names, extra=nested)
        )

        _recorded, error = await _refused(
            monkeypatch, handler, CrossOriginEndpointError
        )

        assert error.origin == _FOREIGN

    @pytest.mark.parametrize(
        ("location", "named"),
        [
            ("//collector.example/inc.xsd", "://collector.example"),
            (f"/vsicurl/{_FOREIGN}/inc.xsd", "a local path"),
            ("\\\\collector.example\\inc.xsd", "a local path"),
            ("C:/inc.xsd", "a local path"),
            ("ftp://collector.example/inc.xsd", "ftp://collector.example"),
            (f"vsicurl/{_FOREIGN}/inc.xsd", "a local path"),
            ("HTTP://collector.example/inc.xsd", "http://collector.example"),
        ],
        ids=[
            "scheme_relative",
            "vsi_path",
            "unc_path",
            "drive_path",
            "other_scheme",
            "embedded_scheme",
            "upper_cased_scheme",
        ],
    )
    async def test_a_location_the_driver_opens_as_a_path_is_refused(
        self, monkeypatch, location, named
    ) -> None:
        """Only a relative location stays inside the process: GDAL resolves it
        under its in-memory directory. Everything `CPLIsFilenameRelative`
        rejects is opened as a VSI path, and a VSI path can reach the network
        or the worker's own storage, so it is refused with the same outcome."""
        handler = _wfs(
            _capabilities([_LAYER]), lambda names: _schema(names, include=location)
        )

        recorded, error = await _refused(monkeypatch, handler, CrossOriginEndpointError)

        assert error.origin == named
        assert _hosts(recorded) == {"service.example"}

    async def test_a_same_origin_include_that_includes_another_origin_is_refused(
        self, monkeypatch
    ) -> None:
        """The driver splices an included schema in and resolves its includes
        too, so a same-origin include is read the way the driver reads it."""
        handler = _wfs(
            _capabilities([_LAYER]),
            lambda names: _schema(names, include=f"{_SVC_ORIGIN}/first.xsd"),
            files={"/first.xsd": _schema(include=f"{_FOREIGN}/second.xsd")},
        )

        recorded, error = await _refused(monkeypatch, handler, CrossOriginEndpointError)

        assert error.origin == _FOREIGN
        assert [r.url.path for r in recorded][-1] == "/first.xsd"
        assert _hosts(recorded) == {"service.example"}


class TestAnOrdinarySchemaPasses:
    uses_the_real_endpoint_check = True

    async def test_a_relative_include_passes(self, monkeypatch) -> None:
        handler = _wfs(
            _capabilities([_LAYER]),
            lambda names: _schema(names, include="types/parcels.xsd"),
        )

        recorded, _value_ = await _check(monkeypatch, handler)

        assert _described(recorded) == [[_LAYER]]
        assert len(recorded) == 2

    async def test_an_import_on_another_origin_passes(self, monkeypatch) -> None:
        """Imports are not fetched by the driver: the WFS driver passes
        `bUseSchemaImports=false` and the GML driver reads a config value the
        vector envs pin to NO. Refusing them would refuse every real schema."""
        imported = (
            '<xs:import namespace="http://example.test/other"'
            f' schemaLocation="{_FOREIGN}/other.xsd"/>'
        )
        handler = _wfs(
            _capabilities([_LAYER]), lambda names: _schema(names, extra=imported)
        )

        recorded, _value_ = await _check(monkeypatch, handler)

        assert _hosts(recorded) == {"service.example"}

    async def test_a_same_origin_absolute_include_is_read_once_and_passes(
        self, monkeypatch
    ) -> None:
        twice = (
            f'<xs:include schemaLocation="{_SVC_ORIGIN}/inc.xsd"/>'
            f'<xs:include schemaLocation="{_SVC_ORIGIN}/inc.xsd"/>'
        )
        handler = _wfs(
            _capabilities([_LAYER]),
            lambda names: _schema(names, extra=twice),
            files={"/inc.xsd": _schema(include="nested-relative.xsd")},
        )

        recorded, _value_ = await _check(monkeypatch, handler)

        assert [r.url.path for r in recorded].count("/inc.xsd") == 1

    async def test_no_advertised_feature_type_means_no_second_request(
        self, monkeypatch
    ) -> None:
        handler = _wfs(_capabilities([]), lambda names: _schema(names))

        recorded, _value_ = await _check(monkeypatch, handler)

        assert len(recorded) == 1
        assert _described(recorded) == []

    async def test_the_request_is_built_the_way_the_driver_builds_it(
        self, monkeypatch
    ) -> None:
        """The caller's own parameters survive; the operation parameters are
        replaced whatever their case; VERSION is the capabilities' own."""
        handler = _wfs(
            _capabilities([_LAYER], version="1.1.0"), lambda names: _schema(names)
        )
        submitted = (
            f"{_SVC_WFS}?request=GetCapabilities&service=wfs&Version=2.0.0&map=x"
        )

        recorded, _value_ = await _check(monkeypatch, handler, url=submitted)

        describe = [
            r for r in recorded if _params(r).get("request") == "DescribeFeatureType"
        ]
        assert len(describe) == 1
        pairs = describe[0].url.params.multi_items()
        assert sorted(pairs) == sorted(
            [
                ("map", "x"),
                ("SERVICE", "WFS"),
                ("VERSION", "1.1.0"),
                ("REQUEST", "DescribeFeatureType"),
                ("TYPENAME", _LAYER),
            ]
        )
        assert describe[0].url.path == "/geoserver/wfs"

    @pytest.mark.parametrize(
        ("version", "sent"), [(None, "1.0.0"), ("", "")], ids=["absent", "empty"]
    )
    async def test_a_version_the_capabilities_do_not_state_is_sent_as_the_driver_sends_it(
        self, monkeypatch, version, sent
    ) -> None:
        handler = _wfs(
            _capabilities([_LAYER], version=version), lambda names: _schema(names)
        )

        recorded, _value_ = await _check(monkeypatch, handler)

        assert _params(recorded[-1])["version"] == sent


class TestTheReadsTheDriverMakesForTheLayerAreChecked:
    """The driver asks for the layer and the other types of its prefix in one
    DescribeFeatureType, fifty at most, and then for the layer alone whenever
    that answer does not cover it. A schema that is clean for the batch and
    not for the single request is the shape this class exists to catch."""

    uses_the_real_endpoint_check = True

    async def test_the_batch_names_the_layer_first_then_its_prefix_siblings(
        self, monkeypatch
    ) -> None:
        handler = _wfs(
            _capabilities([_LAYER, "topp:roads", "sf:x"]), lambda names: _schema(names)
        )

        recorded, _value_ = await _check(monkeypatch, handler, collection="topp:roads")

        assert _described(recorded) == [["topp:roads", _LAYER], ["topp:roads"]]

    async def test_a_sibling_include_in_the_batch_answer_is_found(
        self, monkeypatch
    ) -> None:
        def describe(names: list[str]) -> str:
            include = f"{_FOREIGN}/inc.xsd" if "topp:roads" in names else None
            return _schema(names, include=include)

        handler = _wfs(_capabilities([_LAYER, "topp:roads"]), describe)

        recorded, _error = await _refused(
            monkeypatch, handler, CrossOriginEndpointError
        )

        assert _described(recorded) == [[_LAYER, "topp:roads"]]

    async def test_a_batch_carries_at_most_fifty_names(self, monkeypatch) -> None:
        names = [f"a:t{n}" for n in range(1, 121)] + [f"b:t{n}" for n in range(1, 4)]
        handler = _wfs(_capabilities(names), lambda batch: _schema(batch))

        recorded, _value_ = await _check(monkeypatch, handler, collection="a:t1")

        assert _described(recorded) == [names[0:50], ["a:t1"]]

    async def test_a_batch_answered_with_an_exception_report_falls_back_to_the_layer(
        self, monkeypatch
    ) -> None:
        def describe(names: list[str]) -> str:
            if len(names) > 1:
                return _exception_report()
            include = f"{_FOREIGN}/inc.xsd" if names == ["topp:roads"] else None
            return _schema(names, include=include)

        handler = _wfs(_capabilities([_LAYER, "topp:roads"]), describe)

        recorded, _error = await _refused(
            monkeypatch, handler, CrossOriginEndpointError, collection="topp:roads"
        )

        assert _described(recorded) == [["topp:roads", _LAYER], ["topp:roads"]]

    async def test_a_named_layer_reads_its_batch_and_then_itself(
        self, monkeypatch
    ) -> None:
        """A server that answers the batch cleanly and the single request with
        an include is refused: the driver reads both."""

        def describe(names: list[str]) -> str:
            include = f"{_FOREIGN}/inc.xsd" if names == ["topp:roads"] else None
            return _schema(names, include=include)

        handler = _wfs(_capabilities([_LAYER, "topp:roads", "sf:x"]), describe)

        recorded, _error = await _refused(
            monkeypatch, handler, CrossOriginEndpointError, collection="topp:roads"
        )

        assert _described(recorded) == [["topp:roads", _LAYER], ["topp:roads"]]

    async def test_a_named_layer_alone_in_its_prefix_is_read_once(
        self, monkeypatch
    ) -> None:
        handler = _wfs(_capabilities([_LAYER]), lambda names: _schema(names))

        recorded, _value_ = await _check(monkeypatch, handler)

        assert _described(recorded) == [[_LAYER]]

    @pytest.mark.parametrize("requested", ["TOPP:ROADS", "roads", "Roads"])
    async def test_a_named_layer_is_resolved_the_way_the_driver_resolves_it(
        self, monkeypatch, requested
    ) -> None:
        """`GetLayerByName`: exact, then case-insensitive, then the part after
        the prefix. The request names the advertised spelling, which is what
        the driver puts in its own TYPENAME."""
        handler = _wfs(
            _capabilities([_LAYER, "topp:roads"]), lambda names: _schema(names)
        )

        recorded, _value_ = await _check(monkeypatch, handler, collection=requested)

        assert _described(recorded) == [["topp:roads", _LAYER], ["topp:roads"]]

    @pytest.mark.parametrize(
        ("names", "requested"),
        [
            (["topp:roads", "sf:roads"], "roads"),
            ([_LAYER], "topp:nothing"),
        ],
        ids=["short_name_two_prefixes_share", "not_advertised"],
    )
    async def test_a_layer_the_driver_would_not_resolve_makes_no_schema_read(
        self, monkeypatch, names, requested
    ) -> None:
        """The driver opens no layer for such a name, so it reads no schema."""
        handler = _wfs(
            _capabilities(names),
            lambda batch: _schema(batch, include=f"{_FOREIGN}/inc.xsd"),
        )

        recorded, _value_ = await _check(monkeypatch, handler, collection=requested)

        assert _described(recorded) == []

    async def test_no_layer_is_the_capabilities_check_alone(self, monkeypatch) -> None:
        """The probe names no layer and runs no GDAL."""
        handler = _wfs(
            _capabilities([_LAYER]),
            lambda names: _schema(names, include=f"{_FOREIGN}/inc.xsd"),
        )

        recorded, _value_ = await _check(monkeypatch, handler, collection=None)

        assert len(recorded) == 1
        assert _described(recorded) == []


class TestAnUnreadableSchemaFailsClosed:
    uses_the_real_endpoint_check = True

    async def _failed(self, monkeypatch, handler) -> list[httpx.Request]:
        recorded, error = await _refused(monkeypatch, handler, EndpointCheckFailedError)
        assert error.code == "endpoint_check_failed"
        return recorded

    async def test_a_body_that_is_not_xml_refuses(self, monkeypatch) -> None:
        handler = _wfs(_capabilities([_LAYER]), lambda names: "<not xml")

        await self._failed(monkeypatch, handler)

    async def test_a_batch_that_does_not_parse_refuses_without_falling_back(
        self, monkeypatch
    ) -> None:
        """The driver's own parser is more lenient than this one, so a body
        that does not parse here may still be a schema the driver resolves.
        Not knowing what it would read is a refusal, not a fallback."""

        def describe(names: list[str]) -> str:
            return "<not xml" if len(names) > 1 else _schema(names)

        handler = _wfs(_capabilities([_LAYER, "topp:roads"]), describe)

        recorded = await self._failed(monkeypatch, handler)

        assert _described(recorded) == [[_LAYER, "topp:roads"]]

    async def test_a_document_carrying_a_doctype_refuses(self, monkeypatch) -> None:
        with_doctype = (
            '<?xml version="1.0"?><!DOCTYPE schema>' + _schema().split("?>", 1)[1]
        )
        handler = _wfs(_capabilities([_LAYER]), lambda names: with_doctype)

        await self._failed(monkeypatch, handler)

    async def test_an_exception_report_for_the_layer_alone_refuses(
        self, monkeypatch
    ) -> None:
        handler = _wfs(_capabilities([_LAYER]), lambda names: _exception_report())

        recorded = await self._failed(monkeypatch, handler)

        assert _described(recorded) == [[_LAYER], [_LAYER]]

    async def test_an_http_error_on_a_batch_refuses(self, monkeypatch) -> None:
        def describe(names: list[str]):
            return httpx.Response(500) if len(names) > 1 else _schema(names)

        handler = _wfs(_capabilities([_LAYER, "topp:roads"]), describe)

        recorded = await self._failed(monkeypatch, handler)

        assert _described(recorded) == [[_LAYER, "topp:roads"]]

    async def test_an_unreadable_same_origin_include_refuses(self, monkeypatch) -> None:
        handler = _wfs(
            _capabilities([_LAYER]),
            lambda names: _schema(names, include=f"{_SVC_ORIGIN}/inc.xsd"),
        )

        recorded = await self._failed(monkeypatch, handler)

        assert recorded[-1].url.path == "/inc.xsd"

    async def test_reads_past_the_budget_refuse(self, monkeypatch) -> None:
        """A schema naming more same-origin includes than the budget allows:
        the last read the budget admits is the last one made."""
        from app.platform.service_endpoints import _MAX_WFS_SCHEMA_READS

        count = _MAX_WFS_SCHEMA_READS + 5
        includes = "".join(
            f'<xs:include schemaLocation="{_SVC_ORIGIN}/inc{n}.xsd"/>'
            for n in range(count)
        )
        handler = _wfs(
            _capabilities([_LAYER]),
            lambda names: _schema(names, extra=includes),
            files={f"/inc{n}.xsd": _schema() for n in range(count)},
        )

        recorded = await self._failed(monkeypatch, handler)

        assert _described(recorded) == [[_LAYER]]
        include_reads = [r for r in recorded if r.url.path.startswith("/inc")]
        assert len(include_reads) == _MAX_WFS_SCHEMA_READS - 1


class TestTheDoorsRefuseBeforeGdalRuns:
    """The three doors share `assert_endpoints_stay_on_origin`. The probe
    names no layer and runs no GDAL, so its check is the capabilities check
    alone; the preview and the worker name the layer they open and are
    refused before their subprocess exists."""

    uses_the_real_endpoint_check = True

    @staticmethod
    def _handler():
        return _wfs(
            _capabilities([_LAYER]),
            lambda names: _schema(names, include=f"{_FOREIGN}/inc.xsd"),
        )

    async def test_the_probe_reads_no_schema(
        self, client, admin_auth_header: dict
    ) -> None:
        recorded: list[httpx.Request] = []
        handler = self._handler()

        def _handle(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            return _as_stream(handler(request))

        value = _value()
        with (
            patch.object(
                security, "make_safe_transport", lambda: httpx.MockTransport(_handle)
            ),
            patch.object(security, "validate_url_for_ssrf", AsyncMock()),
            patch(
                "app.modules.catalog.sources.router.validate_url_for_ssrf",
                new_callable=AsyncMock,
            ),
            patch(
                "app.platform.service_endpoints.validate_url_for_ssrf",
                new_callable=AsyncMock,
            ),
        ):
            resp = await client.post(
                "/services/probe",
                json={
                    "url": _SVC_WFS,
                    "auth": {
                        "method": "header",
                        "header_name": "X-Api-Key",
                        "header_value": value,
                    },
                },
                headers=admin_auth_header,
            )

        assert resp.status_code == 200, resp.text
        assert value not in resp.text
        assert _described(recorded) == []
        assert _hosts(recorded) == {"service.example"}

    async def test_the_preview_refuses_before_spawning_ogrinfo(
        self, monkeypatch, tmp_path
    ) -> None:
        from app.core.config import settings

        monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path / "staging"))
        recorded = _transport(monkeypatch, self._handler())
        value = _value()
        credential = ServiceCredential(
            method=CredentialMethod.HEADER_KEY,
            service_format="wfs",
            header_name="X-Api-Key",
            header_value=value,
        )

        async def _fake_exec(*cmd, **kwargs):
            raise AssertionError("ogrinfo must not run for a refused source")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        with pytest.raises(Exception) as raised:  # noqa: PT011 - HTTPException
            await preview_mod.run_service_preview(
                f"WFS:{_SVC_WFS}", _LAYER, credential=credential
            )

        assert raised.value.detail["code"] == "cross_origin_endpoint"
        assert value not in str(raised.value.detail)
        assert _described(recorded) == [[_LAYER]]
        assert _hosts(recorded) == {"service.example"}

    async def test_the_worker_refuses_before_spawning_ogr2ogr(
        self, monkeypatch, tmp_path
    ) -> None:
        from app.core.config import settings
        from app.processing.ingest.ogr import run_ogr2ogr_service

        monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path / "staging"))
        recorded = _transport(monkeypatch, self._handler())

        async def _fake_exec(*cmd, **kwargs):
            raise AssertionError("ogr2ogr must not run for a refused source")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        with pytest.raises(CrossOriginEndpointError) as raised:
            await run_ogr2ogr_service(
                gdal_source=f"WFS:{_SVC_WFS}",
                layer_name=_LAYER,
                table_name="t",
                db_conn_str="PG:dummy",
                service_type="wfs",
                token=f"X-Api-Key: {_value()}",
                schema="data",
            )

        assert raised.value.origin == _FOREIGN
        assert _described(recorded) == [[_LAYER]]
        assert _hosts(recorded) == {"service.example"}


class TestACredentialedWfsNeverReachesGdalWithoutALayer:
    """The schema check reads the description of the layer a door opens, and
    GDAL opened without a layer reads every layer's. So both spawn points
    refuse a credentialed WFS that names no layer before the process starts,
    with the coded shape the origin check uses, and nothing is read from the
    service at all. A credential-free layerless preview is unchanged."""

    uses_the_real_endpoint_check = True

    @pytest.mark.parametrize(
        ("layer_name", "service_format", "credentialed", "refused"),
        [
            ("", "wfs", True, True),
            ("   ", "wfs", True, True),
            (None, "wfs", True, True),
            (_LAYER, "wfs", True, False),
            ("", "wfs", False, False),
            ("", "ogcapi_features", True, False),
            ("", "arcgis_featureserver", True, False),
        ],
        ids=[
            "empty",
            "blank",
            "missing",
            "named",
            "no_credential",
            "oapif",
            "arcgis",
        ],
    )
    def test_only_a_credentialed_layerless_wfs_is_refused(
        self, layer_name, service_format, credentialed, refused
    ) -> None:
        from app.platform.service_endpoints import (
            LayerRequiredError,
            require_wfs_layer,
        )

        line = f"X-Api-Key: {_value()}" if credentialed else None
        if not refused:
            require_wfs_layer(
                layer_name, service_format=service_format, credential_line=line
            )
            return
        with pytest.raises(LayerRequiredError) as raised:
            require_wfs_layer(
                layer_name, service_format=service_format, credential_line=line
            )
        assert raised.value.code == "layer_required"
        assert raised.value.field == "layer_name"
        assert isinstance(raised.value, EndpointCheckFailedError)

    async def test_the_worker_refuses_before_any_request_or_spawn(
        self, monkeypatch, tmp_path
    ) -> None:
        from app.core.config import settings
        from app.platform.service_endpoints import LayerRequiredError
        from app.processing.ingest.ogr import run_ogr2ogr_service

        monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path / "staging"))
        recorded = _transport(monkeypatch, _wfs(_capabilities([_LAYER]), _schema))

        async def _fake_exec(*cmd, **kwargs):
            raise AssertionError("ogr2ogr must not run for a refused source")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        with pytest.raises(LayerRequiredError):
            await run_ogr2ogr_service(
                gdal_source=f"WFS:{_SVC_WFS}",
                layer_name="",
                table_name="t",
                db_conn_str="PG:dummy",
                service_type="wfs",
                token=f"X-Api-Key: {_value()}",
                schema="data",
            )

        assert recorded == []

    async def test_the_preview_refuses_before_any_request_or_spawn(
        self, monkeypatch, tmp_path
    ) -> None:
        from app.core.config import settings

        monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path / "staging"))
        recorded = _transport(monkeypatch, _wfs(_capabilities([_LAYER]), _schema))
        value = _value()
        credential = ServiceCredential(
            method=CredentialMethod.HEADER_KEY,
            service_format="wfs",
            header_name="X-Api-Key",
            header_value=value,
        )

        async def _fake_exec(*cmd, **kwargs):
            raise AssertionError("ogrinfo must not run for a refused source")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        with pytest.raises(Exception) as raised:  # noqa: PT011 - HTTPException
            await preview_mod.run_service_preview(
                f"WFS:{_SVC_WFS}", "", credential=credential
            )

        assert raised.value.status_code == 422
        assert raised.value.detail["code"] == "layer_required"
        assert raised.value.detail["field"] == "layer_name"
        assert value not in str(raised.value.detail)
        assert recorded == []

    async def test_a_credential_free_layerless_preview_still_lists_layers(
        self, monkeypatch, tmp_path
    ) -> None:
        from app.core.config import settings

        monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path / "staging"))
        spawned: list[tuple] = []

        class _FakeProc:
            returncode = 0

            async def communicate(self):
                listing = {
                    "layers": [
                        {
                            "name": "l",
                            "fields": [],
                            "features": [],
                            "geometryFields": [],
                        }
                    ]
                }
                return (json.dumps(listing).encode(), b"")

        async def _fake_exec(*cmd, **kwargs):
            spawned.append(cmd)
            return _FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        result = await preview_mod.run_service_preview(f"WFS:{_SVC_WFS}", "")

        assert result["layer_name"] == "l"
        assert len(spawned) == 1
        assert spawned[0][-1] == f"WFS:{_SVC_WFS}"

    async def test_the_reupload_preview_door_answers_422_before_ogrinfo(
        self, client, admin_auth_header: dict, test_db_session, monkeypatch
    ) -> None:
        from tests.factories import create_dataset, get_user_id

        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(
            test_db_session, created_by=admin_id, name="Layerless WFS"
        )
        recorded = _transport(monkeypatch, _wfs(_capabilities([_LAYER]), _schema))
        monkeypatch.setattr(
            "app.modules.catalog.datasets.api.router_reupload.validate_url_for_ssrf",
            AsyncMock(),
        )

        async def _fake_exec(*cmd, **kwargs):
            raise AssertionError("ogrinfo must not run for a refused source")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        value = _value()

        resp = await client.post(
            f"/datasets/{dataset.id}/reupload/service/preview",
            json={
                "url": _SVC_WFS,
                "service_type": "WFS 2.0.0",
                "layer_name": "",
                "auth": {
                    "method": "header",
                    "header_name": "X-Api-Key",
                    "header_value": value,
                },
            },
            headers=admin_auth_header,
        )

        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "layer_required"
        assert value not in resp.text
        assert recorded == []

    def test_every_spawn_point_that_names_a_layer_passes_through_the_refusal(
        self,
    ) -> None:
        """Every call of `assert_endpoints_stay_on_origin` that passes a
        `collection` is a GDAL spawn point, and its function must call
        `require_wfs_layer` first. The set is exact, so a new spawn point has
        to be added here as well as inherit the refusal."""
        import ast
        import pathlib

        app_root = pathlib.Path(__file__).resolve().parents[1] / "app"
        spawn_points: dict[tuple[str, str], tuple[int, int | None]] = {}
        for path in sorted(app_root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for func in ast.walk(tree):
                if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                check_line = None
                require_line = None
                for node in ast.walk(func):
                    if not isinstance(node, ast.Call):
                        continue
                    name = getattr(node.func, "id", None) or getattr(
                        node.func, "attr", None
                    )
                    if name == "assert_endpoints_stay_on_origin" and any(
                        kw.arg == "collection" for kw in node.keywords
                    ):
                        check_line = node.lineno
                    elif name == "require_wfs_layer":
                        require_line = node.lineno
                if check_line is not None:
                    rel = path.relative_to(app_root).as_posix()
                    spawn_points[(rel, func.name)] = (check_line, require_line)

        assert set(spawn_points) == {
            ("modules/catalog/sources/preview.py", "run_service_preview"),
            ("processing/ingest/ogr.py", "run_ogr2ogr_service"),
        }, spawn_points
        for site, (check_line, require_line) in spawn_points.items():
            assert require_line is not None, site
            assert require_line < check_line, site
