"""Shared dataset utility functions."""

from geoalchemy2.shape import to_shape

from app.modules.catalog.datasets.domain.models import Dataset


def extract_bbox(dataset: Dataset) -> list[float] | None:
    """Extract a bbox array from the dataset's record spatial_extent geometry."""
    if dataset.record and dataset.record.spatial_extent is not None:
        try:
            return list(to_shape(dataset.record.spatial_extent).bounds)
        except Exception:  # broad: extent parse — geoalchemy/shapely errors fall back to None bbox
            return None
    return None
