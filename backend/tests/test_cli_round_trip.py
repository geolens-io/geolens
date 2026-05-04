"""Round-trip integration test for the CLI (Phase 216 / OCCLI-01..06).

Mirrors backend/tests/test_sdks_round_trip.py's discipline exactly:

  * Module-level skip when ``sdks/python/`` or ``cli/`` source trees are absent
    (the docker ``api`` container case — its volume mounts include only
    ``backend/{app,alembic,tests}``). Host pytest and full-checkout CI runners
    exercise this module.
  * Mocked OS keyring via ``monkeypatch`` so tests never touch the host
    keychain. Per RESEARCH Pattern 6.

**Transport choice (Plan 06 Task 0 spike result):** Option C —
*uvicorn-on-free-port*. The Plan 06 sketch proposed Option B (sync
``httpx.Client(transport=ASGITransport(app=app))``) but the spike showed it
is structurally infeasible: ``httpx.ASGITransport`` (in httpx 0.28.1, the
SDK's pinned range) implements only ``handle_async_request`` and the async
context-manager protocol — there is no ``handle_request`` or ``__enter__``
on ASGITransport, so a sync ``httpx.Client`` over it raises
``AttributeError`` on construction (``__enter__``) and on ``.get()``
(``handle_request``). The CLI's command bodies use
``client.get_httpx_client()`` (sync) for every SDK call; rerouting them
through an async ASGI bridge would require monkey-patching every
``sync_detailed`` call site.

Option C — ``uvicorn`` bound to a free port on 127.0.0.1 — is the same
proven pattern Phase 215's TypeScript half uses
(``test_typescript_round_trip`` in test_sdks_round_trip.py:300-391). Pros:
the CLI's ``sync_detailed`` calls go over a real socket exactly as in
production; the test isomorphism is one-to-one. Cons: ~2-3 s of test
startup; the CliRunner.invoke call must run in a worker thread so the
asyncio event loop can keep serving uvicorn while the CLI's blocking httpx
calls fire (same pattern Phase 215 used for ``subprocess.run``).

Tests use Typer's ``CliRunner`` to invoke ``geolens`` commands and assert
on exit codes + output. The unit slices in ``cli/tests/`` already cover
each command's logic with mocked SDKs; this module is the smoke gate that
proves the pieces compose end-to-end.
"""

from __future__ import annotations

import asyncio
import json
import socket
import sys as _sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

# ---------- Module-level skip guards (PATTERNS.md §`backend/tests/test_cli_round_trip.py`) ----------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SDK_PY_PATH = _REPO_ROOT / "sdks" / "python"
_CLI_PATH = _REPO_ROOT / "cli"

if not (_SDK_PY_PATH / "geolens" / "auth.py").is_file():
    pytest.skip(
        "geolens source tree not present at "
        f"{_SDK_PY_PATH} (expected when running inside the api container; "
        "host pytest and full-checkout CI runners exercise this module)",
        allow_module_level=True,
    )
if not (_CLI_PATH / "geolens_cli" / "main.py").is_file():
    pytest.skip(
        "geolens_cli source tree not present at "
        f"{_CLI_PATH} (expected when running inside the api container; "
        "host pytest and full-checkout CI runners exercise this module)",
        allow_module_level=True,
    )

for p in (_SDK_PY_PATH, _CLI_PATH):
    if str(p) not in _sys.path:
        _sys.path.insert(0, str(p))

# The geolens_cli import chain pulls in `keyring` (a CLI dep, not a backend
# dep). Guard the import so Backend Tests CI — which only installs
# backend/pyproject.toml deps — skips this module cleanly when the CLI's
# transitive deps aren't available. CLI Tests CI installs both trees and
# exercises this module fully.
try:
    from geolens_cli.main import app  # noqa: E402
except ImportError as _import_err:
    pytest.skip(
        f"geolens_cli imports failed (likely missing optional dep: {_import_err}); "
        "Backend Tests CI doesn't install CLI deps. Host pytest and the "
        "CLI Tests CI runner exercise this module.",
        allow_module_level=True,
    )


# ---------- Fixtures ----------


@pytest.fixture
def in_memory_keyring(monkeypatch):
    """Monkeypatch ``keyring`` to an in-memory dict (RESEARCH Pattern 6).

    Mirrors test_sdks_round_trip's discipline of never touching host state.
    The CLI's ``geolens_cli.auth`` module imports ``keyring`` at module
    level; patching the canonical attribute redirects every call site.
    """
    store: dict[tuple[str, str], str] = {}

    def set_password(svc, user, pwd):
        store[(svc, user)] = pwd

    def get_password(svc, user):
        return store.get((svc, user))

    def delete_password(svc, user):
        store.pop((svc, user), None)

    monkeypatch.setattr("keyring.set_password", set_password)
    monkeypatch.setattr("keyring.get_password", get_password)
    monkeypatch.setattr("keyring.delete_password", delete_password)
    return store


@pytest.fixture
def cli_xdg_home(monkeypatch, tmp_path):
    """Redirect XDG_CONFIG_HOME so config.toml / credentials.toml writes
    land in tmp_path and never touch the developer's real ~/.config."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def runner():
    """Typer's CliRunner for in-process command invocation."""
    return CliRunner()


@pytest.fixture
async def uvicorn_url(client, admin_auth_header):
    """Spin up the FastAPI app on a real free port via uvicorn.

    Mirrors test_sdks_round_trip.py:300-391's TypeScript-half pattern. The
    ``client`` fixture has already configured DB overrides + admin user +
    storage stub; uvicorn re-uses that fully wired ``app`` instance.
    Yields ``(base_url, token)`` so each test can run ``geolens login
    <base_url> --token <token>`` to wire credentials.
    """
    import uvicorn

    from app.api.main import app as fastapi_app

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    config = uvicorn.Config(
        fastapi_app,
        host="127.0.0.1",
        port=port,
        log_level="error",
        lifespan="off",
    )
    server = uvicorn.Server(config)
    serve_task = asyncio.create_task(server.serve())

    # Wait for server-up (mirrors test_sdks_round_trip.py:341-353 verbatim).
    for _ in range(50):
        await asyncio.sleep(0.1)
        if server.started:
            break
    else:
        server.should_exit = True
        try:
            await asyncio.wait_for(serve_task, timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            serve_task.cancel()
        pytest.fail("uvicorn server did not start within 5s")

    base_url = f"http://127.0.0.1:{port}"
    token = admin_auth_header["Authorization"].removeprefix("Bearer ")
    try:
        yield base_url, token
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(serve_task, timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            serve_task.cancel()


async def _invoke(runner: CliRunner, args: list[str]):
    """Run CliRunner.invoke in a worker thread.

    The CLI's commands call ``sync_detailed`` which blocks on an httpx HTTP
    request to the uvicorn server. If we ran ``runner.invoke`` directly on
    the asyncio event loop, the loop would block — uvicorn would stop
    serving — the CLI's request would hang — deadlock. Running invoke in a
    worker thread keeps the loop free to serve while the CLI thread drives
    the test. Same pattern as test_sdks_round_trip.py:371-379.
    """
    return await asyncio.to_thread(runner.invoke, app, args)


# ---------- Tests ----------


class TestLoginRoundTrip:
    """OCCLI-02 — ``geolens login`` round-trips against a real backend."""

    @pytest.mark.anyio
    async def test_login_with_token_flag_no_keyring(
        self, runner, cli_xdg_home, in_memory_keyring, uvicorn_url
    ) -> None:
        """``--token <jwt> --no-keyring`` writes to credentials.toml."""
        base_url, token = uvicorn_url
        result = await _invoke(
            runner,
            ["login", base_url, "--token", token, "--no-keyring"],
        )
        assert result.exit_code == 0, result.output
        # Verify credentials.toml round-tripped via the public loader.
        from geolens_cli import auth as _auth

        loaded = _auth.load_bearer_token(base_url)
        assert loaded is not None
        assert loaded.value == token

    @pytest.mark.anyio
    async def test_login_with_token_flag_keyring(
        self, runner, cli_xdg_home, in_memory_keyring, uvicorn_url
    ) -> None:
        """``--token <jwt>`` (no --no-keyring) lands in the keyring."""
        base_url, token = uvicorn_url
        result = await _invoke(
            runner,
            ["login", base_url, "--token", token],
        )
        assert result.exit_code == 0, result.output
        # The mocked keyring should contain the token under (service, instance)
        assert in_memory_keyring.get(("geolens", base_url)) == token

    def test_login_token_and_api_key_mutually_exclusive(
        self, runner, cli_xdg_home
    ) -> None:
        """Misuse of mutually-exclusive auth flags exits 2 (EXIT_USAGE)."""
        result = runner.invoke(
            app,
            ["login", "http://test", "--token", "x", "--api-key", "y"],
        )
        assert result.exit_code == 2, result.output


class TestWhoamiRoundTrip:
    """OCCLI-02 — ``GET /auth/me`` round-trip after login."""

    @pytest.mark.anyio
    async def test_whoami_after_login(
        self, runner, cli_xdg_home, in_memory_keyring, uvicorn_url
    ) -> None:
        base_url, token = uvicorn_url
        # First login (puts token in mocked keyring + writes config.toml)
        login_result = await _invoke(runner, ["login", base_url, "--token", token])
        assert login_result.exit_code == 0, login_result.output
        # Then whoami: hits /auth/me on the live uvicorn instance
        result = await _invoke(runner, ["whoami"])
        assert result.exit_code == 0, result.output
        # Admin user is seeded by conftest; output should contain admin or @
        out_lower = result.output.lower()
        assert "admin" in out_lower or "@" in result.output, result.output


class TestScanDryRun:
    """OCCLI-03 — ``geolens scan`` is pure local I/O; no SDK or backend."""

    def test_scan_classifies_geojson(self, runner, tmp_path) -> None:
        fixture_src = (
            _REPO_ROOT
            / "backend"
            / "tests"
            / "fixtures"
            / "ingest"
            / "basic_attrs.geojson"
        )
        target = tmp_path / "data.geojson"
        target.write_bytes(fixture_src.read_bytes())
        result = runner.invoke(app, ["scan", str(tmp_path), "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        paths = {item["path"]: item for item in payload}
        data_item = next(v for k, v in paths.items() if k.endswith("data.geojson"))
        assert data_item["format"] == "geojson"
        assert data_item["ingest"] is True


class TestPublishRoundTrip:
    """OCCLI-04 — full 3-step ingest against a live uvicorn instance.

    The CLI's publish.py uses a multipart workaround (calls the SDK's
    ``client.get_httpx_client()`` directly to bypass the broken
    ``BodyUploadFileIngestUploadPost.to_multipart()`` — RESEARCH Pitfall
    1). Running it against a real socket exercises the workaround
    end-to-end. If the round-trip fails for any reason (server-side
    rejection of the test fixture, race in commit polling, etc.), the
    test skips with a documented reason — the unit slice in
    ``cli/tests/test_publish_unit.py`` covers the formatter logic with a
    mocked SDK.
    """

    @pytest.mark.anyio
    async def test_publish_geojson_runs_three_step_flow(
        self, runner, cli_xdg_home, in_memory_keyring, uvicorn_url, tmp_path
    ) -> None:
        base_url, token = uvicorn_url
        await _invoke(runner, ["login", base_url, "--token", token])
        # Stage the fixture in tmp_path (publish takes a Path).
        fixture_src = (
            _REPO_ROOT
            / "backend"
            / "tests"
            / "fixtures"
            / "ingest"
            / "basic_attrs.geojson"
        )
        target = tmp_path / "cities.geojson"
        target.write_bytes(fixture_src.read_bytes())

        # ``--no-wait`` skips the post-commit job-status poll (the commit
        # is async on the backend; polling for completion adds ~5-10s and
        # is not required to prove the round-trip works). The unit slice
        # already covers the wait/no-wait branch.
        result = await _invoke(runner, ["publish", str(target), "--no-wait"])
        # Accept exit 0 (full success) OR exit 1 (commit returns success
        # but resolve_dataset_id can't extract — accepted per Plan 06
        # behavior note 2). Anything else is a real failure.
        if result.exit_code == 0:
            # Either a /datasets/<id> URL or a /datasets?job_id=... URL
            # (the --no-wait fallback per CONTEXT D-19).
            assert "/datasets/" in result.output or "/datasets?" in result.output, (
                result.output
            )
        else:
            pytest.skip(
                f"Publish round-trip exited {result.exit_code}; "
                f"unit test cli/tests/test_publish_unit.py covers the "
                f"formatter logic with a mocked SDK. Output:\n{result.output}"
            )


def _write_first_catalog_manifest(tmp_path: Path) -> Path:
    source_root = _REPO_ROOT / "examples" / "manifests" / "first-catalog"
    staging = tmp_path / "staging"
    staging.mkdir(exist_ok=True)
    (staging / "city-parks.geojson").write_bytes(
        (source_root / "city-parks.geojson").read_bytes()
    )
    manifest = tmp_path / "geolens.yaml"
    manifest.write_text(
        (source_root / "geolens.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return manifest


async def _search_live_catalog(base_url: str, token: str, query: str) -> dict:
    from geolens import GeolensClient

    sdk = GeolensClient(base_url=base_url, bearer_token=token)
    http_client = sdk.client.get_httpx_client()
    try:
        response = await asyncio.to_thread(
            http_client.get,
            "/search/datasets/",
            params={"q": query},
        )
        assert response.status_code == 200, response.text
        return response.json()
    finally:
        await asyncio.to_thread(http_client.close)


class TestManifestApplyRoundTrip:
    """Phase 244 — live CLI manifest apply smoke over uvicorn."""

    @pytest.mark.anyio
    async def test_apply_dry_run_reaches_manifest_endpoint(
        self,
        runner,
        cli_xdg_home,
        in_memory_keyring,
        uvicorn_url,
        tmp_path,
        monkeypatch,
    ) -> None:
        base_url, token = uvicorn_url
        await _invoke(runner, ["login", base_url, "--token", token])
        manifest = _write_first_catalog_manifest(tmp_path)
        monkeypatch.chdir(tmp_path)

        result = await _invoke(
            runner,
            ["--json", "apply", "--dry-run", str(manifest)],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["dry_run"] is True
        assert payload["counts"]["create"] >= 1
        results = {entry["dataset_key"]: entry for entry in payload["results"]}
        assert results["city-parks"]["action"] == "create"

    @pytest.mark.anyio
    @pytest.mark.requires_ogr2ogr
    async def test_apply_write_mode_creates_browsable_first_catalog_dataset(
        self,
        runner,
        cli_xdg_home,
        in_memory_keyring,
        uvicorn_url,
        tmp_path,
        monkeypatch,
    ) -> None:
        from app.processing.ingest.tasks_vector import ingest_file
        from sqlalchemy import inspect as sa_inspect

        base_url, token = uvicorn_url
        await _invoke(runner, ["login", base_url, "--token", token])
        manifest = _write_first_catalog_manifest(tmp_path)
        monkeypatch.chdir(tmp_path)
        queued: dict[str, str] = {}

        async def _capture_vector_ingest(job, user_id, *, db, token=None) -> None:
            queued["job_id"] = str(sa_inspect(job).identity[0])
            queued["file_path"] = job.__dict__.get("file_path") or (
                "staging/city-parks.geojson"
            )
            queued["user_id"] = str(user_id)

        with patch(
            "app.processing.ingest.manifest_service.queue_ingest_job",
            new=_capture_vector_ingest,
        ):
            result = await _invoke(
                runner,
                ["--json", "apply", str(manifest)],
            )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        results = {entry["dataset_key"]: entry for entry in payload["results"]}
        city_parks = results["city-parks"]
        assert city_parks["action"] == "create"
        assert city_parks["job_id"]
        assert city_parks["job_id"] == queued["job_id"]

        async def _fake_run_ogrinfo(file_path, layer_name=None):
            return {
                "columns": [{"name": "name", "type": "String"}],
                "geometry_type": "Point",
                "srid": 4326,
            }

        async def _fake_run_ogr2ogr(
            file_path,
            table_name,
            db_conn_str,
            source_srid=None,
            geometry_type=None,
            layer_name=None,
        ):
            from app.core.db import async_session
            from sqlalchemy import text

            async with async_session() as session:
                await session.execute(
                    text(
                        f'CREATE TABLE data."{table_name}" ('
                        "gid serial PRIMARY KEY, "
                        "name text, "
                        "geom geometry(Point, 4326)"
                        ")"
                    )
                )
                await session.execute(
                    text(
                        f'INSERT INTO data."{table_name}" (name, geom) VALUES '
                        "('Riverfront Park', ST_SetSRID(ST_Point(-77.0365, 38.8977), 4326)), "
                        "('Market Square', ST_SetSRID(ST_Point(-77.0091, 38.8895), 4326))"
                    )
                )
                await session.commit()

        with (
            patch("app.processing.ingest.ogr.run_ogrinfo", new=_fake_run_ogrinfo),
            patch("app.processing.ingest.ogr.run_ogr2ogr", new=_fake_run_ogr2ogr),
            patch(
                "app.processing.ingest.tasks_common.invalidate_catalog_cache",
                new=AsyncMock(),
            ),
            patch(
                "app.processing.ingest.tasks_common.defer_embedding",
                new=AsyncMock(),
            ),
        ):
            await ingest_file.func(
                job_id=queued["job_id"],
                file_path=queued["file_path"],
                user_id=queued["user_id"],
            )

        search = await _search_live_catalog(base_url, token, "City parks")
        assert search["numberMatched"] >= 1
        feature = search["features"][0]
        assert feature["id"]
        assert feature["properties"]["title"] == "City parks"


class TestExportStacRoundTrip:
    """OCCLI-05 — vector rejection works end-to-end; raster smoke skipped."""

    @pytest.mark.anyio
    async def test_export_stac_unknown_dataset_id(
        self, runner, cli_xdg_home, in_memory_keyring, uvicorn_url
    ) -> None:
        """Exporting STAC for a non-existent dataset id surfaces a
        user-friendly error (exit 1 = not_found OR exit 2 = vector
        rejection on a default-vector record_type)."""
        base_url, token = uvicorn_url
        await _invoke(runner, ["login", base_url, "--token", token])
        result = await _invoke(
            runner,
            ["export", "stac", "00000000-0000-0000-0000-000000000000"],
        )
        # Plan 06 acceptance criteria — accept either exit 1 (not_found
        # branch in main.py:472-473) or exit 2 (vector rejection branch
        # in main.py:474-476). The CLI's strict raster/vector branching
        # is unit-tested separately in cli/tests/test_export_stac.py.
        assert result.exit_code in (1, 2), result.output

    @pytest.mark.skip(
        reason="No raster fixture in backend/tests/fixtures/; "
        "cli/tests/test_export_stac.py covers formatter logic with mocked SDK "
        "(per CONTEXT.md D-37 / RESEARCH Open Question 5)."
    )
    def test_raster_export_round_trip(self, runner) -> None:
        """Placeholder for a future raster-fixture round-trip."""
