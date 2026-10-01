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
from app.processing.export.where_validator import mask_quoted_literals
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

        fix(#1870): word-shaped values are covered by
        TestWhereClauseStringLiterals below; these two stay as the
        numeric-shaped IA-P1-04 cases they were written as."""
        # Numeric-only string (passes identifier check, passes IA-P1-04).
        validate_where_clause("name = '42'", COLS)
        # SQL-escaped doubled quote — IA-P1-04 must accept (collapses to even).
        validate_where_clause("name = '42'' '", COLS)

    def test_numeric_comparison_accepted(self):
        validate_where_clause("pop > 1000", COLS)
        validate_where_clause("pop BETWEEN 100 AND 200", COLS)


# ---------------------------------------------------------------------------
# fix(#1870): a string VALUE is not a column reference
# ---------------------------------------------------------------------------


class TestWhereClauseStringLiterals:
    """The identifier walk reads the code around the values, never the values.

    Before #1870 it ran over the raw clause, so any quoted value containing a
    word was refused as an unknown column and text filtering was unusable.
    Every case here raised ValueError on main.
    """

    def test_literal_containing_a_space_accepted(self):
        assert (
            validate_where_clause("name = 'Main Street'", COLS)
            == "name = 'Main Street'"
        )

    def test_literal_in_like_pattern_accepted(self):
        validate_where_clause("pop > 10 AND name LIKE 'Water%'", COLS)

    def test_literal_equal_to_a_sql_keyword_accepted(self):
        validate_where_clause("name = 'SELECT'", COLS)
        validate_where_clause("name = 'DROP TABLE'", COLS)

    def test_literal_naming_a_foreign_column_accepted(self):
        """A value that happens to be some other dataset's column name is a
        value here, not a reference to a column this dataset does not have."""
        validate_where_clause("name = 'elevation'", COLS)

    def test_literal_naming_this_datasets_own_column_accepted(self):
        validate_where_clause("name = 'country'", COLS)

    def test_escaped_quote_in_literal_accepted(self):
        validate_where_clause("name = 'O''Brien Park'", COLS)

    def test_empty_literal_accepted(self):
        validate_where_clause("name = ''", COLS)

    def test_in_list_of_literals_accepted(self):
        validate_where_clause("name IN ('Main Street', 'Elm Ave')", COLS)

    # --- counterfactuals: nothing outside a literal got looser -------------

    def test_unknown_column_after_a_literal_still_refused(self):
        with pytest.raises(ValueError, match="Unknown column: nope"):
            validate_where_clause("name = 'x' AND nope = 1", COLS)

    def test_unknown_column_before_a_literal_still_refused(self):
        with pytest.raises(ValueError, match="Unknown column: nope"):
            validate_where_clause("nope = 'Main Street'", COLS)

    def test_unknown_column_between_two_literals_still_refused(self):
        with pytest.raises(ValueError, match="Unknown column: nope"):
            validate_where_clause("name = 'a' AND nope = 'b' AND pop > 1", COLS)

    def test_terminator_inside_a_literal_still_refused(self):
        """The meta-SQL checks deliberately run over the RAW clause, so a ';'
        is refused wherever it appears. Narrowing them to code-only would be a
        separate change with its own review."""
        with pytest.raises(ValueError, match="terminator"):
            validate_where_clause("name = 'a;b'", COLS)

    def test_line_comment_inside_a_literal_still_refused(self):
        with pytest.raises(ValueError, match="comment"):
            validate_where_clause("name = 'a--b'", COLS)

    def test_unbalanced_quote_still_refused(self):
        with pytest.raises(ValueError, match="quote"):
            validate_where_clause("name = 'Main Street", COLS)

    def test_ast_gate_still_runs_before_the_walk(self):
        with pytest.raises(ValueError) as exc:
            validate_where_clause("name = 'a' OR 1=1 UNION SELECT 1", COLS)
        assert "unknown column" not in str(exc.value).lower()

    def test_identifiers_split_by_a_literal_do_not_fuse(self):
        """Masking preserves width, so `na'x'me` cannot become the column
        `name`. The AST gate rejects this shape first; the assertion is that
        no layer accepts it."""
        with pytest.raises(ValueError):
            validate_where_clause("na'x'me = 1", COLS)

    # --- a quote inside a double-quoted identifier is not a literal --------

    def test_quote_in_a_double_quoted_identifier_does_not_hide_a_column(self):
        """A single quote inside a double-quoted identifier opens no literal
        in Postgres, so it must open no mask either: the code after it stays
        visible to the walk."""
        with pytest.raises(ValueError, match="Unknown column: secret"):
            validate_where_clause('"name\'" = 1 AND secret = 1 AND "name\'" = 1', COLS)

    def test_lone_quote_in_a_double_quoted_identifier_does_not_hide_a_column(self):
        with pytest.raises(ValueError, match="Unknown column: secret"):
            validate_where_clause('"\'" = 1 AND secret = 1 AND "\'" = 1', COLS)

    def test_double_quoted_identifier_beside_a_literal_accepted(self):
        validate_where_clause("\"name\" = 'x'", COLS)


class TestMaskQuotedLiterals:
    """Unit contract of the masking helper the walk runs through."""

    def test_masking_preserves_length(self):
        where = "name = 'Main Street' AND pop > 1"
        assert len(mask_quoted_literals(where)) == len(where)

    def test_literal_contents_are_blanked(self):
        assert mask_quoted_literals("name = 'Main Street'") == "name = " + " " * 13

    def test_escaped_quote_consumed_as_one_literal(self):
        assert mask_quoted_literals("name = 'O''Brien'") == "name = " + " " * 10

    def test_code_between_literals_survives(self):
        assert mask_quoted_literals("'a' AND nope = 'b'") == "    AND nope =    "

    def test_empty_literal_blanked(self):
        assert mask_quoted_literals("name = ''") == "name =   "

    def test_no_literal_is_a_no_op(self):
        assert mask_quoted_literals("pop > 1000") == "pop > 1000"

    def test_double_quoted_identifier_returned_unchanged(self):
        assert mask_quoted_literals('"name" = 1') == '"name" = 1'

    def test_quote_inside_a_double_quoted_identifier_opens_no_literal(self):
        """Two such identifiers, so a scan that saw only single quotes would
        pair them and blank the code between."""
        where = '"name\'" = 1 AND secret = 1 AND "name\'" = 1'
        assert mask_quoted_literals(where) == where

    def test_literal_after_a_double_quoted_identifier_still_blanked(self):
        assert mask_quoted_literals("\"name\" = 'x'") == '"name" = ' + " " * 3


# ---------------------------------------------------------------------------
# IA-P1-01: capability gate on export_dataset_endpoint
# ---------------------------------------------------------------------------


class TestExportEndpointCapabilityGate:
    def test_export_endpoint_is_anonymous_capable_with_capability_gate(self):
        """EXP-01: the export endpoint is anonymous-capable (get_optional_user),
        NOT gated by require_permission at the signature level. The 'export'
        capability check moved into the authenticated branch of the handler body
        (via get_effective_permissions). This static-shape test pins both:
        (1) the user param resolves via get_optional_user, and
        (2) the handler source still enforces the export capability — guarding
        against the gate being silently dropped.
        Behavioral allow/deny coverage lives in test_export_access.py (EXP-02)."""
        import inspect

        from app.processing.export.router import export_dataset_endpoint

        sig = inspect.signature(export_dataset_endpoint)
        user_param = sig.parameters["user"]
        default = user_param.default

        # FastAPI Depends carries a `dependency` attribute that's the resolver.
        assert default is not None, "user param must have a Depends() default"
        dep_callable = getattr(default, "dependency", None)
        assert dep_callable is not None, "Depends() must reference a callable"
        assert dep_callable.__name__ == "get_optional_user", (
            f"Expected get_optional_user (anonymous-capable per EXP-01), "
            f"got {dep_callable.__name__}"
        )

        # The export capability gate must still be enforced in the handler body
        # (authenticated branch) — pin it so it cannot be silently removed.
        src = inspect.getsource(export_dataset_endpoint)
        assert "get_effective_permissions" in src, (
            "export capability gate (get_effective_permissions) missing from handler body"
        )
        assert '"export"' in src or "'export'" in src, (
            "export capability key missing from handler body"
        )


class TestExportFileTouchedBeforeStreaming:
    def test_export_endpoint_touches_the_file_before_filereponse(self):
        """fix(#1435 codex round 2): the periodic and boot-time export sweeps
        both read an export's mtime as its "last activity" signal. ogr2ogr's
        writes keep the file fresh while it is being generated, but the
        mtime freezes the moment ogr2ogr closes it — including for the rest
        of a (possibly long, possibly slow-client) download. Refreshing the
        file's mtime right before handing it to FileResponse restarts that
        clock at "streaming is about to begin" instead of "generation
        finished sometime earlier," closing the gap where a still-downloading
        export could be swept out from under a client mid-stream.

        Source-inspection, matching the sibling capability-gate test above:
        standing up a full dataset + ogr2ogr run to exercise this one-line
        os.utime call would not cover anything this check does not already
        pin more directly, and the behavioral effect (mtime freshness) is
        exercised by test_worker_exports_sweep.py's sweep-algorithm tests.

        fix(#1532 review, internal): the response is a StreamingResponse over
        the temp file now, not a FileResponse — starlette parses `Range` inside
        the latter and answered a resuming client with a slice of a fresh
        conversion. The invariant is unchanged and so is the reason for it: the
        sweep still reads the temp directory's mtime, and this response still
        streams that file for as long as the client takes.
        """
        import inspect

        from app.processing.export.router import export_dataset_endpoint

        src = inspect.getsource(export_dataset_endpoint)
        assert "os.utime(file_path, None)" in src, (
            "export_dataset_endpoint must refresh file_path's mtime before "
            "streaming it, so the sweep's age clock restarts at download time"
        )
        assert src.index("os.utime(file_path, None)") < src.index(
            "artifact_response.temp_file_response("
        ), (
            "the mtime touch must run BEFORE the streaming response is "
            "constructed, not after"
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
        schema,
        target_srs=None,
        bbox=None,
        where=None,
        pmtiles_maxzoom=None,
        column_info=None,
        deadline=None,
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

    monkeypatch.setattr("app.processing.export.router.export_dataset", _fake_export)

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
                f"Expected detail to mention 'permission' and 'export'; got {detail!r}"
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
