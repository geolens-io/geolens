"""`geolens arcgis migrate` prints no credential the run was given, and prints everything else as before."""

# Imported fixtures are used as test arguments, which F811 reads as redefinition.
# ruff: noqa: F811

from __future__ import annotations

import contextlib
import io
import json
import secrets
import unicodedata
from pathlib import Path
from urllib.parse import quote, quote_plus

import pytest

from geolens_cli import output as output_mod
from geolens_cli.main import app

from . import test_arcgis_migrate_groups as groups
from .arcgis_fake import A2
from .test_arcgis_migrate_files import portal  # noqa: F401  (fixture)
from .test_arcgis_migrate_groups import team  # noqa: F401  (fixture)
from .test_arcgis_migrate_layers import geolens, quick  # noqa: F401  (fixtures)

TOKEN = "Tk" + secrets.token_hex(12)
PASSWORD = "Pä ss/wörd+" + secrets.token_hex(4)
# Shaped like credentials, but none is the run's: the portal's own text.
PATTERNS = (
    "see https://example.test/f?token=abc123&sig=ZmFrZQ Bearer abcdefghijklmnop "
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJl"
)
MODES = {"run": (), "dry-run": ("--dry-run",), "cutover": ("--cutover",)}


def _edit_plan(plan_file: Path, edit) -> None:
    plan = json.loads(plan_file.read_text())
    edit(plan)
    plan_file.write_text(json.dumps(plan))


def _a2(plan: dict) -> dict:
    return next(item for item in plan["items"] if item["id"] == A2)


def _scenario(tmp_path: Path, team, place: str, text: str) -> tuple[Path, list[str]]:
    """A plan whose one runnable item, A2, puts *text* in the output at *place*,
    and the extra arguments that make it reach the output there."""
    service = groups._service(team)
    name = f"Planning {text}" if place == "group" else "Planning"
    groups.GroupsApi(team, service, existing=[groups._group(groups.EXISTING, name)])
    plan_file = groups._write(
        tmp_path,
        members=None if place == "warning" else ["agol_bob"],
        unread=f"denied: {text}" if place == "warning" else None,
        # Members are read only for a group the run makes.
        group_map=None if place == "warning" else {"g1": {"geolens_group": name}},
    )

    def edit(plan: dict) -> None:
        # The cutover runs the whole plan, so every other item is skipped.
        for item in plan["items"]:
            if item["id"] != A2:
                item["action"] = "skip"
        if place == "title":
            _a2(plan)["title"] = f"Parcels {text}"
        if place == "owner":
            _a2(plan)["target"]["owner"] = f"planner {text}"

    _edit_plan(plan_file, edit)
    return plan_file, ["--unmapped-owner", "operator"] if place == "owner" else []


def _invoke(runner, plan_file: Path, mode: str, as_json: bool, *args: str):
    flags = ["--json"] if as_json else []
    return runner.invoke(
        app,
        [*flags, "arcgis", "migrate", str(plan_file), *MODES[mode], *args],
        env={"ARCGIS_PASSWORD": PASSWORD},
    )


def _forms(secret: str) -> list[str]:
    forms = []
    for text in (secret, unicodedata.normalize("NFD", secret)):
        forms += [text, quote(text, safe=""), quote(text), quote_plus(text)]
        forms += [json.dumps(text)[1:-1], json.dumps(text, ensure_ascii=False)[1:-1]]
    return list(dict.fromkeys(forms))


def _holds(text: str, secret: str) -> bool:
    lowered = text.lower()
    return any(form in text or form.lower() in lowered for form in _forms(secret))


@pytest.fixture
def calls(monkeypatch) -> list:
    """Every formatter call the run makes, with the arguments given to it."""
    made: list = []
    for name in ("success", "error", "warn", "json", "info", "debug"):
        method = getattr(output_mod.Formatter, name)

        def record(self, *args, _name=name, _method=method):
            made.append((_name, args))
            return _method(self, *args)

        monkeypatch.setattr(output_mod.Formatter, name, record)
    return made


@pytest.mark.parametrize("as_json", [False, True], ids=["text", "json"])
@pytest.mark.parametrize("mode", list(MODES))
@pytest.mark.parametrize("place", ["title", "owner", "group", "warning"])
def test_neither_stream_holds_the_runs_token(
    runner, tmp_path, team, portal, place, mode, as_json
):
    plan_file, args = _scenario(tmp_path, team, place, TOKEN)

    result = _invoke(runner, plan_file, mode, as_json, "--token", TOKEN, *args)

    # The text output names an item by its id, never by its title.
    if as_json or place != "title":
        assert "[REDACTED]" in result.stdout + result.stderr
    assert TOKEN not in result.stdout
    assert TOKEN not in result.stderr
    if as_json:
        payload = json.loads(result.stdout)
        assert {"items", "groups", "cutover", "owner_reassigned"} <= payload.keys()


@pytest.mark.parametrize("as_json", [False, True], ids=["text", "json"])
@pytest.mark.parametrize("form", range(len(_forms(PASSWORD))))
def test_each_encoded_form_of_a_registered_secret_is_masked(
    runner, tmp_path, team, portal, form, as_json
):
    plan_file, _ = _scenario(tmp_path, team, "title", _forms(PASSWORD)[form])

    result = _invoke(runner, plan_file, "run", as_json, "--token", TOKEN)

    assert not _holds(result.stdout, PASSWORD)
    assert not _holds(result.stderr, PASSWORD)
    if as_json:
        item = next(i for i in json.loads(result.stdout)["items"] if i["id"] == A2)
        assert item["title"] == "Parcels [REDACTED]"


@pytest.mark.parametrize("as_json", [False, True], ids=["text", "json"])
def test_text_shaped_like_a_credential_is_printed_as_is(
    runner, tmp_path, team, portal, as_json
):
    plan_file, _ = _scenario(tmp_path, team, "warning", PATTERNS)

    result = _invoke(runner, plan_file, "run", as_json, "--token", TOKEN)

    assert result.exit_code == 0, result.output
    if as_json:
        unread = json.loads(result.stdout)["groups"]["g1"]["members_unread"]
        assert unread == f"denied: {PATTERNS}"
    else:
        assert f"members not read: denied: {PATTERNS}\n" in result.stderr
    assert "[REDACTED]" not in result.stdout + result.stderr


def _replayed(calls: list, as_json: bool) -> tuple[str, str]:
    """What the recorded formatter calls print with no mask applied."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        fmt = output_mod.Formatter(json_mode=as_json)
        for name, args in list(calls):
            getattr(fmt, name)(*args)
    return out.getvalue(), err.getvalue()


@pytest.mark.parametrize("as_json", [False, True], ids=["text", "json"])
@pytest.mark.parametrize("mode", list(MODES))
def test_output_without_a_credential_is_unchanged(
    runner, tmp_path, team, portal, calls, mode, as_json
):
    plan_file, args = _scenario(tmp_path, team, "owner", PATTERNS)

    result = _invoke(runner, plan_file, mode, as_json, "--token", TOKEN, *args)

    assert PATTERNS in repr(calls)
    assert (result.stdout, result.stderr) == _replayed(calls, as_json)
