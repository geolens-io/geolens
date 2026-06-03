from typing import Literal, cast

ExportFormat = Literal["csv", "geojson", "gpkg", "shp"]

EXPORT_FORMAT_VALUES: set[ExportFormat] = {
    "csv",
    "geojson",
    "gpkg",
    "shp",
}


def check_export_format(value: str) -> ExportFormat:
    if value in EXPORT_FORMAT_VALUES:
        return cast(ExportFormat, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {EXPORT_FORMAT_VALUES!r}"
    )
