"""`geolens arcgis migrate`: the import_layers action against a fake GeoLens."""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from geolens_cli import arcgis_migrate as migrate
from geolens_cli import arcgis_migrate_session as session
from geolens_cli import arcgis_plan as plan_mod
from geolens_cli.main import app

from .arcgis_fake import PORTAL, A1, A2, FakePortal, inventory_report, portal_routes
from .conftest import GEOLENS_INSTANCE

OPERATOR = "00000000-0000-0000-0000-0000000000a0"
NOW = "2026-10-01T00:00:00Z"
PROBE = "POST /services/probe/"
PREVIEW = "POST /services/preview/"
TOKEN_REFUSED = (
    "This service requires authentication. Provide a valid ArcGIS token and try again."
)


def _layer(layer_id: int, name: str, kind: str = "Feature Layer", **extra: Any) -> dict:
    return {
        "name": name,
        "title": name,
        "layer_id": layer_id,
        "source_layer_type": kind,
        "layer_type": "table" if kind == "Table" else "layer",
        "importable": kind in ("Feature Layer", "Table"),
        "object_id_field": "OBJECTID",
        **extra,
    }


class FakeImport:
    """Probe, preview, commit and job routes for one ArcGIS service."""

    def __init__(self, fake, layers: list[dict], *, needs_auth: bool = False) -> None:
        self.fake = fake
        self.layers = layers
        self.needs_auth = needs_auth
        self.job_errors: dict[str, str] = {}
        self.duplicates: dict[str, str] = {}
        self.previews = 0
        self.committed: set[str] = set()
        self.summaries: dict[str, str] = {}
        self.keywords: dict[str, list[str]] = {}
        self.fields: dict[str, dict[str, str]] = {}
        self.other_keywords: dict[str, list[dict]] = {}
        fake.routes[PROBE] = self.probe
        fake.routes[PREVIEW] = self.preview

    def _refused(self, seen) -> tuple | None:
        if self.needs_auth and not (seen.json() or {}).get("auth"):
            return (503, _problem(503, "a credential is required"))
        return None

    def probe(self, seen):
        return self._refused(seen) or {
            "service_type": "ArcGIS FeatureServer",
            "url": seen.json()["url"],
            "layers": self.layers,
            "selected_layer_id": None,
        }

    def preview(self, seen):
        refused = self._refused(seen)
        if refused:
            return refused
        name = seen.json()["layer_name"]
        for created in (dataset_id(name), self.duplicates.get(name)):
            if created:
                self._serve_dataset(created)
        if name in self.duplicates:
            detail = {
                "code": "duplicate_source",
                "message": "already registered",
                "existing_dataset_id": self.duplicates[name],
                "existing_title": name,
            }
            return (409, _problem(409, detail))
        self.previews += 1
        job = _uuid("0b", f"{name}{self.previews:02d}")
        error = self.job_errors.get(name)
        self.fake.routes[f"POST /ingest/commit/{job}"] = (
            lambda seen, n=name: self.commit(seen, n)
        )
        self.fake.routes[f"GET /jobs/{job}"] = (
            lambda _seen, n=name, j=job, e=error: self.job(j, n, e)
        )
        return {
            "job_id": job,
            "source_filename": name,
            "columns": [],
            "crs": 4326,
            "geometry_type": None,
            "feature_count": 1,
            "sample_rows": [],
            "layer_name": name,
        }

    def _serve_dataset(self, dataset: str) -> None:
        def patch(seen):
            body = seen.json()
            if "summary" in body:
                self.summaries[dataset] = body["summary"]
            self.fields.setdefault(dataset, {}).update(
                {
                    k: v
                    for k, v in body.items()
                    if k not in ("summary", "expected_updated_at")
                }
            )
            return self.dataset(dataset, body.get("owner_id", OPERATOR))

        def keyword(seen):
            words = self.keywords.setdefault(dataset, [])
            if seen.json()["keyword"] in words:
                return (409, _problem(409, "Duplicate keyword for this record"))
            words.append(seen.json()["keyword"])
            return (
                201,
                {
                    "id": _uuid("4e", seen.json()["keyword"]),
                    "record_id": dataset,
                    "keyword": seen.json()["keyword"],
                    "vocabulary_uri": None,
                    "keyword_type": "theme",
                },
            )

        self.fake.routes[f"PATCH /datasets/{dataset}"] = patch
        self.fake.routes[f"GET /datasets/{dataset}"] = lambda s: self.dataset(
            dataset, OPERATOR
        )
        self.fake.routes[f"POST /records/{dataset}/keywords/"] = keyword
        self.fake.routes[f"GET /records/{dataset}/keywords/"] = lambda s: {
            "keywords": [
                {
                    "id": _uuid("4e", word),
                    "record_id": dataset,
                    "keyword": word,
                    "vocabulary_uri": None,
                    "keyword_type": "theme",
                    "inherited": False,
                }
                for word in self.keywords.get(dataset, [])
            ]
            + self.other_keywords.get(dataset, []),
            "total": len(self.keywords.get(dataset, [])),
        }

    def dataset(self, dataset: str, owner: str) -> dict:
        return {
            **_dataset(dataset, owner),
            "summary": self.summaries.get(dataset),
            **self.fields.get(dataset, {}),
        }

    def commit(self, seen, name: str):
        refused = self._refused(seen)
        if refused:
            return refused
        job = seen.url.rsplit("/", 1)[-1]
        if job in self.committed:
            return (400, _problem(400, "Job already processed"))
        self.committed.add(job)
        # The dataset the job makes takes the commit's visibility.
        self.fields.setdefault(dataset_id(name), {})["visibility"] = seen.json()[
            "visibility"
        ]
        return (202, {"job_id": job, "status": "pending", "message": "queued"})

    def job(self, job_id: str, name: str, error: str | None) -> dict:
        return {
            "id": job_id,
            "status": "failed" if error else "complete",
            "dataset_id": None if error else dataset_id(name),
            "source_filename": name,
            "error_message": error,
            "can_retry": False,
            "retry_reason": None,
            "started_at": NOW,
            "completed_at": NOW,
            "created_at": NOW,
        }

    def bodies(self, route_prefix: str) -> list[dict]:
        return [
            s.json()
            for s in self.fake.seen
            if f"{s.method} {s.url.split('/api', 1)[1]}".startswith(route_prefix)
        ]


def _uuid(prefix: str, name: str) -> str:
    digits = (prefix + name.encode().hex() + "0" * 32)[:32]
    return f"{digits[:8]}-{digits[8:12]}-{digits[12:16]}-{digits[16:20]}-{digits[20:]}"


def dataset_id(name: str) -> str:
    return _uuid("da", name)


def _dataset(dataset: str, owner: str) -> dict:
    return {
        "id": dataset,
        "record_id": dataset,
        "table_name": "t",
        "title": "t",
        "summary": None,
        "feature_count": 0,
        "source_filename": None,
        "visibility": "private",
        "created_by": owner,
        "created_by_display": None,
        "created_at": NOW,
        "updated_at": NOW,
        "updated_by": OPERATOR,
        "data_revision": 0,
    }


def _problem(status: int, detail: Any) -> dict:
    return {"title": "Error", "status": status, "detail": detail}


@pytest.fixture
def geolens(fake_geolens):
    operator = {
        "id": OPERATOR,
        "username": "operator",
        "email": "operator@example.org",
        "is_active": True,
        "status": "active",
        "last_login_at": None,
        "created_at": NOW,
        "roles": ["admin"],
        "can_reset_password": False,
    }
    fake_geolens.routes.update(
        {
            "GET /auth/me/": operator,
            "GET /admin/users/": {"users": [operator], "total": 1},
            "GET /settings/all/": (403, _problem(403, "no")),
        }
    )
    return fake_geolens


def _write_plan(
    tmp_path: Path,
    urls: dict[str, str] | None = None,
    portal: dict | None = None,
    rows: dict[str, dict] | None = None,
) -> Path:
    report = inventory_report()
    report["portal"].update(portal or {})
    for row in report["items"]:
        row["url"] = (urls or {}).get(row["id"], row["url"])
        row.update((rows or {}).get(row["id"], {}))
    (tmp_path / "arcgis-inventory.json").write_text(json.dumps(report))
    plan = plan_mod.build_plan(
        report,
        inventory_path="arcgis-inventory.json",
        owner_map={"gis_admin": "operator"},
    )
    path = tmp_path / "arcgis-migration-plan.json"
    path.write_text(json.dumps(plan))
    return path


@pytest.fixture
def plan_file(tmp_path) -> Path:
    return _write_plan(tmp_path)


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    for name in ("ARCGIS_TOKEN", "ARCGIS_PASSWORD"):
        monkeypatch.delenv(name, raising=False)


def _migrate(runner, plan_file: Path, *args: str, env: dict | None = None):
    result = runner.invoke(
        app, ["--json", "arcgis", "migrate", str(plan_file), *args], env=env
    )
    payload = json.loads(result.stdout) if result.stdout.strip() else None
    return result, payload


def _state(plan_file: Path) -> dict:
    return json.loads((plan_file.parent / "arcgis-migration-state.json").read_text())


def test_a_two_layer_service_becomes_two_datasets(runner, plan_file, geolens):
    service = FakeImport(geolens, [_layer(0, "Parcels"), _layer(1, "Owners", "Table")])

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert [c["title"] for c in service.bodies("POST /ingest/commit/")] == [
        "Parcels (public view) - Parcels",
        "Parcels (public view) - Owners",
    ]
    assert all(
        c["visibility"] == "public" for c in service.bodies("POST /ingest/commit/")
    )
    entry = _state(plan_file)["items"][A2]
    assert entry["status"] == "done"
    assert entry["dataset_ids"] == [dataset_id("Parcels"), dataset_id("Owners")]
    assert payload["items"][0]["status"] == "done"


def test_two_layers_with_the_same_name_get_their_layer_ids_in_the_title(
    runner, plan_file, geolens
):
    service = FakeImport(geolens, [_layer(0, "Parcels"), _layer(3, "Parcels")])

    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert [c["title"] for c in service.bodies("POST /ingest/commit/")] == [
        "Parcels (public view) - Parcels (0)",
        "Parcels (public view) - Parcels (3)",
    ]


def test_a_layer_named_like_a_tagged_title_is_tagged_too(runner, plan_file, geolens):
    service = FakeImport(
        geolens,
        [_layer(0, "Parcels"), _layer(3, "Parcels"), _layer(5, "Parcels (0)")],
    )

    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert [c["title"] for c in service.bodies("POST /ingest/commit/")] == [
        "Parcels (public view) - Parcels (0)",
        "Parcels (public view) - Parcels (3)",
        "Parcels (public view) - Parcels (0) (5)",
    ]


def test_a_public_item_sends_no_credential(runner, plan_file, geolens):
    service = FakeImport(geolens, [_layer(0, "Parcels")])
    token = secrets.token_urlsafe(16)

    result, _ = _migrate(runner, plan_file, "--only", A2, "--token", token)

    assert result.exit_code == 0, result.output
    bodies = [*service.bodies(PROBE), *service.bodies(PREVIEW)]
    assert bodies and all("auth" not in b for b in bodies)


def test_a_private_item_carries_the_token_on_probe_preview_and_commit(
    runner, plan_file, geolens
):
    service = FakeImport(geolens, [_layer(0, "Parcels")], needs_auth=True)
    token = secrets.token_urlsafe(16)

    result, _ = _migrate(runner, plan_file, "--only", A1, "--token", token)

    assert result.exit_code == 0, result.output
    auth = {"method": "bearer", "token": token}
    for route in (PROBE, PREVIEW, "POST /ingest/commit/"):
        [body] = service.bodies(route)
        assert body["auth"] == auth, route
    raw = (plan_file.parent / "arcgis-migration-state.json").read_text()
    assert token not in raw and token not in result.output


def test_a_private_item_without_a_credential_stops_before_any_request(
    runner, plan_file, geolens
):
    result, _ = _migrate(runner, plan_file, "--only", A1)

    assert result.exit_code == 2
    assert "not public" in result.output
    assert geolens.seen == []


def test_group_and_raster_layers_are_skipped_with_a_note(runner, plan_file, geolens):
    service = FakeImport(
        geolens,
        [
            _layer(0, "Districts", "Group Layer"),
            _layer(1, "Parcels", parent_layer_id=0),
            _layer(2, "Imagery", "Raster Layer"),
        ],
    )

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert [b["layer_name"] for b in service.bodies(PREVIEW)] == ["Parcels"]
    [commit] = service.bodies("POST /ingest/commit/")
    assert commit["title"] == "Parcels (public view)"
    notes = _state(plan_file)["items"][A2]["notes"]
    assert notes == [
        "Districts: Group Layer layer, not imported",
        "Imagery: Raster Layer layer, not imported",
    ]
    assert payload["items"][0]["notes"] == notes


def test_a_service_with_nothing_to_import_is_done_and_imports_nothing_on_a_rerun(
    runner, plan_file, geolens
):
    service = FakeImport(geolens, [_layer(0, "Imagery", "Raster Layer")])
    result, _ = _migrate(runner, plan_file, "--only", A2)
    assert result.exit_code == 0, result.output
    entry = _state(plan_file)["items"][A2]
    assert entry["status"] == "done" and entry["dataset_ids"] == []
    assert "the service has no layer to import" in entry["notes"]

    result, payload = _migrate(runner, plan_file, "--only", A2)
    assert result.exit_code == 0, result.output
    assert payload["not_up_to_date"] == {}
    assert service.bodies(PREVIEW) == []


def test_layers_geolens_already_holds_make_the_item_exist(runner, plan_file, geolens):
    service = FakeImport(geolens, [_layer(0, "Parcels")])
    service.duplicates["Parcels"] = dataset_id("earlier")

    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    entry = _state(plan_file)["items"][A2]
    assert entry["status"] == "exists"
    assert entry["dataset_ids"] == [dataset_id("earlier")]
    assert service.bodies("POST /ingest/commit/") == []
    patches = [s.json() for s in geolens.seen if s.method == "PATCH"]
    assert patches[0] == {
        "title": "Parcels (public view)",
        "visibility": "public",
        "expected_updated_at": "2026-10-01T00:00:00+00:00",
    }


def test_a_target_write_geolens_refuses_as_stale_fails_the_item(
    runner, plan_file, geolens
):
    service = FakeImport(geolens, [_layer(0, "Parcels")])
    service.duplicates["Parcels"] = dataset_id("earlier")
    serve = service._serve_dataset

    def serve_stale(dataset: str) -> None:
        serve(dataset)
        geolens.routes[f"PATCH /datasets/{dataset}"] = (
            409,
            _problem(409, {"code": "stale_write", "message": "changed"}),
        )

    service._serve_dataset = serve_stale

    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    entry = _state(plan_file)["items"][A2]
    assert entry["status"] == "failed"
    assert entry["error"] == (
        "changed in GeoLens while the plan's title and visibility were written to "
        f"dataset {dataset_id('earlier')}; it was left as it is"
    )


def test_a_failed_job_fails_the_item_with_its_error(runner, plan_file, geolens):
    service = FakeImport(geolens, [_layer(0, "Parcels")])
    service.job_errors["Parcels"] = "ogr2ogr could not read layer 0"

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    entry = _state(plan_file)["items"][A2]
    assert entry["status"] == "failed"
    assert "ogr2ogr could not read layer 0" in entry["error"]
    assert entry["job_ids"]
    assert payload["items"][0]["error"] == entry["error"]


def test_a_rerun_does_not_import_a_layer_again(runner, plan_file, geolens):
    service = FakeImport(geolens, [_layer(0, "Parcels"), _layer(1, "Owners")])
    service.job_errors["Owners"] = "boom"
    _migrate(runner, plan_file, "--only", A2)
    assert _state(plan_file)["items"][A2]["layer_datasets"] == {
        "0": dataset_id("Parcels")
    }
    del service.job_errors["Owners"]
    geolens.seen.clear()

    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert [b["layer_name"] for b in service.bodies(PREVIEW)] == ["Owners"]
    assert _state(plan_file)["items"][A2]["dataset_ids"] == [
        dataset_id("Parcels"),
        dataset_id("Owners"),
    ]


def test_a_rejected_pasted_token_stops_the_run(runner, plan_file, geolens):
    service = FakeImport(geolens, [_layer(0, "Parcels")], needs_auth=True)
    geolens.routes[PREVIEW] = (403, _problem(403, TOKEN_REFUSED))
    token = secrets.token_urlsafe(16)

    result, payload = _migrate(runner, plan_file, "--only", A1, "--token", token)

    assert result.exit_code == 1
    assert "fresh token" in payload["stopped"]
    assert _state(plan_file)["items"][A1]["status"] == "failed"
    assert service.bodies("POST /ingest/commit/") == []


def test_an_instance_refusing_token_imports_stops_the_run(runner, plan_file, geolens):
    FakeImport(geolens, [_layer(0, "Parcels")], needs_auth=True)
    geolens.routes[PREVIEW] = (
        503,
        _problem(
            503,
            {
                "code": "credential_store_unavailable",
                "message": "Token-bearing imports need REDIS_URL on this instance.",
            },
        ),
    )

    result, payload = _migrate(
        runner, plan_file, "--only", A1, "--token", secrets.token_urlsafe(16)
    )

    assert result.exit_code == 1
    assert "Token-bearing imports need REDIS_URL" in payload["stopped"]


def test_a_password_token_is_renewed_once_after_a_rejection(
    runner, plan_file, geolens, monkeypatch
):
    portal = FakePortal(portal_routes())
    monkeypatch.setattr(migrate, "build_opener", lambda: portal)
    service = FakeImport(geolens, [_layer(0, "Parcels")], needs_auth=True)
    preview = service.preview
    replies = [(403, _problem(403, TOKEN_REFUSED)), preview]
    geolens.routes[PREVIEW] = lambda seen: (
        replies.pop(0) if isinstance(replies[0], tuple) else replies[0](seen)
    )
    password = secrets.token_urlsafe(16)

    result, _ = _migrate(
        runner,
        plan_file,
        "--only",
        A1,
        "--username",
        "gis_admin",
        env={"ARCGIS_PASSWORD": password},
    )

    assert result.exit_code == 0, result.output
    assert len(portal.requests_to("generateToken")) == 2
    # The run contacts only the plan's portal and GeoLens.
    assert {urlsplit(s.url).hostname for s in portal.seen} == {
        urlsplit(PORTAL).hostname
    }
    assert {urlsplit(s.url).hostname for s in geolens.seen} == {
        urlsplit(GEOLENS_INSTANCE).hostname
    }
    raw = (plan_file.parent / "arcgis-migration-state.json").read_text()
    assert password not in raw and password not in result.output


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_a_password_token_is_renewed_before_it_expires():
    renewals: list[int] = []

    class Client:
        token = "first"

        def renew_token(self) -> bool:
            renewals.append(1)
            self.token = "second"
            return True

    clock = _Clock()
    auth = session.PortalAuth(Client(), renewable=True, clock=clock)
    clock.now = 57 * 60
    assert auth.service_auth().token == "first"
    clock.now = 59 * 60
    assert auth.service_auth().token == "second"
    assert renewals == [1]


def test_a_pasted_token_is_never_renewed():
    class Client:
        token = "pasted"

        def renew_token(self) -> bool:
            raise AssertionError("must not renew")

    clock = _Clock()
    auth = session.PortalAuth(Client(), renewable=False, clock=clock)
    clock.now = 10 * 3600
    assert auth.service_auth().token == "pasted"
    assert auth.renew() is False


@pytest.mark.parametrize(
    "reply",
    [
        (403, _problem(403, "Insufficient permissions")),
        (503, _problem(503, "Service temporarily unavailable")),
    ],
)
def test_other_refusals_fail_the_item_without_stopping(
    runner, plan_file, geolens, reply
):
    FakeImport(geolens, [_layer(0, "Parcels")], needs_auth=True)
    geolens.routes[PREVIEW] = reply

    result, payload = _migrate(
        runner, plan_file, "--only", A1, "--token", secrets.token_urlsafe(16)
    )

    assert result.exit_code == 1
    assert payload["stopped"] is None
    assert _state(plan_file)["items"][A1]["status"] == "failed"


FOREIGN = "https://collector.example.net/arcgis/rest/services/Parcels/FeatureServer"


def test_the_token_is_not_sent_to_a_host_outside_the_organization(
    runner, tmp_path, geolens
):
    plan_file = _write_plan(tmp_path, {A1: FOREIGN})
    service = FakeImport(geolens, [_layer(0, "Parcels")])
    token = secrets.token_urlsafe(16)

    result, _ = _migrate(runner, plan_file, "--only", A1, "--token", token)

    assert result.exit_code == 1
    assert all(token not in s.body.decode() for s in geolens.seen)
    assert service.bodies(PROBE) == []
    error = _state(plan_file)["items"][A1]["error"]
    assert error.startswith("the service host collector")
    assert "is not one of the organization's servers" in error


def test_a_named_federated_host_receives_the_token(runner, tmp_path, geolens):
    plan_file = _write_plan(tmp_path, {A1: FOREIGN})
    service = FakeImport(geolens, [_layer(0, "Parcels")], needs_auth=True)
    token = secrets.token_urlsafe(16)

    result, _ = _migrate(
        runner,
        plan_file,
        "--only",
        A1,
        "--token",
        token,
        "--trust-service-host",
        "collector.example.net",
    )

    assert result.exit_code == 0, result.output
    [probe] = service.bodies(PROBE)
    assert probe["auth"]["token"] == token


def test_the_token_does_not_follow_a_probe_url_to_another_host(
    runner, plan_file, geolens
):
    service = FakeImport(geolens, [_layer(0, "Parcels")], needs_auth=True)
    probe = service.probe
    geolens.routes[PROBE] = lambda seen: {**probe(seen), "url": FOREIGN}
    token = secrets.token_urlsafe(16)

    result, _ = _migrate(runner, plan_file, "--only", A1, "--token", token)

    assert result.exit_code == 1
    assert service.bodies(PREVIEW) == []
    assert (
        "not one of the organization's servers"
        in (_state(plan_file)["items"][A1]["error"])
    )


def test_an_inventory_of_another_organization_is_refused(runner, plan_file, geolens):
    plan = json.loads(plan_file.read_text())
    plan["inventory"]["scope"]["org_id"] = "AnotherOrg000"
    plan_file.write_text(json.dumps(plan))

    result, _ = _migrate(
        runner,
        plan_file,
        "--only",
        A1,
        "--username",
        "gis_admin",
        env={"ARCGIS_PASSWORD": secrets.token_urlsafe(16)},
    )

    assert result.exit_code == 2
    assert "ArcGIS organization" in result.output
    assert geolens.seen == []


def test_a_plan_for_another_portal_than_its_inventory_is_refused(
    runner, plan_file, geolens
):
    plan = json.loads(plan_file.read_text())
    plan["portal"]["url"] = "https://elsewhere.example.org"
    plan_file.write_text(json.dumps(plan))
    (plan_file.parent / "arcgis-migration-state.json").unlink(missing_ok=True)

    result, _ = _migrate(
        runner,
        plan_file,
        "--only",
        A1,
        "--username",
        "gis_admin",
        env={"ARCGIS_PASSWORD": secrets.token_urlsafe(16)},
    )

    assert result.exit_code == 2
    assert "doesn't match the portal of the inventory" in result.output
    assert geolens.seen == []


def test_a_token_echoed_by_geolens_is_redacted_everywhere(runner, plan_file, geolens):
    FakeImport(geolens, [_layer(0, "Parcels")], needs_auth=True)
    token = secrets.token_urlsafe(16)
    geolens.routes[PREVIEW] = (
        503,
        _problem(
            503,
            {"code": "credential_store_unavailable", "message": f"rejected {token}"},
        ),
    )

    result, payload = _migrate(runner, plan_file, "--only", A1, "--token", token)

    assert result.exit_code == 1
    raw = (plan_file.parent / "arcgis-migration-state.json").read_text()
    assert "rejected [REDACTED]" in raw and token not in raw
    assert "rejected [REDACTED]" in payload["stopped"]
    assert token not in result.output


def test_an_item_error_echoing_the_token_is_redacted(runner, plan_file, geolens):
    FakeImport(geolens, [_layer(0, "Parcels")], needs_auth=True)
    token = secrets.token_urlsafe(16)
    geolens.routes[PREVIEW] = (400, _problem(400, f"bad layer for token {token}"))

    result, _ = _migrate(runner, plan_file, "--only", A1, "--token", token)

    assert result.exit_code == 1
    error = _state(plan_file)["items"][A1]["error"]
    assert "token [REDACTED]" in error and token not in error
    assert token not in result.output


ORG_SERVICES = "https://services1.arcgis.com/ExAmPlEoRg0123/arcgis/rest/services"


@pytest.mark.parametrize(
    ("url", "portal"),
    [
        (ORG_SERVICES.replace("https:", "http:") + "/Parcels/FeatureServer", None),
        (
            ORG_SERVICES + "/../../../OtherOrg/arcgis/rest/services/P/FeatureServer",
            None,
        ),
        (
            ORG_SERVICES
            + "/%2e%2e/%2e%2e/%2e%2e/OtherOrg/arcgis/rest/services/P/FeatureServer",
            None,
        ),
        (
            "https://services9.arcgis.com/OtherOrg/arcgis/rest/services/P/FeatureServer",
            None,
        ),
        (
            "https://services1.arcgis.com/exampleorg0123/arcgis/rest/services/P/FeatureServer",
            None,
        ),
        (
            "https://gis-other.example.org/arcgis/rest/services/P/FeatureServer",
            {"kind": "enterprise", "org_id": None},
        ),
    ],
    ids=[
        "http",
        "dot-dot",
        "encoded-dot-dot",
        "other-org",
        "org-case",
        "enterprise-host",
    ],
)
def test_the_token_is_withheld_from_untrusted_service_urls(
    runner, tmp_path, geolens, url, portal
):
    plan_file = _write_plan(tmp_path, {A1: url}, portal)
    service = FakeImport(geolens, [_layer(0, "Parcels")])
    token = secrets.token_urlsafe(16)

    result, _ = _migrate(runner, plan_file, "--only", A1, "--token", token)

    assert result.exit_code == 1, result.output
    assert service.bodies(PROBE) == []
    assert all(token not in s.body.decode() for s in geolens.seen)
    assert (
        "not one of the organization's servers"
        in (_state(plan_file)["items"][A1]["error"])
    )


@pytest.mark.parametrize(
    "host", ["", "collector.example.net/x", "collector.example.net:443"]
)
def test_a_trusted_host_must_be_a_bare_host_name(runner, plan_file, geolens, host):
    result, _ = _migrate(
        runner,
        plan_file,
        "--only",
        A1,
        "--token",
        secrets.token_urlsafe(16),
        "--trust-service-host",
        host,
    )
    assert result.exit_code == 2
    assert "bare host name" in result.output
    assert geolens.seen == []


def test_a_job_committed_before_a_crash_is_resumed_not_repeated(
    runner, plan_file, geolens
):
    service = FakeImport(geolens, [_layer(0, "Parcels")])
    preview = service.preview
    finished: dict[str, Any] = {}

    def crash(_seen):
        raise KeyboardInterrupt

    def preview_then_crash_on_poll(seen):
        reply = preview(seen)
        route = f"GET /jobs/{reply['job_id']}"
        finished[route] = geolens.routes[route]
        geolens.routes[route] = crash
        return reply

    geolens.routes[PREVIEW] = preview_then_crash_on_poll
    result, _ = _migrate(runner, plan_file, "--only", A2)
    assert result.exit_code == 130
    entry = _state(plan_file)["items"][A2]
    assert len(entry["layer_jobs"]) == 1 and entry["layer_datasets"] == {}

    geolens.routes.update(finished)
    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert len(service.bodies(PREVIEW)) == 1
    entry = _state(plan_file)["items"][A2]
    assert entry["layer_datasets"] == {"0": dataset_id("Parcels")}
    assert entry["layer_jobs"] == {}


def test_a_committed_job_that_failed_is_replaced_on_resume(runner, plan_file, geolens):
    service = FakeImport(geolens, [_layer(0, "Parcels")])
    service.job_errors["Parcels"] = "the worker restarted"
    _migrate(runner, plan_file, "--only", A2)
    assert _state(plan_file)["items"][A2]["layer_jobs"]
    del service.job_errors["Parcels"]

    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert len(service.bodies(PREVIEW)) == 2
    assert _state(plan_file)["items"][A2]["layer_jobs"] == {}


def test_pins_from_another_service_are_not_reused(runner, plan_file, geolens):
    service = FakeImport(geolens, [_layer(0, "Parcels")])
    _migrate(runner, plan_file, "--only", A2)
    state_path = plan_file.parent / "arcgis-migration-state.json"
    state = json.loads(state_path.read_text())
    entry = state["items"][A2]
    assert entry["service_url"]
    entry["service_url"] = (
        "https://services.example.org/arcgis/rest/services/Old/FeatureServer"
    )
    entry["status"] = "pending"
    state_path.write_text(json.dumps(state))

    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert len(service.bodies(PREVIEW)) == 2
    assert _state(plan_file)["items"][A2]["service_url"] != entry["service_url"]


def test_pins_survive_a_replacement_service_that_fails_to_probe(
    runner, plan_file, geolens
):
    service = FakeImport(geolens, [_layer(0, "Parcels")])
    _migrate(runner, plan_file, "--only", A2)
    state_path = plan_file.parent / "arcgis-migration-state.json"
    state = json.loads(state_path.read_text())
    entry = state["items"][A2]
    old = "https://services.example.org/arcgis/rest/services/Old/FeatureServer"
    entry["service_url"] = old
    entry["status"] = "pending"
    state_path.write_text(json.dumps(state))
    service.needs_auth = True

    _migrate(runner, plan_file, "--only", A2)

    after = _state(plan_file)["items"][A2]
    assert after["layer_datasets"] == {"0": dataset_id("Parcels")}
    assert after["service_url"] == old


def test_pins_without_a_recorded_service_are_kept(runner, plan_file, geolens):
    service = FakeImport(geolens, [_layer(0, "Parcels")])
    _migrate(runner, plan_file, "--only", A2)
    state_path = plan_file.parent / "arcgis-migration-state.json"
    state = json.loads(state_path.read_text())
    del state["items"][A2]["service_url"]
    state["items"][A2]["status"] = "pending"
    state_path.write_text(json.dumps(state))

    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert len(service.bodies(PREVIEW)) == 1
    assert _state(plan_file)["items"][A2]["service_url"]


def test_a_public_selection_reads_no_credential(runner, plan_file, geolens):
    FakeImport(geolens, [_layer(0, "Parcels")])
    result, _ = _migrate(
        runner, plan_file, "--only", A2, "--username", "gis_admin", "--password-stdin"
    )
    assert result.exit_code == 0, result.output


def test_an_inventory_rewritten_after_the_plan_is_refused(runner, plan_file, geolens):
    path = plan_file.parent / "arcgis-inventory.json"
    report = json.loads(path.read_text())
    report["generated_at"] = "2026-10-02T00:00:00Z"
    path.write_text(json.dumps(report))

    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 2
    assert "rebuild the plan" in result.output
    assert geolens.seen == []


def test_a_commit_whose_answer_was_lost_is_not_repeated(runner, plan_file, geolens):
    import httpx

    service = FakeImport(geolens, [_layer(0, "Parcels")])
    commit = service.commit

    def commit_then_time_out(seen):
        commit(seen, "Parcels")
        raise httpx.ReadTimeout("no answer")

    preview = service.preview

    def preview_with_a_lost_commit(seen):
        reply = preview(seen)
        geolens.routes[f"POST /ingest/commit/{reply['job_id']}"] = commit_then_time_out
        return reply

    geolens.routes[PREVIEW] = preview_with_a_lost_commit
    result, _ = _migrate(runner, plan_file, "--only", A2)
    assert result.exit_code == 4
    [job] = _state(plan_file)["items"][A2]["layer_jobs"].values()

    geolens.routes[PREVIEW] = preview
    geolens.routes[f"POST /ingest/commit/{job}"] = lambda seen: commit(seen, "Parcels")
    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert service.previews == 1
    entry = _state(plan_file)["items"][A2]
    assert entry["layer_datasets"] == {"0": dataset_id("Parcels")}
    assert entry["layer_jobs"] == {}
    assert {
        "title": "Parcels (public view)",
        "visibility": "public",
        "expected_updated_at": "2026-10-01T00:00:00+00:00",
    } in [s.json() for s in geolens.seen if s.method == "PATCH"]


def test_a_recorded_job_geolens_no_longer_has_is_replaced(runner, plan_file, geolens):
    service = FakeImport(geolens, [_layer(0, "Parcels")])
    service.job_errors["Parcels"] = "failed"
    _migrate(runner, plan_file, "--only", A2)
    [job] = _state(plan_file)["items"][A2]["layer_jobs"].values()
    del geolens.routes[f"GET /jobs/{job}"], geolens.routes[f"POST /ingest/commit/{job}"]
    del service.job_errors["Parcels"]

    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert service.previews == 2
    assert _state(plan_file)["items"][A2]["layer_jobs"] == {}


def test_service_derived_notes_are_redacted(runner, plan_file, geolens):
    token = secrets.token_urlsafe(16)
    FakeImport(
        geolens,
        [_layer(0, f"Districts {token}", "Group Layer"), _layer(1, "Parcels")],
        needs_auth=True,
    )

    result, _ = _migrate(runner, plan_file, "--only", A1, "--token", token)

    assert result.exit_code == 0, result.output
    raw = (plan_file.parent / "arcgis-migration-state.json").read_text()
    assert token not in raw and "Districts [REDACTED]" in raw


def test_a_portal_sign_in_outage_exits_with_the_network_code(
    runner, plan_file, geolens, monkeypatch
):
    import urllib.error

    portal = FakePortal(portal_routes({"generateToken": urllib.error.URLError("down")}))
    monkeypatch.setattr(migrate, "build_opener", lambda: portal)
    FakeImport(geolens, [_layer(0, "Parcels")], needs_auth=True)

    result, _ = _migrate(
        runner,
        plan_file,
        "--only",
        A1,
        "--username",
        "gis_admin",
        env={"ARCGIS_PASSWORD": secrets.token_urlsafe(16)},
    )

    assert result.exit_code == 4


def test_a_refreshed_session_keeps_the_long_timeout_for_the_retry(
    fake_geolens, monkeypatch
):
    from geolens.api.auth import me_auth_me_get

    from geolens_cli._sdk_helpers import (
        DEFAULT_HTTP_TIMEOUT_SECONDS,
        long_request_timeout,
        make_client,
    )
    from geolens_cli.arcgis_portal import Redactor

    monkeypatch.setattr(
        "geolens_cli.auth.try_refresh", lambda instance: secrets.token_urlsafe(24)
    )
    replies = [
        (401, _problem(401, "expired")),
        {
            "id": OPERATOR,
            "username": "o",
            "email": None,
            "is_active": True,
            "status": "active",
            "last_login_at": None,
            "created_at": NOW,
            "roles": ["admin"],
            "can_reset_password": False,
        },
    ]
    fake_geolens.routes["GET /auth/me/"] = lambda seen: replies.pop(0)
    sdk = make_client(
        GEOLENS_INSTANCE, bearer_token=fake_geolens.token, provenance="stored-bearer"
    )
    geolens = session.GeoLens(sdk, GEOLENS_INSTANCE, Redactor())

    with long_request_timeout(geolens.client, timeout=600.0):
        geolens.call(me_auth_me_get.sync_detailed)

    assert [s.timeout["read"] for s in fake_geolens.seen] == [600.0, 600.0]
    assert (
        geolens.client.get_httpx_client().timeout.read == DEFAULT_HTTP_TIMEOUT_SECONDS
    )


@pytest.mark.parametrize(
    ("retry_after", "expected"),
    [("7", 7.0), ("nan", session.RATE_LIMIT_WAIT), (None, session.RATE_LIMIT_WAIT)],
)
def test_a_rate_limited_call_waits_the_servers_retry_after(
    fake_geolens, retry_after, expected
):
    from geolens.api.auth import me_auth_me_get

    from geolens_cli._sdk_helpers import make_client
    from geolens_cli.arcgis_portal import Redactor

    replies = [
        (
            429,
            _problem(429, "slow down"),
            {"Retry-After": retry_after} if retry_after else {},
        ),
        {
            "id": OPERATOR,
            "username": "o",
            "email": None,
            "is_active": True,
            "status": "active",
            "last_login_at": None,
            "created_at": NOW,
            "roles": ["admin"],
            "can_reset_password": False,
        },
    ]
    fake_geolens.routes["GET /auth/me/"] = lambda seen: replies.pop(0)
    sdk = make_client(GEOLENS_INSTANCE, bearer_token=fake_geolens.token)
    waits: list[float] = []
    geolens = session.GeoLens(sdk, GEOLENS_INSTANCE, Redactor(), sleep=waits.append)

    geolens.call(me_auth_me_get.sync_detailed)

    assert waits == [expected]


def test_generated_titles_stay_within_the_title_limit(runner, tmp_path, geolens):
    report_plan = _write_plan(tmp_path)
    plan = json.loads(report_plan.read_text())
    for item in plan["items"]:
        if item["id"] == A2:
            item["target"]["title"] = "T" * 600
    report_plan.write_text(json.dumps(plan))
    service = FakeImport(geolens, [_layer(0, "Parcels"), _layer(1, "L" * 400)])

    result, _ = _migrate(runner, report_plan, "--only", A2)

    assert result.exit_code == 0, result.output
    titles = [c["title"] for c in service.bodies("POST /ingest/commit/")]
    assert [len(title) for title in titles] == [500, 500]
    assert titles[0].endswith(" - Parcels")


def test_allowing_an_http_portal_never_sends_the_token_over_http(
    runner, tmp_path, geolens
):
    url = ORG_SERVICES.replace("https:", "http:") + "/Parcels/FeatureServer"
    plan_file = _write_plan(tmp_path, {A1: url})
    service = FakeImport(geolens, [_layer(0, "Parcels")])
    token = secrets.token_urlsafe(16)

    result, _ = _migrate(
        runner, plan_file, "--only", A1, "--token", token, "--allow-insecure-http"
    )

    assert result.exit_code == 1
    assert service.bodies(PROBE) == []
    assert all(token not in s.body.decode() for s in geolens.seen)


def test_a_rerun_gives_layers_imported_earlier_the_edited_target(
    runner, plan_file, geolens
):
    service = FakeImport(geolens, [_layer(0, "Parcels"), _layer(1, "Owners")])
    service.job_errors["Owners"] = "boom"
    _migrate(runner, plan_file, "--only", A2)
    plan = json.loads(plan_file.read_text())
    for item in plan["items"]:
        if item["id"] == A2:
            item["target"]["visibility"] = "private"
    plan_file.write_text(json.dumps(plan))
    del service.job_errors["Owners"]
    geolens.seen.clear()

    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    patches = [
        (s.url.rsplit("/", 1)[-1], s.json())
        for s in geolens.seen
        if s.method == "PATCH" and "visibility" in s.json()
    ]
    assert patches == [
        (
            dataset_id("Parcels"),
            {
                "title": "Parcels (public view) - Parcels",
                "visibility": "private",
                "expected_updated_at": "2026-10-01T00:00:00+00:00",
            },
        )
    ]
    # The failed job is committed again (refused as already processed), then
    # replaced by a fresh one.
    assert [c["visibility"] for c in service.bodies("POST /ingest/commit/")] == [
        "private",
        "private",
    ]


ITEM_TEXT = {
    "snippet": "Tax parcels",
    "description": "<p>Parcels from the <b>assessor</b> &amp; the clerk.</p><p>Updated weekly.</p>",
    "access_information": "Example County GIS",
    "license_info": "<div>CC BY 4.0</div>",
    "tags": ["parcels", "cadastre", "parcels"],
}


def test_item_metadata_is_written_onto_the_datasets(runner, tmp_path, geolens):
    plan_file = _write_plan(
        tmp_path, rows={A2: ITEM_TEXT}, portal={"name": "Example County"}
    )
    service = FakeImport(geolens, [_layer(0, "Parcels")])

    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    [patch] = [
        s.json() for s in geolens.seen if s.method == "PATCH" and "summary" in s.json()
    ]
    assert patch == {
        "summary": "Tax parcels\n\nParcels from the assessor & the clerk.\nUpdated weekly.",
        "attribution": "Example County GIS",
        "license": "CC BY 4.0",
        "source_organization": "Example County",
        "expected_updated_at": "2026-10-01T00:00:00+00:00",
    }
    assert service.keywords[dataset_id("Parcels")] == ["parcels", "cadastre"]
    entry = _state(plan_file)["items"][A2]
    assert entry["record_ids"] == [dataset_id("Parcels")]
    assert entry["metadata_baseline"][dataset_id("Parcels")]["summary"].startswith(
        "Tax parcels"
    )


def test_a_summary_edited_in_geolens_is_kept_on_rerun(runner, tmp_path, geolens):
    plan_file = _write_plan(tmp_path, rows={A2: ITEM_TEXT})
    service = FakeImport(geolens, [_layer(0, "Parcels"), _layer(1, "Owners")])
    service.job_errors["Owners"] = "boom"
    _migrate(runner, plan_file, "--only", A2)
    service.summaries[dataset_id("Parcels")] = "Written by a person"
    del service.job_errors["Owners"]
    geolens.seen.clear()

    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert service.summaries[dataset_id("Parcels")] == "Written by a person"
    assert service.summaries[dataset_id("Owners")].startswith("Tax parcels")


def test_a_failed_metadata_write_fails_the_item_and_a_rerun_redoes_only_it(
    runner, tmp_path, geolens
):
    plan_file = _write_plan(tmp_path, rows={A2: ITEM_TEXT})
    service = FakeImport(geolens, [_layer(0, "Parcels")])
    keyword = f"POST /records/{dataset_id('Parcels')}/keywords/"
    preview = service.preview

    def preview_then_break_keywords(seen):
        reply = preview(seen)
        geolens.routes[keyword] = (500, _problem(500, "database unavailable"))
        return reply

    geolens.routes[PREVIEW] = preview_then_break_keywords
    result, _ = _migrate(runner, plan_file, "--only", A2)
    assert result.exit_code == 1
    entry = _state(plan_file)["items"][A2]
    assert entry["status"] == "failed" and "item metadata" in entry["error"]
    assert entry["dataset_ids"] == [dataset_id("Parcels")]
    # The summary was written before the keyword failed; a rerun has to be
    # able to tell it from an edit.
    assert entry["metadata_baseline"][dataset_id("Parcels")]["summary"].startswith(
        "Tax parcels"
    )

    geolens.routes[PREVIEW] = preview
    service._serve_dataset(dataset_id("Parcels"))
    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert service.previews == 1
    assert service.keywords[dataset_id("Parcels")] == ["parcels", "cadastre"]


def _rerun_as_pending(runner, plan_file):
    state_path = plan_file.parent / "arcgis-migration-state.json"
    state = json.loads(state_path.read_text())
    state["items"][A2]["status"] = "pending"
    state_path.write_text(json.dumps(state))
    return _migrate(runner, plan_file, "--only", A2)


def test_a_rerun_keeps_every_metadata_edit_made_in_geolens(runner, tmp_path, geolens):
    plan_file = _write_plan(
        tmp_path, rows={A2: ITEM_TEXT}, portal={"name": "Example County"}
    )
    service = FakeImport(geolens, [_layer(0, "Parcels")])
    _migrate(runner, plan_file, "--only", A2)
    parcels = dataset_id("Parcels")
    service.summaries[parcels] = ""
    service.fields[parcels].update(
        {"license": "Internal use only", "source_organization": "Planning"}
    )
    service.keywords[parcels].remove("cadastre")
    geolens.seen.clear()

    result, _ = _rerun_as_pending(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert [
        s for s in geolens.seen if s.method == "PATCH" and "summary" in s.json()
    ] == []
    assert service.summaries[parcels] == ""
    assert service.fields[parcels]["license"] == "Internal use only"
    assert service.fields[parcels]["source_organization"] == "Planning"
    assert service.keywords[parcels] == ["parcels"]
    notes = _state(plan_file)["items"][A2]["notes"]
    assert any("summary" in n for n in notes)
    assert any("license" in n for n in notes)
    assert any("source organization" in n for n in notes)
    assert any("'cadastre'" in n for n in notes)
    assert not any("attribution" in n for n in notes)


def test_a_rerun_still_writes_fields_nobody_edited(runner, tmp_path, geolens):
    plan_file = _write_plan(tmp_path, rows={A2: ITEM_TEXT})
    service = FakeImport(geolens, [_layer(0, "Parcels")])
    _migrate(runner, plan_file, "--only", A2)
    parcels = dataset_id("Parcels")
    service.fields[parcels]["license"] = "CC BY 4.0"
    service.keywords[parcels].append("added by a person")

    result, _ = _rerun_as_pending(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert service.keywords[parcels] == ["parcels", "cadastre", "added by a person"]
    assert _state(plan_file)["items"][A2]["notes"] == []


def test_a_mixed_case_tag_is_not_reported_as_removed_on_rerun(
    runner, tmp_path, geolens
):
    rows = {A2: {**ITEM_TEXT, "tags": ["Roads", "roads"]}}
    plan_file = _write_plan(tmp_path, rows=rows)
    service = FakeImport(geolens, [_layer(0, "Parcels")])
    _migrate(runner, plan_file, "--only", A2)
    assert service.keywords[dataset_id("Parcels")] == ["roads"]

    result, _ = _rerun_as_pending(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert _state(plan_file)["items"][A2]["notes"] == []


def test_the_same_text_under_another_keyword_type_does_not_count_as_present(
    runner, tmp_path, geolens
):
    plan_file = _write_plan(tmp_path, rows={A2: ITEM_TEXT})
    service = FakeImport(geolens, [_layer(0, "Parcels")])
    parcels = dataset_id("Parcels")
    preview = service.preview

    def preview_with_a_place_keyword(seen):
        reply = preview(seen)
        service.other_keywords[parcels] = [
            {
                "id": _uuid("4f", "parcels"),
                "record_id": parcels,
                "keyword": "parcels",
                "vocabulary_uri": None,
                "keyword_type": "place",
                "inherited": False,
            }
        ]
        return reply

    geolens.routes[PREVIEW] = preview_with_a_place_keyword

    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert service.keywords[parcels] == ["parcels", "cadastre"]


def test_an_edit_that_matches_the_source_keeps_the_old_baseline(
    runner, tmp_path, geolens
):
    plan_file = _write_plan(tmp_path, rows={A2: ITEM_TEXT})
    service = FakeImport(geolens, [_layer(0, "Parcels")])
    _migrate(runner, plan_file, "--only", A2)
    parcels = dataset_id("Parcels")
    state_path = plan_file.parent / "arcgis-migration-state.json"
    state = json.loads(state_path.read_text())
    # The migration once wrote another license; a person has since set the
    # value the source now holds.
    state["items"][A2]["metadata_baseline"][parcels]["license"] = "Older license"
    state_path.write_text(json.dumps(state))
    assert service.fields[parcels]["license"] == "CC BY 4.0"

    result, _ = _rerun_as_pending(runner, plan_file)

    assert result.exit_code == 0, result.output
    baseline = _state(plan_file)["items"][A2]["metadata_baseline"][parcels]
    assert baseline["license"] == "Older license"


def test_a_keyword_the_record_holds_as_inherited_is_present_not_removed(
    runner, tmp_path, geolens
):
    plan_file = _write_plan(tmp_path, rows={A2: ITEM_TEXT})
    service = FakeImport(geolens, [_layer(0, "Parcels")])
    parcels = dataset_id("Parcels")
    preview = service.preview

    def preview_with_an_inherited_keyword(seen):
        reply = preview(seen)
        service.other_keywords[parcels] = [
            {
                "id": _uuid("4f", "parcels"),
                "record_id": parcels,
                "keyword": "parcels",
                "vocabulary_uri": None,
                "keyword_type": "theme",
                "inherited": True,
            }
        ]
        return reply

    geolens.routes[PREVIEW] = preview_with_an_inherited_keyword
    _migrate(runner, plan_file, "--only", A2)
    assert service.keywords[parcels] == ["cadastre"]

    result, _ = _rerun_as_pending(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert _state(plan_file)["items"][A2]["notes"] == []


def test_a_keyword_written_before_a_failure_is_remembered(runner, tmp_path, geolens):
    plan_file = _write_plan(tmp_path, rows={A2: ITEM_TEXT})
    service = FakeImport(geolens, [_layer(0, "Parcels")])
    parcels = dataset_id("Parcels")
    preview = service.preview
    keyword_route = f"POST /records/{parcels}/keywords/"

    def preview_then_break_the_second_keyword(seen):
        reply = preview(seen)
        working = geolens.routes[keyword_route]

        def first_only(seen):
            if seen.json()["keyword"] == "cadastre":
                return (500, _problem(500, "database unavailable"))
            return working(seen)

        geolens.routes[keyword_route] = first_only
        return reply

    geolens.routes[PREVIEW] = preview_then_break_the_second_keyword
    result, _ = _migrate(runner, plan_file, "--only", A2)
    assert result.exit_code == 1
    assert service.keywords[parcels] == ["parcels"]
    assert _state(plan_file)["items"][A2]["metadata_baseline"][parcels]["keywords"] == [
        "parcels"
    ]

    service.keywords[parcels].remove("parcels")
    geolens.routes[PREVIEW] = preview
    service._serve_dataset(parcels)
    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert service.keywords[parcels] == ["cadastre"]
    assert any("'parcels'" in n for n in _state(plan_file)["items"][A2]["notes"])
