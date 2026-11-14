"""`geolens arcgis migrate` sends no credential the run was given to GeoLens or the state file."""

# Imported fixtures are used as test arguments, which F811 reads as redefinition.
# ruff: noqa: F811

from __future__ import annotations

import ast
import importlib
import inspect
import json
import re
import secrets
import time
import unicodedata
import uuid
from pathlib import Path
from urllib.parse import quote, quote_plus

import pytest

from geolens_cli import arcgis_migrate as migrate_mod
from geolens_cli import arcgis_oauth as oauth_mod
from geolens_cli import publish as publish_mod
from geolens_cli import replace as replace_mod
from geolens_cli.arcgis_migrate_session import CredentialRefused, GeoLens, GeoLensError
from geolens_cli.arcgis_portal import Redactor, holds_secret

from . import test_arcgis_migrate_collections as collections
from . import test_arcgis_migrate_files as files
from . import test_arcgis_migrate_groups as groups
from . import test_arcgis_migrate_layers as layers
from . import test_arcgis_migrate_refresh as refresh
from . import test_arcgis_migrate_report as report_tests
from . import test_arcgis_migrate_webmaps as webmaps
from .arcgis_fake import A1, A2, B1, D3, FakePortal, load, portal_routes
from .test_arcgis_migrate_layers import (  # noqa: F401  (fixtures)
    FakeImport,
    _layer,
    _migrate,
    _write_plan,
    geolens,
    plan_file,
    quick,
)
from .test_arcgis_migrate_files import portal, private_tempdir  # noqa: F401
from .test_arcgis_migrate_groups import team  # noqa: F401

TOKEN = "Tk" + secrets.token_hex(12)
PARCELS = layers.dataset_id("Parcels")
WRITES = ("POST", "PUT", "PATCH", "DELETE")
# Shaped like credentials, but none is the run's: the portal's own text.
PATTERNS = (
    "see https://example.test/f?token=abc123&sig=ZmFrZQ Bearer abcdefghijklmnop "
    'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJl {"apiKey": "x"}'
)


def _refused(path: str, key: str) -> str:
    return (
        f"the request to {path} holds this run's ArcGIS credential in {key}, "
        "so it wasn't sent"
    )


def _reason(*fields: str) -> str:
    shown = ", ".join(fields)
    return f"the item's {shown} holds this run's ArcGIS credential, so it isn't written"


def _sent(geolens, since: int = 0) -> list:
    return geolens.seen[since:]


def _state_text(plan_file: Path) -> str:
    path = plan_file.parent / "arcgis-migration-state.json"
    return path.read_text() if path.exists() else ""


def _body(seen) -> bytes:
    """The request body without the ``auth`` a private service import carries
    the token in by design."""
    try:
        body = json.loads(seen.body)
    except ValueError:
        return seen.body
    if isinstance(body, dict):
        body.pop("auth", None)
    return json.dumps(body).encode()


def _assert_kept_out(geolens, plan_file: Path, token: str = TOKEN) -> None:
    for seen in geolens.seen:
        assert token not in seen.url
        assert token.encode() not in _body(seen)
    assert token not in _state_text(plan_file)


def _with_token(runner, plan_file: Path, *args: str):
    return _migrate(runner, plan_file, *args, f"--token={TOKEN}")


def _edit_plan_item(plan_file: Path, item_id: str, edit) -> None:
    plan = json.loads(plan_file.read_text())
    for item in plan["items"]:
        if item["id"] == item_id:
            edit(item)
    plan_file.write_text(json.dumps(plan))


def _edit_inventory(plan_file: Path, edit) -> None:
    path = plan_file.parent / "arcgis-inventory.json"
    inventory = json.loads(path.read_text())
    edit(inventory)
    path.write_text(json.dumps(inventory))


def _edit_row(plan_file: Path, item_id: str, **changes) -> None:
    def edit(inventory):
        for row in inventory["items"]:
            if row["id"] == item_id:
                row.update(changes)

    _edit_inventory(plan_file, edit)


# What a match is


@pytest.mark.parametrize(
    "value",
    [
        f"see {TOKEN}",
        {"layers": [{"name": f"x {TOKEN}"}]},
        {f"key {TOKEN}": 1},
    ],
    ids=["text", "nested-value", "key"],
)
def test_a_registered_secret_is_found_in_text_and_documents(value):
    redact = Redactor()
    redact.add(TOKEN)

    assert holds_secret(value, redact)


@pytest.mark.parametrize("typed,stored", [("NFD", "NFC"), ("NFC", "NFD")])
def test_a_secret_matches_in_either_unicode_form(typed, stored):
    secret = "Caf\u00e9-" + secrets.token_hex(8)
    redact = Redactor()
    redact.add(unicodedata.normalize(typed, secret))

    assert holds_secret(unicodedata.normalize(stored, secret), redact)


@pytest.mark.parametrize("encode", [quote, quote_plus])
def test_a_secret_matches_in_the_encodings_it_is_masked_in(encode):
    secret = "pa ss/w&rd-" + secrets.token_hex(8)
    redact = Redactor()
    redact.add(secret)

    assert holds_secret(f"https://example.test/?p={encode(secret, safe='')}", redact)


def test_text_shaped_like_a_credential_is_not_one_of_the_runs():
    redact = Redactor()
    redact.add(TOKEN)

    assert not holds_secret(PATTERNS, redact)
    assert not holds_secret({"apiKey": "x", "notes": ["token=abc123"]}, redact)


# Service import


def _refused_service(runner, tmp_path, geolens, case: str):
    title = f"Parcels {TOKEN}" if case == "title" else "Parcels"
    layer = f"Parcels {TOKEN}" if case == "layer_name" else "Parcels"
    url = None
    if case == "service_url":
        url = {A2: f"https://services1.arcgis.com/x/FeatureServer?token={TOKEN}"}
    plan_file = _write_plan(tmp_path, urls=url, rows={A2: {"title": title}})
    service = FakeImport(geolens, [_layer(0, layer), _layer(1, "Owners", "Table")])
    return plan_file, service


@pytest.mark.parametrize(
    "case,error",
    [
        ("title", _reason("title")),
        ("layer_name", _reason("title", "layer name")),
        ("service_url", _refused("/services/probe/", "body.url")),
    ],
)
def test_a_service_item_holding_the_token_stops_before_any_write(
    runner, tmp_path, geolens, case, error
):
    plan_file, service = _refused_service(runner, tmp_path, geolens, case)

    result, payload = _with_token(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    [item] = payload["items"]
    assert item["status"] == "failed" and item["error"] == error
    assert service.previews == 0
    assert not [s for s in geolens.seen if s.method in WRITES and "probe" not in s.url]
    _assert_kept_out(geolens, plan_file)


def test_a_resumed_service_import_checks_the_title_before_its_patch(
    runner, plan_file, geolens
):
    FakeImport(geolens, [_layer(0, "Parcels")])
    assert _with_token(runner, plan_file, "--only", A2)[0].exit_code == 0
    # A dataset not yet handed over gets the plan's title again on resume.
    refresh._edit_state(plan_file, A2, status="failed", last_update={})
    _edit_plan_item(
        plan_file, A2, lambda item: item["target"].update(title=f"Parcels {TOKEN}")
    )
    before = len(geolens.seen)

    result, payload = _with_token(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert payload["items"][0]["error"] == _refused(
        f"/datasets/{PARCELS}", "body.title"
    )
    assert not [s for s in _sent(geolens, before) if s.method in WRITES]
    _assert_kept_out(geolens, plan_file)


def test_a_refresh_probes_no_service_url_holding_the_token(runner, plan_file, geolens):
    service = refresh._migrated(runner, plan_file, geolens)
    refresh.FakeRefresh(geolens, service).allow(PARCELS)
    # A state file from before the URL was recorded holds none.
    refresh._edit_state(plan_file, A2, service_url=None)
    url = f"{refresh._service_url(plan_file, A2)}?token={TOKEN}"
    _edit_row(plan_file, A2, url=url)
    before = len(geolens.seen)

    result, payload = _with_token(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert payload["not_up_to_date"][A2] == [_refused("/services/probe/", "body.url")]
    assert not [s for s in _sent(geolens, before) if "probe" in s.url]
    _assert_kept_out(geolens, plan_file)


# File import


@pytest.mark.parametrize(
    "case,field", [("title", "title"), ("layer_name", "title, layer name")]
)
def test_a_file_item_holding_the_token_sends_no_title_or_layer_holding_it(
    runner, tmp_path, geolens, portal, case, field
):
    title = f"Inspections {TOKEN}" if case == "title" else "Inspections"
    plan_file = files._plan(tmp_path, title=title)
    names = [f"Roads {TOKEN}", "Parcels"] if case == "layer_name" else None
    fake = files.FakeFiles(geolens, layer_names=names)

    result, payload = _with_token(runner, plan_file, "--only", D3)

    assert result.exit_code == 1
    assert payload["items"][0]["error"] == _reason(field)
    assert not fake.commits and not fake.fan_outs
    if case == "title":
        # The upload's file name is made from the title, so nothing is uploaded.
        assert not fake.uploads
    _assert_kept_out(geolens, plan_file)


def test_a_file_replacement_holding_the_token_in_its_name_is_not_uploaded(
    runner, tmp_path, geolens, portal
):
    plan_file = files._plan(tmp_path)
    fake = files.FakeFiles(geolens)
    assert _with_token(runner, plan_file, "--only", D3)[0].exit_code == 0
    uploads = len(fake.uploads)
    _edit_plan_item(plan_file, D3, lambda item: item.update(title=f"Insp {TOKEN}"))

    result, payload = _with_token(runner, plan_file, "--only", D3)

    assert result.exit_code == 1
    assert payload["not_up_to_date"][D3] == [_reason("title")]
    assert len(fake.uploads) == uploads
    _assert_kept_out(geolens, plan_file)


# Web map import


def _webmap_with_renderer() -> dict:
    webmap = load("item_web_map_data.json")
    webmap["operationalLayers"][0]["layerDefinition"] = {
        "drawingInfo": {
            "renderer": {
                "type": "simple",
                "label": f"Parcels {TOKEN}",
                "symbol": {"type": "esriSFS", "color": [0, 92, 230, 255]},
            }
        }
    }
    return webmap


def _item(payload: dict, item_id: str) -> dict:
    return next(item for item in payload["items"] if item["id"] == item_id)


@pytest.mark.parametrize("case", ["title", "target"])
def test_a_web_map_titled_with_the_token_is_not_imported(
    runner, tmp_path, geolens, portal, case
):
    plan_file = _write_plan(
        tmp_path, rows={B1: {"title": f"Map {TOKEN}"}} if case == "title" else None
    )
    if case == "target":
        _edit_plan_item(
            plan_file, B1, lambda item: item["target"].update(title=f"Map {TOKEN}")
        )
    webmaps._services(geolens)
    geolens.routes[webmaps.IMPORT] = (201, webmaps._response())

    result, payload = _with_token(runner, plan_file, "--only", B1)

    assert result.exit_code == 1
    assert _item(payload, B1)["error"] in (
        _refused("/maps/import/arcgis-webmap/", "body.name"),
        _refused("/maps/import/arcgis-webmap/", "body.title"),
    )
    assert webmaps._sent(geolens) == []
    _assert_kept_out(geolens, plan_file)


def test_a_renderer_holding_the_token_reaches_neither_geolens_nor_the_state(
    runner, plan_file, geolens, portal
):
    portal.routes[f"content/items/{B1}/data"] = _webmap_with_renderer()
    webmaps._services(geolens)
    geolens.routes[webmaps.IMPORT] = (201, webmaps._response())

    result, payload = _with_token(runner, plan_file, "--only", B1)

    assert result.exit_code == 0, result.output
    [sent] = webmaps._sent(geolens)
    layer = sent.json()["webmap"]["operationalLayers"][0]
    assert layer["layerDefinition"]["drawingInfo"]["renderer"]["label"] == (
        "Parcels [REDACTED]"
    )
    _assert_kept_out(geolens, plan_file)


# Rerun of a migrated dataset


def _set_portal_name(name: str):
    def edit(inventory):
        inventory["portal"]["name"] = name

    return edit


@pytest.mark.parametrize(
    "field,edit",
    [
        ("summary", lambda p: _edit_row(p, A2, snippet=f"Now {TOKEN}")),
        ("summary", lambda p: _edit_row(p, A2, description=f"<p>{TOKEN}</p>")),
        ("attribution", lambda p: _edit_row(p, A2, access_information=TOKEN)),
        ("license", lambda p: _edit_row(p, A2, license_info=f"<b>{TOKEN}</b>")),
        (
            "source organization",
            lambda p: _edit_inventory(p, _set_portal_name(f"County {TOKEN}")),
        ),
        (
            "tags",
            lambda p: _edit_plan_item(
                p, A2, lambda item: item["target"]["tags"].append(TOKEN.upper())
            ),
        ),
        (
            "title",
            lambda p: _edit_plan_item(
                p, A2, lambda item: item["target"].update(title=f"Parcels {TOKEN}")
            ),
        ),
    ],
    ids=[
        "snippet",
        "description",
        "attribution",
        "license",
        "organization",
        "tag-lowercased",
        "title",
    ],
)
def test_a_rerun_of_an_unchanged_dataset_writes_no_metadata_holding_the_token(
    runner, plan_file, geolens, field, edit
):
    service = refresh._migrated(runner, plan_file, geolens)
    refresh.FakeRefresh(geolens, service).allow(PARCELS)
    edit(plan_file)
    before = len(geolens.seen)
    # A tag is lowercased as it is sent; the token is registered as given.
    token = TOKEN.lower() if field == "tags" else TOKEN

    result, payload = _migrate(runner, plan_file, "--only", A2, f"--token={token}")

    assert result.exit_code == 1
    assert payload["not_up_to_date"][A2] == [f"dataset {PARCELS}: {_reason(field)}"]
    assert not [
        s for s in _sent(geolens, before) if s.method == "PATCH" or "/keywords" in s.url
    ]
    _assert_kept_out(geolens, plan_file, token)


# Collections and groups


def test_a_collection_named_with_the_token_is_not_created(runner, tmp_path, geolens):
    collections._services(geolens)
    made = collections.FakeCollections(geolens)
    plan_file = collections._plan(
        tmp_path,
        lambda plan: [
            item["target"].update(collections=[f"Folder {TOKEN}"])
            for item in plan["items"]
        ],
    )

    result, payload = _with_token(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert payload["items"][0]["error"] == _reason("collection")
    assert made.names == {}
    _assert_kept_out(geolens, plan_file)


def test_a_group_titled_with_the_token_is_not_created(runner, tmp_path, team):
    service = groups._service(team)
    api = groups.GroupsApi(team, service, existing=[])
    plan_file = groups._write(tmp_path, members=["agol_bob"])

    def retitle(inventory):
        inventory["groups"][0]["title"] = f"Planners {TOKEN}"

    _edit_inventory(plan_file, retitle)

    result, _ = _with_token(runner, plan_file, "--only", A2)

    assert result.exit_code == 2
    assert _refused("/admin/groups/", "body.name") in result.output
    assert TOKEN not in result.output
    assert api.groups == []
    _assert_kept_out(team, plan_file)


# Text shaped like a credential that isn't the run's is copied as before


def _state(plan_file: Path) -> dict:
    return json.loads(_state_text(plan_file))


@pytest.mark.parametrize("case", ["title", "layer_name"])
def test_a_service_item_with_credential_shaped_text_is_imported_as_is(
    runner, tmp_path, geolens, case
):
    plan_file = _write_plan(
        tmp_path, rows={A2: {"title": PATTERNS if case == "title" else "Parcels"}}
    )
    layer = PATTERNS if case == "layer_name" else "Parcels"
    service = FakeImport(geolens, [_layer(0, layer)])

    result, _ = _with_token(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    [preview] = service.bodies("POST /services/preview/")
    [commit] = service.bodies("POST /ingest/commit/")
    assert preview["layer_name"] == layer
    assert commit["title"] == (PATTERNS if case == "title" else "Parcels")
    assert _state(plan_file)["items"][A2]["status"] == "done"


def test_a_rerun_writes_a_credential_shaped_description_and_tag_as_is(
    runner, plan_file, geolens
):
    service = refresh._migrated(runner, plan_file, geolens)
    refresh.FakeRefresh(geolens, service).allow(PARCELS)
    _edit_row(plan_file, A2, snippet=PATTERNS)
    _edit_plan_item(plan_file, A2, lambda item: item["target"]["tags"].append(PATTERNS))

    result, _ = _with_token(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert service.summaries[PARCELS].startswith(PATTERNS)
    assert PATTERNS.lower() in service.keywords[PARCELS]
    baseline = _state(plan_file)["items"][A2]["metadata_baseline"][PARCELS]
    assert baseline["summary"].startswith(PATTERNS)
    assert PATTERNS.lower() in baseline["keywords"]


def test_a_web_map_with_a_credential_shaped_title_is_imported_as_is(
    runner, tmp_path, geolens, portal
):
    plan_file = _write_plan(tmp_path, rows={B1: {"title": PATTERNS}})
    webmaps._services(geolens)
    geolens.routes[webmaps.IMPORT] = (201, webmaps._response())

    result, _ = _with_token(runner, plan_file, "--only", B1)

    assert result.exit_code == 0, result.output
    [sent] = webmaps._sent(geolens)
    assert sent.json()["name"] == sent.json()["title"] == PATTERNS


def test_a_collection_with_a_credential_shaped_name_is_created_as_is(
    runner, tmp_path, geolens
):
    collections._services(geolens)
    made = collections.FakeCollections(geolens)
    plan_file = collections._plan(
        tmp_path,
        lambda plan: [
            item["target"].update(collections=[PATTERNS]) for item in plan["items"]
        ],
    )

    result, _ = _with_token(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert list(made.names.values()) == [PATTERNS]
    assert PATTERNS in _state(plan_file)["collections"]


def test_a_group_with_a_credential_shaped_title_is_created_as_is(
    runner, tmp_path, team
):
    service = groups._service(team)
    api = groups.GroupsApi(team, service, existing=[])
    plan_file = groups._write(tmp_path, members=["agol_bob"])

    def retitle(inventory):
        inventory["groups"][0]["title"] = PATTERNS

    _edit_inventory(plan_file, retitle)

    result, _ = _with_token(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert [g["name"] for g in api.groups] == [PATTERNS]
    assert _state(plan_file)["groups"]["g1"]["name"] == PATTERNS


# Credentials the run is given


def test_a_token_from_stdin_is_registered_though_no_item_needs_it(
    runner, tmp_path, geolens
):
    plan_file = _write_plan(tmp_path, rows={A2: {"title": f"Parcels {TOKEN}"}})
    FakeImport(geolens, [_layer(0, "Parcels")])

    result = runner.invoke(
        layers.app,
        ["--json", "arcgis", "migrate", str(plan_file), "--only", A2, "--token-stdin"],
        input=f"{TOKEN}\n",
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout)["items"][0]["error"] == _reason("title")
    _assert_kept_out(geolens, plan_file)


def test_an_empty_stdin_token_is_refused_as_before(runner, tmp_path, geolens):
    plan_file = _write_plan(tmp_path)
    FakeImport(geolens, [_layer(0, "Parcels")])

    result = runner.invoke(
        layers.app,
        ["arcgis", "migrate", str(plan_file), "--only", "a1" * 16, "--token-stdin"],
        input="\n",
    )

    assert result.exit_code == 2
    assert "--token-stdin read an empty line" in result.output


def test_a_state_file_holding_the_token_loads_masked_and_the_run_goes_on(
    runner, plan_file, geolens
):
    service = refresh._migrated(runner, plan_file, geolens)
    refresh.FakeRefresh(geolens, service).allow(PARCELS)
    path = plan_file.parent / "arcgis-migration-state.json"
    state = json.loads(path.read_text())
    state["items"][A2]["notes"].append(f"written by an earlier version: {TOKEN}")
    path.write_text(json.dumps(state))

    result, _ = _with_token(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert "written by an earlier version: [REDACTED]" in _state_text(plan_file)
    _assert_kept_out(geolens, plan_file)


# Every request the migrate flow sends


INSTANCE = "https://geolens.example.org/api"
PACKAGE = Path(migrate_mod.__file__).parent


def _migrate_requests() -> list[str]:
    """Every SDK request module the migrate flow imports."""
    found = set()
    sources = [*PACKAGE.glob("arcgis_migrate*.py"), PACKAGE / "arcgis_item_metadata.py"]
    for path in sources:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "geolens.api."
            ):
                found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return sorted(found)


class _Planted:
    """A request body with the token in a field no call site knows of."""

    def to_dict(self) -> dict:
        return {"unchecked": {"nested": [f"x {TOKEN}"]}}


def _session(fake_geolens) -> GeoLens:
    from geolens_cli._sdk_helpers import make_client

    redact = Redactor()
    redact.add(TOKEN)
    sdk = make_client(INSTANCE, bearer_token=fake_geolens.token, provenance="env")
    return GeoLens(sdk, INSTANCE, redact)


def _planted_kwargs(fn) -> dict | None:
    """Arguments for *fn* with the token in its body or each text parameter,
    None when it takes no text at all."""
    kwargs, planted = {}, False
    for name, param in inspect.signature(fn).parameters.items():
        kind = str(param.annotation)
        if name == "client":
            continue
        if name == "body":
            kwargs[name], planted = _Planted(), True
        elif "str" in kind:
            kwargs[name], planted = f"x {TOKEN}", True
        elif "UUID" in kind:
            kwargs[name] = uuid.uuid4()
        elif "int" in kind or "float" in kind:
            kwargs[name] = 1
        elif "bool" in kind:
            kwargs[name] = False
    return kwargs if planted else None


@pytest.mark.parametrize("module", _migrate_requests())
def test_no_request_the_migrate_flow_sends_carries_the_token(fake_geolens, module):
    fn = importlib.import_module(module).sync_detailed
    kwargs = _planted_kwargs(fn)
    session = _session(fake_geolens)

    if kwargs is None:
        # Ids and numbers only: no portal text can ride on this request.
        params = inspect.signature(fn).parameters.values()
        assert not [p for p in params if "str" in str(p.annotation)]
        return
    with pytest.raises(CredentialRefused, match="holds this run's ArcGIS credential"):
        session.call(fn, **kwargs)

    assert fake_geolens.seen == []


@pytest.mark.parametrize("upload", [publish_mod.upload_file, replace_mod.upload_file])
def test_an_upload_named_with_the_token_is_not_sent(fake_geolens, tmp_path, upload):
    path = tmp_path / f"{TOKEN}.csv"
    path.write_bytes(b"a,b\n1,2\n")
    kwargs = {"path": path}
    if upload is replace_mod.upload_file:
        kwargs["dataset_id"] = uuid.uuid4()

    with pytest.raises(CredentialRefused, match=" in path, "):
        _session(fake_geolens).call(upload, **kwargs)

    assert fake_geolens.seen == []


def test_the_requests_own_credentials_are_still_sent(fake_geolens):
    from geolens.api.admin import create_user_admin_users_post as create
    from geolens.api.datasets import probe_service_url_services_probe_post as probe
    from geolens.models.admin_user_create import AdminUserCreate
    from geolens.models.probe_request import ProbeRequest
    from geolens.models.service_auth_request import ServiceAuthRequest

    session = _session(fake_geolens)
    auth = ServiceAuthRequest(method="bearer", token=TOKEN)
    user = AdminUserCreate(username="new", password=TOKEN, role="viewer")

    for call in (
        lambda: session.call(
            probe.sync_detailed,
            body=ProbeRequest(url="https://x.example.test/", auth=auth),
        ),
        lambda: session.call(create.sync_detailed, body=user, sends=("body.password",)),
    ):
        with pytest.raises(GeoLensError):
            call()

    probed, created = fake_geolens.seen
    assert probed.json()["auth"]["token"] == TOKEN
    assert created.json()["password"] == TOKEN
    assert created.headers["authorization"] == f"Bearer {fake_geolens.token}"


def test_a_field_no_call_site_checks_fails_the_item_before_it_is_sent(
    runner, plan_file, geolens
):
    service = FakeImport(geolens, [_layer(0, "Parcels", object_id_field=f"OID{TOKEN}")])

    result, payload = _with_token(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert payload["items"][0]["error"] == _refused(
        "/services/preview/", "body.object_id_field"
    )
    assert service.previews == 0
    _assert_kept_out(geolens, plan_file)


# Percent-escapes in either case

ESCAPED = "pa/ss wörd-" + secrets.token_hex(6)


def _escapes() -> list[str]:
    canonical = quote(ESCAPED, safe="")
    lower = re.sub(r"%[0-9A-F]{2}", lambda m: m.group(0).lower(), canonical)
    mixed = re.sub(
        r"%([0-9A-F])([0-9A-F])", lambda m: f"%{m[1].lower()}{m[2]}", canonical
    )
    return [canonical, lower, mixed]


def _escaped_redactor() -> Redactor:
    redact = Redactor()
    redact.add(ESCAPED)
    return redact


@pytest.mark.parametrize("text", _escapes(), ids=["canonical", "lower", "mixed"])
def test_an_escaped_secret_is_found_and_masked_in_either_case(
    fake_geolens, tmp_path, text
):
    from geolens.api.admin import create_group_admin_groups_post as create
    from geolens.models.group_write import GroupWrite

    from geolens_cli.arcgis_migrate_report import build_run_report, write_run_report
    from geolens_cli.arcgis_migrate_state import ItemState, MigrationState

    redact = _escaped_redactor()
    session = _session(fake_geolens)
    session._redact = redact
    with pytest.raises(CredentialRefused):
        session.call(create.sync_detailed, body=GroupWrite(name=f"see {text}"))
    assert fake_geolens.seen == []

    state = MigrationState(tmp_path / "state.json", "p", "i", redact)
    state.items["a"] = ItemState(notes=[f"see {text}"])
    state.save()
    assert state.items["a"].notes == ["see [REDACTED]"]
    assert text not in state.path.read_text()

    plan = report_tests._plan(tmp_path)
    reported = report_tests._state(tmp_path, redact)
    # Past the state's own masking, as a regression would.
    report_tests._set(reported, A2, "failed", error=f"see {text}")
    report = build_run_report(plan, reported)
    for path in write_run_report(tmp_path / "report", report, redact):
        assert text not in path.read_text()


# Every credential is registered before the first write


def _group_titled(tmp_path: Path, secret: str) -> Path:
    plan_file = groups._write(tmp_path, members=["agol_bob"])

    def retitle(inventory):
        inventory["groups"][0]["title"] = f"Planners {secret}"

    _edit_inventory(plan_file, retitle)
    return plan_file


@pytest.mark.parametrize(
    "source", ["option", "environment", "stdin", "prompt", "stored-oauth"]
)
def test_each_credential_is_registered_before_the_first_geolens_write(
    runner, tmp_path, team, monkeypatch, source
):
    secret = "S" + secrets.token_hex(12)
    api = groups.GroupsApi(team, groups._service(team), existing=[])
    plan_file = _group_titled(tmp_path, secret)
    args = ["--json", "arcgis", "migrate", str(plan_file), "--only", A2]
    stdin = None
    if source == "option":
        args.append(f"--token={secret}")
    elif source == "environment":
        monkeypatch.setenv("ARCGIS_TOKEN", secret)
    elif source == "stdin":
        args.append("--token-stdin")
        stdin = f"{secret}\n"
    elif source == "prompt":
        args += ["--username", "gis_admin"]
        monkeypatch.setattr(
            "geolens_cli.arcgis_portal.getpass.getpass", lambda prompt: secret
        )
    else:
        args += ["--client-id", "ExampleClient1"]
        monkeypatch.setattr(
            oauth_mod, "_load", lambda account: [("keyring", oauth_mod._Saved(secret))]
        )

    result = runner.invoke(layers.app, args, input=stdin)

    assert result.exit_code == 2, result.output
    assert _refused("/admin/groups/", "body.name") in result.output
    assert api.groups == []
    _assert_kept_out(team, plan_file, secret)


def test_a_renewed_token_is_registered_before_it_is_used(fake_geolens, monkeypatch):
    from geolens.api.admin import create_group_admin_groups_post as create
    from geolens.models.group_write import GroupWrite

    from geolens_cli.arcgis_portal import PortalClient

    renewed = "R" + secrets.token_hex(12)
    session = _session(fake_geolens)
    client = PortalClient(
        "https://example.test/portal",
        opener=FakePortal(
            portal_routes(
                {"generateToken": {"token": renewed, "expires": 1, "ssl": True}}
            )
        ),
        redact=session._redact,
        sleep=lambda seconds: None,
    )

    client.generate_token("gis_admin", "pw-" + secrets.token_hex(4))

    with pytest.raises(CredentialRefused):
        session.call(create.sync_detailed, body=GroupWrite(name=f"G {renewed}"))
    assert fake_geolens.seen == []


def test_a_relationship_named_with_the_token_is_saved_masked_and_reported(
    runner, plan_file, geolens
):
    relationship = {
        "name": f"Parcels_{TOKEN}",
        "related_layer_id": 1,
        "cardinality": "OneToMany",
        "role": "Origin",
    }
    FakeImport(
        geolens,
        [
            _layer(0, "Parcels", relationships=[relationship]),
            _layer(1, "Owners", "Table"),
        ],
    )

    result, payload = _with_token(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    saved = _state(plan_file)["items"][A2]["relationships"]
    assert saved["0"][0]["name"] == "Parcels_[REDACTED]"
    for path in payload["report"]:
        assert TOKEN not in Path(path).read_text()
    _assert_kept_out(geolens, plan_file)


# Registration cost


def test_registering_many_secrets_stays_cheap():
    redact = Redactor()
    started = time.monotonic()

    for n in range(2000):
        redact.add(f"generated-{n:05d}-{secrets.token_urlsafe(12)}")

    assert time.monotonic() - started < 10


def test_every_secret_still_matches_after_many_registrations():
    redact = Redactor()
    secrets_given = [f"pw/{n:04d}-é-{secrets.token_hex(6)}" for n in range(500)]
    for secret in secrets_given:
        redact.add(secret)

    for secret in (secrets_given[0], secrets_given[250], secrets_given[-1]):
        lowered = re.sub(
            r"%[0-9A-F]{2}", lambda m: m[0].lower(), quote(secret, safe="")
        )
        for text in (secret, lowered, json.dumps(secret)[1:-1]):
            assert redact.holds(f"x {text} y")
            assert redact(f"x {text} y") == "x [REDACTED] y"
    assert not redact.holds("pw/9999-é-none")


# Encodings: the bound


SPECIAL = 'a"b\\cé/d-' + secrets.token_hex(6)


@pytest.mark.parametrize(
    "form",
    [
        json.dumps(SPECIAL)[1:-1],
        json.dumps(SPECIAL, ensure_ascii=False)[1:-1],
        quote(SPECIAL),
        quote(SPECIAL, safe=""),
        quote_plus(SPECIAL),
    ],
    ids=["json-ascii", "json-unicode", "quote-default", "quote-all", "quote-plus"],
)
def test_a_secret_is_found_json_escaped_and_url_encoded(fake_geolens, form):
    from geolens.api.admin import create_group_admin_groups_post as create
    from geolens.models.group_write import GroupWrite

    session = _session(fake_geolens)
    session._redact.add(SPECIAL)

    assert holds_secret(f'{{"description": "see {form}"}}', session._redact)
    with pytest.raises(CredentialRefused):
        session.call(create.sync_detailed, body=GroupWrite(name=f"see {form}"))
    assert fake_geolens.seen == []


# Collections and baselines


def test_a_long_collection_name_holding_the_token_makes_no_collection(
    runner, tmp_path, geolens
):
    collections._services(geolens)
    made = collections.FakeCollections(geolens)
    # Sent shortened to 255 characters, the name itself is clean.
    long = "F" * 260 + f" {TOKEN}"
    plan_file = collections._plan(
        tmp_path,
        lambda plan: [
            item["target"].update(collections=[long]) for item in plan["items"]
        ],
    )

    for _run in range(2):
        result, payload = _with_token(runner, plan_file, "--only", A1, "--only", A2)

        assert result.exit_code == 1
        assert [i["error"] for i in payload["items"]] == [_reason("collection")] * 2
        assert made.names == {}
        assert _state(plan_file)["collections"] == {}
    _assert_kept_out(geolens, plan_file)


def test_a_baseline_holding_the_token_is_dropped_not_masked(runner, plan_file, geolens):
    service = refresh._migrated(runner, plan_file, geolens)
    refresh.FakeRefresh(geolens, service).allow(PARCELS)
    path = plan_file.parent / "arcgis-migration-state.json"
    state = json.loads(path.read_text())
    state["items"][A2]["metadata_baseline"][PARCELS]["summary"] = f"Old {TOKEN}"
    path.write_text(json.dumps(state))
    # GeoLens holds text equal to what a masked baseline would have read.
    service.summaries[PARCELS] = "Old [REDACTED]"
    _edit_row(plan_file, A2, snippet="New summary")

    result, _ = _with_token(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert service.summaries[PARCELS] == "Old [REDACTED]"
    entry = _state(plan_file)["items"][A2]
    assert f"kept the summary edited in GeoLens on dataset {PARCELS}" in entry["notes"]
    assert "summary" not in entry["metadata_baseline"][PARCELS]
    _assert_kept_out(geolens, plan_file)
