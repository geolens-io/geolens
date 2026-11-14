"""Why geometry built from a file's chosen columns failed, as coded sentences.

A job stores the sentence with its code. The frontend translates the code and
reads the values back out of the stored sentence, so each template here has a
copy in ``frontend/src/lib/failure-reason.ts``.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.core.failure_reason import (
    INTERNAL_FAILURE_REASON,
    FixedReason,
    redact_failure_reason,
)

GEOMETRY_BUILD_SENTENCES: dict[str, str] = {
    "geometry_columns_missing": (
        "The replacement lacks the columns this dataset's geometry is built "
        "from ({columns}), so nothing was changed. Add them to the file, or "
        "import the file as a new dataset instead."
    ),
    "geometry_xy_not_numeric": "{rows} row(s) contain X/Y values that are not numbers",
    "geometry_xy_outside_wgs84": (
        "{rows} row(s) contain X/Y coordinates outside EPSG:4326 ranges"
    ),
    "geometry_xy_not_finite": (
        "{rows} row(s) contain X/Y coordinates outside finite values"
    ),
    "geometry_wkt_invalid_wgs84": (
        "{rows} row(s) contain invalid WKT geometry or coordinates outside "
        "EPSG:4326 ranges"
    ),
    "geometry_wkt_invalid": (
        "{rows} row(s) contain invalid WKT geometry or coordinates outside "
        "finite values"
    ),
    "geometry_wkt_malformed": "WKT column contains malformed geometry text",
    "geometry_wkt_mixed_dimensions": (
        "The WKT column mixes coordinate dimensions ({dimensions}), so no "
        "geometry was built. Give every row the same dimensions."
    ),
}


class GeometryBuildError(ValueError):
    """Geometry could not be built from the chosen columns.

    The only argument is a ``FixedReason``, so every failure sink stores its
    sentence and code as they are.
    """

    def __init__(self, reason: FixedReason) -> None:
        super().__init__(reason)
        self.reason = reason


def _sentence(code: str, **values: object) -> str:
    return GEOMETRY_BUILD_SENTENCES[code].format(**values)


def _column_label(name: str) -> str:
    # A header is file content: one line, scrubbed as stored text is, so the
    # sentence around it survives storage whole.
    label = redact_failure_reason(" ".join(name.split()))
    return "?" if label == INTERNAL_FAILURE_REASON else label


def columns_missing(columns: Sequence[str]) -> GeometryBuildError:
    """A replacement lacks columns the dataset's geometry is built from."""
    text = _sentence(
        "geometry_columns_missing",
        columns=", ".join(_column_label(column) for column in columns),
    )
    return GeometryBuildError(FixedReason(text, code="geometry_columns_missing"))


def xy_not_numeric(rows: int) -> GeometryBuildError:
    """Rows whose X or Y is not a number."""
    text = _sentence("geometry_xy_not_numeric", rows=rows)
    return GeometryBuildError(FixedReason(text, code="geometry_xy_not_numeric"))


def xy_out_of_range(rows: int, *, wgs84: bool) -> GeometryBuildError:
    """Rows whose X/Y fall outside the CRS's range."""
    if wgs84:
        text = _sentence("geometry_xy_outside_wgs84", rows=rows)
        return GeometryBuildError(FixedReason(text, code="geometry_xy_outside_wgs84"))
    text = _sentence("geometry_xy_not_finite", rows=rows)
    return GeometryBuildError(FixedReason(text, code="geometry_xy_not_finite"))


def wkt_invalid(rows: int, *, wgs84: bool) -> GeometryBuildError:
    """Rows whose WKT is invalid or outside the CRS's range."""
    if wgs84:
        text = _sentence("geometry_wkt_invalid_wgs84", rows=rows)
        return GeometryBuildError(FixedReason(text, code="geometry_wkt_invalid_wgs84"))
    text = _sentence("geometry_wkt_invalid", rows=rows)
    return GeometryBuildError(FixedReason(text, code="geometry_wkt_invalid"))


def wkt_malformed() -> GeometryBuildError:
    """WKT that PostGIS cannot parse."""
    text = _sentence("geometry_wkt_malformed")
    return GeometryBuildError(FixedReason(text, code="geometry_wkt_malformed"))


def wkt_mixed_dimensions(dimensions: Sequence[str]) -> GeometryBuildError:
    """Rows whose WKT carry different coordinate dimensions, such as XYZ and XYZM."""
    text = _sentence("geometry_wkt_mixed_dimensions", dimensions=", ".join(dimensions))
    return GeometryBuildError(FixedReason(text, code="geometry_wkt_mixed_dimensions"))
