"""Every published v2 example still applies, and still uses accepted styling keys.

The examples in ``fixtures/publish_contract_v2.json`` are what desktop clients
copy. Each must pass a dry run against a real database, and the style and label
keys they carry must stay inside the publish vocabulary, so a builder refactor
that drops a published key fails here.

Requirements: the docker database must be running with migrations applied.
"""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.modules.auth.models import User
from app.modules.catalog.maps import publish_vocabulary as vocabulary
from app.modules.catalog.maps import style_sanitizers as sanitizers
from app.modules.catalog.maps.schemas import _BUILDER_CAMEL_TO_SNAKE_KEYS
from app.platform.jobs.models import IngestJob
from tests.factories import create_dataset

pytestmark = pytest.mark.anyio

EXAMPLES = json.loads(
    (Path(__file__).parent / "fixtures" / "publish_contract_v2.json").read_text()
)["valid"]
_BUILT_IN_INTENTS = {"draft", "ready", "internal", "published"}
_EXTENSION = {"vector": "geojson", "raster_cog": "tif"}


def _layers(manifest: dict):
    for map_entry in manifest.get("maps", []):
        yield from map_entry["layers"]


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda e: e["name"])
def test_published_style_keys_are_still_in_the_vocabulary(example):
    for layer in _layers(example["manifest"]):
        style = layer.get("style_config") or {}
        assert set(style) <= vocabulary.STYLE_METADATA_KEYS
        assert set(sanitizers.clean_style_metadata(style) or {}) == set(style)
        builder = style.get("builder") or {}
        known = vocabulary.BUILDER_STYLE_KEYS
        assert {_BUILDER_CAMEL_TO_SNAKE_KEYS.get(k, k) for k in builder} <= known
        symbol = style.get("symbol")
        if isinstance(symbol, dict):
            assert set(symbol) <= vocabulary.SYMBOL_METADATA_KEYS
        assert set(layer.get("label_config") or {}) <= vocabulary.LABEL_METADATA_KEYS


def test_the_examples_use_style_and_label_keys():
    used = [
        layer
        for example in EXAMPLES
        for layer in _layers(example["manifest"])
        if layer.get("style_config") or layer.get("label_config")
    ]
    assert used


async def _stage_upload(session, owner: uuid.UUID, job_id: str, source_type: str):
    """A pending upload the examples' `upload:` URI names, and its real checksum."""
    body = f"example upload {job_id}".encode()
    path = Path(settings.upload_staging_dir) / f"{job_id}_example"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    session.add(
        IngestJob(
            id=uuid.UUID(job_id),
            status="pending",
            created_by=owner,
            source_filename=f"example.{_EXTENSION[source_type]}",
            file_path=str(path),
            user_metadata={"staged_at": datetime.now(timezone.utc).isoformat()},
        )
    )
    await session.commit()
    return "sha256:" + hashlib.sha256(body).hexdigest()


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda e: e["name"])
async def test_each_example_applies_as_a_dry_run(
    example,
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    clean_tables,
):
    owner = (
        await test_db_session.execute(select(User).where(User.username == "admin"))
    ).scalar_one()
    manifest = copy.deepcopy(example["manifest"])
    manifest["dry_run"] = True

    for dataset in manifest.get("datasets", []):
        # An intent outside the built-in stages belongs to a workflow extension
        # this server doesn't have, and a dry run refuses it.
        if dataset["publication"]["intent"] not in _BUILT_IN_INTENTS:
            dataset["publication"] = {"intent": "published"}
        for source in dataset["sources"]:
            job_id = source["uri"].removeprefix("upload:")
            source["checksum"] = await _stage_upload(
                test_db_session, owner.id, job_id, source["type"]
            )
    dataset_ids = {}
    for layer in _layers(manifest):
        if "dataset_id" in layer:
            old = layer["dataset_id"]
            if old not in dataset_ids:
                dataset_ids[old] = str(
                    (
                        await create_dataset(
                            test_db_session,
                            created_by=owner.id,
                            geometry_type="MultiPolygon",
                            column_info=[{"name": "park_type", "type": "text"}],
                        )
                    ).id
                )
            layer["dataset_id"] = dataset_ids[old]

    response = await client.post(
        "/ingest/manifest/apply", json=manifest, headers=admin_auth_header
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["dry_run"] is True
    results = [*body["results"], *(body.get("maps") or [])]
    assert results
    allow_errors = example.get("expect_errors", False)
    for result in results:
        assert result["action"] != "error" or allow_errors, json.dumps(result)
        for message in result.get("messages") or []:
            assert message["severity"] != "error" or allow_errors, message
