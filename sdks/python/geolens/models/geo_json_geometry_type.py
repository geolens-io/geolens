from typing import Literal, cast

GeoJSONGeometryType = Literal[
    "LineString", "MultiLineString", "MultiPoint", "MultiPolygon", "Point", "Polygon"
]

GEO_JSON_GEOMETRY_TYPE_VALUES: set[GeoJSONGeometryType] = {
    "LineString",
    "MultiLineString",
    "MultiPoint",
    "MultiPolygon",
    "Point",
    "Polygon",
}


def check_geo_json_geometry_type(value: str) -> GeoJSONGeometryType:
    if value in GEO_JSON_GEOMETRY_TYPE_VALUES:
        return cast(GeoJSONGeometryType, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {GEO_JSON_GEOMETRY_TYPE_VALUES!r}"
    )
