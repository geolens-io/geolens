"""Unit tests for IA-P1-06: subprocess env must not leak Authorization token.

Pins the migration from GDAL_HTTP_HEADERS env var to a 0600 tempfile
referenced by GDAL_HTTP_HEADER_FILE.

Requirement: IA-P1-06
Phase: 1068
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.processing.ingest.ogr import run_ogr2ogr_service


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

    with patch(
        "asyncio.create_subprocess_exec",
        side_effect=_fake_create_subprocess_exec,
    ), patch(
        "app.processing.ingest.ogr._communicate_with_timeout",
        new=_fake_communicate_with_timeout,
    ):
        await run_ogr2ogr_service(
            gdal_source="WFS:https://example.test/wfs",
            layer_name="roads",
            table_name="test_table",
            db_conn_str="PG:dummy",
            service_type="wfs",
            token="example-jwt-token-base64url",
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
    assert captured_header_file_contents is not None
    assert b"Authorization: Bearer example-jwt-token-base64url" in (
        captured_header_file_contents
    )

    # 4) The header file is unlinked after subprocess completes.
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

    with patch(
        "asyncio.create_subprocess_exec",
        side_effect=_fake_create_subprocess_exec,
    ), patch(
        "app.processing.ingest.ogr._communicate_with_timeout",
        new=_fake_communicate_with_timeout,
    ):
        await run_ogr2ogr_service(
            gdal_source="WFS:https://example.test/wfs",
            layer_name="roads",
            table_name="test_table",
            db_conn_str="PG:dummy",
            service_type="wfs",
            token=None,
        )

    # No header file, no header env var.
    assert "GDAL_HTTP_HEADERS" not in captured_env
    assert "GDAL_HTTP_HEADER_FILE" not in captured_env
    # FOLLOWLOCATION should still be NO.
    assert captured_env.get("GDAL_HTTP_FOLLOWLOCATION") == "NO"


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

    with patch(
        "asyncio.create_subprocess_exec",
        side_effect=_fake_create_subprocess_exec,
    ), patch(
        "app.processing.ingest.ogr._communicate_with_timeout",
        new=_fake_communicate_with_timeout,
    ):
        await run_ogr2ogr_service(
            gdal_source="WFS:https://example.test/wfs",
            layer_name="roads",
            table_name="test_table",
            db_conn_str="PG:dummy",
            service_type="wfs",
            token="example-token",
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

    with patch(
        "asyncio.create_subprocess_exec",
        side_effect=_fake_create_subprocess_exec,
    ), patch(
        "app.processing.ingest.ogr._communicate_with_timeout",
        new=_fake_communicate_with_timeout,
    ):
        with pytest.raises(IngestionError):
            await run_ogr2ogr_service(
                gdal_source="WFS:https://example.test/wfs",
                layer_name="roads",
                table_name="test_table",
                db_conn_str="PG:dummy",
                service_type="wfs",
                token="example-token",
            )

    assert captured_path is not None
    assert not os.path.exists(captured_path), (
        f"Header file {captured_path} must be unlinked even when subprocess fails"
    )
