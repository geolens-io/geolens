"""Convert stored raster_assets.crs_wkt from WKT1_GDAL to WKT2:2019.

fix(#1376): ``RasterAsset.to_stac_properties()`` publishes ``crs_wkt``
verbatim as the STAC Projection Extension's ``proj:wkt2``, but both writers
of the column asked rasterio for its DEFAULT serialization, which is
WKT1_GDAL (``PROJCS[...]``, not ``PROJCRS[...]``). Both now request
``version="WKT2_2019"`` — ``processing/raster/cog.py`` for local uploads and
``modules/catalog/sources/cog_info.py`` for the remote-asset probe.

Why the rows get backfilled rather than left to drift. Fixing only the
writers would make the dialect a function of INGEST ERA: a consumer reading
``proj:wkt2`` off this catalog could no longer assume one format for the
field, and nothing in a row says which era wrote it. Re-ingest is the only
other way a row would ever change, and a stable raster has no reason to be
re-ingested. So the conversion happens once, here, and the column means one
thing afterwards.

Idempotent by construction: the predicate matches WKT1 root keywords only,
and every row this migration rewrites leaves that predicate (WKT2 roots are
``PROJCRS``/``GEOGCRS``/``GEODCRS``/``ENGCRS``/``COMPOUNDCRS``/``VERTCRS``).
A row whose stored WKT PROJ cannot parse is left exactly as it was — an
unreadable CRS is not a reason to fail a deployment, and the value is no
worse off than before.

Downgrade is a deliberate no-op. WKT1 is the strictly less expressive
dialect, so the pre-migration bytes are not faithfully recoverable, and
nothing reads this column expecting WKT1: the two consumers
(``core/geo.py``'s ``wkt_is_geographic``/``wkt_has_degree_unit``) hand it to
PROJ and their keyword fallback already recognises both dialects.

Revision ID: 0041_raster_assets_crs_wkt2
Revises: 0040_dataset_origin_ref_indexes
Create Date: 2026-08-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0041_raster_assets_crs_wkt2"
down_revision: Union[str, None] = "0040_dataset_origin_ref_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Every WKT1 root keyword, not just the projected/geographic pair: each has a
# DISTINCT WKT2 counterpart, so matching the whole set converts the column
# completely instead of leaving a second dialect behind on the rarer CRS
# kinds. The ``\[`` anchor is what keeps ``GEOGCS`` from also matching a
# ``GEOGCRS[`` prefix (likewise PROJCS/PROJCRS). Case-insensitive because WKT
# keywords are case-insensitive per spec, even though GDAL writes them upper.
_WKT1_ROOT_RE = r"^\s*(PROJCS|GEOGCS|GEOCCS|LOCAL_CS|COMPD_CS|VERT_CS|FITTED_CS)\s*\["

# Keyset-paged rather than read whole. raster_assets holds one row per raster
# dataset and each WKT is a few kB, which is small on any install this project
# has seen — but a single SELECT of the entire matching set is the kind of
# thing that only fails on the largest catalog, i.e. the one where a failed
# migration costs the most. Paging by ``id`` also steps PAST rows this
# migration deliberately leaves unconverted, so an unparseable row cannot be
# re-selected forever.
_BATCH_SIZE = 500


def upgrade() -> None:
    import logging

    from rasterio.crs import CRS

    log = logging.getLogger("alembic.runtime.migration")
    conn = op.get_bind()

    converted = 0
    unparseable: list[str] = []
    last_id = None

    while True:
        sql = (
            "SELECT id, crs_wkt FROM catalog.raster_assets "
            "WHERE crs_wkt IS NOT NULL AND crs_wkt ~* :wkt1_root"
        )
        params: dict = {"wkt1_root": _WKT1_ROOT_RE, "batch": _BATCH_SIZE}
        if last_id is not None:
            sql += " AND id > :last_id"
            params["last_id"] = last_id
        sql += " ORDER BY id LIMIT :batch"

        rows = conn.execute(sa.text(sql), params).all()
        if not rows:
            break
        last_id = rows[-1][0]

        for asset_id, wkt1 in rows:
            try:
                wkt2 = CRS.from_wkt(wkt1).to_wkt(version="WKT2_2019")
            except Exception:  # broad: crs_wkt is whatever GDAL wrote at ingest — any PROJ failure means "leave this row alone", not "abort the deployment"
                wkt2 = None
            # The equality check keeps the promise the predicate makes: only a
            # value that actually CHANGED gets written, so a hypothetical CRS
            # whose WKT2 export still carries a WKT1 root keyword is recorded
            # as unconverted rather than rewritten to itself on every run.
            if not wkt2 or wkt2 == wkt1:
                unparseable.append(str(asset_id))
                continue
            conn.execute(
                sa.text(
                    "UPDATE catalog.raster_assets SET crs_wkt = :wkt WHERE id = :id"
                ),
                {"wkt": wkt2, "id": asset_id},
            )
            converted += 1

    log.info("raster_assets.crs_wkt converted to WKT2:2019: %d row(s)", converted)
    if unparseable:
        log.warning(
            "raster_assets.crs_wkt left as WKT1 on %d row(s) PROJ could not "
            "convert (ids: %s). These publish a WKT1 string under proj:wkt2 "
            "until the raster is re-ingested.",
            len(unparseable),
            ", ".join(unparseable),
        )


def downgrade() -> None:
    """No-op — see the module docstring.

    WKT1 cannot express everything WKT2 can, so re-serializing these values
    back would not restore the bytes this migration replaced, and no reader of
    the column requires WKT1.
    """
