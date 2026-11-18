"""Which GDAL stderr a service import reports as an authentication failure."""

import pytest

from app.processing.ingest.ogr import _SERVICE_FAILURE_CLASSES, _gdal_failure_reason

_AUTH = "ogr2ogr failed (exit 1): the source service reported an authentication failure"


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        ("ERROR 1: Invalid token.", _AUTH),
        ("ERROR 1: invalid credentials supplied", _AUTH),
        (
            "ERROR 1: XML parsing of GML file failed : "
            "not well-formed (invalid token) at line 11540, column 22",
            "ogr2ogr failed (exit 1)",
        ),
    ],
    ids=["token", "credentials", "malformed-xml"],
)
def test_a_malformed_xml_response_is_not_an_authentication_failure(stderr, expected):
    reason = _gdal_failure_reason("ogr2ogr", 1, stderr, _SERVICE_FAILURE_CLASSES)

    assert reason == expected
