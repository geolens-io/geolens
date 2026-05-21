# Quick Task 260318-7i3: Cleanup Unused Code - Research

**Researched:** 2026-03-18
**Domain:** Dead code detection (Python + TypeScript)
**Confidence:** HIGH

## Summary

The project already has the right tools installed for dead code detection. Ruff (backend) catches unused imports/variables with autofix. ESLint + typescript-eslint (frontend) catches unused vars/imports. TypeScript compiler (`tsc --noEmit`) catches unreachable code and unused locals. The main gap is **dead file detection** and **unused export detection**, which require manual trace work or specialized tooling.

**Primary recommendation:** Use existing tools (ruff, eslint, tsc) for imports/variables, then do manual dead-file analysis by tracing entry points.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Both backend (Python/FastAPI) and frontend (React/TypeScript)
- Covers dead imports, dead functions, and dead files
- Deep pass: trace call graphs, remove unreachable code paths
- Entire codebase, no specific directories excluded

### Claude's Discretion
- Tooling choices for static analysis
- Order of operations (backend first vs frontend first)
</user_constraints>

## Standard Stack (Already Installed)

| Tool | Location | Purpose | Command |
|------|----------|---------|---------|
| Ruff | backend dev dep | Unused imports (F401), unused variables (F841), undefined names (F821) | `cd backend && uv run ruff check --select F401,F811,F841 .` |
| ESLint 9 + typescript-eslint | frontend dev dep | `@typescript-eslint/no-unused-vars` (enabled by recommended config) | `cd frontend && npx eslint .` |
| TypeScript 5.9 | frontend dev dep | `noUnusedLocals`, `noUnusedParameters`, unreachable code | `cd frontend && npx tsc --noEmit` |

**No additional installs needed.** The existing toolchain covers imports and variables. Dead file/export detection is best done manually for a codebase this size (187 Python files, 312 TS/TSX files).

## Architecture Patterns

### Backend (Python/FastAPI) Entry Points
Trace from these roots to find dead code:
- `backend/app/main.py` — FastAPI app, router includes
- `backend/app/*/router.py` — API route handlers (referenced by main)
- `backend/app/*/models.py` — SQLAlchemy models (imported by alembic + services)
- `alembic/` — migration files (may have legitimately "unused" imports like `sa` that alembic needs)
- Procrastinate workers — background job entry points

### Frontend (React/TS) Entry Points
- `frontend/src/main.tsx` — React entry point
- `frontend/src/App.tsx` — Router, lazy imports define the reachable component tree
- `frontend/src/api/` — API client functions (only dead if no component imports them)
- `frontend/src/components/ui/` — shadcn/ui components (some may be installed but never used)
- `frontend/src/i18n/` — i18n resources (loaded dynamically)

### Approach: Backend First
Backend is simpler (no JSX, no dynamic imports). Start there, then frontend.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| Unused imports | Manual grep | `ruff check --select F401` (autofix with `--fix`) |
| Unused TS vars | Manual grep | ESLint `no-unused-vars` rule |
| Dead TS types | Manual trace | `tsc --noEmit` with `noUnusedLocals` |

## Common Pitfalls

### Pitfall 1: Alembic Migration False Positives
**What:** Ruff flags `import sqlalchemy as sa` in alembic migrations as unused.
**Why:** Alembic autogenerate creates these imports; some migrations use `op.execute()` with raw SQL and don't reference `sa` directly.
**How to avoid:** Add `# noqa: F401` or skip `alembic/` directory. These are generated files -- do NOT remove imports from migration files.

### Pitfall 2: __init__.py Re-exports
**What:** `__init__.py` files often import symbols purely for re-export (`from .models import User`).
**Why:** Ruff may flag these as unused if the `__init__.py` itself doesn't use them.
**How to avoid:** Check if symbol is imported elsewhere via the package path before removing. Ruff's `F401` is smart about `__all__` but not always about implicit re-exports. Use `__all__` or add `# noqa: F401` for intentional re-exports.

### Pitfall 3: FastAPI Dependency Injection
**What:** Functions used only as `Depends()` parameters may appear "unused" to naive analysis.
**Why:** They're referenced as function objects, not called directly.
**How to avoid:** These show up in router signatures -- trace from router.py files, not grep for function calls.

### Pitfall 4: Dynamic/Lazy Imports in Frontend
**What:** `React.lazy(() => import('./pages/Foo'))` makes `Foo.tsx` appear unreferenced by static import analysis.
**Why:** Dynamic imports use string paths, not static import graph.
**How to avoid:** Check `App.tsx` and route config for lazy imports before declaring a page component dead.

### Pitfall 5: shadcn/ui Components
**What:** `frontend/src/components/ui/` contains installed but potentially unused UI primitives.
**Why:** shadcn installs components as source files. Some may have been installed for a feature that was later removed.
**How to avoid:** Grep for each component's import path across the codebase. If zero imports outside its own file, it's dead.

### Pitfall 6: i18n Keys and Type Definitions
**What:** i18n resource files and TypeScript type/interface definitions may appear unused.
**Why:** i18n keys are referenced as strings, not imports. Types may be used only in JSDoc or generic constraints.
**How to avoid:** Don't remove i18n files. For types, check `tsc --noEmit` -- it understands type-only usage.

### Pitfall 7: Test Utilities and Fixtures
**What:** Shared test helpers/fixtures may appear unused.
**Why:** They're imported by test files which aren't part of the main app graph.
**How to avoid:** Analyze test files separately. `conftest.py` fixtures are used by pytest discovery, not direct imports.

## Recommended Execution Order

1. **Backend automated pass**: `ruff check --select F401,F841 app/` (skip alembic/)
2. **Backend manual pass**: Grep for functions/classes defined but never imported/called
3. **Frontend automated pass**: `npx eslint . 2>&1 | grep 'no-unused-vars'` + `npx tsc --noEmit`
4. **Frontend dead file detection**: Check each `components/ui/*.tsx` for external imports; check pages referenced in router
5. **Frontend dead export detection**: For each exported function/component, grep for its import across the codebase
6. **Verify**: Run `tsc --noEmit`, `eslint .`, `ruff check .`, and test suites after cleanup

## Validation

| Check | Command |
|-------|---------|
| Backend lint clean | `cd backend && uv run ruff check app/` |
| Frontend lint clean | `cd frontend && npx eslint .` |
| Frontend types clean | `cd frontend && npx tsc --noEmit` |
| Backend tests pass | `cd backend && uv run pytest -x` |
| Frontend tests pass | `cd frontend && npx vitest run --passWithNoTests` |

## Sources

### Primary (HIGH confidence)
- Project `pyproject.toml` — ruff is in dev dependencies, no custom config (uses defaults)
- Project `eslint.config.js` — ESLint 9 flat config with typescript-eslint recommended
- Project `package.json` — TypeScript 5.9, `tsc -b` in build script
- Direct tool execution confirmed ruff and tsc work in this repo

## Metadata

**Confidence breakdown:**
- Tooling: HIGH - verified tools exist and run in this project
- Pitfalls: HIGH - based on direct codebase inspection (alembic migrations, FastAPI patterns, shadcn/ui)
- Dead file strategy: MEDIUM - manual approach works for this codebase size, no specialized tooling needed

**Research date:** 2026-03-18
**Valid until:** 2026-04-18
