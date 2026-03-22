"""Shared dataset utility functions."""

from geoalchemy2.shape import to_shape

from app.datasets.models import Dataset


def extract_bbox(dataset: Dataset) -> list[float] | None:
    """Extract a bbox array from the dataset's record spatial_extent geometry."""
    if dataset.record and dataset.record.spatial_extent is not None:
        try:
            return list(to_shape(dataset.record.spatial_extent).bounds)
        except Exception:
            return None
    return None
