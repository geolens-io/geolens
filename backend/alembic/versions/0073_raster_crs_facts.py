"""Store each raster's CRS facts beside its CRS text, and fill them for existing rows.

Requests read these instead of parsing ``crs_wkt``, because PROJ may open files
named in CRS text. The backfill runs each distinct stored text through the same
raster probe child ingest uses. A text the child can't answer for keeps NULL
facts, which readers treat as unknown.

Revision ID: 0073_raster_crs_facts
Revises: 0072_ingest_job_error_code
Create Date: 2026-09-26
"""

import logging
from collections.abc import Callable
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0073_raster_crs_facts"
down_revision: Union[str, None] = "0072_ingest_job_error_code"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FACT_COLUMNS = (
    ("crs_is_geographic", sa.Boolean()),
    ("crs_has_degree_unit", sa.Boolean()),
    ("crs_metres_per_unit", sa.Double()),
)

# WGS 84, which a working probe child always describes this way. Asked first,
# so a child that can't run stops the migration instead of leaving every row
# NULL.
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

_BATCH_SIZE = 200


def upgrade() -> None:
    for name, type_ in _FACT_COLUMNS:
        op.add_column(
            "raster_assets", sa.Column(name, type_, nullable=True), schema="catalog"
        )
    backfill(op.get_bind())


def downgrade() -> None:
    for name, _ in reversed(_FACT_COLUMNS):
        op.drop_column("raster_assets", name, schema="catalog")


def backfill(conn, facts_of: Callable[[str], dict] | None = None) -> None:
    """Fill the facts of every stored CRS text, one probe child per distinct text."""
    log = logging.getLogger("alembic.runtime.migration")
    probe = None
    answered = 0
    unanswered: list[str] = []
    after = ""
    while True:
        digests = (
            conn.execute(
                sa.text(
                    "SELECT DISTINCT md5(crs_wkt) AS digest FROM catalog.raster_assets "
                    "WHERE crs_wkt IS NOT NULL AND md5(crs_wkt) > :after "
                    "ORDER BY digest LIMIT :batch"
                ),
                {"after": after, "batch": _BATCH_SIZE},
            )
            .scalars()
            .all()
        )
        if not digests:
            break
        after = digests[-1]
        if probe is None:
            # Imported only when there are rows, so a fresh database never
            # loads the app.
            from app.processing.raster import probe

            facts_of = facts_of or probe.crs_facts
            _check_control(facts_of)
        for digest in digests:
            wkts = (
                conn.execute(
                    sa.text(
                        "SELECT DISTINCT crs_wkt FROM catalog.raster_assets "
                        "WHERE md5(crs_wkt) = :digest"
                    ),
                    {"digest": digest},
                )
                .scalars()
                .all()
            )
            for wkt in wkts:
                where = {"digest": digest, "wkt": wkt}
                try:
                    facts = facts_of(wkt)
                except probe.RasterProbeError:
                    unanswered.extend(
                        str(asset_id)
                        for asset_id in conn.execute(
                            sa.text(
                                "SELECT id FROM catalog.raster_assets "
                                "WHERE md5(crs_wkt) = :digest AND crs_wkt = :wkt"
                            ),
                            where,
                        ).scalars()
                    )
                    continue
                conn.execute(
                    sa.text(
                        "UPDATE catalog.raster_assets SET "
                        "crs_is_geographic = :crs_is_geographic, "
                        "crs_has_degree_unit = :crs_has_degree_unit, "
                        "crs_metres_per_unit = :crs_metres_per_unit "
                        "WHERE md5(crs_wkt) = :digest AND crs_wkt = :wkt"
                    ),
                    {**{name: facts.get(name) for name, _ in _FACT_COLUMNS}, **where},
                )
                answered += 1

    log.info("raster_assets CRS facts filled for %d distinct CRS text(s)", answered)
    if unanswered:
        log.warning(
            "raster_assets CRS facts left unknown on %d row(s) the probe child "
            "could not answer for (ids: %s). They read as unknown until the "
            "raster is replaced.",
            len(unanswered),
            ", ".join(unanswered),
        )


def _check_control(facts_of: Callable[[str], dict]) -> None:
    try:
        facts = facts_of(_CONTROL_WKT)
    except (
        Exception
    ) as exc:  # broad: any failure here means the child can't run, whatever raised
        raise RuntimeError(
            "The raster probe child could not describe WGS 84, so the CRS facts "
            "backfill stopped before writing anything. Check that this "
            "environment can run `python -m app.processing.raster.probe`."
        ) from exc
    if facts != _CONTROL_FACTS:
        raise RuntimeError(
            "The raster probe child described WGS 84 wrongly, so the CRS facts "
            "backfill stopped before writing anything."
        )
