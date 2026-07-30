"""Shared dataset utility functions."""

from app.core.geo import extent_to_bbox
from app.modules.catalog.datasets.domain.models import Dataset


def extract_bbox(dataset: Dataset) -> list[float] | None:
    """Extract a bbox array from the dataset's record spatial_extent geometry.

    fix(#892): delegates to ``extent_to_bbox`` so a seam-crossing extent yields
    the RFC 7946 §5.2 west > east pair rather than a globe-spanning -180..180.
    Both consumers want the spec form: the STAC/OGC record ``bbox``
    (``search/service_records.py``) and the AI dataset-context ``extent_bbox``.
    """
    if dataset.record and dataset.record.spatial_extent is not None:
        return extent_to_bbox(dataset.record.spatial_extent)
    return None
