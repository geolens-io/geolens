"""Sandbox schemas and error types."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel


class SandboxError(Exception):
    """Sandbox validation or execution error.

    Categories:
        - invalid_query: SQL is not a valid single SELECT
        - table_not_accessible: Table not in user's RBAC allowlist
        - query_timeout: Query exceeded time limit
        - query_busy: Another query is already running for the caller
        - query_failed: Database execution error
    """

    def __init__(self, category: str, user_message: str) -> None:
        self.category = category
        self.user_message = user_message
        super().__init__(user_message)


@dataclass
class ValidatedQuery:
    """Result of successful SQL validation.

    ``table_counts`` counts every named table/CTE REFERENCE in the statement,
    keyed by lowercased ``(schema, name)`` — unlike ``tables``, which dedupes.
    feat(#565): the raw-SQL endpoint uses these counts for its self-join
    repetition cap; see ``validate_and_execute(max_table_repeats=...)``.
    """

    sql: str
    tables: set[tuple[str, str]] = field(default_factory=set)
    cte_names: set[str] = field(default_factory=set)
    table_counts: dict[tuple[str, str], int] = field(default_factory=dict)


class SandboxResult(BaseModel):
    """Structured result from sandbox query execution.

    Uses list-of-lists for rows (not list-of-dicts) for serialization performance.
    """

    rows: list[list]
    columns: list[str]
    row_count: int
    truncated: bool
