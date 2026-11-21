"""The Python SDK's manifest request keeps the positional order callers already use."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.processing.ingest.manifest_schemas import ManifestApplyRequest

_SDK_PY_PATH = Path(__file__).resolve().parents[2] / "sdks" / "python"
# The api container mounts backend/ only; host and CI checkouts have the SDK.
if not (_SDK_PY_PATH / "geolens" / "auth.py").is_file():
    pytest.skip("geolens SDK source tree not present", allow_module_level=True)
if str(_SDK_PY_PATH) not in sys.path:
    sys.path.insert(0, str(_SDK_PY_PATH))

from geolens.models.manifest_apply_request import (  # noqa: E402
    ManifestApplyRequest as SdkManifestApplyRequest,
)
from geolens.models.manifest_catalog import ManifestCatalog  # noqa: E402
from geolens.models.manifest_dataset import ManifestDataset  # noqa: E402


def test_the_fourth_positional_argument_is_still_dry_run():
    dataset = ManifestDataset.from_dict(
        {
            "key": "roads",
            "title": "Roads",
            "sources": [{"type": "vector", "uri": "https://example.com/roads.fgb"}],
            "publication": {"intent": "draft"},
        }
    )

    body = SdkManifestApplyRequest(
        "1", ManifestCatalog(title="Catalog"), [dataset], True
    ).to_dict()

    assert body["dry_run"] is True
    assert "client" not in body
    assert ManifestApplyRequest.model_validate(body).dry_run is True
