"""Builds the frozen view of the publish manifest v2 contract.

Run ``cd backend && set -a && source ../.env.test && set +a && uv run python -m
tests.publish_contract_v2_snapshot`` to rewrite ``fixtures/publish_contract_v2_snapshot.json``
after a deliberate change to the manifest models or their codes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.platform.jobs import schemas as job_schemas
from app.processing.ingest.manifest_schemas import (
    ManifestApplyRequest,
    ManifestApplyResponse,
)

FIXTURES = Path(__file__).parent / "fixtures"
SNAPSHOT_PATH = FIXTURES / "publish_contract_v2_snapshot.json"
REGENERATE = (
    "cd backend && set -a && source ../.env.test && set +a && "
    "uv run python -m tests.publish_contract_v2_snapshot"
)

_APP = Path(__file__).parents[1] / "app"
# Every file that defines a code the manifest answers with.
_CODE_SOURCES = (
    "core/processing_port.py",
    "modules/catalog/collections/manifest.py",
    "modules/catalog/maps/manifest_messages.py",
    "processing/ingest/manifest_dataset_fields.py",
    "processing/ingest/manifest_maps.py",
    "processing/ingest/manifest_publication.py",
    "processing/ingest/manifest_schemas.py",
)
_CODE = re.compile(r"""["'](A\d{3})["']""")


def _describe(node: dict[str, Any]) -> str:
    if "$ref" in node:
        return node["$ref"].rsplit("/", 1)[1]
    if "anyOf" in node:
        return "|".join(sorted(_describe(branch) for branch in node["anyOf"]))
    if "const" in node:
        return f"const:{node['const']}"
    if "enum" in node:
        return "enum:" + ",".join(map(str, node["enum"]))
    kind = node.get("type", "any")
    if kind == "array" and "prefixItems" in node:
        return "tuple<" + ",".join(_describe(n) for n in node["prefixItems"]) + ">"
    if kind == "array":
        return f"array<{_describe(node.get('items', {}))}>"
    if kind == "object" and "additionalProperties" in node:
        extra = node["additionalProperties"]
        return f"map<{_describe(extra) if isinstance(extra, dict) else extra}>"
    if "format" in node:
        return f"{kind}:{node['format']}"
    return str(kind)


def _models(root: str, schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    nodes = {root: schema, **schema.get("$defs", {})}
    return {
        name: {
            field: {
                "type": _describe(prop),
                "required": field in node.get("required", []),
            }
            for field, prop in sorted(node.get("properties", {}).items())
        }
        for name, node in nodes.items()
        if "properties" in node
    }


def message_codes() -> list[str]:
    found: set[str] = set()
    for relative in _CODE_SOURCES:
        found.update(_CODE.findall((_APP / relative).read_text(encoding="utf-8")))
    return sorted(found)


def job_message_kinds() -> list[str]:
    """Kinds of structured notes a manifest apply writes onto its jobs."""
    source = Path(job_schemas.__file__).read_text(encoding="utf-8")
    return sorted(set(re.findall(r'kind: Literal\["(manifest_\w+)"\]', source)))


def build() -> dict[str, Any]:
    models = _models("ManifestApplyRequest", ManifestApplyRequest.model_json_schema())
    models |= _models(
        "ManifestApplyResponse", ManifestApplyResponse.model_json_schema()
    )
    return {
        "contract_version": 2,
        "models": dict(sorted(models.items())),
        "message_codes": message_codes(),
        "job_message_kinds": job_message_kinds(),
        # The server takes any non-empty single-line string as a loss kind; the
        # connector chooses the vocabulary.
        "loss_item_kind": models["ManifestLossItem"]["kind"],
    }


def render() -> str:
    return json.dumps(build(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    SNAPSHOT_PATH.write_text(render(), encoding="utf-8")
    print(f"wrote {SNAPSHOT_PATH}")
