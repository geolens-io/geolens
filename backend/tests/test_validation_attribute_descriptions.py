"""The attribute-description warning reads as proper English for one and many columns."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.models import AttributeMetadata, Record
from app.modules.catalog.validation.service import validate_record
from tests.factories import get_user_id
from tests.test_analysis_preview import _create_polygon_dataset

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (1, "1 attribute missing a description"),
        (2, "2 attributes missing descriptions"),
    ],
)
async def test_attribute_description_warning_pluralizes(
    test_db_session: AsyncSession, count: int, expected: str
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_polygon_dataset(test_db_session, created_by=admin_id)
    for i in range(count):
        test_db_session.add(
            AttributeMetadata(
                dataset_id=dataset.id,
                field_name=f"col_{i}",
                semantic_role="measure",
                is_current=True,
            )
        )
    await test_db_session.commit()
    record = await test_db_session.get(Record, dataset.record_id)

    result = await validate_record(test_db_session, record, dataset)

    messages = {w.field: w.message for w in result.warnings}
    assert messages["attribute_descriptions"] == expected


async def test_attribute_without_a_semantic_role_is_counted(
    test_db_session: AsyncSession,
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_polygon_dataset(test_db_session, created_by=admin_id)
    test_db_session.add(
        AttributeMetadata(
            dataset_id=dataset.id,
            field_name="no_role",
            semantic_role=None,
            is_current=True,
        )
    )
    test_db_session.add(
        AttributeMetadata(
            dataset_id=dataset.id,
            field_name="geom",
            semantic_role="geometry",
            is_current=True,
        )
    )
    await test_db_session.commit()
    record = await test_db_session.get(Record, dataset.record_id)

    result = await validate_record(test_db_session, record, dataset)

    messages = {w.field: w.message for w in result.warnings}
    assert messages["attribute_descriptions"] == "1 attribute missing a description"
