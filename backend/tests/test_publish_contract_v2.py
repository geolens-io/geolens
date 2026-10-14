"""The publish manifest v2 schema accepts every valid example and rejects every invalid one."""

import base64
import copy
import io
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from PIL import Image

FIXTURES = Path(__file__).parent / "fixtures"
SCHEMA = json.loads((FIXTURES / "publish_manifest_v2.schema.json").read_text())
EXAMPLES = json.loads((FIXTURES / "publish_contract_v2.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA)


def _valid(name: str) -> dict:
    return next(e["manifest"] for e in EXAMPLES["valid"] if e["name"] == name)


def test_schema_is_a_valid_draft_2020_12_schema():
    Draft202012Validator.check_schema(SCHEMA)
    assert "Apache-2.0 OR MIT" in SCHEMA["$comment"]


@pytest.mark.parametrize("example", EXAMPLES["valid"], ids=lambda e: e["name"])
def test_valid_example_passes(example):
    errors = [e.message for e in VALIDATOR.iter_errors(example["manifest"])]
    assert errors == []


@pytest.mark.parametrize("example", EXAMPLES["invalid"], ids=lambda e: e["name"])
def test_invalid_example_is_rejected(example):
    assert example["breaks"]
    assert not VALIDATOR.is_valid(example["manifest"])


def _datasets(count: int) -> dict:
    manifest = copy.deepcopy(_valid("create"))
    base = manifest["datasets"][0]
    manifest["datasets"] = [{**base, "key": f"k{i}"} for i in range(count)]
    return manifest


def _attributes(count: int) -> dict:
    manifest = copy.deepcopy(_valid("create"))
    manifest["datasets"][0]["attributes"] = [
        {"source_name": f"c{i}"} for i in range(count)
    ]
    return manifest


def _thumbnail(payload_chars: int) -> dict:
    manifest = copy.deepcopy(_valid("create"))
    manifest["maps"][0]["thumbnail"] = "data:image/png;base64," + "A" * payload_chars
    return manifest


@pytest.mark.parametrize(
    ("build", "largest_valid", "smallest_invalid"),
    [
        (_datasets, 100, 101),
        (_attributes, 500, 501),
        # The prefix is 22 characters and the payload grows in groups of four,
        # so no thumbnail is exactly 100,000 characters long.
        (_thumbnail, 99_976, 99_980),
    ],
)
def test_size_limits_are_enforced(build, largest_valid, smallest_invalid):
    assert VALIDATOR.is_valid(build(largest_valid))
    assert not VALIDATOR.is_valid(build(smallest_invalid))


def test_a_jpeg_thumbnail_is_accepted():
    buffer = io.BytesIO()
    Image.new("RGB", (1, 1), (255, 255, 255)).save(buffer, "JPEG")
    payload = base64.b64encode(buffer.getvalue()).decode()
    Image.open(io.BytesIO(base64.b64decode(payload))).verify()
    manifest = copy.deepcopy(_valid("create"))
    manifest["maps"][0]["thumbnail"] = f"data:image/jpeg;base64,{payload}"
    assert VALIDATOR.is_valid(manifest)


def _layers(count: int) -> dict:
    manifest = copy.deepcopy(_valid("create"))
    layer = manifest["maps"][0]["layers"][0]
    manifest["maps"][0]["layers"] = [{**layer, "key": f"l{i}"} for i in range(count)]
    return manifest


def test_a_map_holds_at_most_200_layers():
    assert VALIDATOR.is_valid(_layers(200))
    assert not VALIDATOR.is_valid(_layers(201))


@pytest.mark.parametrize(
    ("path", "limit"),
    [
        (("maps", 0, "name"), 255),
        (("maps", 0, "description"), 2000),
        (("maps", 0, "basemap_style"), 2000),
        (("maps", 0, "layers", 0, "display_name"), 255),
    ],
)
def test_map_text_fields_stop_at_their_storage_limit(path, limit):
    manifest = copy.deepcopy(_valid("create"))
    target = manifest
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = "x" * limit
    assert VALIDATOR.is_valid(manifest)
    target[path[-1]] = "x" * (limit + 1)
    assert not VALIDATOR.is_valid(manifest)


def test_a_request_holds_at_most_100_maps():
    manifest = copy.deepcopy(_valid("create"))
    map_entry = manifest["maps"][0]
    manifest["maps"] = [{**map_entry, "key": f"m{i}"} for i in range(100)]
    assert VALIDATOR.is_valid(manifest)
    manifest["maps"].append({**map_entry, "key": "m100"})
    assert not VALIDATOR.is_valid(manifest)


@pytest.mark.parametrize(
    ("path", "limit"),
    [
        (("datasets", 0, "collection", "name"), 255),
        (("datasets", 0, "attributes", 0, "title"), 500),
        (("datasets", 0, "attributes", 0, "description"), 2000),
        (("datasets", 0, "attributes", 0, "units"), 50),
    ],
)
def test_dataset_text_fields_stop_at_their_storage_limit(path, limit):
    manifest = copy.deepcopy(_valid("create"))
    target = manifest
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = "x" * limit
    assert VALIDATOR.is_valid(manifest)
    target[path[-1]] = "x" * (limit + 1)
    assert not VALIDATOR.is_valid(manifest)


@pytest.mark.parametrize(
    ("path", "limit"),
    [
        (("catalog", "title"), 500),
        (("catalog", "description"), 5000),
        (("catalog", "organization"), 500),
        (("datasets", 0, "title"), 500),
        (("datasets", 0, "description"), 5000),
        (("datasets", 0, "metadata", "organization"), 500),
        (("datasets", 0, "metadata", "license"), 500),
        (("datasets", 0, "metadata", "attribution"), 5000),
        (("datasets", 0, "publication", "intent"), 20),
    ],
)
def test_catalog_and_dataset_text_fields_stop_at_their_limit(path, limit):
    manifest = copy.deepcopy(_valid("create"))
    target = manifest
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = "x" * limit
    assert VALIDATOR.is_valid(manifest)
    target[path[-1]] = "x" * (limit + 1)
    assert not VALIDATOR.is_valid(manifest)


@pytest.mark.parametrize(
    ("path", "low", "high"),
    [
        (("maps", 0, "view", "zoom"), 0, 24),
        (("maps", 0, "view", "pitch"), 0, 85),
        (("maps", 0, "view", "bearing"), -180, 180),
        (("maps", 0, "view", "center", 0), -180, 180),
        (("maps", 0, "view", "center", 1), -90, 90),
        (("maps", 0, "layers", 0, "opacity"), 0, 1),
        (("maps", 0, "layers", 0, "min_zoom"), 0, 24),
        (("maps", 0, "layers", 0, "max_zoom"), 0, 24),
        (("datasets", 0, "metadata", "bbox", 0), -180, 180),
        (("datasets", 0, "metadata", "bbox", 3), -180, 180),
    ],
)
def test_numeric_ranges_are_inclusive_and_bounded(path, low, high):
    def with_value(value):
        manifest = copy.deepcopy(_valid("create"))
        manifest["datasets"][0]["metadata"]["bbox"] = [-89.7, 39.7, -89.6, 39.8]
        target = manifest
        for step in path[:-1]:
            target = target[step]
        target[path[-1]] = value
        return manifest

    assert VALIDATOR.is_valid(with_value(low))
    assert VALIDATOR.is_valid(with_value(high))
    assert not VALIDATOR.is_valid(with_value(low - 0.5))
    assert not VALIDATOR.is_valid(with_value(high + 0.5))


@pytest.mark.parametrize(
    ("path", "size"),
    [(("maps", 0, "view", "center"), 2), (("datasets", 0, "metadata", "bbox"), 4)],
)
def test_coordinate_arrays_have_a_fixed_length(path, size):
    def with_length(length):
        manifest = copy.deepcopy(_valid("create"))
        manifest["datasets"][0]["metadata"]["bbox"] = [-89.7, 39.7, -89.6, 39.8]
        target = manifest
        for step in path[:-1]:
            target = target[step]
        target[path[-1]] = [1.0] * length
        return manifest

    assert VALIDATOR.is_valid(with_length(size))
    assert not VALIDATOR.is_valid(with_length(size - 1))
    assert not VALIDATOR.is_valid(with_length(size + 1))


def test_popup_visible_fields_hold_at_most_100_entries():
    def with_fields(count):
        manifest = copy.deepcopy(_valid("create"))
        popup = manifest["maps"][0]["layers"][0]["popup_config"]
        popup["visible_fields"] = [f"f{i}" for i in range(count)]
        return manifest

    assert VALIDATOR.is_valid(with_fields(100))
    assert not VALIDATOR.is_valid(with_fields(101))


_BOUNDS = ("maxLength", "minLength", "maxItems", "minItems", "minimum", "maximum")
# Bounded strings whose pattern fixes their shape, so a filler of "a" cannot
# sit at the limit. Their patterns have their own invalid examples.
MIN_BOUNDS = 89
MIN_REQUIRED = 27
_PATTERN_PINNED = {
    ("datasets", 0, "sources", 0, "checksum"),
    ("maps", 0, "thumbnail"),
}


def _walk(node, path=()):
    """Yield (instance path, bound name, limit) for every bound reachable from node."""
    ref = node.get("$ref")
    if ref:
        node = SCHEMA["$defs"][ref.rsplit("/", 1)[1]]
    for name in _BOUNDS:
        if name in node:
            yield path, name, node[name]
    for prop, child in node.get("properties", {}).items():
        yield from _walk(child, (*path, prop))
    for index, child in enumerate(node.get("prefixItems", [])):
        yield from _walk(child, (*path, index))
    if "items" in node:
        yield from _walk(node["items"], (*path, 0))
    for branch in node.get("oneOf", []):
        yield from _walk(branch, path)


def _full_example() -> dict:
    manifest = copy.deepcopy(_valid("create"))
    manifest["catalog"].update(description="d", organization="o")
    manifest["datasets"][0]["metadata"].update(
        organization="o", crs="EPSG:4326", bbox=[-89.7, 39.7, -89.6, 39.8]
    )
    return manifest


def _bound_cases() -> list[tuple[tuple, str, float]]:
    return [
        (path, name, limit)
        for path, name, limit in _walk(SCHEMA)
        if path and (path[0] in ("catalog", "client", "datasets", "maps"))
    ]


def _mutated(path, name, limit, at_limit):
    manifest = _full_example()
    target = manifest
    for step in path[:-1]:
        target = target[step]
    beyond = 1 if name.startswith("max") else -1
    if name in ("maxLength", "minLength"):
        value = "a" * (limit if at_limit else limit + beyond)
    elif name in ("maxItems", "minItems"):
        count = limit if at_limit else limit + beyond
        sample = target[path[-1]][0]
        target[path[-1]] = [
            f"v{i}" if isinstance(sample, str) else copy.deepcopy(sample)
            for i in range(count)
        ]
        return manifest
    else:
        value = limit if at_limit else limit + beyond / 2
    target[path[-1]] = value
    return manifest


def test_every_schema_bound_is_pinned():
    cases = _bound_cases()
    assert len(cases) >= MIN_BOUNDS
    unpinned = []
    for path, name, limit in cases:
        if path in _PATTERN_PINNED:
            continue
        if not VALIDATOR.is_valid(_mutated(path, name, limit, at_limit=True)):
            unpinned.append((path, name, "at limit rejected"))
        if VALIDATOR.is_valid(_mutated(path, name, limit, at_limit=False)):
            unpinned.append((path, name, "over limit accepted"))
    assert unpinned == []


def _required(node, path=()):
    ref = node.get("$ref")
    if ref:
        node = SCHEMA["$defs"][ref.rsplit("/", 1)[1]]
    for name in node.get("required", []):
        yield (*path, name)
    for prop, child in node.get("properties", {}).items():
        yield from _required(child, (*path, prop))
    if "items" in node:
        yield from _required(node["items"], (*path, 0))
    for branch in node.get("oneOf", []):
        yield from _required(branch, path)


def _without(path):
    manifest = _full_example()
    target = manifest
    for step in path[:-1]:
        if step not in target if isinstance(step, str) else step >= len(target):
            return None
        target = target[step]
    if path[-1] not in target:
        return None
    del target[path[-1]]
    return manifest


def test_every_required_member_is_required():
    omitted = [(path, _without(path)) for path in _required(SCHEMA)]
    reachable = [(path, m) for path, m in omitted if m is not None]
    assert len(reachable) >= MIN_REQUIRED
    accepted = [path for path, m in reachable if VALIDATOR.is_valid(m)]
    assert accepted == []
