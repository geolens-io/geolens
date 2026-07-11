"""MapLayerPatch must keep omitted fields omitted (HT-14 regression).

The old after-mode ``_normalize_paint_boundary`` validator assigned
``self.paint``/``self.style_config`` unconditionally, adding both names to
``model_fields_set`` and defeating the router's ``exclude_unset=True``. Any
partial patch (the builder's own eye-toggle Save sends exactly ``{id,
visible}``) then carried ``style_config=None``, which ``apply_layer_diff``
treated as an explicit clear — wiping DEM hypsometric metadata and clearing
non-DEM style_config. History ``changed_fields`` was falsified the same way.
"""

import uuid

from app.modules.catalog.maps.schemas import MapLayerPatch

LAYER_ID = uuid.uuid4()


def test_visibility_only_patch_keeps_style_fields_unset():
    patch = MapLayerPatch(id=LAYER_ID, visible=False)
    assert patch.model_fields_set == {"id", "visible"}
    assert patch.model_dump(exclude_unset=True) == {"id": LAYER_ID, "visible": False}


def test_opacity_only_patch_keeps_style_fields_unset():
    patch = MapLayerPatch(id=LAYER_ID, opacity=0.5)
    assert patch.model_fields_set == {"id", "opacity"}


def test_explicit_style_config_still_normalizes():
    patch = MapLayerPatch(
        id=LAYER_ID,
        style_config={"builder": {"outlineWidth": 2}, "render_mode": "hillshade"},
    )
    assert "style_config" in patch.model_fields_set
    # Phase 1060 canonicalization still applies on the explicit path.
    assert patch.style_config == {
        "builder": {"outline_width": 2},
        "render_mode": "hillshade",
    }


def test_explicit_null_style_config_survives_as_explicit():
    patch = MapLayerPatch.model_validate({"id": str(LAYER_ID), "style_config": None})
    assert "style_config" in patch.model_fields_set
    assert patch.style_config is None


def test_legacy_builder_paint_split_marks_style_config_set():
    patch = MapLayerPatch(id=LAYER_ID, paint={"_outline-width": 2})
    assert patch.paint == {}
    assert patch.style_config == {"builder": {"outline_width": 2}}
    assert "style_config" in patch.model_fields_set


def test_plain_paint_patch_does_not_fabricate_style_config():
    patch = MapLayerPatch(id=LAYER_ID, paint={"fill-color": "#123456"})
    assert patch.model_fields_set == {"id", "paint"}
    assert patch.paint == {"fill-color": "#123456"}
