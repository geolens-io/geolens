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
from geolens_cli.arcgis_migrate_state import ItemState

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
        self.service.fields.setdefault(dataset, {}).update(
            groups=refs, visibility="restricted"
        )
        return {"visibility": "restricted", "groups": refs, "metadata_warnings": None}


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
    ghost = "00000000-0000-0000-0000-0000000000c0"
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


def test_a_rerun_reports_a_group_its_map_lacks_and_records_none():
    entry = ItemState(map_id="m1", groups={"m1": [CREATED]})
    item = {"target": {"geolens_groups": [CREATED, EXISTING]}}

    reasons = share(SimpleNamespace(save=lambda: None), item, entry, with_map=False)

    assert EXISTING in reasons[0] and "share it by hand" in reasons[0]
    assert entry.groups == {"m1": [CREATED]}


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
    assert "wasn't shared with its new groups" in payload["not_up_to_date"][A2][0]


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
