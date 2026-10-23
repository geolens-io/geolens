"""Code labels a remote service publishes, carried across a refresh."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def refresh_source_value_labels(
    session: AsyncSession, dataset_id: uuid.UUID, field_labels: dict | None
) -> None:
    """Give each attribute the code labels its source publishes now.

    A column the source no longer labels loses them, and a column whose labels
    a user edited keeps them.
    """
    if field_labels is None:
        return
    from app.platform.extensions import get_processing_port

    AttributeMetadata = get_processing_port().get_attribute_metadata_orm_class()
    result = await session.execute(
        select(AttributeMetadata).where(AttributeMetadata.dataset_id == dataset_id)
    )
    for am in result.scalars().all():
        if "value_labels" in (am.user_modified_fields or []):
            continue
        am.value_labels = (field_labels.get(am.field_name) or {}).get("value_labels")
    await session.flush()
