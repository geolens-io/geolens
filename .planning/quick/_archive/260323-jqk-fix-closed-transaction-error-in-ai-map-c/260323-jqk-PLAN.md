---
phase: quick-260323-jqk
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/maps/service.py
  - backend/app/ai/router.py
  - backend/app/ai/service.py
autonomous: true
requirements: [FIX-CLOSED-TRANSACTION]

must_haves:
  truths:
    - "AI generate map (non-streaming) creates and persists a map without transaction errors"
    - "AI generate map (streaming) creates and persists a map without transaction errors"
    - "Direct map update endpoint still commits correctly (no regression)"
  artifacts:
    - path: "backend/app/maps/service.py"
      provides: "update_map with flush instead of commit"
      contains: "await session.flush()"
    - path: "backend/app/ai/router.py"
      provides: "Explicit commit after non-streaming generate"
      contains: "await db.commit()"
    - path: "backend/app/ai/service.py"
      provides: "Explicit commit after streaming persist"
      contains: "await session.commit()"
  key_links:
    - from: "backend/app/ai/service.py:_validate_and_persist_map"
      to: "backend/app/maps/service.py:update_map"
      via: "begin_nested savepoint wrapping flush-only update_map"
      pattern: "begin_nested.*update_map"
    - from: "backend/app/ai/router.py:generate_map_endpoint"
      to: "backend/app/ai/service.py:generate_map_from_prompt"
      via: "caller commits after service returns"
      pattern: "await db\\.commit\\(\\)"
---

<objective>
Fix "Can't operate on closed transaction inside context manager" error when creating a map via AI Generate.

Purpose: `update_map()` calls `session.commit()` inside a `begin_nested()` savepoint in `_validate_and_persist_map()`, which closes the outer transaction. Changing to `flush()` lets the savepoint work correctly. Callers must then own the commit lifecycle.

Output: Three files patched -- transaction error eliminated, map persistence verified for all paths.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/quick/260323-jqk-fix-closed-transaction-error-in-ai-map-c/260323-jqk-CONTEXT.md
@.planning/quick/260323-jqk-fix-closed-transaction-error-in-ai-map-c/260323-jqk-RESEARCH.md

<interfaces>
<!-- Key code locations for the executor -->

From backend/app/maps/service.py (line 279-307):
```python
async def update_map(
    session: AsyncSession,
    map_id: uuid.UUID,
    **kwargs,
) -> Map:
    """Update map fields. If 'layers' key present, replace all layers.
    Raises ValueError if not found. Commits and refreshes."""
    # ... field updates ...
    await session.commit()    # LINE 305 — BUG: must become flush()
    await session.refresh(map_obj)
    return map_obj
```

From backend/app/ai/service.py (line 442-458):
```python
# Inside _validate_and_persist_map():
async with session.begin_nested():
    map_obj = await create_map(session, ...)
    await update_map(session, map_obj.id, ...)  # crashes here
```

From backend/app/ai/router.py (line 144-188):
```python
@router.post("/generate-map/", response_model=MapGenerateResponse)
async def generate_map_endpoint(...):
    result = await generate_map_from_prompt(db, user, user_roles, body.prompt, ...)
    return MapGenerateResponse(**result)  # NO commit anywhere
```

From backend/app/ai/service.py (line 663-666):
```python
map_result = await _validate_and_persist_map(session, user, user_roles, spec, ...)
yield {"type": "done", **map_result}  # NO commit before yield
```

From backend/app/maps/router.py (line 312-323):
```python
await update_map(db, map_id, **kwargs)
# ... log_action ...
await db.commit()  # line 323 — was double-commit, now becomes sole commit (correct)
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Change update_map to flush-only and add commits to AI callers</name>
  <files>backend/app/maps/service.py, backend/app/ai/router.py, backend/app/ai/service.py</files>
  <action>
Three changes per user decisions and research findings:

1. **backend/app/maps/service.py line 305**: Change `await session.commit()` to `await session.flush()`. Update the docstring at line 284-287 to say "Flushes but does NOT commit" instead of "Commits and refreshes." Keep the `await session.refresh(map_obj)` on line 306 as-is (refresh after flush loads server-side defaults).

2. **backend/app/ai/router.py line 187-188** (non-streaming endpoint): Add `await db.commit()` after the try/except block succeeds, before returning the response:
```python
    result = await generate_map_from_prompt(
        db, user, user_roles, body.prompt, language=body.language
    )
    # ... existing except blocks ...

    await db.commit()
    return MapGenerateResponse(**result)
```
Place the commit AFTER all exception handlers (line ~186), before the return on line 188.

3. **backend/app/ai/service.py line 665** (streaming path inside `stream_generate_map`): Add `await session.commit()` after `_validate_and_persist_map()` returns and before yielding the done event:
```python
    map_result = await _validate_and_persist_map(
        session, user, user_roles, spec, basemap_ids=basemap_ids
    )
    await session.commit()
    yield {"type": "done", **map_result}
```

Do NOT touch the `maps/router.py` update endpoint -- it already has `await db.commit()` at line 323 which becomes the sole (correct) commit point after this fix.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && grep -n "await session.flush()" backend/app/maps/service.py | grep -q "305\|flush" && grep -n "await db.commit()" backend/app/ai/router.py | grep -q "commit" && grep -n "await session.commit()" backend/app/ai/service.py | head -5 && echo "All three changes present"</automated>
  </verify>
  <done>
    - update_map() uses flush() instead of commit()
    - update_map() docstring says "Flushes but does NOT commit"
    - generate_map_endpoint has await db.commit() before return
    - stream_generate_map has await session.commit() before yielding done event
    - maps/router.py update endpoint unchanged (still has commit at line 323)
  </done>
</task>

<task type="auto">
  <name>Task 2: Verify no regressions with backend test suite</name>
  <files>backend/app/maps/service.py</files>
  <action>
Run the existing backend test suite focused on maps and AI to confirm no regressions. Specifically:

1. Run map-related tests: `pytest backend/tests/ -k "map" -x --timeout=30`
2. Run AI-related tests: `pytest backend/tests/ -k "ai" -x --timeout=30`
3. If no AI-specific tests exist, run the full backend suite: `pytest backend/tests/ -x --timeout=60`

Verify that:
- Map CRUD operations still work (update_map callers commit correctly)
- No transaction-related errors appear
- All existing tests pass

If any test fails due to the flush change (e.g., a test that relied on update_map committing), fix it by adding an explicit commit in the test or the caller.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && python -m pytest backend/tests/ -k "map or ai" -x --timeout=60 2>&1 | tail -20</automated>
  </verify>
  <done>All existing map and AI tests pass with zero transaction errors</done>
</task>

</tasks>

<verification>
1. `grep -n "flush\|commit" backend/app/maps/service.py` shows flush on the update_map line, no commit
2. `grep -n "commit" backend/app/ai/router.py` shows db.commit() in generate_map_endpoint
3. `grep -n "commit" backend/app/ai/service.py` shows session.commit() in stream_generate_map
4. Backend tests pass: `pytest backend/tests/ -k "map or ai" -x`
</verification>

<success_criteria>
- update_map uses flush() not commit()
- AI non-streaming endpoint commits after generate_map_from_prompt
- AI streaming path commits after _validate_and_persist_map
- maps/router.py update endpoint unchanged (already correct)
- All backend tests pass
</success_criteria>

<output>
After completion, create `.planning/quick/260323-jqk-fix-closed-transaction-error-in-ai-map-c/260323-jqk-SUMMARY.md`
</output>
