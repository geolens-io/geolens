"""Fill the CRS facts of raster rows whose ``crs_wkt`` has none.

Rows written before the facts existed hold NULL facts, as do rows a worker
still on the previous image inserts during a rolling deploy, or whose text it
changes (migration 0073's trigger then clears the stale facts). Each run pages
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
# sha256 of a text the child couldn't answer for -> (failures, when to ask
# again). Per process: a restarted worker asks again at once.
_backoff: dict[str, tuple[int, float]] = {}

_CANDIDATES = text(
    "SELECT id, encode(sha256(convert_to(crs_wkt, 'UTF8')), 'hex') AS digest, "
    "crs_wkt FROM catalog.raster_assets WHERE crs_wkt IS NOT NULL "
    "AND crs_is_geographic IS NULL AND crs_has_degree_unit IS NULL "
    "AND crs_metres_per_unit IS NULL AND id > :after ORDER BY id LIMIT :limit"
)
# By id, and only while the row still holds the text the facts describe.
_FILL = text(
    "UPDATE catalog.raster_assets SET crs_is_geographic = :crs_is_geographic, "
    "crs_has_degree_unit = :crs_has_degree_unit, "
    "crs_metres_per_unit = :crs_metres_per_unit, "
    "crs_facts_digest = sha256(convert_to(crs_wkt, 'UTF8')) "
    "WHERE id = ANY(:ids) "
    "AND encode(sha256(convert_to(crs_wkt, 'UTF8')), 'hex') = :digest "
    "AND crs_is_geographic IS NULL AND crs_has_degree_unit IS NULL "
    "AND crs_metres_per_unit IS NULL"
)

# A distinct CRS text, as (sha256 hex digest, text).
CrsText = tuple[str, str]


@dataclass
class RepairOutcome:
    filled: int = 0
    unanswered: list[str] = field(default_factory=list)
    skipped: bool = False


def _timeout(deadline: float) -> float:
    """The run's remaining time, capped at a probe's own timeout.

    The control and each batch take this. The cap leaves time to ask one text
    at a time after a whole batch stalls.
    """
    return min(deadline - _clock(), probe.CRS_FACTS_TIMEOUT_SECONDS)


def _cut_short(exc: probe.RasterProbeError, timeout: float) -> bool:
    """A batch timeout the run's budget shortened says nothing about its texts."""
    return exc.kind == "timeout" and timeout < probe.CRS_FACTS_TIMEOUT_SECONDS


def _back_off(digest: str) -> None:
    failures = _backoff.get(digest, (0, 0.0))[0] + 1
    delay = min(FIRST_BACKOFF_SECONDS * 2 ** (failures - 1), MAX_BACKOFF_SECONDS)
    _backoff[digest] = (failures, _clock() + delay)


def _ask(texts: list[CrsText], deadline: float) -> dict[CrsText, dict | None]:
    """The child's facts for each text it was asked about, None where it failed.

    A batch that fails is asked again one text at a time, so a text that stalls
    every batch is found. A text the child fails on alone backs off at once. A
    text missing from the answer wasn't asked and doesn't back off.
    """
    timeout = _timeout(deadline)
    if timeout <= 0:
        return {}
    try:
        facts = probe.crs_facts_many([wkt for _, wkt in texts], timeout=timeout)
    except probe.RasterProbeError as exc:
        if _cut_short(exc, timeout):
            return {}
        if len(texts) > 1:
            return _ask_one_at_a_time(texts, deadline)
        _back_off(texts[0][0])
        return {texts[0]: None}
    return dict(zip(texts, facts))


def _ask_one_at_a_time(
    texts: list[CrsText], deadline: float
) -> dict[CrsText, dict | None]:
    """Each text alone with a probe's full timeout, starting none past the deadline.

    A shortened timeout would let a stalling text run out the budget without
    blame, and the next run would meet it first again.
    """
    answers: dict[CrsText, dict | None] = {}
    for key in texts:
        if _clock() >= deadline:
            break
        try:
            answers[key] = probe.crs_facts(
                key[1], timeout=probe.CRS_FACTS_TIMEOUT_SECONDS
            )
        except probe.RasterProbeError:
            _back_off(key[0])
            answers[key] = None
    return answers


def _control_passes(deadline: float) -> bool:
    try:
        answer = probe.crs_facts_many([_CONTROL_WKT], timeout=_timeout(deadline))
    except probe.RasterProbeError as exc:
        logger.warning("crs_facts_repair_skipped", reason=exc.kind)
        return False
    if answer != [_CONTROL_FACTS]:
        logger.warning("crs_facts_repair_skipped", reason="control_mismatch")
        return False
    return True


async def repair_missing_crs_facts(
    *, run_texts: int = RUN_TEXTS, run_seconds: float = RUN_SECONDS
) -> RepairOutcome:
    """Fill missing facts for up to ``run_texts`` texts or ``run_seconds``.

    No probe starts after ``run_seconds``, so a run lasts at most
    ``run_seconds`` plus one probe timeout.
    """
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
        pending: dict[CrsText, list[uuid.UUID]] = {}
        for row in rows:
            if _backoff.get(row.digest, (0, 0.0))[1] > _clock():
                continue
            pending.setdefault((row.digest, row.crs_wkt), []).append(row.id)
        keys = list(pending)[: run_texts - asked]
        if not keys:
            continue
        if not checked:
            if not await asyncio.to_thread(_control_passes, deadline):
                outcome.skipped = True
                return outcome
            checked = True
        asked += len(keys)
        for start in range(0, len(keys), BATCH_TEXTS):
            if _clock() >= deadline:
                break
            answers = await asyncio.to_thread(
                _ask, keys[start : start + BATCH_TEXTS], deadline
            )
            async with async_session() as session:
                for key, facts in answers.items():
                    ids = pending[key]
                    known = facts is not None and any(
                        value is not None for value in facts.values()
                    )
                    if not known:
                        if facts is not None:
                            _back_off(key[0])
                        outcome.unanswered.extend(str(asset_id) for asset_id in ids)
                        continue
                    _backoff.pop(key[0], None)
                    result = await session.execute(
                        _FILL, {**facts, "ids": ids, "digest": key[0]}
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
@task_app.task(
    queue="raster",
    retry=0,
    # queueing_lock keeps one run waiting; lock keeps two from running at once.
    queueing_lock="crs-facts-repair",
    lock="crs-facts-repair",
)
async def repair_crs_facts(timestamp: int | None = None) -> None:
    """Fill missing CRS facts; the worker also queues one run when it starts."""
    await repair_missing_crs_facts()
