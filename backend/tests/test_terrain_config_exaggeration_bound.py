"""TerrainConfig.exaggeration upper bound parity with the frontend.

The frontend clamps the rendered terrain exaggeration to [0, 3]
(TERRAIN_EXAGGERATION_MAX in map-sync.ts; the DEM editor slider caps there too).
The backend bound must match so a stored value can never exceed what the mesh
actually renders. Guards against the silent "stored 10, renders 3" divergence.
"""

import uuid

import pytest
from pydantic import ValidationError

from app.modules.catalog.maps.schemas import TerrainConfig


def test_exaggeration_at_upper_bound_accepted():
    assert TerrainConfig(exaggeration=3.0).exaggeration == 3.0


def test_exaggeration_above_three_rejected():
    # Previously le=10.0 accepted this; the frontend would silently render it as 3.
    with pytest.raises(ValidationError):
        TerrainConfig(exaggeration=3.5)


def test_exaggeration_default_is_true_scale():
    assert TerrainConfig().exaggeration == 1.0


def test_enabled_without_source_coerced_to_disabled():
    # fix(HT-15): enabled=True with no source is internally inconsistent — it
    # can only produce dangling status and resolver no-ops. It is coerced to
    # disabled (not rejected) so this same model can also validate stored JSONB
    # on the read path without 500-ing a legacy/corrupt row.
    cfg = TerrainConfig(enabled=True)
    assert cfg.enabled is False
    assert cfg.source_dataset_id is None


def test_disabled_without_source_accepted():
    cfg = TerrainConfig(enabled=False, source_dataset_id=None)
    assert cfg.enabled is False


def test_enabled_with_source_preserved():
    src = uuid.uuid4()
    cfg = TerrainConfig(enabled=True, source_dataset_id=src)
    assert cfg.enabled is True
    assert cfg.source_dataset_id == src
