"""fix(#836): the raster-family record-type check has one canonical home.

The membership check ``record_type in ("raster_dataset", "vrt_dataset")`` was
pasted across modules/, processing/, and standards/ as tuple/set literals.
These tests pin the centralized vocabulary's semantics and fail if a literal
copy reappears outside ``app/core/record_types.py``.
"""

from pathlib import Path

from app.core.record_types import RASTER_FAMILY_RECORD_TYPES, is_raster_family

_APP_ROOT = Path(__file__).resolve().parents[1] / "app"


def test_raster_family_membership() -> None:
    assert RASTER_FAMILY_RECORD_TYPES == ("raster_dataset", "vrt_dataset")
    assert is_raster_family("raster_dataset")
    assert is_raster_family("vrt_dataset")


def test_raster_family_non_membership() -> None:
    for record_type in ("vector_dataset", "table", "map", "service", "collection"):
        assert not is_raster_family(record_type)
    assert not is_raster_family(None)
    assert not is_raster_family("")


def test_no_literal_raster_family_copies_remain() -> None:
    """A reintroduced family literal is the seed of the next divergent copy."""
    offenders: list[str] = []
    for path in sorted(_APP_ROOT.rglob("*.py")):
        if path.name == "record_types.py":
            continue
        text = path.read_text(encoding="utf-8")
        if '"raster_dataset", "vrt_dataset"' in text or (
            '"vrt_dataset", "raster_dataset"' in text
        ):
            offenders.append(str(path.relative_to(_APP_ROOT)))
    assert not offenders, (
        "Raster-family literal found outside app/core/record_types.py — import "
        f"RASTER_FAMILY_RECORD_TYPES / is_raster_family instead: {offenders}"
    )
