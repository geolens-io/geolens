# Quick Task 260323-jqk: Fix closed transaction error in AI map creation - Context

**Gathered:** 2026-03-23
**Status:** Ready for planning

<domain>
## Task Boundary

Fix "Can't operate on closed transaction inside context manager" error when creating a map via AI Generate. The error occurs because `update_map()` calls `session.commit()` inside a `begin_nested()` savepoint in `_validate_and_persist_map()`.

</domain>

<decisions>
## Implementation Decisions

### Transaction Fix Strategy
- Remove `session.commit()` from `update_map()`, replace with `session.flush()` to match the pattern used by `create_map()` and `_replace_layers()`
- Let callers own the commit lifecycle

### Caller Impact Scope
- Fix `update_map()` to flush-only
- Clean up redundant `db.commit()` in `maps/router.py` update endpoint (line 323) — it was a double-commit since `update_map()` already committed. Now it becomes the single, necessary commit.
- The AI service path (`ai/service.py`) uses `begin_nested()` which auto-commits on context exit, then the outer session handles the final commit.

</decisions>

<specifics>
## Specific Ideas

- `update_map()` at `backend/app/maps/service.py:305` — change `commit()` to `flush()`
- `maps/router.py:323` — keep the `db.commit()` here since it's now the sole commit point
- `ai/service.py:442-458` — the `begin_nested()` savepoint will work correctly once `update_map()` stops committing

</specifics>
