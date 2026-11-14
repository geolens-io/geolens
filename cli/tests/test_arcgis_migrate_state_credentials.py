"""The migration state file never holds the run's credential: every load and save masks it."""

from __future__ import annotations

import dataclasses
import json
import secrets

import pytest

from geolens_cli.arcgis_migrate_state import (
    DONE,
    STATE_VERSION,
    ItemState,
    MigrationState,
)
from geolens_cli.arcgis_portal import Redactor

PORTAL = "https://example.test/portal"
INSTANCE = "https://geolens.example.test"
ITEM = "a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2"
SECRET = secrets.token_urlsafe(32)
# Shaped like credentials, but none is the run's.
SHAPED = [
    f"https://example.org/data?access_token={secrets.token_hex(12)}&sig=ZmFrZQ",
    "Authorization: Bearer abcdefghijklmnop",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJl",
]


def _redactor() -> Redactor:
    redact = Redactor()
    redact.add(SECRET)
    return redact


def _holding(default, text: str):
    """A value of *default*'s shape that holds *text*."""
    if isinstance(default, list):
        return [f"x {text}"]
    if isinstance(default, dict):
        return {"k": f"x {text}"}
    return f"x {text}"


_ITEM_FIELDS = [
    f.name
    for f in dataclasses.fields(ItemState)
    if not isinstance(getattr(ItemState(), f.name), bool)
]


def _state(tmp_path, redact: Redactor) -> MigrationState:
    state = MigrationState(tmp_path / "state.json", PORTAL, INSTANCE, redact)
    state.items[ITEM] = ItemState(status=DONE)
    return state


@pytest.mark.parametrize("name", _ITEM_FIELDS)
def test_save_masks_any_item_member_holding_the_runs_secret(tmp_path, name):
    state = _state(tmp_path, _redactor())
    setattr(state.items[ITEM], name, _holding(getattr(state.items[ITEM], name), SECRET))

    state.save()

    raw = state.path.read_text()
    assert SECRET not in raw
    assert "x [REDACTED]" in str(json.loads(raw)["items"][ITEM][name])
    # Later comparisons see what the file holds.
    assert "x [REDACTED]" in str(getattr(state.items[ITEM], name))


@pytest.mark.parametrize("name", _ITEM_FIELDS)
def test_save_writes_credential_shaped_text_that_is_not_the_runs(tmp_path, name):
    state = _state(tmp_path, _redactor())
    shaped = " ".join(SHAPED)
    setattr(state.items[ITEM], name, _holding(getattr(state.items[ITEM], name), shaped))

    state.save()

    saved = json.loads(state.path.read_text())["items"][ITEM][name]
    assert shaped in str(saved)


def test_save_writes_a_credential_named_key_with_a_value_that_is_not_the_runs(
    tmp_path,
):
    state = _state(tmp_path, _redactor())
    state.items[ITEM].layer_styles = {"0": {"paint": {"apiKey": "x"}}}

    state.save()

    saved = json.loads(state.path.read_text())["items"][ITEM]
    assert saved["layer_styles"] == {"0": {"paint": {"apiKey": "x"}}}


def test_save_masks_the_runs_secret_in_keys_and_top_level_members(tmp_path):
    state = _state(tmp_path, _redactor())
    shared = {f"Roads {SECRET}": "c1"}
    state.collections = shared
    state.groups = {"g1": {"name": f"Planners {SECRET}", "id": "g"}}
    state.cutover = {"accepted": [f"x {SECRET}"]}
    state.items[ITEM].metadata_baseline = {f"dataset {SECRET}": {"title": "t"}}

    state.save()

    saved = json.loads(state.path.read_text())
    assert SECRET not in state.path.read_text()
    assert saved["collections"] == {"Roads [REDACTED]": "c1"}
    assert saved["groups"]["g1"]["name"] == "Planners [REDACTED]"
    assert saved["items"][ITEM]["metadata_baseline"] == {
        "dataset [REDACTED]": {"title": "t"}
    }
    # Masked in place: whoever holds the same dict sees the masked key.
    assert shared == {"Roads [REDACTED]": "c1"}


def test_a_fan_out_checkpoint_keeps_its_jobs_when_its_error_echoes_the_secret(
    tmp_path,
):
    state = _state(tmp_path, _redactor())
    entry = state.items[ITEM]
    entry.fan_out = {"job": "j0", "layers": ["Roads"], "titles": ["Roads"]}
    entry.layer_jobs = {"layer:Roads": "j1"}
    entry.job_ids = ["j0"]
    entry.error = f"commit failed, HTTP 400: bad token {SECRET}"

    state.save()

    saved = json.loads(state.path.read_text())["items"][ITEM]
    assert saved["fan_out"]["job"] == "j0"
    assert saved["layer_jobs"] == {"layer:Roads": "j1"}
    assert saved["job_ids"] == ["j0"]
    assert saved["error"] == "commit failed, HTTP 400: bad token [REDACTED]"


def test_relationship_records_holding_the_secret_are_saved_masked(tmp_path):
    state = _state(tmp_path, _redactor())
    state.items[ITEM].relationships = {
        "0": [{"id": 1, "name": f"Parcels_{SECRET}", "related": "1"}]
    }

    state.save()

    saved = json.loads(state.path.read_text())["items"][ITEM]["relationships"]
    assert saved == {"0": [{"id": 1, "name": "Parcels_[REDACTED]", "related": "1"}]}


def _write(path, entry: dict, **top) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": STATE_VERSION,
                "portal_url": PORTAL,
                "geolens_instance": INSTANCE,
                "items": {ITEM: entry},
                **top,
            }
        )
    )


def test_the_runs_secret_an_earlier_version_wrote_is_masked_on_load(tmp_path):
    path = tmp_path / "state.json"
    entry = dataclasses.asdict(ItemState(status=DONE))
    entry["metadata_baseline"] = {"d": {"summary": f"see {SECRET}"}}
    entry["layer_styles"] = {"0": json.dumps({"label": f"x {SECRET}"})}
    entry["notes"] = list(SHAPED)
    _write(path, entry)

    state = MigrationState.load(path, PORTAL, INSTANCE, _redactor())

    assert state.items[ITEM].metadata_baseline["d"]["summary"] == "see [REDACTED]"
    state.save()
    saved = json.loads(path.read_text())
    assert SECRET not in path.read_text()
    assert saved["schema_version"] == STATE_VERSION
    assert saved["items"][ITEM]["notes"] == SHAPED


def test_a_password_registered_after_load_is_masked_by_the_next_save(tmp_path):
    path = tmp_path / "state.json"
    password = secrets.token_urlsafe(16)
    entry = dataclasses.asdict(ItemState(status=DONE))
    entry["notes"] = [f"echoed {password}"]
    _write(path, entry)
    redact = _redactor()
    state = MigrationState.load(path, PORTAL, INSTANCE, redact)
    state.save()
    assert password in path.read_text()

    redact.add(password)
    state.save()

    assert password not in path.read_text()
    assert state.items[ITEM].notes == ["echoed [REDACTED]"]
    assert redact.version == 2


def test_names_masking_would_merge_leave_one_out_and_keep_the_rest(tmp_path):
    path = tmp_path / "state.json"
    entry = dataclasses.asdict(ItemState(status=DONE))
    entry["layer_datasets"] = {f"layer {SECRET}": "a", "layer [REDACTED]": "b"}
    entry["dataset_ids"] = ["a", "b"]
    _write(path, entry, collections={f"Roads {SECRET}": "c", "Roads [REDACTED]": "d"})

    state = MigrationState.load(path, PORTAL, INSTANCE, _redactor())
    state.save()

    saved = json.loads(path.read_text())
    assert SECRET not in path.read_text()
    assert saved["items"][ITEM]["layer_datasets"] == {"layer [REDACTED]": "b"}
    assert saved["items"][ITEM]["dataset_ids"] == ["a", "b"]
    assert saved["collections"] == {"Roads [REDACTED]": "d"}
    assert sorted(state.left_out) == [
        f"item {ITEM}, member layer_datasets has two entries whose names differ "
        "only by this run's ArcGIS credential; one was left out of the state file",
        "the state's collections has two entries whose names differ only by "
        "this run's ArcGIS credential; one was left out of the state file",
    ]
    assert all(SECRET not in note for note in state.left_out)
