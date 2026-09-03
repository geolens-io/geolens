"""Normalisation for the `raster_assets.band_info` JSONB column.

fix(#1778). `band_info` is schemaless and has two producers that never agreed
on a shape, and two serializers that each read one of them.

Producer A, `extract_raster_metadata` (local ingest), writes
`{index, dtype, nodata, color_interp, unit?}`. Producer B, `fetch_cog_info` (a
remote COG described through the STAC import path), writes `{min, max, mean}`.
The canonical shape is A: it is what every locally ingested raster carries,
what the STAC serializer was written against, and the only one of the two that
says anything a `raster:bands` entry needs.

B is normalised on READ rather than migrated. The two readers are the only
consumers, and neither can be handed a shape it does not understand without
this normalisation anyway, so a data migration would buy nothing the readers do
not already have to do.

It lives in `core/` because both readers need it and they sit on opposite sides
of a layering rule: `app/modules/catalog/` may not import `app.processing.*`
(CATPORT-02/04), and the STAC half of the pair is
`app/processing/raster/models.py`. A shared low-level module is the seam that
keeps the two representations of one dataset from disagreeing about a band
again, which is the defect this file exists to close.
"""

# The three non-numeric values the STAC Raster Extension accepts for `nodata`.
_STAC_NODATA_SENTINELS = ("nan", "inf", "-inf")


def band_display_name(band: dict) -> str | None:
    """The band's human-readable name, from whichever key carries it.

    Producer A writes the colour interpretation under `color_interp`. Nothing
    writes `name`, which is what the OGC Records serializer used to read, so
    every locally ingested raster reported band names through STAC and not
    through Records.
    """
    return band.get("name") or band.get("color_interp")


def stac_band_nodata(value: object) -> float | int | str | None:
    """A `raster:bands[].nodata` value the STAC Raster Extension accepts.

    The extension allows a number, or the strings "nan", "inf" and "-inf".
    Producer A stores `str(src.nodata)`, so a raster with nodata 0 arrives here
    as `"0.0"` and used to be published verbatim: a string where the schema
    requires a number, which fails validation and hands pystac and rio-stac
    consumers the wrong type.

    Anything that parses as a number is emitted as a number; the three named
    sentinels pass through as the strings the extension defines; anything else
    is dropped, because an unparseable nodata is not a value a conforming
    consumer can act on.

    `bool` is rejected rather than emitted as 0/1: it is an `int` subclass in
    Python, and no raster carries a boolean nodata, so a True here means the
    column holds something this function should not be guessing about.
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
