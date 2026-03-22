"""Export format definitions."""

from enum import StrEnum


class ExportFormat(StrEnum):
    gpkg = "gpkg"
    geojson = "geojson"
    shp = "shp"
    csv = "csv"
