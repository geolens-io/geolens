"""The migration state file never holds the run's credential: load masks it, save refuses it."""

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
    StateError,
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
def test_save_refuses_any_item_member_holding_the_runs_secret(tmp_path, name):
    state = _state(tmp_path, _redactor())
    setattr(state.items[ITEM], name, _holding(getattr(state.items[ITEM], name), SECRET))

    with pytest.raises(StateError) as refused:
        state.save()

    assert f"item {ITEM}, field {name}," in str(refused.value)
    assert SECRET not in str(refused.value)
    assert not state.path.exists()


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


@pytest.mark.parametrize("where", ["key", "nested"])
def test_save_refuses_the_runs_secret_in_a_key_or_nested_value(tmp_path, where):
    state = _state(tmp_path, _redactor())
    entry = state.items[ITEM]
    if where == "key":
        entry.metadata_baseline = {f"dataset {SECRET}": {"title": "t"}}
    else:
        entry.metadata_baseline = {"d": {"keywords": ["ok", f"tag {SECRET}"]}}

    with pytest.raises(StateError, match="field metadata_baseline,"):
        state.save()


@pytest.mark.parametrize("member", ["collections", "groups", "cutover"])
def test_save_refuses_a_top_level_member_holding_the_runs_secret(tmp_path, member):
    state = _state(tmp_path, _redactor())
    setattr(state, member, {"k": {"name": f"x {SECRET}"}})

    with pytest.raises(StateError, match=f"the state's {member} field"):
        state.save()

    assert not state.path.exists()


def test_a_note_cleaned_of_the_secret_saves(tmp_path):
    state = _state(tmp_path, _redactor())
    state.items[ITEM].notes = [state.clean(f"a note holding {SECRET} once")]

    state.save()

    raw = state.path.read_text()
    assert "[REDACTED]" in raw and SECRET not in raw


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
    state.save()

    saved = json.loads(path.read_text())
    assert SECRET not in path.read_text()
    assert saved["schema_version"] == STATE_VERSION
    assert saved["items"][ITEM]["metadata_baseline"]["d"]["summary"] == (
        "see [REDACTED]"
    )
    assert saved["items"][ITEM]["notes"] == SHAPED


def test_a_string_found_clean_is_checked_again_after_a_new_secret(tmp_path):
    redact = _redactor()
    state = _state(tmp_path, redact)
    later = secrets.token_urlsafe(16)
    state.items[ITEM].notes = [f"a note naming {later}"]
    state.save()

    redact.add(later)

    with pytest.raises(StateError, match="field notes,"):
        state.save()
    assert later in state.path.read_text()
    assert redact.version == 2


def test_names_that_differ_only_by_the_secret_refuse_to_load(tmp_path):
    path = tmp_path / "state.json"
    entry = dataclasses.asdict(ItemState(status=DONE))
    entry["layer_datasets"] = {f"layer {SECRET}": "a", "layer [REDACTED]": "b"}
    _write(path, entry)

    with pytest.raises(StateError) as refused:
        MigrationState.load(path, PORTAL, INSTANCE, _redactor())

    message = str(refused.value)
    assert f"item {ITEM}, field layer_datasets," in message
    assert SECRET not in message


def test_collection_names_that_differ_only_by_the_secret_refuse_to_load(tmp_path):
    path = tmp_path / "state.json"
    entry = dataclasses.asdict(ItemState(status=DONE))
    _write(path, entry, collections={f"Roads {SECRET}": "a", "Roads [REDACTED]": "b"})

    with pytest.raises(StateError, match="the state's collections field holds two"):
        MigrationState.load(path, PORTAL, INSTANCE, _redactor())
