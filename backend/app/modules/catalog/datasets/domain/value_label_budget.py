"""The dataset-wide cap on attribute value labels."""

from __future__ import annotations

from sqlalchemy import Text, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.models import AttributeMetadata
from app.modules.catalog.sources.field_labels import (
    MAX_DATASET_VALUE_LABEL_BYTES,
    value_labels_bytes,
)


class ValueLabelsOverBudget(Exception):
    """The dataset's value labels would pass ``MAX_DATASET_VALUE_LABEL_BYTES``."""


async def refuse_value_labels_over_budget(
    session: AsyncSession, attr: AttributeMetadata, labels: dict[str, str]
) -> None:
    others = await session.scalar(
        select(
            func.coalesce(
                func.sum(func.octet_length(cast(AttributeMetadata.value_labels, Text))),
                0,
            )
        ).where(
            AttributeMetadata.dataset_id == attr.dataset_id,
            AttributeMetadata.id != attr.id,
            AttributeMetadata.is_current.is_(True),
            AttributeMetadata.value_labels.is_not(None),
        )
    )
    if others + value_labels_bytes(labels) > MAX_DATASET_VALUE_LABEL_BYTES:
        raise ValueLabelsOverBudget
