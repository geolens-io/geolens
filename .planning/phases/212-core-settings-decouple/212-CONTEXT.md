# Phase 212: core-settings-decouple - Context

**Gathered:** 2026-04-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Break the `core ↔ settings` layering inversion. After this phase, `backend/app/core/` no longer imports anything from `backend/app/modules/settings/`. The two specific imports that violate the open-core layering rule today —
- `backend/app/core/persistent_config.py:30` → `from app.modules.settings.models import AppSetting`
- `backend/app/core/public_urls.py:14`       → `from app.modules.settings.models import AppSetting`
— are gone. PersistentConfig (DB-backed config with cache + audit) and the public URL resolver (request → DB override → env precedence) keep their existing observable behavior. The 1965-test backend baseline stays green.

In scope: relocate `AppSetting` ORM model, update all imports across the repo, add a regression guard, verify migrations and tests still pass.

Out of scope: any change to PersistentConfig semantics, settings router behavior, settings UI, audit-log emission, cache TTLs, JSONB unwrap logic, or the public URL precedence rules. No new ConfigProvider abstraction (rejected — see decisions below).

</domain>

<decisions>
## Implementation Decisions

### Decoupling approach
- **D-01 (auto-selected):** Relocate the `AppSetting` SQLAlchemy model from `backend/app/modules/settings/models.py` to `backend/app/core/db/models.py`. Reason: the audit explicitly offers this as the simpler of the two options; it is a mechanical Python-only refactor with no behavior change, no new abstraction, and no startup-registration plumbing. The alternative — defining a `ConfigProvider` Protocol in `core/` and registering a concrete impl from `settings/` at app startup — adds a new extension seam this phase doesn't need (Phase 214's `IdentityProtocol` is the right place to introduce that pattern; doing it here would duplicate work and inflate Phase 212's scope).
- **D-02:** `backend/app/core/db/models.py` is a new file. It will hold `AppSetting` only at this phase. Future core-owned ORM models can land here; this phase does NOT pre-emptively move other models (no scope creep).
- **D-03:** The `app_settings` table keeps its current schema (`schema="catalog"`, `key TEXT PK`, `value JSONB NOT NULL`). The Python class moves; the table does not. No Alembic migration is generated or required (audit success-criterion 4: "no test required `AppSetting`-import shimming" is satisfied because it's a pure Python relocation, and Alembic identifies tables by `__tablename__` + `__table_args__`, not by import path — verified mental model; phase plan should run `make migrations-check` / `alembic check` as proof).

### Caller migration
- **D-04 (auto-selected):** Migrate ALL callers in one shot — no backward-compat re-export shim left behind in `backend/app/modules/settings/models.py`. The repo is a closed set; every importer is known and inside this codebase. Known caller sites to migrate:
  - `backend/app/core/persistent_config.py:30` (the offending import — this is the whole point)
  - `backend/app/core/public_urls.py:14` (the offending import)
  - `backend/app/modules/settings/router.py:33` (in-domain caller — switches to `core.db.models` like everyone else)
  - `backend/tests/test_hybrid_search.py:24` (test fixture)
  - `backend/tests/test_validation.py:221` (test fixture, deferred-import inside function)
  - Any other imports surfaced by `grep -rn "from app.modules.settings.models import AppSetting\|from app.modules.settings import .*AppSetting\|app.modules.settings.models" backend/` during planning — planner must run this grep and migrate every hit.
- **D-05:** The file `backend/app/modules/settings/models.py` is **deleted** (no shim, no re-export). If `modules/settings/` later needs domain-specific models, a new `models.py` can be reintroduced — but as of this phase, nothing in that module needs an ORM model of its own.

### Regression prevention
- **D-06 (auto-selected):** Add a regression guard to prevent future re-introduction of the exact layering inversion this phase removes. Implementation: a small Python test under `backend/tests/test_layering.py` (or extension of an existing architecture test if one exists — planner checks first) that asserts `subprocess.run(["git", "grep", "-n", "from app.modules.settings", "--", "backend/app/core/"])` returns no matches AND that no module under `backend/app/core/` does `from app.modules.<anything>` at import time. Reason: the audit caught this exact pattern; without an automated guard, the next contributor adding a "convenient" core import will reopen the finding and Phase 218's `/oc-audit` re-run will fail. The guard is cheap (one process spawn in a fast test) and explicit about the rule.
- **D-07:** The guard test SHOULD be skippable in dev (`pytest -m architecture` opt-out path is fine) but MUST run in CI. Don't break local TDD loops over a static check.

### Migration & verification
- **D-08 (auto-selected):** No Alembic migration is generated. Proof step in the phase plan: after the refactor, run `cd backend && uv run alembic check` (or the project's equivalent — `make migrations-check` if defined) and confirm it reports "no new operations." If it ever reports a diff, the move was not pure (e.g., someone changed `__table_args__` accidentally) and the planner stops.
- **D-09:** The 1965-test backend baseline (per STATE.md, restored 2026-04-26 by `260425-sl1`) is the acceptance gate. Plan must include a full `pytest` run; any non-baseline failure is a defect introduced by the refactor and must be fixed before the phase commits.
- **D-10:** Frontend has no involvement in this phase. The settings router's HTTP contract is unchanged; the admin Settings UI does not need to be rebuilt or retested manually beyond the smoke check in success-criterion 2 of ROADMAP.md.

### Claude's Discretion
- The exact name of the new file (`core/db/models.py` vs. `core/db/app_settings.py`) — `core/db/models.py` is the audit's wording and aligns with SQLAlchemy convention of co-locating models with `Base`. Planner may use a different filename if there is a strong reason, but should not invent one without justification.
- The exact form of the architecture guard test (subprocess `git grep` vs. AST walk vs. import-graph library) — planner picks based on what's already in `backend/tests/` (e.g., if there's already an arch-style test, extend it; otherwise the simplest `git grep` invocation suffices).
- Commit decomposition — likely 3 atomic commits: (1) introduce `core/db/models.py` with `AppSetting`, (2) migrate all callers + delete old `models.py`, (3) add the architecture guard test. Planner may collapse or split as appropriate.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Audit / spec
- `docs-internal/audits/oc-separation-deferred-items-20260426.md` — P1 bucket, row "Break `core ↔ settings` layering inversion." This is the source spec. Names the two specific files and the two implementation options.
- `docs-internal/audits/oc-separation-audit-20260426.md` — full audit body (§5 layering finding context).
- `docs-internal/audits/oc-separation-audit-20260426-b.md` — supplementary audit (referenced by the deferred-items doc).
- `.planning/REQUIREMENTS.md` §LAYER-01 — the requirement this phase closes.
- `.planning/ROADMAP.md` §Phase 212 — the goal statement and 5 success criteria.

### Project / state
- `.planning/PROJECT.md` — milestone overview; confirms v13.1 is the audit-driven milestone with target grades Boundary B → A−, Seam Quality C → B, OSS Surface D → C.
- `.planning/STATE.md` — confirms 1965/1965 backend test baseline (restored 2026-04-26 by quick task `260425-sl1`).

### Code
- `backend/app/core/persistent_config.py` — the larger of the two consumer files (680 lines, 16 PersistentConfig instances). Read end-to-end before planning so the planner understands the cache → DB → env precedence and the JSONB unwrap pattern.
- `backend/app/core/public_urls.py` — the second consumer (246 lines). Read end-to-end; URL precedence (request origin → DB override → env → default) and the 60s `_PUBLIC_URL_CACHE` are the behavior the phase must preserve.
- `backend/app/modules/settings/models.py` — current home of `AppSetting`. Tiny (10 lines).
- `backend/app/core/db/__init__.py` and `backend/app/core/db/session.py` — where `Base` is defined; the new model file lives next to these.
- `backend/app/modules/settings/router.py` — third in-repo importer (line 33); migrated as part of D-04.
- `backend/tests/test_hybrid_search.py` — test importer (line 24).
- `backend/tests/test_validation.py` — test importer (line 221, function-scope deferred import).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`backend/app/core/db/session.py` `Base`**: SQLAlchemy declarative base, already the parent class of `AppSetting`. The relocation is "where the file lives," not "what `Base` it uses" — no class hierarchy change.
- **`backend/app/core/db/__init__.py`**: already re-exports `Base, async_session, engine`. The new `models.py` sits next to `session.py` in the same package; no `__init__.py` re-export of `AppSetting` is required for current callers (they import the model directly from `core.db.models` per D-04).
- **`PersistentConfig` registry pattern at `core/persistent_config.py:43`**: the `_registry: list[PersistentConfig]` accumulator + `get_all_registry_values()` batch reader is the only code that reads `app_settings` outside of `public_urls.py`. Both will be touched by D-04 but neither's logic changes.

### Established Patterns
- **Architecture-guard tests via `git grep`**: search the existing test suite for any `subprocess.run(["git", "grep" ...])` patterns before inventing one (planner: `grep -rn "git.*grep\|git_grep" backend/tests/`). If `oc-audit` or any existing test already does layering checks, extend it instead of adding a new file.
- **Closed-set caller migration**: prior layering-style refactors in this codebase have used "find every import, change them all in one PR, no shim" (consistent with D-04). The repo has tools like `ruff`/`pyright` that will surface any missed import as a hard error before merge — that's the safety net, not a deprecation shim.
- **`__table_args__ = {"schema": "catalog"}`**: every catalog-domain ORM model uses this. `AppSetting` keeps it. New `core/db/models.py` will likely host other catalog-schema models in future phases, but for v13.1 it holds only `AppSetting`.
- **JSONB scalar wrapping convention**: `AppSetting.value` is `JSONB NOT NULL`. Scalars are wrapped as `{"v": value}`; dicts/lists are stored directly. This is implemented at `persistent_config.py:189-193` and unwrapped at `:152-154`. The phase MUST NOT touch this convention.

### Integration Points
- **Alembic env / migrations**: Alembic discovers tables via `Base.metadata`, which is populated by importing models. As long as some module imports `AppSetting` at startup (the existing `core/persistent_config.py` module-level import will continue to do this — it just imports from `core.db.models` instead of `modules.settings.models`), the table stays in metadata. No `alembic env.py` change needed unless that file explicitly references `app.modules.settings.models` (planner checks: `grep -n "modules.settings" backend/alembic/env.py`).
- **`backend/app/modules/settings/__init__.py`**: if it re-exports `AppSetting`, that re-export is removed as part of D-05 (settings module no longer "owns" the model). Planner verifies and updates if present.
- **OpenAPI snapshot (`backend/openapi.json`)**: unaffected — the relocation is purely internal to backend Python; no HTTP contract changes. Therefore `make openapi-check` continues to pass without regenerating.

</code_context>

<specifics>
## Specific Ideas

- **Audit option chosen, in their words:** "Either move `AppSetting` to `core/db/models.py` or invert by registering a config provider into core at startup." We're taking the first (move). The audit author flagged this as the simpler path; the milestone's job is to close the boundary debt with the smallest correct change, not to add new abstractions.
- **Phase 218 closing audit is the proof:** success isn't "tests pass," it's "Boundary grade rises from B to A−." Phase 218 reruns `/oc-audit`. Phase 212's contribution is removing the two layering-inversion findings; the regression guard (D-06) ensures they stay removed.
- **Independent of Phase 213:** ROADMAP.md says 212 and 213 may run in parallel. They do not share files. The planner should NOT bundle them.
- **No interaction with Phase 214's `IdentityProtocol`:** that phase introduces a Protocol-based extension seam in `core/identity.py`. Phase 212 deliberately does NOT introduce a parallel `ConfigProtocol` for `AppSetting`, because (a) settings is not a cross-domain abstraction the way identity is, and (b) the audit didn't ask for one. Keep the boundary tight.

</specifics>

<deferred>
## Deferred Ideas

- **`ConfigProvider` Protocol in core**: the audit's second option (invert via Protocol + startup registration). Not needed for v13.1; revisit only if a future phase actually has a non-`AppSetting` config backend (e.g., HashiCorp Vault, AWS Parameter Store, file-based config). Track as a hypothetical, not a backlog item.
- **Generalizing `core/db/models.py` for other catalog models**: tempting to move other catalog-domain models here too, but that's scope creep into Phase 213's territory and beyond. Each domain owns its models; only `AppSetting` is in `core/` because PersistentConfig (a core-layer concern) needs it.
- **Splitting `persistent_config.py`**: the file is 680 lines with 16 registry instances and a generic class. Worth a tidy-up at some point, but not this phase — pure mechanical refactor only.
- **OpenAPI/SDK regeneration**: not affected by this phase; happens in Phase 215.

</deferred>

---

*Phase: 212-core-settings-decouple*
*Context gathered: 2026-04-27*
