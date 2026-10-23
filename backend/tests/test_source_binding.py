"""The source binding's "same stored pointer" seam: ``bound_pointer`` and ``still_bound``."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import update

import app.core.db as db_module
from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.dataset_origin import (
    BoundPointer,
    bound_pointer,
    set_dataset_origin,
    set_postgis_origin,
    still_bound,
)
from tests.factories import create_dataset, get_user_id

_WFS = "https://services.example.test/wfs"
_REF = {"kind": "service", "service_type": "wfs", "url": _WFS, "layer_id": "roads"}


def _row(origin_ref, *, origin_uri=_WFS, source_format="wfs"):
    return SimpleNamespace(
        origin_uri=origin_uri, origin_ref=origin_ref, source_format=source_format
    )


class TestBoundPointer:
    def test_reads_the_three_columns_as_a_plain_triple_too(self) -> None:
        pointer = bound_pointer(_row(_REF))
        assert pointer == BoundPointer(_WFS, _REF, "wfs") == (_WFS, _REF, "wfs")

    def test_key_order_is_not_a_rebind(self) -> None:
        reordered = dict(reversed(list(_REF.items())))
        assert bound_pointer(_row(reordered)) == bound_pointer(_row(_REF))

    @pytest.mark.parametrize(
        "changed",
        [
            _row({**_REF, "auth_required": True}),
            _row({**_REF, "item_id": "abc123", "portal_url": "https://example.test"}),
            _row(_REF, origin_uri=f"{_WFS}/roads"),
            _row(_REF, source_format="ogcapi_features"),
            _row(None),
        ],
        ids=["auth_required", "portal_link", "uri", "format", "ref_cleared"],
    )
    def test_any_difference_in_the_whole_triple_is_a_rebind(self, changed) -> None:
        assert bound_pointer(changed) != bound_pointer(_row(_REF))


async def _stamp(dataset_id, pointer) -> int:
    """Date contact under ``still_bound`` in a fresh session; the rows it matched."""
    async with db_module.async_session() as session:
        result = await session.execute(
            update(Dataset)
            .where(still_bound(Dataset, dataset_id, pointer))
            .values(last_checked_at=datetime.now(timezone.utc))
        )
        await session.commit()
        return result.rowcount


async def _dataset(session, source_format: str | None) -> Dataset:
    return await create_dataset(
        session,
        created_by=await get_user_id(session, "admin"),
        name="Still Bound",
        visibility="private",
        source_format=source_format,
    )


def _bind_service(dataset: Dataset, **extra) -> None:
    set_dataset_origin(
        dataset,
        "service",
        uri=_WFS,
        service_type="wfs",
        url=_WFS,
        layer_id="roads",
        **extra,
    )


@pytest.mark.anyio
class TestStillBound:
    async def _service_dataset(self, session) -> Dataset:
        dataset = await _dataset(session, "wfs")
        _bind_service(dataset)
        await session.commit()
        return dataset

    async def test_a_rebind_that_committed_first_matches_nothing(
        self, test_db_session
    ) -> None:
        dataset = await self._service_dataset(test_db_session)
        read = bound_pointer(dataset)
        set_dataset_origin(dataset, "upload", filename="roads.gpkg")
        dataset.source_format = "gpkg"
        await test_db_session.commit()

        assert await _stamp(dataset.id, read) == 0
        assert await _stamp(dataset.id, bound_pointer(dataset)) == 1

    async def test_an_auth_required_flip_matches_nothing(self, test_db_session) -> None:
        dataset = await self._service_dataset(test_db_session)
        read = bound_pointer(dataset)
        _bind_service(dataset, auth_required=True)
        await test_db_session.commit()

        assert await _stamp(dataset.id, read) == 0

    async def test_null_columns_match_their_own_null(self, test_db_session) -> None:
        """A registered table stores no format and a drawn layer no ref; both still match."""
        registered = await _dataset(test_db_session, None)
        set_postgis_origin(registered, registered.table_name, schema="data")
        drawn = await _dataset(test_db_session, "created")
        set_dataset_origin(drawn, "created")
        await test_db_session.commit()
        assert registered.source_format is None
        assert (drawn.origin_uri, drawn.origin_ref) == (None, None)

        assert await _stamp(registered.id, bound_pointer(registered)) == 1
        assert await _stamp(drawn.id, bound_pointer(drawn)) == 1
