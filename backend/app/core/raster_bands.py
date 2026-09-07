"""Normalisation for the `raster_assets.band_info` JSONB column.

fix(#1778): `band_info` is schemaless with two producers that never agreed on
a shape. Producer A, `extract_raster_metadata` (local ingest), writes
`{index, dtype, nodata, color_interp, unit?}` — the canonical shape, which the
STAC serializer targets. Producer B, `fetch_cog_info` (remote COG via STAC
import), writes `{min, max, mean}` and is normalised on READ rather than
migrated, since both readers already need to handle an unrecognised shape.

Lives in `core/` because the two readers sit on opposite sides of a layering
rule (`app/modules/catalog/` may not import `app.processing.*`, CATPORT-02/04)
and need a shared module to avoid disagreeing about a band again.
"""

# The three non-numeric values the STAC Raster Extension accepts for `nodata`.
_STAC_NODATA_SENTINELS = ("nan", "inf", "-inf")


def band_display_name(band: dict) -> str | None:
    """The band's human-readable name, from whichever key carries it.

    Producer A writes the colour interpretation under `color_interp`, not
    `name` (which the OGC Records serializer reads).
    """
    return band.get("name") or band.get("color_interp")


def stac_band_nodata(value: object) -> float | int | str | None:
    """A `raster:bands[].nodata` value the STAC Raster Extension accepts.

    The extension allows a number or the strings "nan"/"inf"/"-inf". Producer A
    stores `str(src.nodata)`, so nodata 0 arrives as `"0.0"` and must be parsed
    back to a number, not published verbatim as a string. Anything unparseable
    is dropped.

    `bool` is rejected rather than emitted as 0/1: it's an `int` subclass, but
    no raster carries a boolean nodata, so a `True` here means the column holds
    something this function shouldn't guess about.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.lower() in _STAC_NODATA_SENTINELS:
        return text.lower()
    try:
        return float(text)
    except ValueError:
        return None
