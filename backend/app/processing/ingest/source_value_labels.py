"""Code labels a remote service publishes, carried across a refresh."""

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.value_labels import (
    MAX_DATASET_VALUE_LABEL_BYTES,
    value_labels_bytes,
)

logger = structlog.get_logger()


async def refresh_source_value_labels(
    session: AsyncSession, dataset_id: uuid.UUID, field_labels: dict | None
) -> None:
    """Give each attribute the code labels its source publishes now.

    A column the source no longer labels loses them, and a column whose labels
    a user edited keeps them. The source's labels fit what the edited ones
    leave of the dataset budget, in field order; the first that does not fit
    and every later one are dropped.
    """
    if field_labels is None:
        return
    from app.platform.extensions import get_processing_port

    AttributeMetadata = get_processing_port().get_attribute_metadata_orm_class()
    result = await session.execute(
        select(AttributeMetadata).where(AttributeMetadata.dataset_id == dataset_id)
    )
    unedited = {}
    left = MAX_DATASET_VALUE_LABEL_BYTES
    for am in result.scalars().all():
        if "value_labels" in (am.user_modified_fields or []):
            left -= value_labels_bytes(am.value_labels)
        else:
            am.value_labels = None
            unedited[am.field_name] = am
    dropped: list[str] = []
    for name, label in field_labels.items():
        am = unedited.get(name)
        labels = label.get("value_labels")
        if am is None or not labels:
            continue
        size = value_labels_bytes(labels)
        if dropped or size > left:
            dropped.append(name)
            continue
        left -= size
        am.value_labels = labels
    if dropped:
        logger.warning("value_labels_over_dataset_budget", dropped_fields=dropped)
    await session.flush()
