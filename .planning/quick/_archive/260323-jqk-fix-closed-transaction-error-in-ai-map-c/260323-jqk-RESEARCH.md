# Quick Task 260323-jqk: Fix closed transaction error in AI map creation - Research

**Researched:** 2026-03-23
**Domain:** SQLAlchemy async transaction management
**Confidence:** HIGH

## Summary

The bug is clear-cut: `update_map()` calls `session.commit()` (line 305), but `_validate_and_persist_map()` in the AI service calls it inside `session.begin_nested()` (a SAVEPOINT). Committing inside a savepoint closes the outer transaction, causing "Can't operate on closed transaction inside context manager."

The fix is to change `update_map()` from `commit()` to `flush()`, matching the pattern already used by `create_map()`, `_replace_layers()`, `delete_map()`, `duplicate_map()`, and `add_layer()` in the same file.

**Critical discovery:** The AI router endpoints (`generate_map_endpoint` at `ai/router.py:145` and `generate_map_stream_endpoint` at `ai/router.py:191`) do NOT call `db.commit()`. The `get_db` dependency (`dependencies.py:8`) does NOT auto-commit -- it just yields the session and closes it. This means the AI path currently has NO explicit commit point. The old (broken) `update_map()` commit was accidentally the only persistence mechanism. After fixing `update_map()` to flush-only, we MUST add `await db.commit()` in the AI router's `generate_map_endpoint`, or the map will be created in the transaction but never committed.

**Primary recommendation:** Three changes required:
1. `maps/service.py:305` -- change `commit()` to `flush()`
2. `ai/router.py` -- add `await db.commit()` after `generate_map_from_prompt()` returns (line ~188)
3. `ai/router.py` -- streaming endpoint needs commit too (but it's trickier since it's inside an SSE generator)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Remove `session.commit()` from `update_map()`, replace with `session.flush()` to match the pattern used by `create_map()` and `_replace_layers()`
- Let callers own the commit lifecycle
- Fix `update_map()` to flush-only
- Clean up redundant `db.commit()` in `maps/router.py` update endpoint (line 323) -- it was a double-commit since `update_map()` already committed. Now it becomes the single, necessary commit.

### Claude's Discretion
None specified.

### Deferred Ideas (OUT OF SCOPE)
None specified.
</user_constraints>

## Caller Analysis

### All callers of `update_map()` (verified via grep)

| Caller | File:Line | Current Behavior | After Fix |
|--------|-----------|-----------------|-----------|
| `update_map_endpoint` | `maps/router.py:312` | Double-commit (update_map commits at 305, then router commits at 323) | Single commit at router line 323 (correct) |
| `_validate_and_persist_map` | `ai/service.py:450` | Crashes -- commit inside `begin_nested()` closes transaction | flush() works inside savepoint; savepoint releases on exit |

No other callers exist.

### AI router commit gap (CRITICAL)

**`generate_map_endpoint`** (`ai/router.py:145-188`):
- Calls `generate_map_from_prompt()` which calls `_validate_and_persist_map()`
- Does NOT call `db.commit()` anywhere
- `get_db()` (`dependencies.py:8-10`) yields session without auto-commit
- After fix: must add `await db.commit()` before returning `MapGenerateResponse`

**`generate_map_stream_endpoint`** (`ai/router.py:191-213`):
- Calls `stream_generate_map()` inside an SSE event generator
- The "done" event is yielded from `stream_generate_map()` at `ai/service.py:666`
- After the `_validate_and_persist_map()` call succeeds (service.py:663), a commit is needed
- Best place: inside `stream_generate_map()` itself at `ai/service.py:665` (after `map_result` is obtained, before yielding the done event), since the SSE generator doesn't have clean access to commit afterward

## Technical Verification

### flush() + refresh() after flush (HIGH confidence)

SQLAlchemy `session.flush()` writes pending changes to the database within the current transaction without committing. `session.refresh()` issues a SELECT to reload the object. Both work correctly inside and outside savepoints.

The project uses `expire_on_commit=False` (database.py:28). After flush, the object has current values, but `refresh()` ensures server-side defaults (e.g., `updated_at` triggers) are loaded.

### begin_nested() savepoint behavior (HIGH confidence)

`session.begin_nested()` creates a SQL SAVEPOINT. On successful `async with` exit, it issues `RELEASE SAVEPOINT` (not COMMIT). On exception, `ROLLBACK TO SAVEPOINT`. The outer transaction remains open.

After fix, `_validate_and_persist_map` flow:
1. `begin_nested()` creates SAVEPOINT
2. `create_map()` flushes (correct)
3. `update_map()` flushes (fixed)
4. Context manager exits, RELEASE SAVEPOINT
5. Caller commits the outer transaction

## Code Changes Required

### Change 1: `backend/app/maps/service.py` line 305
```python
# Before:
    await session.commit()
    await session.refresh(map_obj)

# After:
    await session.flush()
    await session.refresh(map_obj)
```

Update docstring at line 284-287 to say "Flushes but does NOT commit" instead of "Commits and refreshes."

### Change 2: `backend/app/ai/router.py` -- non-streaming endpoint
Add `await db.commit()` after `generate_map_from_prompt()` returns successfully (before line 188):
```python
    result = await generate_map_from_prompt(
        db, user, user_roles, body.prompt, language=body.language
    )
    await db.commit()  # <-- ADD THIS
    return MapGenerateResponse(**result)
```

### Change 3: `backend/app/ai/service.py` -- streaming path
Add `await session.commit()` inside `stream_generate_map()` after `_validate_and_persist_map()` succeeds:
```python
        map_result = await _validate_and_persist_map(
            session, user, user_roles, spec, basemap_ids=basemap_ids
        )
        await session.commit()  # <-- ADD THIS
        yield {"type": "done", **map_result}
```

This is better than committing in the router's SSE generator because the service owns the transaction lifecycle for the streaming path.

## Similar Pattern Elsewhere (informational, not in scope)

Two other service files commit inside service functions:
- `collections/service.py:55` -- `update_collection()` commits
- `datasets/service.py:501` -- dataset update commits

Neither is called from nested transactions currently. Not in scope.

## Common Pitfalls

### Pitfall 1: Forgetting commit in AI path
**What goes wrong:** Map is created in the transaction but never committed. User sees success response but map doesn't persist.
**How to avoid:** Add explicit `db.commit()` in AI router (non-streaming) and `session.commit()` in AI service (streaming).

### Pitfall 2: Committing inside SSE generator
**What goes wrong:** If commit is placed in the router's event generator, error handling becomes awkward.
**How to avoid:** Commit inside `stream_generate_map()` in the service layer, right after `_validate_and_persist_map()` succeeds.

## Sources

### Primary (HIGH confidence)
- Direct code inspection of all files in the call chain:
  - `backend/app/maps/service.py` (update_map with commit)
  - `backend/app/ai/service.py` (_validate_and_persist_map with begin_nested)
  - `backend/app/maps/router.py` (update endpoint with double-commit)
  - `backend/app/ai/router.py` (AI endpoints missing commit)
  - `backend/app/dependencies.py` (get_db -- no auto-commit)
  - `backend/app/database.py` (expire_on_commit=False)

## Metadata

**Confidence breakdown:**
- Transaction fix (commit -> flush): HIGH - clear bug, matches codebase patterns
- Router path (maps/router.py): HIGH - already has commit at line 323
- AI path commit gap: HIGH - verified via code inspection, no commit exists
- Streaming commit placement: MEDIUM - service-level commit is cleanest but verify no side effects

**Research date:** 2026-03-23
**Valid until:** N/A (bug fix, not library research)
