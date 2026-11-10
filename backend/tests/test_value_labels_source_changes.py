"""Code labels follow the source a dataset is published from.

Every path that replaces or re-reads a dataset's data runs through
``catalog_projection.project``. Unedited labels follow the new source (cleared
when it publishes none), labels a user edited stay, and a restore keeps the
current attribute metadata as it does for titles and descriptions.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.catalog.datasets.domain.models import AttributeMetadata

from tests.factories import get_user_id
from tests.test_postgis_refresh_1265 import _dispatch, _execute, _registered_dataset
from tests.test_previous_version_2590 import _replace, _restore_version, _seed

pytestmark = pytest.mark.anyio

_LABELS = {"1": "Active"}


async def _label(session, dataset_id, *, edited: bool) -> None:
    attr = await session.scalar(
        select(AttributeMetadata).where(
            AttributeMetadata.dataset_id == dataset_id,
            AttributeMetadata.field_name == "name",
        )
    )
    if attr is None:
        attr = AttributeMetadata(
            dataset_id=dataset_id, field_name="name", title="Name", data_type="text"
        )
        session.add(attr)
    attr.value_labels = _LABELS
    attr.user_modified_fields = ["value_labels"] if edited else []
    await session.commit()


async def _stored(session, dataset_id):
    session.expire_all()
    return await session.scalar(
        select(AttributeMetadata.value_labels).where(
            AttributeMetadata.dataset_id == dataset_id,
            AttributeMetadata.field_name == "name",
        )
    )


@pytest.mark.parametrize(
    ("edited", "expected"), [(False, None), (True, _LABELS)], ids=["unedited", "edited"]
)
async def test_a_file_replacement_clears_unedited_labels(
    test_db_session, edited, expected
):
    admin_id, dataset = await _seed(test_db_session)
    await _label(test_db_session, dataset.id, edited=edited)

    await _replace(test_db_session, dataset, admin_id, ["paris"])

    assert await _stored(test_db_session, dataset.id) == expected


@pytest.mark.parametrize(
    ("edited", "expected"), [(False, None), (True, _LABELS)], ids=["unedited", "edited"]
)
async def test_a_registered_table_refresh_clears_unedited_labels(
    client: AsyncClient, admin_auth_header, test_db_session, edited, expected
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _registered_dataset(test_db_session, created_by=admin_id)
    await _label(test_db_session, dataset.id, edited=edited)

    payload = await _dispatch(client, admin_auth_header, dataset.id)
    await _execute(test_db_session, payload)

    assert await _stored(test_db_session, dataset.id) == expected


async def test_a_restore_keeps_the_current_labels(
    client: AsyncClient, admin_auth_header, test_db_session
):
    admin_id, dataset = await _seed(test_db_session)
    await _replace(test_db_session, dataset, admin_id, ["paris"])
    await _label(test_db_session, dataset.id, edited=False)

    restored = await _restore_version(client, admin_auth_header, dataset, 1)

    assert restored.status_code == 202, restored.text
    assert await _stored(test_db_session, dataset.id) == _LABELS
