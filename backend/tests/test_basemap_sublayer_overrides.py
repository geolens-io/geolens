"""Tests for BasemapConfig.sublayer_overrides and the new SublayerOverride Pydantic model.

Coverage:
- SublayerOverride field defaults, valid values, range clamping, hex validation, extra="forbid"
- BasemapConfig.sublayer_overrides field wiring
- Legacy basemap_config payloads (without sublayer_overrides) deserialize cleanly
- Round-trip through BasemapConfig.model_validate + model_dump
- Round-trip through _clean_basemap_config (the style_json cleaner)
- _clean_basemap_config rejects invalid override payloads

Security coverage:
- T-1059A-01: hex validator blocks javascript: URIs, raw names, short/long hex
- T-1059A-02: numeric bounds on stroke_width, casing_width, zoom, opacity
- T-1059A-03: extra="forbid" blocks undeclared style axes (halo_blur, dash_pattern, etc.)
- T-1059A-04: legacy maps without sublayer_overrides deserialize cleanly (sublayer_overrides=None)
"""

import pytest
from pydantic import ValidationError

from app.modules.catalog.maps.schemas import BasemapConfig, SublayerOverride
from app.modules.catalog.maps.style_json import _clean_basemap_config

# ---------------------------------------------------------------------------
# Base fixture for a legacy basemap_config payload (no sublayer_overrides key)
# ---------------------------------------------------------------------------
LEGACY_BASEMAP_PAYLOAD = {
    "label_mode": "full",
    "road_visibility": "full",
    "boundary_visibility": "full",
    "building_visibility": True,
    "land_water_tone": "default",
    "opacity": 1.0,
}


# ---------------------------------------------------------------------------
# 1. SublayerOverride: all defaults are None
# ---------------------------------------------------------------------------
def test_sublayer_override_defaults_all_none():
    override = SublayerOverride()
    assert override.stroke_color is None
    assert override.stroke_width is None
    assert override.casing_color is None
    assert override.casing_width is None
    assert override.min_zoom is None
    assert override.max_zoom is None
    assert override.opacity is None


# ---------------------------------------------------------------------------
# 2. SublayerOverride: full payload round-trips
# ---------------------------------------------------------------------------
def test_sublayer_override_accepts_full_payload():
    payload = {
        "stroke_color": "#ff0000",
        "stroke_width": 3.5,
        "casing_color": "#0000ff",
        "casing_width": 1.0,
        "min_zoom": 5.0,
        "max_zoom": 18.0,
        "opacity": 0.75,
    }
    override = SublayerOverride.model_validate(payload)
    dumped = override.model_dump(mode="json")
    assert dumped["stroke_color"] == "#ff0000"
    assert dumped["stroke_width"] == 3.5
    assert dumped["casing_color"] == "#0000ff"
    assert dumped["casing_width"] == 1.0
    assert dumped["min_zoom"] == 5.0
    assert dumped["max_zoom"] == 18.0
    assert dumped["opacity"] == 0.75


# ---------------------------------------------------------------------------
# 3. stroke_width: reject negative values
# ---------------------------------------------------------------------------
def test_sublayer_override_rejects_negative_stroke_width():
    with pytest.raises(ValidationError):
        SublayerOverride(stroke_width=-0.1)


# ---------------------------------------------------------------------------
# 4. stroke_width: reject values above 20
# ---------------------------------------------------------------------------
def test_sublayer_override_rejects_oversized_stroke_width():
    with pytest.raises(ValidationError):
        SublayerOverride(stroke_width=20.5)


# ---------------------------------------------------------------------------
# 5. Zoom range: reject out-of-range values
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("min_zoom", -0.5),
        ("max_zoom", 24.5),
        ("min_zoom", -1.0),
        ("max_zoom", 25.0),
    ],
)
def test_sublayer_override_rejects_zoom_out_of_range(field, bad_value):
    with pytest.raises(ValidationError):
        SublayerOverride(**{field: bad_value})


# ---------------------------------------------------------------------------
# 6. opacity: reject values outside 0..1
# ---------------------------------------------------------------------------
def test_sublayer_override_rejects_opacity_out_of_range():
    with pytest.raises(ValidationError):
        SublayerOverride(opacity=1.5)
    with pytest.raises(ValidationError):
        SublayerOverride(opacity=-0.1)


# ---------------------------------------------------------------------------
# 7. Color validators: reject malformed hex (security: T-1059A-01)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad_hex",
    [
        "red",
        "#abc",
        "#1234567",
        "javascript:alert(1)",
        "",
        "rgb(255,0,0)",
    ],
)
def test_sublayer_override_rejects_malformed_hex(bad_hex):
    with pytest.raises(ValidationError):
        SublayerOverride(stroke_color=bad_hex)
    with pytest.raises(ValidationError):
        SublayerOverride(casing_color=bad_hex)


# ---------------------------------------------------------------------------
# 8. Color validators: accept uppercase hex (#FFAABB)
# ---------------------------------------------------------------------------
def test_sublayer_override_accepts_uppercase_hex():
    override = SublayerOverride(stroke_color="#FFAABB")
    assert override.stroke_color == "#FFAABB"
    override2 = SublayerOverride(casing_color="#AABBCC")
    assert override2.casing_color == "#AABBCC"


# ---------------------------------------------------------------------------
# 9. extra="forbid" blocks unknown style axes (D-14 scope guardrail; T-1059A-03)
# ---------------------------------------------------------------------------
def test_sublayer_override_rejects_unknown_extra_field():
    with pytest.raises(ValidationError):
        SublayerOverride(opacity=0.5, halo_blur=1)
    with pytest.raises(ValidationError):
        SublayerOverride.model_validate({"opacity": 0.5, "dash_pattern": "5,5"})


# ---------------------------------------------------------------------------
# 10. Legacy basemap_config (no sublayer_overrides key) deserializes cleanly
#     (D-03 zero-migration backward compat; T-1059A-04)
# ---------------------------------------------------------------------------
def test_basemap_config_legacy_payload_deserializes_with_no_overrides():
    cfg = BasemapConfig.model_validate(LEGACY_BASEMAP_PAYLOAD)
    assert cfg.sublayer_overrides is None


# ---------------------------------------------------------------------------
# 11. BasemapConfig with overrides round-trips through model_validate + model_dump
# ---------------------------------------------------------------------------
def test_basemap_config_with_overrides_round_trips():
    payload = {
        **LEGACY_BASEMAP_PAYLOAD,
        "sublayer_overrides": {
            "road": {"stroke_color": "#ff0000", "stroke_width": 2},
        },
    }
    cfg = BasemapConfig.model_validate(payload)
    dumped = cfg.model_dump(mode="json")
    assert dumped["sublayer_overrides"]["road"]["stroke_color"] == "#ff0000"
    assert dumped["sublayer_overrides"]["road"]["stroke_width"] == 2


# ---------------------------------------------------------------------------
# 12. _clean_basemap_config preserves sublayer_overrides through the round-trip cleaner
# ---------------------------------------------------------------------------
def test_clean_basemap_config_preserves_overrides():
    payload = {
        **LEGACY_BASEMAP_PAYLOAD,
        "sublayer_overrides": {
            "road": {"stroke_color": "#00ff00"},
        },
    }
    result = _clean_basemap_config(payload)
    assert result is not None
    assert result["sublayer_overrides"]["road"]["stroke_color"] == "#00ff00"


# ---------------------------------------------------------------------------
# 13. _clean_basemap_config rejects invalid sublayer_overrides (invalid hex)
#     The cleaner wraps ValidationError as ValueError("Invalid basemap_config metadata")
# ---------------------------------------------------------------------------
def test_clean_basemap_config_rejects_invalid_override():
    payload = {
        **LEGACY_BASEMAP_PAYLOAD,
        "sublayer_overrides": {
            "road": {"stroke_color": "not-hex"},
        },
    }
    with pytest.raises(ValueError, match="Invalid basemap_config metadata"):
        _clean_basemap_config(payload)


# ---------------------------------------------------------------------------
# 14. Opaque keyset: unknown sublayer IDs parse cleanly (D-01 forward-compat)
# ---------------------------------------------------------------------------
def test_sublayer_overrides_opaque_keyset():
    cfg = BasemapConfig.model_validate(
        {
            **LEGACY_BASEMAP_PAYLOAD,
            "sublayer_overrides": {
                "some_future_provider_specific_id": {"opacity": 0.5},
            },
        }
    )
    assert cfg.sublayer_overrides is not None
    assert cfg.sublayer_overrides["some_future_provider_specific_id"].opacity == 0.5
