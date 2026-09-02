"""Unit tests for IA-P1-06: subprocess env must not leak Authorization token.

Pins the migration from GDAL_HTTP_HEADERS env var to a 0600 tempfile
referenced by GDAL_HTTP_HEADER_FILE.

fix(#1746 B2b) plan D9: what crosses the queue to this worker is one finished
header line rather than a bare token, so the ``token`` argument here is a line.
The worker composes nothing; it validates the line and writes it. The bearer
case is asserted byte for byte against what this path wrote before, which is
what proves moving the prefix into the shared builder changed nothing on the
shipping path.

Requirement: IA-P1-06
Phase: 1068
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from app.core.runtime import staging as staging_runtime
from app.processing.ingest.ogr import run_ogr2ogr_service

# The wire value for a bearer credential, composed by the door.
_BEARER_TOKEN = "example-jwt-token-base64url"
_BEARER_LINE = f"Authorization: Bearer {_BEARER_TOKEN}"


@pytest.fixture(autouse=True)
def gdal_header_tmpdir(tmp_path, monkeypatch):
    """fix(#1746 codex r2): keep header files out of the real /tmp/gdal-auth.

    The mkstemp for the bearer header passes ``dir=gdal_header_dir()``, which
    creates and returns ``GDAL_HEADER_DIR`` — the container tmpfs in
    production, and the developer's or the CI runner's actual /tmp under
    pytest. Pointing the module constant at a per-test directory keeps the
    suite from writing credential-shaped files outside its own tmp_path.

    Imported by the other modules that exercise the same branch
    (test_preview_token_sec021, test_door_token_policy_1746); it is autouse
    there too, which is the intent — no test in this repo should touch the
    real directory.
    """
    monkeypatch.setattr(
        staging_runtime, "GDAL_HEADER_DIR", tmp_path / "gdal-auth", raising=True
    )
    return tmp_path / "gdal-auth"


@pytest.mark.asyncio
async def test_token_not_in_subprocess_env_via_header_file():
    """When a token is supplied, GDAL_HTTP_HEADERS MUST NOT appear in env;
    GDAL_HTTP_HEADER_FILE is set instead, pointing at a 0600 tempfile."""
    captured_env = {}
    captured_header_file_contents: bytes | None = None

    async def _fake_create_subprocess_exec(*args, env=None, **kwargs):
        nonlocal captured_env, captured_header_file_contents
        captured_env = env or {}
        # Read the header file contents while the subprocess "runs"
        hfp = captured_env.get("GDAL_HTTP_HEADER_FILE")
        if hfp and os.path.exists(hfp):
            with open(hfp, "rb") as f:
                captured_header_file_contents = f.read()
        # Mock a successful exit
        proc = MagicMock()
        proc.returncode = 0
        return proc

    async def _fake_communicate_with_timeout(proc, timeout, tool_name):
        return (b"", b"")

    with (
        patch(
            "asyncio.create_subprocess_exec",
            side_effect=_fake_create_subprocess_exec,
        ),
        patch(
            "app.processing.ingest.ogr._communicate_with_timeout",
            new=_fake_communicate_with_timeout,
        ),
    ):
        await run_ogr2ogr_service(
            gdal_source="WFS:https://example.test/wfs",
            layer_name="roads",
            table_name="test_table",
            db_conn_str="PG:dummy",
            service_type="wfs",
            token=_BEARER_LINE,
            schema="data",
        )

    # 1) The deprecated GDAL_HTTP_HEADERS var MUST NOT be present.
    assert "GDAL_HTTP_HEADERS" not in captured_env, (
        f"Authorization must not appear via env var; got: {captured_env.get('GDAL_HTTP_HEADERS')}"
    )

    # 2) GDAL_HTTP_HEADER_FILE points at a path, not a token.
    assert "GDAL_HTTP_HEADER_FILE" in captured_env
    header_file_path = captured_env["GDAL_HTTP_HEADER_FILE"]
    assert isinstance(header_file_path, str) and header_file_path.endswith(".hdr")

    # 3) The header file contains exactly the header line (and not in env).
    #    Byte-identical to what this path wrote before the prefix moved into
    #    the shared builder, and exactly one line: a second one would be a
    #    smuggled header.
    assert captured_header_file_contents == _BEARER_LINE.encode() + b"\n"

    # 4) Plan rule A: the Authorization header follows only to the host it was
    #    given to. Stated explicitly rather than inherited from GDAL's default,
    #    and NOT "NO" -- that would drop it on a same-host canonical redirect
    #    too, which a protected service answers with a 401
    #    (fix(#1746 B2b review r4)).
    assert (
        captured_env["CPL_VSIL_CURL_AUTHORIZATION_HEADER_ALLOWED_IF_REDIRECT"]
        == "IF_SAME_HOST"
    )

    # 5) The header file is unlinked after subprocess completes.
    assert not os.path.exists(header_file_path), (
        f"Header file {header_file_path} should be unlinked after subprocess"
    )


@pytest.mark.asyncio
async def test_no_token_no_header_file_created():
    """When no token is supplied, no GDAL_HTTP_HEADER_FILE env var is set
    and no tempfile is created."""
    captured_env = {}

    async def _fake_create_subprocess_exec(*args, env=None, **kwargs):
        nonlocal captured_env
        captured_env = env or {}
        proc = MagicMock()
        proc.returncode = 0
        return proc

    async def _fake_communicate_with_timeout(proc, timeout, tool_name):
        return (b"", b"")

    with (
        patch(
            "asyncio.create_subprocess_exec",
            side_effect=_fake_create_subprocess_exec,
        ),
        patch(
            "app.processing.ingest.ogr._communicate_with_timeout",
            new=_fake_communicate_with_timeout,
        ),
    ):
        await run_ogr2ogr_service(
            gdal_source="WFS:https://example.test/wfs",
            layer_name="roads",
            table_name="test_table",
            db_conn_str="PG:dummy",
            service_type="wfs",
            token=None,
            schema="data",
        )

    # No header file, no header env var.
    assert "GDAL_HTTP_HEADERS" not in captured_env
    assert "GDAL_HTTP_HEADER_FILE" not in captured_env
    # fix(#937): GDAL_HTTP_FOLLOWLOCATION is not a GDAL option and provides no
    # redirect protection; it must not be reintroduced as if it did.
    assert "GDAL_HTTP_FOLLOWLOCATION" not in captured_env


@pytest.mark.asyncio
async def test_header_file_is_0600():
    """The temp header file must be readable only by owner (0o600)."""
    captured_mode: int | None = None

    async def _fake_create_subprocess_exec(*args, env=None, **kwargs):
        nonlocal captured_mode
        hfp = (env or {}).get("GDAL_HTTP_HEADER_FILE")
        if hfp and os.path.exists(hfp):
            captured_mode = os.stat(hfp).st_mode & 0o777
        proc = MagicMock()
        proc.returncode = 0
        return proc

    async def _fake_communicate_with_timeout(proc, timeout, tool_name):
        return (b"", b"")

    with (
        patch(
            "asyncio.create_subprocess_exec",
            side_effect=_fake_create_subprocess_exec,
        ),
        patch(
            "app.processing.ingest.ogr._communicate_with_timeout",
            new=_fake_communicate_with_timeout,
        ),
    ):
        await run_ogr2ogr_service(
            gdal_source="WFS:https://example.test/wfs",
            layer_name="roads",
            table_name="test_table",
            db_conn_str="PG:dummy",
            service_type="wfs",
            token=_BEARER_LINE,
            schema="data",
        )

    assert captured_mode == 0o600, f"Header file must be 0600, got 0o{captured_mode:o}"


@pytest.mark.asyncio
async def test_header_file_unlinked_even_on_subprocess_error():
    """If the subprocess errors, the header file must still be unlinked."""
    captured_path: str | None = None

    async def _fake_create_subprocess_exec(*args, env=None, **kwargs):
        nonlocal captured_path
        captured_path = (env or {}).get("GDAL_HTTP_HEADER_FILE")
        proc = MagicMock()
        proc.returncode = 1
        return proc

    async def _fake_communicate_with_timeout(proc, timeout, tool_name):
        return (b"", b"ogr2ogr failed")

    from app.processing.ingest.ogr import IngestionError

    with (
        patch(
            "asyncio.create_subprocess_exec",
            side_effect=_fake_create_subprocess_exec,
        ),
        patch(
            "app.processing.ingest.ogr._communicate_with_timeout",
            new=_fake_communicate_with_timeout,
        ),
    ):
        with pytest.raises(IngestionError):
            await run_ogr2ogr_service(
                gdal_source="WFS:https://example.test/wfs",
                layer_name="roads",
                table_name="test_table",
                db_conn_str="PG:dummy",
                service_type="wfs",
                token=_BEARER_LINE,
                schema="data",
            )

    assert captured_path is not None
    assert not os.path.exists(captured_path), (
        f"Header file {captured_path} must be unlinked even when subprocess fails"
    )
