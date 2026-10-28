"""`geolens arcgis migrate`: ArcGIS sharing becomes GeoLens visibility and groups."""

# Imported fixtures are used as test arguments, which F811 reads as redefinition.
# ruff: noqa: F811

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

import pytest
from types import SimpleNamespace

from geolens_cli import arcgis_migrate as migrate
from geolens_cli import arcgis_plan as plan_mod
from geolens_cli.main import app
from geolens_cli.arcgis_migrate_groups import Sharing, share, wanted_groups
from geolens_cli.arcgis_migrate_session import ItemFailed
from geolens_cli.arcgis_migrate_report import build_run_report
from geolens_cli.arcgis_migrate_state import ItemState, MigrationState
from geolens_cli.arcgis_portal import Redactor

from .arcgis_fake import A1, A2, inventory_report
from .conftest import GEOLENS_INSTANCE
from .test_arcgis_migrate_layers import (  # noqa: F401  (fixtures)
    NOW,
    OPERATOR,
    FakeImport,
    _layer,
    _migrate,
    _problem,
    _state,
    dataset_id,
    geolens,
    quick,
)

BOB = "00000000-0000-0000-0000-0000000000b0"
EVE = "00000000-0000-0000-0000-0000000000e0"
GHOST = "00000000-0000-0000-0000-0000000000c0"
CREATED = "00000000-0000-0000-0005-000000000001"
EXISTING = "00000000-0000-0000-0005-000000000002"
DATASETS = (dataset_id("Parcels"), dataset_id("Owners"))


def _user(user_id: str, username: str, roles: list[str]) -> dict:
    return {
        "id": user_id,
        "username": username,
        "email": f"{username}@example.org",
        "is_active": True,
        "status": "active",
        "last_login_at": None,
        "created_at": NOW,
        "roles": roles,
        "can_reset_password": False,
    }


def _group(group_id: str, name: str) -> dict:
    return {
        "id": group_id,
        "name": name,
        "member_count": 0,
        "created_at": NOW,
        "updated_at": NOW,
    }


@pytest.mark.parametrize(
    ("access", "visibility"),
    [
        ("private", "private"),
        ("org", "internal"),
        ("public", "public"),
        ("shared", "restricted"),
    ],
)
def test_each_arcgis_sharing_level_gets_its_plan_visibility(access, visibility):
    report = inventory_report()
    for row in report["items"]:
        row["sharing"]["access"] = access
    plan = plan_mod.build_plan(report, inventory_path="inv.json")

    assert {item["target"]["visibility"] for item in plan["items"]} == {visibility}


@pytest.mark.parametrize(
    ("wanted", "restrict_public", "owner", "visibility", "groups", "noted"),
    [
        ("private", False, BOB, "private", [], False),
        ("internal", True, BOB, "internal", [], False),
        ("public", False, BOB, "public", [], False),
        ("public", True, BOB, "internal", [], True),
        ("public", True, OPERATOR, "public", [], False),
        ("restricted", False, BOB, "restricted", [CREATED, EXISTING], False),
        ("restricted", False, BOB, "restricted", [CREATED], False),
        ("restricted", False, BOB, "private", [], True),
    ],
    ids=[
        "private",
        "internal",
        "public",
        "public-under-policy",
        "public-under-policy-admin-owner",
        "group-only",
        "group-only-partly-mapped",
        "group-only-unmapped",
    ],
)
def test_the_run_gives_each_sharing_row_its_geolens_audience(
    wanted, restrict_public, owner, visibility, groups, noted
):
    mapped = {"g1": CREATED, "g2": EXISTING}
    if len(groups) == 1:
        mapped["g2"] = None
    if not groups:
        mapped = {"g1": None, "g2": None}
    sharing = Sharing(
        groups=mapped, restrict_public=restrict_public, admins=frozenset({OPERATOR})
    )
    item = {"target": {"visibility": wanted, "groups": ["g1", "g2"]}}

    effective, notes = sharing.target(item, owner)

    assert effective["target"]["visibility"] == visibility
    assert effective["target"]["geolens_groups"] == groups
    assert bool(notes) is noted
    assert item["target"]["visibility"] == wanted


class GroupsApi:
    """Admin group routes and the dataset and map group shares, recorded."""

    def __init__(self, fake, service: FakeImport, existing: list[dict]) -> None:
        self.fake = fake
        self.service = service
        self.groups = list(existing)
        self.members: dict[str, list[str]] = {}
        self.removed: list[str] = []
        self.shares: list[tuple[str, list[str]]] = []
        fake.routes["GET /admin/groups/"] = lambda seen: {
            "groups": self.groups,
            "total": len(self.groups),
        }
        fake.routes["POST /admin/groups/"] = self.create
        for group in existing:
            self._serve(group["id"])
        for dataset in DATASETS:
            fake.routes[f"PUT /datasets/{dataset}/groups/"] = lambda seen, d=dataset: (
                self.share(seen, d)
            )

    def _serve(self, group_id: str) -> None:
        self.fake.routes[f"GET /admin/groups/{group_id}"] = lambda seen: next(
            g for g in self.groups if g["id"] == group_id
        )
        self.fake.routes[f"POST /admin/groups/{group_id}/members/"] = lambda seen: (
            self.add(seen, group_id)
        )
        self.fake.routes[f"GET /admin/groups/{group_id}/members/"] = lambda seen: {
            "members": [
                {"id": u, "username": u} for u in self.members.get(group_id, [])
            ],
            "total": len(self.members.get(group_id, [])),
        }
        for user_id in (BOB, EVE, GHOST):
            self.fake.routes[f"DELETE /admin/groups/{group_id}/members/{user_id}"] = (
                lambda seen, u=user_id: self.remove(group_id, u)
            )

    def remove(self, group_id: str, user_id: str):
        if user_id not in self.members.get(group_id, []):
            return (404, _problem(404, "User is not a member of this group"))
        self.members[group_id].remove(user_id)
        self.removed.append(user_id)
        return (204, None)

    def create(self, seen):
        name = seen.json()["name"]
        # Names are unique as written, as on the server.
        if any(g["name"] == name for g in self.groups):
            return (409, _problem(409, f"A group named '{name}' already exists"))
        group = _group(CREATED, name)
        self.groups.append(group)
        self._serve(CREATED)
        return (201, group)

    def add(self, seen, group_id: str):
        self.members.setdefault(group_id, []).extend(seen.json()["user_ids"])
        return next(g for g in self.groups if g["id"] == group_id)

    def share(self, seen, dataset: str):
        ids = seen.json()["group_ids"]
        self.shares.append((dataset, ids))
        refs = [
            {"id": g["id"], "name": g["name"]} for g in self.groups if g["id"] in ids
        ]
        visibility = "restricted" if refs else "private"
        self.service.fields.setdefault(dataset, {}).update(
            groups=refs, visibility=visibility
        )
        return {"visibility": visibility, "groups": refs, "metadata_warnings": None}


def _write(
    tmp_path: Path,
    *,
    members: list[str] | None,
    unread: str | None = None,
    role: str = "org_admin",
    group_map: dict[str, Any] | None = None,
    eve_email: str | None = None,
) -> Path:
    report = inventory_report()
    report["auth"]["role"] = role
    for row in report["items"]:
        if row["id"] == A2:
            row["sharing"] = {"access": "shared", "groups": ["g1"]}
            row["groups"] = [{"id": "g1", "title": "Planners", "access": "org"}]
        if row["id"] == A1 and eve_email:
            # The inventory reads an owner's email, here for a member too.
            row["owner"], row["owner_email"] = "agol_eve", eve_email
    report["groups"] = [
        {
            "id": "g1",
            "title": "Planners",
            "access": "org",
            "members": members,
            "members_unread": unread,
        }
    ]
    (tmp_path / "arcgis-inventory.json").write_text(json.dumps(report))
    plan = plan_mod.build_plan(
        report,
        inventory_path="arcgis-inventory.json",
        owner_map={"gis_admin": "operator"},
    )
    # A member who owns nothing can still be mapped like an owner.
    plan["owner_map"]["agol_bob"] = "bob"
    for group_id, entry in (group_map or {}).items():
        plan["group_map"][group_id].update(entry)
    path = tmp_path / "arcgis-migration-plan.json"
    path.write_text(json.dumps(plan))
    return path


@pytest.fixture
def up_to_date(monkeypatch):
    """A rerun's refresh of the finished item finds nothing to bring over."""
    for action in migrate.REFRESHERS:
        monkeypatch.setitem(migrate.REFRESHERS, action, lambda ctx, item, entry: [])


@pytest.fixture
def team(geolens):
    users = [
        _user(OPERATOR, "operator", ["admin"]),
        _user(BOB, "bob", ["editor"]),
        _user(EVE, "agol_eve", ["viewer"]),
    ]
    geolens.routes["GET /admin/users/"] = {"users": users, "total": len(users)}
    return geolens


def _run(runner, plan_file: Path, *args: str):
    return _migrate(
        runner, plan_file, "--only", A2, "--token", secrets.token_urlsafe(16), *args
    )


def _service(fake) -> FakeImport:
    return FakeImport(fake, [_layer(0, "Parcels"), _layer(1, "Owners", "Table")])


def test_a_group_only_item_is_restricted_to_a_group_made_with_its_members(
    runner, tmp_path, team
):
    service = _service(team)
    api = GroupsApi(team, service, existing=[])
    plan_file = _write(tmp_path, members=["agol_bob", "agol_eve", "agol_ghost"])

    result, payload = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert [c["visibility"] for c in service.bodies("POST /ingest/commit/")] == [
        "restricted",
        "restricted",
    ]
    assert [g["name"] for g in api.groups] == ["Planners"]
    # By owner_map, and by the same username for a member it doesn't list.
    assert sorted(api.members[CREATED]) == sorted([BOB, EVE])
    assert api.shares == [(d, [CREATED]) for d in DATASETS]
    group = _state(plan_file)["groups"]["g1"]
    assert group["id"] == CREATED and group["added"] == sorted([BOB, EVE])
    assert [p["member"] for p in group["pending"]] == ["agol_ghost"]
    assert _state(plan_file)["items"][A2]["groups"] == {d: [CREATED] for d in DATASETS}
    assert payload["groups"]["g1"]["name"] == "Planners"


def test_shares_land_before_the_owner_transfer(runner, tmp_path, team):
    service = _service(team)
    GroupsApi(team, service, existing=[])
    plan_file = _write(tmp_path, members=[])
    plan = json.loads(plan_file.read_text())
    plan["owner_map"]["gis_admin"] = "bob"
    plan_file.write_text(json.dumps(plan))

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    path = f"/datasets/{DATASETS[0]}"
    writes = [
        "share" if s.method == "PUT" else "transfer"
        for s in team.seen
        if (s.method == "PUT" and s.url.endswith(f"{path}/groups/"))
        or (s.method == "PATCH" and s.url.endswith(path) and "owner_id" in s.json())
    ]
    assert writes == ["share", "transfer"]


def test_a_rerun_neither_makes_the_group_again_nor_reshares(
    runner, tmp_path, team, up_to_date
):
    service = _service(team)
    api = GroupsApi(team, service, existing=[])
    plan_file = _write(tmp_path, members=["agol_bob"])
    assert _run(runner, plan_file)[0].exit_code == 0

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert len(api.groups) == 1
    assert len(api.shares) == len(DATASETS)
    assert api.members[CREATED] == [BOB]


def test_a_member_who_signs_up_later_is_added_on_a_rerun(
    runner, tmp_path, team, up_to_date
):
    service = _service(team)
    api = GroupsApi(team, service, existing=[])
    plan_file = _write(tmp_path, members=["agol_bob", "agol_ghost"])
    assert _run(runner, plan_file)[0].exit_code == 0
    ghost = GHOST
    users = team.routes["GET /admin/users/"]["users"]
    team.routes["GET /admin/users/"] = {
        "users": [*users, _user(ghost, "agol_ghost", ["viewer"])],
        "total": len(users) + 1,
    }

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert api.members[CREATED] == [BOB, ghost]
    assert _state(plan_file)["groups"]["g1"]["pending"] == []


def test_group_map_can_point_at_an_existing_group_whose_members_stay(
    runner, tmp_path, team
):
    service = _service(team)
    api = GroupsApi(team, service, existing=[_group(EXISTING, "Planning")])
    plan_file = _write(
        tmp_path,
        members=["agol_bob"],
        group_map={"g1": {"geolens_group": "planning"}},
    )

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert [g["id"] for g in api.groups] == [EXISTING]
    assert api.members == {}
    assert api.shares == [(d, [EXISTING]) for d in DATASETS]


def test_an_existing_group_group_map_names_must_exist(runner, tmp_path, team):
    service = _service(team)
    GroupsApi(team, service, existing=[])
    plan_file = _write(
        tmp_path, members=[], group_map={"g1": {"geolens_group": "Nobody"}}
    )

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 2
    assert "Nobody" in result.output
    assert service.bodies("POST /ingest/commit/") == []


def test_a_name_another_group_holds_is_never_joined(runner, tmp_path, team):
    service = _service(team)
    api = GroupsApi(team, service, existing=[_group(EXISTING, "Planners")])
    plan_file = _write(tmp_path, members=["agol_bob"])

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert api.groups[-1]["name"] == "ArcGIS - Planners"
    assert EXISTING not in api.members
    assert api.shares == [(d, [CREATED]) for d in DATASETS]


def test_an_unmapped_group_leaves_the_item_private(runner, tmp_path, team):
    service = _service(team)
    api = GroupsApi(team, service, existing=[])
    plan_file = _write(
        tmp_path, members=["agol_bob"], group_map={"g1": {"geolens_group": ""}}
    )

    result, payload = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert {c["visibility"] for c in service.bodies("POST /ingest/commit/")} == {
        "private"
    }
    assert api.groups == [] and api.shares == []
    assert any("made private" in note for note in payload["items"][0]["notes"])


def test_a_refused_share_fails_the_item_and_the_exit_code(runner, tmp_path, team):
    service = _service(team)
    GroupsApi(team, service, existing=[])
    team.routes[f"PUT /datasets/{DATASETS[0]}/groups/"] = (
        422,
        _problem(422, "a VRT would reach past one of its sources"),
    )
    plan_file = _write(tmp_path, members=[])

    result, payload = _run(runner, plan_file)

    assert result.exit_code == 1
    assert _state(plan_file)["items"][A2]["status"] == "failed"
    assert (
        "sharing it with its GeoLens groups failed"
        in (_state(plan_file)["items"][A2]["error"])
    )
    assert payload["failed"] == [A2]


def test_a_group_removed_in_geolens_is_not_shared_again(
    runner, tmp_path, team, up_to_date
):
    service = _service(team)
    api = GroupsApi(team, service, existing=[])
    plan_file = _write(tmp_path, members=[])
    assert _run(runner, plan_file)[0].exit_code == 0
    for dataset in DATASETS:
        service.fields[dataset]["groups"] = []

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert len(api.shares) == len(DATASETS)


def test_public_is_internal_under_the_policy_for_a_non_admin_owner(
    runner, tmp_path, team
):
    service = _service(team)
    team.routes["GET /settings/feature-flags/"] = {"restrict_public_visibility": True}
    plan_file = _write(tmp_path, members=[])
    plan = json.loads(plan_file.read_text())
    plan["owner_map"]["gis_admin"] = "bob"
    for item in plan["items"]:
        if item["id"] == A2:
            item["target"]["visibility"] = "public"
    plan_file.write_text(json.dumps(plan))
    team.routes.update(
        {
            f"PATCH /datasets/{d}": (
                lambda seen, d=d: service.dataset(
                    d, seen.json().get("owner_id", OPERATOR)
                )
            )
            for d in DATASETS
        }
    )

    result, payload = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert {c["visibility"] for c in service.bodies("POST /ingest/commit/")} == {
        "internal"
    }
    assert any("restrict_public_visibility" in n for n in payload["items"][0]["notes"])


def test_cutover_counts_groups_a_non_admin_inventory_may_have_missed(
    runner, tmp_path, team
):
    service = _service(team)
    GroupsApi(team, service, existing=[])
    plan_file = _write(tmp_path, members=["agol_bob"], role="org_user")
    assert _run(runner, plan_file)[0].exit_code == 0

    result, payload = _migrate(
        runner,
        plan_file,
        "--cutover",
        "--dry-run",
        "--accept-unfinished-items",
        "--accept-incomplete-inventory",
        "--accept-attachment-loss",
    )

    checks = {c["check"]: c["items"] for c in payload["cutover"]["checks"]}
    assert payload["cutover"]["refused"] == ["under-sharing"]
    assert [i["item"] for i in checks["under-sharing"]] == [A2]
    assert "isn't an org admin" in checks["under-sharing"][0]["reason"]

    result, payload = _migrate(
        runner,
        plan_file,
        "--cutover",
        "--dry-run",
        "--accept-unfinished-items",
        "--accept-incomplete-inventory",
        "--accept-attachment-loss",
        "--accept-under-sharing",
    )
    assert payload["cutover"]["refused"] == []


def test_unread_members_and_pending_members_reach_the_cutover_checks(
    runner, tmp_path, team
):
    service = _service(team)
    GroupsApi(team, service, existing=[])
    plan_file = _write(
        tmp_path,
        members=None,
        unread="the group hides its members from the inventory's account",
    )
    assert _run(runner, plan_file)[0].exit_code == 0

    _result, payload = _migrate(runner, plan_file, "--cutover", "--dry-run")

    checks = {c["check"]: c["items"] for c in payload["cutover"]["checks"]}
    assert "hides its members" in checks["under-sharing"][0]["reason"]
    assert "unresolved-users" not in checks


def test_a_group_deleted_in_geolens_is_not_made_again_and_counts_at_cutover(
    runner, tmp_path, team, up_to_date
):
    service = _service(team)
    api = GroupsApi(team, service, existing=[])
    plan_file = _write(tmp_path, members=[])
    assert _run(runner, plan_file)[0].exit_code == 0
    api.groups = []
    del team.routes[f"GET /admin/groups/{CREATED}"]

    result, payload = _run(runner, plan_file)
    rerun, _ = _run(runner, plan_file)

    assert result.exit_code == 0 and rerun.exit_code == 0, result.output
    assert api.groups == []
    assert "was deleted in GeoLens" in payload["group_warnings"][0]
    _result, payload = _migrate(runner, plan_file, "--cutover", "--dry-run")
    checks = {c["check"]: c["items"] for c in payload["cutover"]["checks"]}
    assert "maps to no GeoLens group" in checks["under-sharing"][0]["reason"]


def test_a_refused_member_add_stays_pending_and_fails_the_run(runner, tmp_path, team):
    service = _service(team)
    api = GroupsApi(team, service, existing=[])
    api.add = lambda seen, group_id: (
        422,
        _problem(422, "a VRT would reach past one of its sources"),
    )
    plan_file = _write(tmp_path, members=["agol_bob"])

    result, payload = _run(runner, plan_file)

    assert result.exit_code == 1
    group = _state(plan_file)["groups"]["g1"]
    assert group["added"] == []
    assert [p["member"] for p in group["pending"]] == ["agol_bob"]
    assert "a VRT would reach past" in group["pending"][0]["reason"]
    _result, payload = _migrate(runner, plan_file, "--cutover", "--dry-run")
    checks = {c["check"]: c["items"] for c in payload["cutover"]["checks"]}
    assert [i["item"] for i in checks["unresolved-users"]] == ["group g1"]


OTHER = "00000000-0000-0000-0005-000000000009"


def test_an_existing_group_reports_the_arcgis_members_it_lacks(runner, tmp_path, team):
    service = _service(team)
    api = GroupsApi(team, service, existing=[_group(EXISTING, "Planning")])
    plan_file = _write(
        tmp_path,
        members=["agol_bob", "agol_eve"],
        group_map={"g1": {"geolens_group": "Planning"}},
    )
    api.members[EXISTING] = [BOB]
    assert _run(runner, plan_file)[0].exit_code == 0

    _result, payload = _migrate(runner, plan_file, "--cutover", "--dry-run")

    checks = {c["check"]: c["items"] for c in payload["cutover"]["checks"]}
    [loss] = checks["under-sharing"]
    assert (
        "1 ArcGIS member(s) of group g1 aren't in the existing GeoLens group"
        in (loss["reason"])
    )
    group = _state(plan_file)["groups"]["g1"]
    assert group["created"] is False and group["members"] == {"agol_bob": "bob"}
    assert [u["member"] for u in group["unsynced"]] == ["agol_eve"]
    assert "unresolved-users" not in checks


def test_an_existing_group_holding_every_member_is_no_loss(runner, tmp_path, team):
    service = _service(team)
    api = GroupsApi(team, service, existing=[_group(EXISTING, "Planning")])
    api.members[EXISTING] = [BOB]
    plan_file = _write(
        tmp_path, members=["agol_bob"], group_map={"g1": {"geolens_group": "Planning"}}
    )
    assert _run(runner, plan_file)[0].exit_code == 0

    _result, payload = _migrate(runner, plan_file, "--cutover", "--dry-run")

    assert "under-sharing" not in {c["check"] for c in payload["cutover"]["checks"]}


def test_group_map_takes_the_group_named_exactly(runner, tmp_path, team):
    service = _service(team)
    api = GroupsApi(
        team,
        service,
        existing=[_group(OTHER, "PLANNING"), _group(EXISTING, "planning")],
    )
    plan_file = _write(
        tmp_path, members=[], group_map={"g1": {"geolens_group": "planning"}}
    )

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert api.shares == [(d, [EXISTING]) for d in DATASETS]


def test_group_map_matching_several_groups_by_case_alone_is_refused(
    runner, tmp_path, team
):
    service = _service(team)
    GroupsApi(
        team,
        service,
        existing=[_group(OTHER, "PLANNING"), _group(EXISTING, "Planning")],
    )
    plan_file = _write(
        tmp_path, members=[], group_map={"g1": {"geolens_group": "planning"}}
    )

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 2
    assert "several groups named planning" in result.output
    assert service.bodies("POST /ingest/commit/") == []


def test_a_dry_run_makes_no_group_and_lists_the_member_mapping(runner, tmp_path, team):
    service = _service(team)
    api = GroupsApi(team, service, existing=[_group(EXISTING, "Planners")])
    plan_file = _write(tmp_path, members=["agol_bob", "agol_eve"])

    result = runner.invoke(
        app, ["arcgis", "migrate", str(plan_file), "--only", A2, "--dry-run"]
    )

    assert result.exit_code == 0, result.output
    assert len(api.groups) == 1 and api.members == {}
    assert "would get GeoLens group ArcGIS - Planners" in result.output
    assert "ArcGIS agol_bob -> GeoLens bob" in result.output
    assert "ArcGIS agol_eve -> GeoLens agol_eve" in result.output
    assert not (plan_file.parent / "arcgis-migration-state.json").exists()


@pytest.mark.parametrize("dry_run", [False, True])
def test_a_name_held_with_and_without_the_prefix_stops_the_run(
    runner, tmp_path, team, dry_run
):
    service = _service(team)
    api = GroupsApi(
        team,
        service,
        existing=[_group(EXISTING, "Planners"), _group(OTHER, "ArcGIS - Planners")],
    )
    plan_file = _write(tmp_path, members=["agol_bob"])

    result, _ = _run(runner, plan_file, *(["--dry-run"] if dry_run else []))

    assert result.exit_code == 2
    assert "groups named Planners and ArcGIS - Planners" in result.output
    assert "group_map g1 geolens_group" in result.output
    assert len(api.groups) == 2 and api.members == {}
    assert service.bodies("POST /ingest/commit/") == []


def test_the_report_lists_the_member_mapping(runner, tmp_path, team):
    service = _service(team)
    GroupsApi(team, service, existing=[])
    plan_file = _write(tmp_path, members=["agol_bob"])
    assert _run(runner, plan_file)[0].exit_code == 0

    report = json.loads((tmp_path / "arcgis-migration-report.json").read_text())

    assert report["groups"][0]["members"] == {"agol_bob": "bob"}
    text = (tmp_path / "arcgis-migration-report.md").read_text()
    assert "agol\\_bob: bob" in text


def test_a_same_named_account_with_another_email_stays_pending(runner, tmp_path, team):
    service = _service(team)
    api = GroupsApi(team, service, existing=[])
    plan_file = _write(tmp_path, members=["agol_eve"], eve_email="eve@elsewhere.org")

    assert _run(runner, plan_file)[0].exit_code == 0

    group = _state(plan_file)["groups"]["g1"]
    assert api.members.get(CREATED, []) == []
    assert "another email" in group["pending"][0]["reason"]


def test_a_same_named_account_with_the_inventory_email_resolves(runner, tmp_path, team):
    service = _service(team)
    api = GroupsApi(team, service, existing=[])
    plan_file = _write(tmp_path, members=["agol_eve"], eve_email="AGOL_EVE@example.org")

    assert _run(runner, plan_file)[0].exit_code == 0

    assert api.members[CREATED] == [EVE]


def test_a_share_keeps_the_groups_a_dataset_already_has(runner, tmp_path, team):
    service = _service(team)
    api = GroupsApi(team, service, existing=[_group(OTHER, "Other")])
    for dataset in DATASETS:
        service.fields[dataset] = {"groups": [{"id": OTHER, "name": "Other"}]}
    plan_file = _write(tmp_path, members=[])

    assert _run(runner, plan_file)[0].exit_code == 0

    assert api.shares == [(d, sorted([CREATED, OTHER])) for d in DATASETS]


def test_pending_members_reach_unresolved_users(runner, tmp_path, team):
    service = _service(team)
    GroupsApi(team, service, existing=[])
    plan_file = _write(tmp_path, members=["agol_bob", "agol_ghost"])
    assert _run(runner, plan_file)[0].exit_code == 0

    _result, payload = _migrate(runner, plan_file, "--cutover", "--dry-run")

    checks = {c["check"]: c["items"] for c in payload["cutover"]["checks"]}
    [pending] = checks["unresolved-users"]
    assert pending["item"] == "group g1" and "agol_ghost" in pending["reason"]


def test_a_retried_share_skips_datasets_already_shared(runner, tmp_path, team):
    service = _service(team)
    api = GroupsApi(team, service, existing=[])
    refused = (422, _problem(422, "a VRT would reach past one of its sources"))
    team.routes[f"PUT /datasets/{DATASETS[1]}/groups/"] = refused
    plan_file = _write(tmp_path, members=[])
    assert _run(runner, plan_file)[0].exit_code == 1
    assert _state(plan_file)["items"][A2]["groups"] == {DATASETS[0]: [CREATED]}
    # An admin takes the first dataset back out of the group meanwhile.
    service.fields[DATASETS[0]]["groups"] = []
    team.routes[f"PUT /datasets/{DATASETS[1]}/groups/"] = lambda seen: api.share(
        seen, DATASETS[1]
    )

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert api.shares == [(d, [CREATED]) for d in DATASETS]


def test_an_unreadable_public_policy_stops_the_run(runner, tmp_path, team):
    service = _service(team)
    team.routes["GET /settings/feature-flags/"] = (500, _problem(500, "boom"))
    plan_file = _write(tmp_path, members=[])
    plan = json.loads(plan_file.read_text())
    for item in plan["items"]:
        if item["id"] == A2:
            item["target"]["visibility"] = "public"
    plan_file.write_text(json.dumps(plan))

    result, _ = _run(runner, plan_file)

    assert result.exit_code != 0
    assert "restrict_public_visibility" in result.output
    assert service.bodies("POST /ingest/commit/") == []


def test_a_malformed_group_record_in_the_state_is_refused(runner, tmp_path, team):
    _service(team)
    plan_file = _write(tmp_path, members=[])
    (tmp_path / "arcgis-migration-state.json").write_text(
        json.dumps(
            {
                "schema_version": "3",
                "portal_url": json.loads(plan_file.read_text())["portal"]["url"],
                "geolens_instance": GEOLENS_INSTANCE,
                "groups": {"g1": {"id": CREATED, "pending": ["agol_bob"]}},
                "items": {},
            }
        )
    )

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 2
    assert "malformed group record" in result.output


def test_a_rerun_says_why_it_narrowed_an_item(runner, tmp_path, team, up_to_date):
    service = _service(team)
    GroupsApi(team, service, existing=[])
    plan_file = _write(tmp_path, members=[])
    assert _run(runner, plan_file)[0].exit_code == 0
    plan = json.loads(plan_file.read_text())
    plan["group_map"]["g1"]["geolens_group"] = ""
    plan_file.write_text(json.dumps(plan))

    assert _run(runner, plan_file)[0].exit_code == 0

    notes = _state(plan_file)["items"][A2]["notes"]
    assert any("made private" in note for note in notes)


def test_unmapping_a_migrated_group_counts_at_cutover_and_a_remap_reuses_it(
    runner, tmp_path, team, up_to_date
):
    service = _service(team)
    api = GroupsApi(team, service, existing=[])
    plan_file = _write(tmp_path, members=["agol_ghost"])
    assert _run(runner, plan_file)[0].exit_code == 0
    plan = json.loads(plan_file.read_text())
    plan["group_map"]["g1"]["geolens_group"] = ""
    plan_file.write_text(json.dumps(plan))
    assert _run(runner, plan_file)[0].exit_code == 0

    _result, payload = _migrate(runner, plan_file, "--cutover", "--dry-run")

    checks = {c["check"]: c["items"] for c in payload["cutover"]["checks"]}
    assert "maps to no GeoLens group" in checks["under-sharing"][0]["reason"]
    # The unused group's pending members no longer count.
    assert "unresolved-users" not in checks
    report = json.loads((tmp_path / "arcgis-migration-report.json").read_text())
    assert report["groups"][0]["name"] is None

    plan["group_map"]["g1"]["geolens_group"] = None
    plan_file.write_text(json.dumps(plan))
    assert _run(runner, plan_file)[0].exit_code == 0
    assert [g["id"] for g in api.groups] == [CREATED]
    assert "unmapped" not in _state(plan_file)["groups"]["g1"]


def _map_a_second_group(plan_file: Path) -> None:
    plan = json.loads(plan_file.read_text())
    for item in plan["items"]:
        if item["id"] == A2:
            item["target"]["groups"] = ["g1", "g2"]
    plan["group_map"]["g2"] = {
        "collection": "Other",
        "visibility": "private",
        "geolens_group": "Other",
    }
    plan_file.write_text(json.dumps(plan))


def test_an_edit_landing_during_a_rerun_share_is_never_adopted(
    runner, tmp_path, team, up_to_date
):
    service = _service(team)
    api = GroupsApi(team, service, existing=[_group(OTHER, "Other")])
    plan_file = _write(tmp_path, members=[])
    assert _run(runner, plan_file)[0].exit_code == 0
    baseline = _state(plan_file)["items"][A2]["last_update"][DATASETS[0]]
    _map_a_second_group(plan_file)
    share = api.share

    def edit_after_share(seen, dataset):
        answer = share(seen, dataset)
        if dataset == DATASETS[0]:
            # Someone edits the data between the share and the read after it.
            service.fields[dataset].update(data_revision=7, updated_by=BOB)
        return answer

    api.share = edit_after_share

    result, payload = _run(runner, plan_file)

    assert result.exit_code == 1
    entry = _state(plan_file)["items"][A2]
    assert entry["last_update"][DATASETS[0]] == baseline
    assert (
        "changed in GeoLens while it was shared" in (payload["not_up_to_date"][A2][0])
    )


def test_a_dataset_changed_since_the_last_run_isnt_shared_on_a_rerun(
    runner, tmp_path, team, up_to_date
):
    service = _service(team)
    api = GroupsApi(team, service, existing=[_group(OTHER, "Other")])
    plan_file = _write(tmp_path, members=[])
    assert _run(runner, plan_file)[0].exit_code == 0
    baseline = _state(plan_file)["items"][A2]["last_update"][DATASETS[0]]
    _map_a_second_group(plan_file)
    service.fields[DATASETS[0]].update(data_revision=3, updated_by=BOB)

    result, payload = _run(runner, plan_file)

    assert result.exit_code == 1
    assert [s for s in api.shares if OTHER in s[1]] == []
    assert _state(plan_file)["items"][A2]["last_update"][DATASETS[0]] == baseline
    assert "its groups weren't changed" in payload["not_up_to_date"][A2][0]


def test_only_items_to_import_get_groups():
    def item(action: str, **extra: Any) -> dict:
        return {
            "action": action,
            "target": {"visibility": "restricted", "groups": [action]},
            **extra,
        }

    items = [
        item("import_layers"),
        item("import_file"),
        item("import_map"),
        item("export_only"),
        item("skip"),
        {
            **item("import_layers"),
            "target": {"visibility": "restricted", "groups": ["gone"]},
            "removed": True,
        },
        {
            **item("import_layers"),
            "target": {"visibility": "restricted", "groups": ["unlisted"]},
            "unlisted": True,
        },
    ]

    assert wanted_groups({}, items) == ["import_file", "import_layers", "import_map"]


def test_the_public_policy_is_read_before_any_group_is_made(runner, tmp_path, team):
    GroupsApi(team, _service(team), existing=[])
    team.routes["GET /settings/feature-flags/"] = (500, _problem(500, "boom"))
    plan_file = _write(tmp_path, members=["agol_bob"])
    plan = json.loads(plan_file.read_text())
    for entry in plan["items"]:
        if entry["id"] == A1:
            entry["target"]["visibility"] = "public"
    plan_file.write_text(json.dumps(plan))

    result, _ = _run(runner, plan_file, "--only", A1)

    assert result.exit_code != 0
    assert not [
        s for s in team.seen if s.method == "POST" and "/admin/groups/" in s.url
    ]


def test_a_share_reads_the_grants_again_right_before_writing(monkeypatch):
    from geolens_cli import arcgis_migrate_refresh as refresh

    reads = iter([[{"id": EXISTING}], [{"id": OTHER}]])
    monkeypatch.setattr(
        refresh,
        "get_dataset",
        lambda ctx, dataset_id: SimpleNamespace(
            groups=[SimpleNamespace(id=g["id"]) for g in next(reads)]
        ),
    )
    sent: list[dict] = []
    geolens = SimpleNamespace(
        call=lambda fn, **kwargs: sent.append(kwargs["body"].to_dict())
    )
    ctx = SimpleNamespace(geolens=geolens, save=lambda: None, operator_id=OPERATOR)
    entry = ItemState(dataset_ids=[DATASETS[0]])

    share(ctx, {"target": {"geolens_groups": [CREATED]}}, entry)

    # A grant changed to OTHER after the first read is kept, not reverted.
    assert sent == [{"group_ids": sorted([CREATED, OTHER])}]


@pytest.mark.parametrize(
    ("change", "counted"),
    [("removed", False), ("private", False), ("unlisted", True)],
)
def test_pending_members_count_while_a_migrated_or_planned_item_needs_the_group(
    runner, tmp_path, team, change, counted
):
    service = _service(team)
    GroupsApi(team, service, existing=[])
    plan_file = _write(tmp_path, members=["agol_ghost"])
    assert _run(runner, plan_file)[0].exit_code == 0
    plan = json.loads(plan_file.read_text())
    for item in plan["items"]:
        if item["id"] == A2:
            if change == "private":
                item["target"]["visibility"] = "private"
            else:
                # A partial inventory marks a migrated item unlisted; its
                # GeoLens datasets keep the group's grant.
                item[change] = True
    plan_file.write_text(json.dumps(plan))

    _result, payload = _migrate(runner, plan_file, "--cutover", "--dry-run")

    checks = {c["check"] for c in payload["cutover"]["checks"]}
    assert ("unresolved-users" in checks) is counted
    state = MigrationState.load(
        tmp_path / "arcgis-migration-state.json",
        plan["portal"]["url"],
        GEOLENS_INSTANCE,
        Redactor(),
        persist=False,
    )
    report = build_run_report(plan, state)
    assert ("member_pending" in {f["kind"] for f in report["follow_ups"]}) is counted


# A rerun's sharing merge

GEO = "00000000-0000-0000-0005-00000000000a"
C, E = CREATED, EXISTING


@pytest.mark.parametrize(
    ("given", "granted", "current", "wanted", "read", "sent", "groups", "mine"),
    [
        ([C], [C], [C, GEO], [C, E], True, [C, E, GEO], [C, E], [C, E]),
        ([C, E], [C, E], [C, E, GEO], [C], True, [C, GEO], [C], [C]),
        ([C], [C], [C], [], True, [], None, None),
        ([C, E], [C, E], [C, E], [C], False, None, [C, E], [C, E]),
        ([C], [C], [], [C], True, None, [C], None),
        ([C], [C], [GEO], [], True, None, [C], None),
        ([], [], [GEO], [], True, None, None, None),
        ([], [], [GEO], [GEO], True, None, [GEO], None),
        ([GEO], [], [GEO], [], True, None, [GEO], None),
        ([C], [], [C], [], True, None, [C], None),
    ],
    ids=[
        "portal-adds-a-group",
        "portal-drops-a-group",
        "no-longer-group-only",
        "groups-not-read",
        "removed-in-geolens-stays-removed",
        "removed-in-geolens-then-dropped",
        "geolens-grant-alone",
        "group-already-there-isnt-its-own",
        "group-already-there-stays-when-dropped",
        "state-without-its-own-groups-removes-none",
    ],
)
def test_a_dataset_share_follows_the_target_and_keeps_geolens_grants(
    monkeypatch, given, granted, current, wanted, read, sent, groups, mine
):
    from geolens_cli import arcgis_migrate_refresh as refresh

    monkeypatch.setattr(
        refresh,
        "get_dataset",
        lambda ctx, dataset_id: SimpleNamespace(
            groups=[SimpleNamespace(id=g) for g in current]
        ),
    )
    puts: list[list[str]] = []
    geolens = SimpleNamespace(
        call=lambda fn, **kwargs: puts.append(kwargs["body"].to_dict()["group_ids"])
    )
    ctx = SimpleNamespace(geolens=geolens, save=lambda: None, operator_id=OPERATOR)
    ds = DATASETS[0]
    entry = ItemState(
        dataset_ids=[ds],
        groups={ds: given} if given else {},
        granted={ds: granted} if granted else {},
    )
    target = {"geolens_groups": wanted, "groups": ["g1"] if read else None}

    assert share(ctx, {"target": target}, entry) == []

    assert puts == ([] if sent is None else [sorted(sent)])
    assert entry.groups.get(ds) == groups
    assert entry.granted.get(ds) == mine


@pytest.mark.parametrize(
    ("visibility", "target", "current", "granted", "wanted", "sent"),
    [
        ("private", "private", [GEO, C], [C], [], None),
        ("private", "private", [C], [C], [], []),
        ("private", "restricted", [], [], [C], [C]),
        ("internal", "internal", [GEO, C], [C], [], [GEO]),
        ("restricted", "restricted", [GEO, C], [C], [E], [E, GEO]),
    ],
    ids=[
        "private-keeping-a-geolens-group",
        "private-losing-its-last-group",
        "private-becoming-restricted-as-planned",
        "internal-keeps-its-audience",
        "restricted-stays-restricted",
    ],
)
def test_a_dataset_share_never_makes_a_private_dataset_restricted_off_plan(
    monkeypatch, visibility, target, current, granted, wanted, sent
):
    from geolens_cli import arcgis_migrate_refresh as refresh

    monkeypatch.setattr(
        refresh,
        "get_dataset",
        lambda ctx, dataset_id: SimpleNamespace(
            groups=[SimpleNamespace(id=g) for g in current], visibility=visibility
        ),
    )
    puts: list[list[str]] = []
    ctx = SimpleNamespace(
        geolens=SimpleNamespace(
            call=lambda fn, **kw: puts.append(kw["body"].to_dict()["group_ids"])
        ),
        save=lambda: None,
        operator_id=OPERATOR,
    )
    ds = DATASETS[0]
    entry = ItemState(
        dataset_ids=[ds], groups={ds: granted} if granted else {}, granted={ds: granted}
    )
    item = {
        "target": {"visibility": target, "geolens_groups": wanted, "groups": ["g1"]}
    }

    if sent is None:
        with pytest.raises(ItemFailed, match="would make it restricted"):
            share(ctx, item, entry)
        assert puts == [] and entry.granted == {ds: granted}
    else:
        share(ctx, item, entry)
        assert puts == [sorted(sent)]


def test_a_dataset_group_removed_in_geolens_and_shared_again_is_theirs(monkeypatch):
    from geolens_cli import arcgis_migrate_refresh as refresh

    held: list[str] = []
    monkeypatch.setattr(
        refresh,
        "get_dataset",
        lambda ctx, dataset_id: SimpleNamespace(
            groups=[SimpleNamespace(id=g) for g in held]
        ),
    )
    puts: list = []
    ctx = SimpleNamespace(
        geolens=SimpleNamespace(call=lambda fn, **kw: puts.append(kw)),
        save=lambda: None,
        operator_id=OPERATOR,
    )
    ds = DATASETS[0]
    entry = ItemState(dataset_ids=[ds], groups={ds: [C]}, granted={ds: [C]})
    keep = {
        "target": {"visibility": "restricted", "geolens_groups": [C], "groups": ["g1"]}
    }
    # An admin removes the group; a rerun with nothing to change sees it.
    share(ctx, keep, entry)
    assert entry.granted == {} and entry.groups == {ds: [C]}
    # The admin shares it again by hand, and the plan then drops it.
    held.append(C)
    drop = {
        "target": {"visibility": "restricted", "geolens_groups": [], "groups": ["g1"]}
    }

    share(ctx, drop, entry)

    assert puts == []


def test_a_map_group_removed_in_geolens_and_shared_again_is_theirs(monkeypatch):
    ctx, puts, reads = _map_ctx(monkeypatch, _map_read("restricted", [C]))
    entry = ItemState(
        map_id=MAP, groups={MAP: [C, E]}, granted={MAP: [C, E]}, map_snapshot=dict(SEEN)
    )
    keep = {
        "target": {
            "visibility": "restricted",
            "geolens_groups": [C, E],
            "groups": ["g1"],
        }
    }
    assert share(ctx, keep, entry, with_map=False) == []
    assert entry.granted == {MAP: [C]}
    # The admin shares the map with E again by hand; the plan then drops E.
    reads["map"] = _map_read("restricted", [C, E])
    drop = {
        "target": {"visibility": "restricted", "geolens_groups": [C], "groups": ["g1"]}
    }

    assert share(ctx, drop, entry, with_map=False) == []

    assert puts == []


def test_a_private_map_is_never_made_restricted_off_plan(monkeypatch):
    ctx, puts, _reads = _map_ctx(monkeypatch, _map_read("private", [GEO, C]))
    entry = ItemState(
        map_id=MAP, groups={MAP: [C]}, granted={MAP: [C]}, map_snapshot=dict(SEEN)
    )
    item = {
        "target": {"visibility": "private", "geolens_groups": [E], "groups": ["g1"]}
    }

    [reason] = share(ctx, item, entry, with_map=False)

    assert "would make it restricted" in reason
    assert puts == []


def test_a_share_without_a_sharing_decision_changes_nothing():
    entry = ItemState(
        dataset_ids=[DATASETS[0]],
        groups={DATASETS[0]: [C]},
        granted={DATASETS[0]: [C]},
    )

    share(SimpleNamespace(), {"target": {"groups": ["g1"]}}, entry)

    assert entry.groups == entry.granted == {DATASETS[0]: [C]}


def test_a_dataset_changed_between_its_two_reads_isnt_shared(monkeypatch):
    from datetime import datetime

    from geolens_cli import arcgis_migrate_refresh as refresh

    def read(updated_at):
        return SimpleNamespace(
            groups=[],
            updated_at=datetime.fromisoformat(updated_at),
            feature_count=0,
            data_revision=1,
            updated_by=OPERATOR,
        )

    reads = iter([read(LEFT_AT), read("2026-10-02T00:00:00+00:00")])
    monkeypatch.setattr(refresh, "get_dataset", lambda ctx, d: next(reads))
    monkeypatch.setattr(refresh, "changed_in_geolens", lambda *args: None)
    puts: list = []
    ctx = SimpleNamespace(
        geolens=SimpleNamespace(call=lambda fn, **kw: puts.append(kw)),
        save=lambda: None,
        operator_id=OPERATOR,
    )
    entry = ItemState(dataset_ids=[DATASETS[0]], last_update={DATASETS[0]: {}})
    item = {"target": {"geolens_groups": [C], "groups": ["g1"]}}

    with pytest.raises(ItemFailed, match="changed in GeoLens while its groups"):
        share(ctx, item, entry)

    assert puts == [] and entry.groups == {}


LEFT_AT = "2026-10-01T00:00:00+00:00"
LATER = "2026-10-03T00:00:00+00:00"
MAP = "00000000-0000-0000-0006-000000000001"


def _map_read(visibility: str, groups: list[str], updated_at: str = LEFT_AT):
    from datetime import datetime

    return SimpleNamespace(
        created_by=OPERATOR,
        updated_at=datetime.fromisoformat(updated_at),
        visibility=visibility,
        groups=[SimpleNamespace(id=g) for g in groups],
    )


def _map_ctx(monkeypatch, found, after=None):
    """A ctx whose map reads *found* until a group write, then what *after*
    makes of the ids written (by default, what GeoLens would leave)."""
    from geolens_cli import arcgis_migrate_webmaps as webmaps

    reads = {"map": found}
    puts: list[list[str]] = []

    def put(fn, **kwargs):
        ids = kwargs["body"].to_dict()["group_ids"]
        puts.append(ids)
        before = reads["map"]
        if after is not None:
            reads["map"] = after(ids, before)
            return
        reads["map"] = _map_read("restricted" if ids else "private", ids)
        if reads["map"].visibility == before.visibility:
            reads["map"].updated_at = before.updated_at

    monkeypatch.setattr(webmaps, "get_map", lambda geolens, map_id: reads["map"])
    ctx = SimpleNamespace(
        geolens=SimpleNamespace(call=put), save=lambda: None, operator_id=OPERATOR
    )
    return ctx, puts, reads


SEEN = {"owner": OPERATOR, "updated_at": LEFT_AT}


@pytest.mark.parametrize(
    (
        "given",
        "granted",
        "wanted",
        "target",
        "found",
        "snapshot",
        "read",
        "sent",
        "reason",
    ),
    [
        (
            [C],
            [C],
            [C, E],
            "restricted",
            ("restricted", [C, GEO]),
            SEEN,
            True,
            [C, E, GEO],
            None,
        ),
        (
            [C, E],
            [C, E],
            [C],
            "restricted",
            ("restricted", [C, E]),
            SEEN,
            True,
            [C],
            None,
        ),
        ([], [], [C], "restricted", ("private", []), SEEN, True, [C], None),
        (
            [C],
            [C],
            [C, E],
            "restricted",
            ("restricted", [C]),
            {**SEEN, "updated_at": LATER},
            True,
            None,
            "changed in GeoLens since",
        ),
        (
            [C],
            [C],
            [C, E],
            "restricted",
            ("restricted", [C]),
            None,
            True,
            None,
            "doesn't record how this command left",
        ),
        (
            [C],
            [C],
            [C],
            "restricted",
            ("private", []),
            SEEN,
            True,
            None,
            "the GeoLens map is private",
        ),
        ([C], [C], [], "internal", ("internal", [C]), SEEN, True, None, None),
        (
            [C, GEO],
            [C],
            [C],
            "restricted",
            ("restricted", [C, GEO]),
            SEEN,
            True,
            None,
            None,
        ),
        (
            [C, E],
            [C, E],
            [C],
            "restricted",
            ("restricted", [C, E]),
            SEEN,
            False,
            None,
            None,
        ),
    ],
    ids=[
        "gains-a-group",
        "loses-a-group",
        "private-gains-its-first-group",
        "changed-in-geolens",
        "no-snapshot",
        "group-removed-in-geolens",
        "not-a-matter-of-groups",
        "geolens-grant-stays",
        "removals-wait-until-groups-are-read",
    ],
)
def test_a_rerun_shares_a_map_only_as_this_command_left_it(
    monkeypatch, given, granted, wanted, target, found, snapshot, read, sent, reason
):
    from geolens_cli import arcgis_migrate_webmaps as webmaps

    ctx, puts, reads = _map_ctx(monkeypatch, _map_read(*found))
    entry = ItemState(
        map_id=MAP,
        groups={MAP: given} if given else {},
        granted={MAP: granted} if granted else {},
        map_snapshot=snapshot,
    )
    groups = ["g1"] if read else None
    item = {
        "target": {"visibility": target, "geolens_groups": wanted, "groups": groups}
    }

    reasons = share(ctx, item, entry, with_map=False)

    assert puts == ([] if sent is None else [sorted(sent)])
    if reason is None:
        assert reasons == []
    else:
        [only] = reasons
        assert reason in only
    if sent is not None:
        assert entry.groups.get(MAP) == sorted(wanted)
        assert entry.granted.get(MAP) == sorted(set(sent) - {GEO})
        assert entry.map_snapshot == webmaps.map_state(reads["map"])


def test_a_group_geolens_shared_the_map_with_is_never_taken_as_its_own(monkeypatch):
    ctx, puts, _reads = _map_ctx(monkeypatch, _map_read("restricted", [C, GEO]))
    entry = ItemState(
        map_id=MAP, groups={MAP: [C]}, granted={MAP: [C]}, map_snapshot=dict(SEEN)
    )
    # The portal shares with the group GeoLens already gave the map.
    item = {
        "target": {
            "visibility": "restricted",
            "geolens_groups": [C, GEO],
            "groups": ["g1", "g2"],
        }
    }
    assert share(ctx, item, entry, with_map=False) == []
    # And drops it again.
    item = {
        "target": {"visibility": "restricted", "geolens_groups": [C], "groups": ["g1"]}
    }
    assert share(ctx, item, entry, with_map=False) == []

    assert puts == []
    assert entry.granted == {MAP: [C]}


def _changed_meanwhile(ids, before):
    # Someone else edits the map right after the write.
    return _map_read("restricted", ids, LATER)


def _flipped_by_someone_else(ids, before):
    return _map_read("internal", ids, LATER)


@pytest.mark.parametrize(
    ("found", "after", "adopted"),
    [
        (("private", []), None, True),
        (("restricted", [C]), None, True),
        (("restricted", [C]), _changed_meanwhile, False),
        (("private", []), _flipped_by_someone_else, False),
    ],
    ids=["flip-to-restricted", "no-flip", "edited-after-the-write", "other-visibility"],
)
def test_the_map_after_a_rerun_share_is_adopted_only_as_the_write_left_it(
    monkeypatch, found, after, adopted
):
    from geolens_cli import arcgis_migrate_webmaps as webmaps

    ctx, puts, reads = _map_ctx(monkeypatch, _map_read(*found), after)
    entry = ItemState(map_id=MAP, map_snapshot=dict(SEEN), groups={}, granted={})
    item = {
        "target": {
            "visibility": "restricted",
            "geolens_groups": [C, E],
            "groups": ["g1"],
        }
    }

    share(ctx, item, entry, with_map=False)

    assert puts
    expected = webmaps.map_state(reads["map"]) if adopted else SEEN
    assert entry.map_snapshot == expected


def test_a_map_changed_after_the_check_isnt_written(monkeypatch):
    from geolens_cli import arcgis_migrate_webmaps as webmaps

    reads = iter([_map_read("restricted", [C]), _map_read("restricted", [C], LATER)])
    monkeypatch.setattr(webmaps, "get_map", lambda geolens, map_id: next(reads))
    puts: list = []
    ctx = SimpleNamespace(
        geolens=SimpleNamespace(call=lambda fn, **kw: puts.append(kw)),
        save=lambda: None,
    )
    entry = ItemState(map_id=MAP, map_snapshot=dict(SEEN), groups={MAP: [C]})
    item = {
        "target": {
            "visibility": "restricted",
            "geolens_groups": [C, E],
            "groups": ["g1"],
        }
    }

    [reason] = share(ctx, item, entry, with_map=False)

    assert "changed in GeoLens while its groups were read" in reason
    assert puts == [] and entry.groups == {MAP: [C]}


def test_a_group_the_portal_stops_sharing_with_is_removed_on_a_rerun(
    runner, tmp_path, team, up_to_date
):
    service = _service(team)
    api = GroupsApi(
        team, service, existing=[_group(OTHER, "Other"), _group(GEO, "Geo")]
    )
    plan_file = _write(tmp_path, members=[])
    _map_a_second_group(plan_file)
    assert _run(runner, plan_file)[0].exit_code == 0
    # An admin shares the first dataset with another group in GeoLens.
    groups = service.fields[DATASETS[0]]["groups"]
    service.fields[DATASETS[0]]["groups"] = [*groups, {"id": GEO, "name": "Geo"}]
    plan = json.loads(plan_file.read_text())
    for item in plan["items"]:
        if item["id"] == A2:
            item["target"]["groups"] = ["g1"]
    plan_file.write_text(json.dumps(plan))

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert api.shares[-2:] == [
        (DATASETS[0], sorted([CREATED, GEO])),
        (DATASETS[1], [CREATED]),
    ]
    entry = _state(plan_file)["items"][A2]
    assert entry["groups"] == entry["granted"] == {d: [CREATED] for d in DATASETS}


def test_a_rerun_that_cant_share_says_which_groups_wait(
    runner, tmp_path, team, monkeypatch
):
    service = _service(team)
    api = GroupsApi(team, service, existing=[_group(OTHER, "Other")])
    plan_file = _write(tmp_path, members=[])
    assert _run(runner, plan_file)[0].exit_code == 0
    _map_a_second_group(plan_file)
    for action in migrate.REFRESHERS:
        monkeypatch.setitem(
            migrate.REFRESHERS,
            action,
            lambda ctx, item, entry: ["layer x was added to the service"],
        )
    shares = len(api.shares)

    result, payload = _run(runner, plan_file)

    assert result.exit_code == 1
    assert len(api.shares) == shares
    reasons = payload["not_up_to_date"][A2]
    assert reasons[0] == "layer x was added to the service"
    assert [r for r in reasons[1:] if f"add {OTHER}" in r and "waits" in r]


def _members_next_run(plan_file: Path, members: list[str] | None) -> None:
    inventory = plan_file.parent / "arcgis-inventory.json"
    report = json.loads(inventory.read_text())
    report["groups"][0]["members"] = members
    report["groups"][0]["members_unread"] = (
        None if members is not None else "the group hides its members"
    )
    inventory.write_text(json.dumps(report))


@pytest.mark.parametrize(
    ("members", "removed"),
    [
        (["agol_eve"], [BOB]),
        ([], [BOB, EVE]),
        (None, []),
        (["agol_bob", "agol_eve"], []),
        (["AGOL_BOB", "agol_eve"], []),
    ],
    ids=[
        "one-left",
        "all-left",
        "members-not-read",
        "still-members",
        "name-in-another-case",
    ],
)
def test_a_member_who_left_the_arcgis_group_is_removed_on_a_rerun(
    runner, tmp_path, team, up_to_date, members, removed
):
    service = _service(team)
    api = GroupsApi(team, service, existing=[])
    plan_file = _write(tmp_path, members=["agol_bob", "agol_eve"])
    assert _run(runner, plan_file)[0].exit_code == 0
    assert _state(plan_file)["groups"]["g1"]["joined"] == {
        BOB: ["agol_bob"],
        EVE: ["agol_eve"],
    }
    _members_next_run(plan_file, members)
    names = [{BOB: "bob", EVE: "agol_eve"}[u] for u in removed]
    _dry, preview = _run(runner, plan_file, "--dry-run")
    assert preview["groups"]["g1"]["removed"] == names and api.removed == []

    result, payload = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert api.removed == removed
    group = _state(plan_file)["groups"]["g1"]
    assert sorted(group["joined"]) == sorted({BOB, EVE} - set(removed))
    assert "removed" not in group
    assert payload["groups"]["g1"]["removed"] == names
    report = json.loads((tmp_path / "arcgis-migration-report.json").read_text())
    assert report["groups"][0]["members_removed"] == names

    # The next run reports no removal again.
    _result, payload = _run(runner, plan_file)
    assert payload["groups"]["g1"]["removed"] == []


@pytest.mark.parametrize(
    "why", ["deactivated", "name-matches-two-users", "owner-map-typo", "renamed"]
)
def test_a_member_still_listed_but_unresolved_is_not_removed(
    runner, tmp_path, team, up_to_date, why
):
    service = _service(team)
    api = GroupsApi(team, service, existing=[])
    plan_file = _write(tmp_path, members=["agol_bob"])
    assert _run(runner, plan_file)[0].exit_code == 0
    users = team.routes["GET /admin/users/"]["users"]
    bob = next(u for u in users if u["id"] == BOB)
    if why == "deactivated":
        bob.update(is_active=False, status="deactivated")
    elif why == "renamed":
        bob.update(username="robert", email="robert@example.org")
    elif why == "owner-map-typo":
        plan = json.loads(plan_file.read_text())
        plan["owner_map"]["agol_bob"] = "bobb"
        plan_file.write_text(json.dumps(plan))
    else:
        # Another account's email is bob's username, so "bob" means either.
        other = _user("00000000-0000-0000-0000-0000000000d0", "robert", ["viewer"])
        users.append({**other, "email": "bob"})
        team.routes["GET /admin/users/"]["total"] = len(users)

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert api.removed == []
    assert [p["member"] for p in _state(plan_file)["groups"]["g1"]["pending"]] == [
        "agol_bob"
    ]
    assert _state(plan_file)["groups"]["g1"]["joined"] == {BOB: ["agol_bob"]}


def test_a_member_added_in_geolens_stays_after_leaving_the_arcgis_group(
    runner, tmp_path, team, up_to_date
):
    service = _service(team)
    api = GroupsApi(team, service, existing=[])
    plan_file = _write(tmp_path, members=[])
    assert _run(runner, plan_file)[0].exit_code == 0
    # An admin adds bob in GeoLens before he joins the ArcGIS group.
    api.members[CREATED] = [BOB]
    _members_next_run(plan_file, ["agol_bob"])
    assert _run(runner, plan_file)[0].exit_code == 0
    group = _state(plan_file)["groups"]["g1"]
    assert group["joined"] == {} and group["added"] == [BOB]
    _members_next_run(plan_file, [])

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert api.removed == [] and api.members[CREATED] == [BOB]


def test_a_member_removed_in_geolens_isnt_added_again(
    runner, tmp_path, team, up_to_date
):
    service = _service(team)
    api = GroupsApi(team, service, existing=[])
    plan_file = _write(tmp_path, members=[])
    assert _run(runner, plan_file)[0].exit_code == 0
    api.members[CREATED] = [BOB]
    _members_next_run(plan_file, ["agol_bob"])
    assert _run(runner, plan_file)[0].exit_code == 0
    # The admin takes bob out again, on purpose.
    api.members[CREATED] = []

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert api.members[CREATED] == []
    assert _state(plan_file)["groups"]["g1"]["joined"] == {}


def test_a_member_removed_and_added_back_by_hand_is_theirs(
    runner, tmp_path, team, up_to_date
):
    service = _service(team)
    api = GroupsApi(team, service, existing=[])
    plan_file = _write(tmp_path, members=["agol_bob"])
    assert _run(runner, plan_file)[0].exit_code == 0
    api.members[CREATED] = []
    assert _run(runner, plan_file)[0].exit_code == 0
    assert api.members[CREATED] == []
    # The admin adds bob back by hand, and he then leaves the ArcGIS group.
    api.members[CREATED] = [BOB]
    _members_next_run(plan_file, [])

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert api.removed == [] and api.members[CREATED] == [BOB]


def test_a_member_removed_after_leaving_is_added_again_on_rejoining(
    runner, tmp_path, team, up_to_date
):
    service = _service(team)
    api = GroupsApi(team, service, existing=[])
    plan_file = _write(tmp_path, members=["agol_bob"])
    assert _run(runner, plan_file)[0].exit_code == 0
    _members_next_run(plan_file, [])
    assert _run(runner, plan_file)[0].exit_code == 0
    assert api.removed == [BOB] and api.members[CREATED] == []
    _members_next_run(plan_file, ["agol_bob"])

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert api.members[CREATED] == [BOB]
    assert _state(plan_file)["groups"]["g1"]["joined"] == {BOB: ["agol_bob"]}


def test_a_member_someone_removed_during_the_run_is_not_reported_as_removed(
    runner, tmp_path, team, up_to_date
):
    service = _service(team)
    api = GroupsApi(team, service, existing=[])
    plan_file = _write(tmp_path, members=["agol_bob"])
    assert _run(runner, plan_file)[0].exit_code == 0
    _members_next_run(plan_file, [])
    # Gone by the time the removal lands.
    team.routes[f"DELETE /admin/groups/{CREATED}/members/{BOB}"] = (
        404,
        _problem(404, "User is not a member of this group"),
    )

    result, payload = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert payload["groups"]["g1"]["removed"] == [] and api.removed == []
    group = _state(plan_file)["groups"]["g1"]
    assert group["joined"] == {} and group["added"] == [BOB]


@pytest.mark.parametrize("next_members", [[], None], ids=["read", "not-read"])
def test_members_a_v3_state_added_are_reported_once_and_kept(
    runner, tmp_path, team, up_to_date, next_members
):
    service = _service(team)
    api = GroupsApi(team, service, existing=[])
    plan_file = _write(tmp_path, members=["agol_bob"])
    assert _run(runner, plan_file)[0].exit_code == 0
    state_file = tmp_path / "arcgis-migration-state.json"
    state = json.loads(state_file.read_text())
    state["schema_version"] = "3"
    del state["groups"]["g1"]["joined"]
    state_file.write_text(json.dumps(state))
    _members_next_run(plan_file, next_members)

    result, payload = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert api.removed == []
    [warning] = [w for w in payload["group_warnings"] if "check them by hand" in w]
    assert "bob" in warning
    assert _state(plan_file)["schema_version"] == "4"

    # A later run that reads the members neither warns again nor removes bob.
    _members_next_run(plan_file, [])
    _result, payload = _run(runner, plan_file)
    assert not [w for w in payload["group_warnings"] if "check them by hand" in w]
    assert api.removed == []


def test_a_refused_member_removal_fails_the_run_and_is_tried_again(
    runner, tmp_path, team, up_to_date
):
    service = _service(team)
    api = GroupsApi(team, service, existing=[])
    plan_file = _write(tmp_path, members=["agol_bob"])
    assert _run(runner, plan_file)[0].exit_code == 0
    _members_next_run(plan_file, [])
    route = f"DELETE /admin/groups/{CREATED}/members/{BOB}"
    allowed = team.routes[route]
    team.routes[route] = (500, _problem(500, "boom"))

    result, payload = _run(runner, plan_file)

    assert result.exit_code == 1
    [failure] = payload["group_failures"]
    assert failure.startswith("removing a member who left ArcGIS group Planners")
    assert api.members[CREATED] == [BOB]
    assert _state(plan_file)["groups"]["g1"]["joined"] == {BOB: ["agol_bob"]}

    team.routes[route] = allowed
    assert _run(runner, plan_file)[0].exit_code == 0
    assert api.removed == [BOB]


@pytest.mark.parametrize(
    "joined",
    [
        {"not-a-uuid": ["agol_bob"]},
        {EVE: ["agol_eve"]},
        {BOB: "agol_bob"},
        [BOB],
    ],
    ids=["not-a-uuid", "not-in-added", "names-not-a-list", "not-a-map"],
)
def test_a_malformed_joined_record_is_refused(runner, tmp_path, team, joined):
    _service(team)
    plan_file = _write(tmp_path, members=[])
    (tmp_path / "arcgis-migration-state.json").write_text(
        json.dumps(
            {
                "schema_version": "4",
                "portal_url": json.loads(plan_file.read_text())["portal"]["url"],
                "geolens_instance": GEOLENS_INSTANCE,
                "groups": {
                    "g1": {
                        "id": CREATED,
                        "created": True,
                        "added": [BOB],
                        "joined": joined,
                    }
                },
                "items": {},
            }
        )
    )

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 2
    assert "malformed group record" in result.output
