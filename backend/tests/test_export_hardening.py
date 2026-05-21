"""Unit tests for Phase 1069 export hardening:
- IA-P1-04: validate_where_clause rejects statement terminators, comments,
  and unbalanced single-quotes (in addition to v1014 SEC-S09 AST allowlist).
- IA-P1-01: export_dataset_endpoint depends on require_permission("export")
  instead of get_current_active_user, closing the capability-matrix gap.

Phase 1071 (v1016) follow-up:
- KNOWN-05: TestExportRevokedViewerParity — live 403-for-revoked-viewer
  regression test, closing the v1015 Phase 1069 IA-P1-01 verification gap.

Requirements: IA-P1-04, IA-P1-01, KNOWN-05
Phase: 1069, 1071
"""

import os
import shutil
import tempfile

import pytest
from httpx import AsyncClient

from app.processing.export.service import validate_where_clause
from app.processing.export.ogr import FORMAT_MAP

from tests.factories import create_dataset, get_user_id


# ---------------------------------------------------------------------------
# IA-P1-04: where-clause rejects meta-SQL tokens
# ---------------------------------------------------------------------------


COLS = [{"name": "pop"}, {"name": "name"}, {"name": "country"}]


class TestWhereClauseInjectionRejection:
    def test_statement_terminator_rejected(self):
        with pytest.raises(ValueError) as exc:
            validate_where_clause("pop > 1000; DROP TABLE catalog.records", COLS)
        assert "terminator" in str(exc.value).lower() or ";" in str(exc.value)

    def test_line_comment_rejected(self):
        with pytest.raises(ValueError) as exc:
            validate_where_clause("pop > 1000 -- malicious", COLS)
        assert "comment" in str(exc.value).lower() or "--" in str(exc.value)

    def test_block_comment_open_rejected(self):
        with pytest.raises(ValueError) as exc:
            validate_where_clause("pop > 1000 /* injection", COLS)
        assert "comment" in str(exc.value).lower() or "/*" in str(exc.value)

    def test_block_comment_close_rejected(self):
        with pytest.raises(ValueError) as exc:
            validate_where_clause("name = */ 'x'", COLS)
        assert "comment" in str(exc.value).lower() or "*/" in str(exc.value)

    def test_unbalanced_quote_rejected(self):
        with pytest.raises(ValueError) as exc:
            validate_where_clause("name = 'a", COLS)
        assert "quote" in str(exc.value).lower()

    def test_classic_or_injection_blocked_by_ast(self):
        """The AST layer (v1014 SEC-S09) blocks UNION/subquery injection."""
        with pytest.raises(ValueError) as exc:
            validate_where_clause(
                "name = 'a' OR '1'='1' UNION SELECT password FROM users",
                COLS,
            )
        # Any layer (string-level or AST) is fine; just verify it's rejected.
        assert exc.value  # truthy

    def test_balanced_string_literal_accepted(self):
        """A legitimate WHERE with properly-quoted string literals passes the
        IA-P1-04 checks (statement terminator / comment / unbalanced quote)
        and the v1014 SEC-S09 AST allowlist.

        Note: the identifier regex inside validate_where_clause may flag
        text-inside-quotes as a candidate identifier (pre-existing v1014
        behavior, out of IA-P1-04 scope). To exercise just the IA-P1-04
        layer we use a quoted value that doesn't look like an identifier."""
        # Numeric-only string (passes identifier check, passes IA-P1-04).
        validate_where_clause("name = '42'", COLS)
        # SQL-escaped doubled quote — IA-P1-04 must accept (collapses to even).
        validate_where_clause("name = '42'' '", COLS)

    def test_numeric_comparison_accepted(self):
        validate_where_clause("pop > 1000", COLS)
        validate_where_clause("pop BETWEEN 100 AND 200", COLS)


# ---------------------------------------------------------------------------
# IA-P1-01: capability gate on export_dataset_endpoint
# ---------------------------------------------------------------------------


class TestExportEndpointCapabilityGate:
    def test_export_endpoint_uses_require_permission(self):
        """The dependency on the endpoint must be the require_permission
        factory for 'export', NOT bare get_current_active_user. This is a
        static-shape test that doesn't need a live FastAPI app."""
        import inspect

        from app.processing.export.router import export_dataset_endpoint
        from app.modules.auth.dependencies import require_permission

        sig = inspect.signature(export_dataset_endpoint)
        user_param = sig.parameters["user"]
        default = user_param.default

        # FastAPI Depends carries a `dependency` attribute that's the resolver.
        # require_permission("export") returns a closure named _permission_checker.
        assert default is not None, "user param must have a Depends() default"
        dep_callable = getattr(default, "dependency", None)
        assert dep_callable is not None, "Depends() must reference a callable"
        # The closure name from require_permission factory is _permission_checker.
        assert dep_callable.__name__ == "_permission_checker", (
            f"Expected require_permission factory, got {dep_callable.__name__}"
        )


# ---------------------------------------------------------------------------
# KNOWN-05 (Phase 1071): live 403-for-revoked-viewer parity with v1014 SEC-S04
# ---------------------------------------------------------------------------
#
# v1015 Phase 1069 IA-P1-01 verified the dependency via signature inspection
# (TestExportEndpointCapabilityGate above) plus a live 401-for-anonymous
# Playwright MCP smoke. The 403-for-revoked-viewer path — the actual
# capability-matrix branch that runs in production — was never exercised by a
# test that would fail if the matrix-consultation code in require_permission's
# closure were silently bypassed. This section closes that gap.
#
# Production code is already correct (see require_permission at
# app/modules/auth/dependencies.py:270 and export router at
# app/processing/export/router.py:47). This is a regression pin.


# Default matrix payload — viewer.export=True (the v1014 SEC-S04 baseline).
# Used to restore the permission state after revoke tests so leakage
# into other tests is prevented. (The clean_tables fixture does NOT
# truncate the persistent_config table, so manual restore is needed.)
_DEFAULT_PERMISSION_MATRIX = {
    "viewer": {
        "upload": False,
        "create_layers": False,
        "export": True,
        "edit_metadata": False,
        "manage_collections": False,
        "use_ai_chat": False,
        "manage_users": False,
        "manage_settings": False,
    },
    "editor": {
        "upload": True,
        "create_layers": True,
        "export": True,
        "edit_metadata": True,
        "manage_collections": True,
        "use_ai_chat": True,
        "manage_users": False,
        "manage_settings": False,
    },
    "admin": {
        "upload": True,
        "create_layers": True,
        "export": True,
        "edit_metadata": True,
        "manage_collections": True,
        "use_ai_chat": True,
        "manage_users": True,
        "manage_settings": True,
    },
}


# Revoke matrix: same as default but viewer.export=False.
_VIEWER_EXPORT_REVOKED_MATRIX = {
    **_DEFAULT_PERMISSION_MATRIX,
    "viewer": {**_DEFAULT_PERMISSION_MATRIX["viewer"], "export": False},
}


@pytest.fixture
def mock_export_service_for_known05(monkeypatch):
    """Mock app.processing.export.router.export_dataset to avoid ogr2ogr.

    Mirrors the autouse fixture in tests/test_export.py so this file's live
    integration tests can exercise the router without a real PostGIS table.
    Returns a dummy GeoPackage path; FileResponse handles the rest.
    """
    temp_dir = tempfile.mkdtemp(prefix="test_export_hardening_known05_")

    async def _fake_export(
        table_name,
        dataset_name,
        format_key,
        *,
        target_srs=None,
        bbox=None,
        where=None,
        column_info=None,
    ):
        if format_key not in FORMAT_MAP:
            raise ValueError(f"Unsupported export format: {format_key}")
        fmt = FORMAT_MAP[format_key]
        ext = fmt["ext"]
        media = fmt["media"]
        if format_key == "shp":
            filename = f"{dataset_name}.zip"
        else:
            filename = f"{dataset_name}{ext}"
        file_path = os.path.join(temp_dir, filename)
        with open(file_path, "wb") as f:
            f.write(b"mock export data")
        return file_path, filename, media

    monkeypatch.setattr(
        "app.processing.export.router.export_dataset", _fake_export
    )

    yield _fake_export

    if os.path.isdir(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)


async def _put_permission_matrix(
    client: AsyncClient, admin_auth_header: dict, matrix: dict
) -> None:
    """Helper: admin PUT to /settings/ to update the permission matrix.

    Mirrors the pattern from tests/test_permissions.py::test_get_put_permissions
    (lines 184-189). The /settings/ endpoint is the canonical admin path
    for the role_permissions PersistentConfig key.
    """
    resp = await client.put(
        "/settings/",
        json={"settings": {"role_permissions": matrix}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, (
        f"Admin PUT to update role_permissions must succeed; got "
        f"{resp.status_code}: {resp.text}"
    )


async def _reset_permission_matrix(
    client: AsyncClient, admin_auth_header: dict
) -> None:
    """Helper: admin POST to /settings/reset/ to drop role_permissions override.

    After reset, get_effective_permissions falls back to
    DEFAULT_ROLE_PERMISSIONS (viewer.export=True).
    """
    resp = await client.post(
        "/settings/reset/",
        json={"keys": ["role_permissions"]},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, (
        f"Admin POST to reset role_permissions must succeed; got "
        f"{resp.status_code}: {resp.text}"
    )


class TestExportRevokedViewerParity:
    """v1015 Phase 1069 IA-P1-01 verified the dependency via signature
    inspection + a live 401-for-anonymous smoke. KNOWN-05 closes the
    remaining gap: an authenticated viewer whose `export` capability has
    been REVOKED by admin gets 403 from GET /datasets/{id}/export — full
    parity with the v1014 SEC-S04 capability-matrix contract.

    Both tests are self-contained — they explicitly set the matrix they
    need and reset it on exit — because the clean_tables fixture does NOT
    truncate the persistent_config table.
    """

    @pytest.mark.anyio
    async def test_export_403_when_viewer_export_revoked(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
        mock_export_service_for_known05,
    ):
        """Revoke viewer.export via admin matrix PUT, then attempt export
        as viewer on a PUBLIC dataset. Expect 403.

        Uses a PUBLIC dataset so the visibility filter passes and we
        exercise the capability gate's 403 branch (NOT the visibility
        filter's 404 branch — see test_export.py:163).
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="PublicExportRevokedTest",
        )

        try:
            # Sanity: with default matrix (viewer.export=True), viewer CAN
            # export a public dataset. Pins the baseline before we revoke.
            resp = await client.get(
                f"/datasets/{ds.id}/export", headers=viewer_auth_header
            )
            assert resp.status_code == 200, (
                f"Default matrix should let viewer export public datasets; "
                f"got {resp.status_code}: {resp.text}"
            )

            # Revoke export from viewer (everything else preserved).
            await _put_permission_matrix(
                client, admin_auth_header, _VIEWER_EXPORT_REVOKED_MATRIX
            )

            # As viewer, attempt the same export — expect 403.
            resp = await client.get(
                f"/datasets/{ds.id}/export", headers=viewer_auth_header
            )
            assert resp.status_code == 403, (
                f"Revoked viewer must get 403 on export (NOT 401, NOT 404); "
                f"got {resp.status_code}: {resp.text}"
            )
            # require_permission emits f"Missing permission: {cap}"
            # (see dependencies.py:314).
            detail = resp.json().get("detail", "")
            assert "permission" in detail.lower() and "export" in detail.lower(), (
                f"Expected detail to mention 'permission' and 'export'; "
                f"got {detail!r}"
            )
        finally:
            # Restore the matrix to defaults so the revoke doesn't leak
            # into subsequent tests in the suite.
            await _reset_permission_matrix(client, admin_auth_header)

    @pytest.mark.anyio
    async def test_export_200_when_editor_export_kept(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        editor_auth_header: dict,
        test_db_session,
        mock_export_service_for_known05,
    ):
        """Defense-in-depth: confirm the revoke is scoped to viewer.
        Editor (whose export was NOT revoked) STILL gets 200.

        Prevents a regression where the matrix PUT accidentally wipes
        other roles' capabilities. This test is self-contained — it
        issues its own PUT and reset rather than depending on the
        previous test's state.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="EditorExportPreservedTest",
        )

        try:
            # Apply the SAME revoke matrix used in the viewer test
            # (viewer.export=False, editor.export=True). The editor still
            # has export — this verifies the revoke is scoped, not blanket.
            await _put_permission_matrix(
                client, admin_auth_header, _VIEWER_EXPORT_REVOKED_MATRIX
            )

            resp = await client.get(
                f"/datasets/{ds.id}/export", headers=editor_auth_header
            )
            assert resp.status_code == 200, (
                f"Editor must still export (matrix did not revoke "
                f"editor.export); got {resp.status_code}: {resp.text}"
            )
        finally:
            await _reset_permission_matrix(client, admin_auth_header)
