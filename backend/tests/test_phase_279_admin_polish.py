"""Phase 279 ADMIN-01 + ADMIN-02 regression tests.

ADMIN-01 (M-01): Pin ApiKeyCreateRequest.name max_length=255 against future
schema refactors. Without this gate a future "tidy up the validators" PR
could drop the constraint and rely on the DB column to truncate, which
silently corrupts user input.

ADMIN-02 (M-02; corrected in T-1): Pin the admin audit-log search query
rewrite from ILIKE to lower(catalog.immutable_unaccent(...)).like(...) against
future refactors. The trigram GIN indexes (ix_audit_logs_action_trgm,
ix_users_username_trgm from migration 0015) are built on
lower(catalog.immutable_unaccent(...)) -- the query MUST use that exact
schema-qualified IMMUTABLE function. A bare ILIKE, OR a plain unaccent()
(which renders unqualified -> public.unaccent, STABLE), does NOT match the
indexed expression, so without this gate a refactor could silently regress
admin-search latency from index-scan to seq-scan.
"""

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.audit.service import _apply_filters
from app.modules.auth.schemas import ApiKeyCreateRequest


# -------------------------------------------------------------------
# ADMIN-01 -- ApiKeyCreateRequest.name max_length regression tests
# -------------------------------------------------------------------


def test_api_key_create_name_max_length_enforced():
    with pytest.raises(ValidationError) as exc_info:
        ApiKeyCreateRequest(name="x" * 256)
    # pydantic v2 emits 'string_too_long' for max_length violations
    errors = exc_info.value.errors()
    assert any(
        e["type"] == "string_too_long" or "max_length" in str(e).lower() for e in errors
    ), f"Expected max_length error, got: {errors}"


def test_api_key_create_name_max_length_boundary():
    req = ApiKeyCreateRequest(name="x" * 255)
    assert len(req.name) == 255


def test_api_key_create_name_min_length():
    with pytest.raises(ValidationError):
        ApiKeyCreateRequest(name="")


# -------------------------------------------------------------------
# ADMIN-02 -- Audit-log search uses indexed lower(catalog.immutable_unaccent(...)) form
# -------------------------------------------------------------------


def _compiled_search_sql(search: str | None) -> str:
    """Return the compiled SQL string for _apply_filters with the given search term."""
    q = _apply_filters(select(AuditLog), search=search)
    return str(q.compile(compile_kwargs={"literal_binds": True})).lower()


def test_audit_search_query_uses_indexed_action_expression():
    sql = _compiled_search_sql("login")
    # The migration 0015 GIN trigram index is on
    # lower(catalog.immutable_unaccent(action)). Postgres only uses the index
    # when the query expression matches that exact schema-qualified function --
    # bare ILIKE, or a plain unaccent() (-> public.unaccent), does NOT match.
    assert "lower(catalog.immutable_unaccent(" in sql, sql
    assert "audit_logs.action" in sql or "audit_logs_1.action" in sql, sql


def test_audit_search_query_uses_indexed_username_expression():
    sql = _compiled_search_sql("admin")
    # ix_users_username_trgm is on lower(catalog.immutable_unaccent(username)).
    assert "lower(catalog.immutable_unaccent(" in sql, sql
    assert "users.username" in sql, sql


def test_audit_search_query_omits_search_branch_when_search_is_none():
    sql = _compiled_search_sql(None)
    # When search is None we must NOT emit the rewritten expression;
    # this guards against an accidental always-on rewrite.
    assert "lower(catalog.immutable_unaccent(" not in sql, sql
