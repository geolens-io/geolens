"""`geolens admin users import`: bulk user creation with generated passwords."""

from __future__ import annotations

import json
import stat
import string
from pathlib import Path

import httpx
import pytest

from geolens_cli import admin_users
from geolens_cli.main import app

from .arcgis_fake import inventory_report

NOW = "2026-10-01T00:00:00Z"
OPERATOR = "00000000-0000-0000-0000-0000000000a0"
OIDC = ["password", "oidc"]


def _capabilities(methods: list[str]) -> dict:
    return {
        "server": {"version": "1.28.0", "edition": "community"},
        "publish_contract": 1,
        "auth": {"password_login_enabled": "password" in methods, "methods": methods},
        "upload": None,
        "basemaps": [],
        "flags": {},
        "status_order": ["draft", "published"],
        "rate_limits": {"global_per_second": 10, "login_per_minute": 5},
        "me": None,
    }


def _user(user_id: str, username: str, email: str | None, roles: list[str]) -> dict:
    return {
        "id": user_id,
        "username": username,
        "email": email,
        "is_active": True,
        "status": "active",
        "last_login_at": None,
        "created_at": NOW,
        "roles": roles,
        "can_reset_password": True,
    }


class Users:
    """The admin user routes of a fake instance, recording what was created."""

    def __init__(self, fake, methods: list[str] | None = None) -> None:
        self.users = [
            _user(OPERATOR, "operator", "operator@example.org", ["admin"]),
            _user(
                "00000000-0000-0000-0000-0000000000a1",
                "alice",
                "Alice@Example.org",
                ["editor"],
            ),
        ]
        self.sent: list[dict] = []
        self.refuse: dict[str, tuple[int, dict]] = {}
        fake.routes["GET /capabilities/"] = _capabilities(methods or ["password"])
        fake.routes["GET /admin/users/"] = lambda seen: {
            "users": self.users,
            "total": len(self.users),
        }
        fake.routes["POST /admin/users/"] = self.create

    def create(self, seen):
        body = seen.json()
        self.sent.append(body)
        if body["username"] in self.refuse:
            return self.refuse[body["username"]]
        user = _user(
            f"00000000-0000-0000-0001-{len(self.sent):012d}",
            body["username"],
            body.get("email"),
            [body["role"]],
        )
        self.users.append(user)
        return (201, user)

    @property
    def passwords(self) -> list[str]:
        return [body["password"] for body in self.sent]


def _csv(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "users.csv"
    path.write_text(text, encoding="utf-8")
    return path


def _run(runner, *args: str):
    result = runner.invoke(app, ["--json", "admin", "users", "import", *args])
    payload = json.loads(result.stdout) if result.stdout.strip() else None
    return result, payload


ROWS = "username,email,role\nbob,bob@example.org,editor\ncarol,,\n"


def test_a_generated_password_meets_the_policy():
    passwords = {admin_users.generate_password() for _ in range(200)}

    assert len(passwords) == 200
    for password in passwords:
        assert len(password) == admin_users.PASSWORD_LENGTH
        assert len(password.encode("utf-8")) <= 72
        assert any(c in string.ascii_lowercase for c in password)
        assert any(c in string.ascii_uppercase for c in password)
        assert any(c in string.digits for c in password)
        assert any(not c.isalnum() for c in password)


def test_new_users_are_created_and_existing_ones_skipped(
    runner, tmp_path, fake_geolens
):
    users = Users(fake_geolens)
    path = _csv(
        tmp_path, ROWS + "Alice,,viewer\noperator,OPERATOR@example.org,viewer\n"
    )

    result, payload = _run(runner, str(path))

    assert result.exit_code == 0, result.output
    assert [(b["username"], b.get("email"), b["role"]) for b in users.sent] == [
        ("bob", "bob@example.org", "editor"),
        ("carol", None, "viewer"),
    ]
    assert [u["username"] for u in payload["skipped"]] == ["Alice", "operator"]
    assert [u["username"] for u in payload["created"]] == ["bob", "carol"]


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        ("alice,someone@example.org,viewer", "GeoLens user alice has another email"),
        ("dave,alice@example.org,viewer", "the email belongs to GeoLens user alice"),
    ],
    ids=["same-name-other-email", "other-name-same-email"],
)
def test_a_row_clashing_with_an_account_is_a_conflict(
    runner, tmp_path, fake_geolens, row, reason
):
    users = Users(fake_geolens)

    result, payload = _run(runner, str(_csv(tmp_path, f"username,email,role\n{row}\n")))

    assert result.exit_code == 1
    assert users.sent == []
    assert payload["skipped"] == []
    assert payload["conflicts"][0]["reason"] == reason


def test_passwords_are_shown_only_with_print_passwords(runner, tmp_path, fake_geolens):
    users = Users(fake_geolens)
    path = _csv(tmp_path, ROWS)

    result, payload = _run(runner, str(path))

    assert result.exit_code == 0, result.output
    assert all("password" not in u for u in payload["created"])
    assert not any(p in result.output for p in users.passwords)

    users.users = users.users[:2]
    result, payload = _run(runner, str(path), "--print-passwords")

    assert result.exit_code == 0, result.output
    assert [u["password"] for u in payload["created"]] == users.passwords[2:]


def test_passwords_never_reach_a_file_or_a_log(
    runner, tmp_path, tmp_xdg_home, fake_geolens
):
    users = Users(fake_geolens)
    path = _csv(tmp_path, ROWS)

    result = runner.invoke(
        app, ["-v", "admin", "users", "import", str(path), "--print-passwords"]
    )

    assert result.exit_code == 0, result.output
    assert len(users.passwords) == 2
    for root in (tmp_path, Path(tmp_xdg_home)):
        for file in root.rglob("*"):
            if file.is_file():
                text = file.read_bytes().decode("utf-8", "replace")
                assert not any(p in text for p in users.passwords), file


def test_a_refusal_echoing_the_password_is_redacted(runner, tmp_path, fake_geolens):
    users = Users(fake_geolens)

    def echo(seen):
        body = seen.json()
        users.sent.append(body)
        detail = [{"loc": ["body", "password"], "input": body["password"]}]
        return (422, {"title": "Invalid", "status": 422, "detail": detail})

    fake_geolens.routes["POST /admin/users/"] = echo

    result, payload = _run(runner, str(_csv(tmp_path, ROWS)))

    assert result.exit_code == 1
    assert len(payload["failed"]) == 2
    assert not any(p in result.output for p in users.passwords)
    assert "[REDACTED]" in payload["failed"][0]["error"]


def test_a_partial_failure_exits_1_after_creating_the_rest(
    runner, tmp_path, fake_geolens
):
    users = Users(fake_geolens)
    users.refuse["bob"] = (
        422,
        {"title": "Invalid", "status": 422, "detail": "Email is not valid"},
    )

    result, payload = _run(runner, str(_csv(tmp_path, ROWS)))

    assert result.exit_code == 1
    assert [u["username"] for u in payload["failed"]] == ["bob"]
    assert [u["username"] for u in payload["created"]] == ["carol"]


def test_an_oidc_instance_gets_no_users_without_link_by_email(
    runner, tmp_path, fake_geolens
):
    users = Users(fake_geolens, methods=OIDC)

    result, payload = _run(runner, str(_csv(tmp_path, ROWS)))

    assert result.exit_code == 0, result.output
    assert users.sent == []
    assert payload["identity_providers"] == ["oidc"]
    assert [u["username"] for u in payload["pending"]] == ["bob", "carol"]


def test_link_by_email_creates_users_that_have_an_email_and_shows_no_password(
    runner, tmp_path, fake_geolens
):
    users = Users(fake_geolens, methods=OIDC)

    result, payload = _run(runner, str(_csv(tmp_path, ROWS)), "--link-by-email")

    assert result.exit_code == 0, result.output
    assert [b["username"] for b in users.sent] == ["bob"]
    assert [u["username"] for u in payload["pending"]] == ["carol"]
    assert "password" not in payload["created"][0]
    assert not any(p in result.output for p in users.passwords)


@pytest.mark.parametrize(
    ("args", "methods"),
    [
        (["--link-by-email", "--print-passwords"], OIDC),
        (["--link-by-email"], ["password"]),
    ],
)
def test_link_by_email_misuse_is_refused(runner, tmp_path, fake_geolens, args, methods):
    users = Users(fake_geolens, methods=methods)

    result, _ = _run(runner, str(_csv(tmp_path, ROWS)), *args)

    assert result.exit_code == 2
    assert users.sent == []


@pytest.mark.parametrize(
    "text",
    [
        "bob,bob@example.org,editor\n",
        "username,email,role\nbob,,owner\n",
        "username,email,role\nbob,,\nBOB,,\n",
        "username,email,role\nx,,\n",
        "username,email,role\nbob,bob@example.org,editor,\n",
    ],
    ids=["no-header", "unknown-role", "repeated-user", "short-name", "extra-field"],
)
def test_a_malformed_csv_creates_nothing(runner, tmp_path, fake_geolens, text):
    users = Users(fake_geolens)

    result, _ = _run(runner, str(_csv(tmp_path, text)))

    assert result.exit_code == 2
    assert users.sent == []


def _inventory(tmp_path: Path) -> Path:
    report = inventory_report()
    report["groups"] = [
        {
            "id": "g1",
            "title": "Planning",
            "access": "org",
            "members": ["gis_admin", "planner_one"],
            "members_unread": None,
        },
        {
            "id": "g2",
            "title": "Hidden",
            "access": "private",
            "members": None,
            "members_unread": "hidden",
        },
    ]
    path = tmp_path / "arcgis-inventory.json"
    path.write_text(json.dumps(report))
    return path


def test_the_inventory_seeds_owners_as_editors_and_members_as_viewers(tmp_path):
    rows = admin_users.rows_from_inventory(json.loads(_inventory(tmp_path).read_text()))

    assert rows == [
        admin_users.Row("gis_admin", "gina.admin@example.org", "editor"),
        admin_users.Row("planner_one", None, "viewer"),
    ]


def test_seed_csv_writes_the_rows_privately_and_creates_nothing(
    runner, tmp_path, fake_geolens
):
    users = Users(fake_geolens)
    out = tmp_path / "seed.csv"

    result = runner.invoke(
        app,
        [
            "admin",
            "users",
            "import",
            "--from-inventory",
            str(_inventory(tmp_path)),
            "--seed-csv",
            str(out),
        ],
    )

    assert result.exit_code == 0, result.output
    assert out.read_text() == (
        "username,email,role\n"
        "gis_admin,gina.admin@example.org,editor\n"
        "planner_one,,viewer\n"
    )
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    assert users.sent == []
    assert admin_users.read_csv(out) == admin_users.rows_from_inventory(
        json.loads((tmp_path / "arcgis-inventory.json").read_text())
    )


def test_from_inventory_creates_its_users(runner, tmp_path, fake_geolens):
    users = Users(fake_geolens)

    result, _ = _run(runner, "--from-inventory", str(_inventory(tmp_path)))

    assert result.exit_code == 0, result.output
    assert [(b["username"], b["role"]) for b in users.sent] == [
        ("gis_admin", "editor"),
        ("planner_one", "viewer"),
    ]


def test_saml_counts_as_an_identity_provider(runner, tmp_path, fake_geolens):
    users = Users(fake_geolens, methods=["saml"])

    result, payload = _run(runner, str(_csv(tmp_path, ROWS)))

    assert result.exit_code == 0, result.output
    assert users.sent == []
    assert payload["identity_providers"] == ["saml"]


def test_a_dry_run_creates_nothing(runner, tmp_path, fake_geolens):
    users = Users(fake_geolens)

    result, payload = _run(runner, str(_csv(tmp_path, ROWS)), "--dry-run")

    assert result.exit_code == 0, result.output
    assert users.sent == []
    assert [u["username"] for u in payload["created"]] == ["bob", "carol"]
    assert all("password" not in u and "id" not in u for u in payload["created"])


def test_seed_csv_never_overwrites_a_file(runner, tmp_path, fake_geolens):
    Users(fake_geolens)
    out = tmp_path / "seed.csv"
    out.write_text("keep me\n")

    result = runner.invoke(
        app,
        [
            "admin",
            "users",
            "import",
            "--from-inventory",
            str(_inventory(tmp_path)),
            "--seed-csv",
            str(out),
        ],
    )

    assert result.exit_code == 2
    assert "already exists" in result.output
    assert out.read_text() == "keep me\n"


def test_seed_cells_a_spreadsheet_would_run_are_made_inert(tmp_path):
    out = tmp_path / "seed.csv"

    admin_users.write_seed(
        out,
        [
            admin_users.Row("=cmd|' /C calc'!A0", None, "viewer"),
            admin_users.Row("@sum", "+1@example.org", "viewer"),
            admin_users.Row("plain", "-x@example.org", "viewer"),
        ],
    )

    assert out.read_text().splitlines()[1:] == [
        "'=cmd|' /C calc'!A0,,viewer",
        "'@sum,'+1@example.org,viewer",
        "plain,'-x@example.org,viewer",
    ]


def test_an_unexpected_error_carrying_the_password_is_redacted(
    runner, tmp_path, fake_geolens, monkeypatch
):
    Users(fake_geolens)
    sent: list[str] = []

    def explode(geolens, row, password):
        sent.append(password)
        raise RuntimeError(f"connection reset while sending {password}")

    monkeypatch.setattr(admin_users, "_create", explode)

    result, _ = _run(runner, str(_csv(tmp_path, ROWS)))

    assert result.exit_code == 1
    assert sent and sent[0] not in result.output
    assert "[REDACTED]" in result.output


def test_ctrl_c_keeps_the_passwords_already_made(
    runner, tmp_path, fake_geolens, monkeypatch
):
    users = Users(fake_geolens)
    create = admin_users._create

    def interrupt_second(geolens, row, password):
        if users.sent:
            raise KeyboardInterrupt
        return create(geolens, row, password)

    monkeypatch.setattr(admin_users, "_create", interrupt_second)

    result, payload = _run(runner, str(_csv(tmp_path, ROWS)), "--print-passwords")

    assert result.exit_code == 130
    assert payload["stopped"] == "interrupted"
    assert [u["password"] for u in payload["created"]] == users.passwords


def test_a_transport_failure_still_shows_the_passwords_already_made(
    runner, tmp_path, fake_geolens
):
    users = Users(fake_geolens)
    create = users.create

    def drop_second(seen):
        if users.sent:
            users.sent.append(seen.json())
            raise httpx.ConnectTimeout("timed out")
        return create(seen)

    fake_geolens.routes["POST /admin/users/"] = drop_second

    result, payload = _run(runner, str(_csv(tmp_path, ROWS)), "--print-passwords")

    assert result.exit_code != 0
    assert payload["stopped"] == "stopped by a failed request"
    [made] = payload["created"]
    assert made["username"] == "bob" and made["password"] == users.passwords[0]
    assert users.passwords[1] not in result.output


def test_an_extra_field_is_refused_with_its_line(runner, tmp_path, fake_geolens):
    Users(fake_geolens)
    path = _csv(tmp_path, "username,email,role\ncarol,,\nbob,bob@example.org,editor,\n")

    result = runner.invoke(app, ["admin", "users", "import", str(path)])

    assert result.exit_code == 2
    assert "line 3 has more fields than the header's 3" in " ".join(
        result.output.split()
    )


def test_a_seed_keeps_rows_sharing_an_email_for_review(runner, tmp_path, fake_geolens):
    users = Users(fake_geolens)
    report = json.loads(_inventory(tmp_path).read_text())
    for row in report["items"]:
        if row["owner"] == "gis_admin":
            row["owner"], row["owner_email"] = "gina_personal", "gina@example.org"
            break
    report["items"].append({**report["items"][0], "id": "f0" * 16})
    report["items"][-1].update(owner="gina_admin", owner_email="gina@example.org")
    inventory = tmp_path / "shared-email-inventory.json"
    inventory.write_text(json.dumps(report))
    out = tmp_path / "seed.csv"

    seeded = runner.invoke(
        app,
        [
            "admin",
            "users",
            "import",
            "--from-inventory",
            str(inventory),
            "--seed-csv",
            str(out),
        ],
    )
    imported, _ = _run(runner, "--from-inventory", str(inventory))

    assert seeded.exit_code == 0, seeded.output
    lines = out.read_text().splitlines()
    assert "gina_admin,gina@example.org,editor" in lines
    assert "gina_personal,gina@example.org,editor" in lines
    assert imported.exit_code == 2
    assert users.sent == []
