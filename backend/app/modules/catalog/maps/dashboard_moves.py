"""Whether a save that moves map layers to other datasets may leave their
dashboard widgets in front of readers of the dataset a layer moves to."""

import uuid
from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.authorization import datasets_beyond_audience
from app.modules.catalog.maps.dashboard import can_drop_widgets

Move = tuple[uuid.UUID, uuid.UUID]

STRANDED_WIDGETS = (
    "This map's dashboard holds widgets this version of GeoLens can't read, "
    "so a layer can't move to a dataset that people who can't read its "
    "current dataset can read. Remove the layer's widgets in the GeoLens that "
    "added them, or keep the layer on its dataset."
)


async def widening_pairs(session: AsyncSession, moves: Iterable[Move]) -> set[Move]:
    """The ``(from, to)`` dataset pairs among ``moves`` where somebody who
    reads ``to`` may be unable to read ``from``."""
    pairs = sorted(set(moves))
    if not pairs:
        return set()
    beyond = await datasets_beyond_audience(session, [(to, was) for was, to in pairs])
    return {pair for pair, flag in zip(pairs, beyond, strict=True) if flag}


async def stranding_moves(
    session: AsyncSession, dashboard: object, moves: Iterable[Move]
) -> set[Move]:
    """The moves among ``moves`` a save must refuse under ``dashboard``: those
    that widen who reads the layer while the dashboard holds widgets
    ``drop_repointed`` can't remove, which may name the old dataset's columns
    and hold its filter values. Reads nothing when it can remove them."""
    if can_drop_widgets(dashboard):
        return set()
    return await widening_pairs(session, moves)
