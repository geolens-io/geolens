"""The migration state file never holds a credential: load masks one, save refuses one."""

from __future__ import annotations

import dataclasses
import json
import secrets

import pytest

from geolens_cli.arcgis_migrate_state import (
    DONE,
    ItemState,
    MigrationState,
    StateError,
)
from geolens_cli.arcgis_portal import Redactor

PORTAL = "https://example.test/portal"
INSTANCE = "https://geolens.example.test"
ITEM = "a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2"
SECRET = secrets.token_urlsafe(32)
# A credential the scrubber knows by its shape, registered or not.
SHAPED = f"https://example.org/data#access_token={secrets.token_urlsafe(24)}"
_SHAPED_SECRET = SHAPED.rsplit("=", 1)[1]


def _redactor() -> Redactor:
    redact = Redactor()
    redact.add(SECRET)
    return redact


def _holding(default, text: str):
    """A value of *default*'s shape that holds *text*, as a value and as a key."""
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


@pytest.mark.parametrize("text", [SECRET, SHAPED], ids=["registered", "shaped"])
@pytest.mark.parametrize("name", _ITEM_FIELDS)
def test_save_refuses_any_item_member_holding_a_credential(tmp_path, name, text):
    state = _state(tmp_path, _redactor())
    setattr(state.items[ITEM], name, _holding(getattr(state.items[ITEM], name), text))

    with pytest.raises(StateError) as refused:
        state.save()

    message = str(refused.value)
    assert f"item {ITEM}, field {name}," in message
    assert SECRET not in message and _SHAPED_SECRET not in message
    assert not state.path.exists()


@pytest.mark.parametrize("where", ["key", "nested"])
def test_save_refuses_a_credential_in_a_key_or_nested_value(tmp_path, where):
    state = _state(tmp_path, _redactor())
    entry = state.items[ITEM]
    if where == "key":
        entry.metadata_baseline = {f"dataset {SECRET}": {"title": "t"}}
    else:
        entry.metadata_baseline = {"d": {"keywords": ["ok", f"tag {SECRET}"]}}

    with pytest.raises(StateError, match="field metadata_baseline,"):
        state.save()


@pytest.mark.parametrize("member", ["collections", "groups", "cutover"])
def test_save_refuses_a_top_level_member_holding_a_credential(tmp_path, member):
    state = _state(tmp_path, _redactor())
    setattr(state, member, {"k": {"name": f"x {SECRET}"}})

    with pytest.raises(StateError, match=f"the state's {member} field"):
        state.save()

    assert not state.path.exists()


def test_a_state_without_credentials_saves(tmp_path):
    state = _state(tmp_path, _redactor())
    state.items[ITEM].notes = [state.clean(f"a note holding {SECRET} once")]
    state.items[ITEM].metadata_baseline = {"d": {"title": "Parcels"}}

    state.save()

    raw = state.path.read_text()
    assert "[REDACTED]" in raw and SECRET not in raw


def test_a_credential_an_earlier_version_wrote_is_masked_on_load(tmp_path):
    path = tmp_path / "state.json"
    entry = dataclasses.asdict(ItemState(status=DONE))
    entry["metadata_baseline"] = {"d": {"summary": f"see {SHAPED}"}}
    entry["last_update"] = {"d": {"source_url": SHAPED}}
    path.write_text(
        json.dumps(
            {
                "schema_version": "6",
                "portal_url": PORTAL,
                "geolens_instance": INSTANCE,
                "items": {ITEM: entry},
            }
        )
    )

    state = MigrationState.load(path, PORTAL, INSTANCE, _redactor())
    state.save()

    assert _SHAPED_SECRET not in path.read_text()
    assert state.items[ITEM].metadata_baseline["d"]["summary"].startswith("see ")
