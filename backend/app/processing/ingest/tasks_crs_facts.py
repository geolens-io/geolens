"""Fill the CRS facts of raster rows whose ``crs_wkt`` has none.

Rows stored before the facts existed, or by a worker still running the
previous image during a rolling deploy, hold NULL facts. Each run pages
through them by id, asks the probe child about each distinct text once, and
stops when it runs out of rows, texts or time, so a backlog drains over
several runs. ``raster_assets`` has no row-level security, so one pass covers
every tenant.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field

import structlog
from sqlalchemy import text

from app.processing.ingest.tasks_common import task_app
from app.processing.raster import probe

logger = structlog.get_logger(__name__)

# WGS 84, which a working probe child always describes this way. A run whose
# child can't give this answer writes nothing.
_CONTROL_WKT = (
    'GEOGCRS["WGS 84",DATUM["World Geodetic System 1984",'
    'ELLIPSOID["WGS 84",6378137,298.257223563]],CS[ellipsoidal,2],'
    'AXIS["latitude",north],AXIS["longitude",east],'
    'ANGLEUNIT["degree",0.0174532925199433]]'
)
_CONTROL_FACTS = {
    "crs_is_geographic": True,
    "crs_has_degree_unit": True,
    "crs_metres_per_unit": None,
}

PAGE_ROWS = 500
BATCH_TEXTS = 50
RUN_TEXTS = 200
RUN_SECONDS = 60.0
FIRST_BACKOFF_SECONDS = 15 * 60
MAX_BACKOFF_SECONDS = 24 * 60 * 60

_clock = time.monotonic
# md5 of a text the child couldn't answer for -> (failures, when to ask again).
# Per process: a restarted worker asks again at once.
_backoff: dict[str, tuple[int, float]] = {}

_CANDIDATES = text(
    "SELECT id, md5(crs_wkt) AS digest, crs_wkt FROM catalog.raster_assets "
    "WHERE crs_wkt IS NOT NULL AND crs_is_geographic IS NULL "
    "AND crs_has_degree_unit IS NULL AND crs_metres_per_unit IS NULL "
    "AND id > :after ORDER BY id LIMIT :limit"
)
# By id, and only while the row still holds the text the facts describe.
_FILL = text(
    "UPDATE catalog.raster_assets SET crs_is_geographic = :crs_is_geographic, "
    "crs_has_degree_unit = :crs_has_degree_unit, "
    "crs_metres_per_unit = :crs_metres_per_unit "
    "WHERE id = ANY(:ids) AND md5(crs_wkt) = :digest "
    "AND crs_is_geographic IS NULL AND crs_has_degree_unit IS NULL "
    "AND crs_metres_per_unit IS NULL"
)


@dataclass
class RepairOutcome:
    filled: int = 0
    unanswered: list[str] = field(default_factory=list)
    skipped: bool = False


def _answers(wkts: list[str]) -> list[dict | None]:
    """The facts of each text, or None where the child gave none."""
    try:
        return probe.crs_facts_many(wkts)
    except probe.RasterProbeError:
        if len(wkts) == 1:
            return [None]
    # One text can stall the whole batch; asking one at a time isolates it.
    answers: list[dict | None] = []
    for wkt in wkts:
        try:
            answers.append(probe.crs_facts(wkt))
        except probe.RasterProbeError:
            answers.append(None)
    return answers


def _control_passes() -> bool:
    try:
        answer = probe.crs_facts_many([_CONTROL_WKT])
    except probe.RasterProbeError as exc:
        logger.warning("crs_facts_repair_skipped", reason=exc.kind)
        return False
    if answer != [_CONTROL_FACTS]:
        logger.warning("crs_facts_repair_skipped", reason="control_mismatch")
        return False
    return True


def _back_off(digest: str, now: float) -> None:
    failures = _backoff.get(digest, (0, 0.0))[0] + 1
    delay = min(FIRST_BACKOFF_SECONDS * 2 ** (failures - 1), MAX_BACKOFF_SECONDS)
    _backoff[digest] = (failures, now + delay)


async def repair_missing_crs_facts(
    *, run_texts: int = RUN_TEXTS, run_seconds: float = RUN_SECONDS
) -> RepairOutcome:
    """Fill missing facts for up to ``run_texts`` texts or ``run_seconds``."""
    from app.core.db import async_session

    outcome = RepairOutcome()
    deadline = _clock() + run_seconds
    asked = 0
    checked = False
    after = uuid.UUID(int=0)
    while asked < run_texts and _clock() < deadline:
        async with async_session() as session:
            rows = (
                await session.execute(_CANDIDATES, {"after": after, "limit": PAGE_ROWS})
            ).all()
        if not rows:
            break
        after = rows[-1].id
        pending: dict[str, tuple[str, list[uuid.UUID]]] = {}
        for row in rows:
            if _backoff.get(row.digest, (0, 0.0))[1] > _clock():
                continue
            pending.setdefault(row.digest, (row.crs_wkt, []))[1].append(row.id)
        digests = list(pending)[: run_texts - asked]
        if not digests:
            continue
        if not checked:
            if not await asyncio.to_thread(_control_passes):
                outcome.skipped = True
                return outcome
            checked = True
        asked += len(digests)
        for start in range(0, len(digests), BATCH_TEXTS):
            if _clock() >= deadline:
                break
            batch = digests[start : start + BATCH_TEXTS]
            answers = await asyncio.to_thread(
                _answers, [pending[digest][0] for digest in batch]
            )
            async with async_session() as session:
                for digest, facts in zip(batch, answers):
                    ids = pending[digest][1]
                    if facts is None or all(value is None for value in facts.values()):
                        _back_off(digest, _clock())
                        outcome.unanswered.extend(str(asset_id) for asset_id in ids)
                        continue
                    _backoff.pop(digest, None)
                    result = await session.execute(
                        _FILL, {**facts, "ids": ids, "digest": digest}
                    )
                    outcome.filled += result.rowcount
                await session.commit()

    if outcome.filled or outcome.unanswered:
        logger.info(
            "crs_facts_repair_run",
            filled=outcome.filled,
            unanswered=len(outcome.unanswered),
            unanswered_asset_ids=outcome.unanswered,
        )
    return outcome


@task_app.periodic(cron="*/15 * * * *", periodic_id="crs-facts-repair")
@task_app.task(queue="raster", retry=0, queueing_lock="crs-facts-repair")
async def repair_crs_facts(timestamp: int | None = None) -> None:
    """Fill missing CRS facts; the worker also queues one run when it starts."""
    await repair_missing_crs_facts()
