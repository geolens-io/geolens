# Security audit lessons

Append-only ledger of recurring patterns surfaced by `/sec-audit` runs. Newest at the top.

---

## 2026-05-20 — Phase 1062-06: SEC-S14 ESLint guard + httpOnly migration plan

### What shipped (Phase 1062-06)

| Audit Finding | Plan | Files | Pattern |
|---------------|------|-------|---------|
| SEC-S14 (JWT in localStorage) | 1062-06 | `frontend/eslint.config.js` + `frontend/src/__tests__/sec-s14-eslint-regression*.ts` | `no-restricted-syntax` rule banning `localStorage.setItem('<token-shape>', ...)` outside auth-store |

**Rule pattern:**
```js
'no-restricted-syntax': ['error', {
  selector: "CallExpression[callee.object.name='localStorage'][callee.property.name='setItem'][arguments.0.type='Literal'][arguments.0.value=/token|jwt|auth/i]",
  message: 'SEC-S14 ...',
}],
```

**Exemptions:**
- `frontend/src/stores/__tests__/auth-store.test.ts` — legitimately writes `'geolens-auth'` to set up zustand persist fixtures. Per-file `rules: { 'no-restricted-syntax': 'off' }` override.
- The single production write site (`auth-store.ts`) does NOT call `localStorage.setItem` directly — zustand persist middleware wraps it inside node_modules, so no exemption is needed there.

**Known gaps (documented for future SEC-FU):**
- Identifier-as-key (e.g. `const KEY = 'token'; localStorage.setItem(KEY, ...)`) — passes silently. Rule selector requires `arguments.0.type='Literal'`.
- Template-literal-as-key (e.g. `` localStorage.setItem(`token-${id}`, ...) ``) — passes silently. Same reason.
- Both gaps are acceptable per the audit framing: the rule catches accidental copy-paste / cargo-cult regression, not motivated evasion. Closing them requires a custom ESLint plugin (out of scope for v1014).

**Regression verification:**
```bash
cd frontend
npm run lint:sec-s14-regression        # exits 0 when rule fires (inverted exit code)
npm run lint:sec-s14-no-false-positive  # exits 0 when safe patterns pass
```

### httpOnly-cookie + CSRF migration plan (deferred to future hardening pass)

**Context.** The audit's secondary recommendation for SEC-S14 is to migrate JWT storage from `localStorage` to `httpOnly` cookies. This eliminates XSS exfiltration risk entirely (JS cannot read httpOnly cookies). The current zustand-persist-to-localStorage architecture (`frontend/src/stores/auth-store.ts:29-54`) was chosen for simplicity at v1.0 and remains correct for the open-core single-tenant deployment model. The audit notes no current XSS sinks (zero `dangerouslySetInnerHTML`, popups render via React text nodes) — so the present risk is **conditional on future regressions**.

**Decision (deferred).** Migration to httpOnly cookies + CSRF token is the long-term hardening path. It is **NOT scheduled** in v1014; this plan ships the ESLint guard (cheap, regression-pinning) and defers the architectural change.

**Consequences if migration happens later:**

Positive:
- XSS-resistant token storage (httpOnly cookie cannot be read by `document.cookie` or `localStorage` access).
- No more "logout doesn't clear OS-level password manager" UX edge cases (cookie scope is clean).
- Cleaner mobile/SDK token handoff (some SDKs default to cookie auth).

Negative:
- Requires a CSRF token primitive on every state-mutating request (POST/PUT/PATCH/DELETE). Current GeoLens has no CSRF token surface — adding one touches every API client call site (`frontend/src/api/client.ts` + every mutator hook).
- `/auth/login/` must shift from "returns JSON body with access_token" to "sets Set-Cookie response header". OAuth2-compatible callers (OpenAPI-spec consumers, SDKs, CLI tools) expect the JSON body. Need a dual-mode: cookie for browser, JSON for non-browser. Detect via `Accept` / `Sec-Fetch-Mode` headers.
- Cross-subdomain deployments (api.geolens.com vs app.geolens.com) need careful `Domain=` cookie scoping. SameSite=Lax breaks cross-origin POST without explicit allowlist. Current dev stack uses `localhost:8000` (API) + `localhost:8080` (frontend) — different ports = different origins = browsers may not send the cookie even with Domain set.
- `refresh_token` cookie has different rotation semantics from the current opaque-token-in-body. Refresh-token theft via XSS goes away, but XSRF on `/auth/refresh/` becomes a new (smaller) risk vector.
- Existing third-party integrations (Postman, curl scripts, CI smoke tests) that login via JSON body need to opt into the cookie shape or stick with the JSON path.

Neutral:
- JWT signing/validation/expiry/jti/token_version (Phase 1062-01 SEC-S15) all work identically with the cookie-bound bearer pattern. No backend auth-logic changes needed for the JWT itself.

**Estimated effort:** 1–2 phase milestones. Suggested split:
1. Phase A: dual-mode `/auth/login/` (JSON body + optional Set-Cookie based on Accept header). CSRF token issuance endpoint. Frontend client refactor to use cookies when present. Backwards-compatible.
2. Phase B: deprecate the JSON-body path for browsers; require cookies for production browser flow. Keep JSON for SDK/CLI callers.

**When to schedule:** Trigger this migration when EITHER (a) an XSS sink is introduced in the SPA (e.g. a markdown renderer with HTML passthrough), OR (b) a SaaS / Cloud tier launches that hosts multiple-customer data on shared origin (audit Phase 999.6 marked deferred SaaS). Until either condition fires, the localStorage path remains acceptable given the zero-XSS-sink posture documented in the audit and the new ESLint guard.

**Related:**
- **SEC-FU-03** (Phase 1063): ESLint `react/no-danger` rule. Locks the popup-template ban introduced by v13.12. Complement to this plan's localStorage guard — both reduce the surface area for XSS-derived token theft.

---

## 2026-05-20 — Phase 1061: HIGH-severity remediation shipped

### Patterns now locked in AGENTS.md (see `AGENTS.md` §"Security pre-commit checklist")

- **Rule 1 — Visibility-filter coverage** — see implementation references below.
- **Rule 2 — SSRF redirect-revalidation** — pre-commit grep shipped in `.pre-commit-config.yaml`.
- **Rule 3 — Demo credentials are per-deploy** — `scripts/init-demo-env.sh` + extended `validate_demo_credentials_guard`.

### Implementation references (Phase 1061)

| Audit Finding | Plan | Files | Pattern |
|---------------|------|-------|---------|
| SEC-S01 (STAC visibility) | 1061-01 | `backend/app/standards/stac/router.py` | `_base_published_raster_query(user, user_roles)` applies `apply_visibility_filter` |
| SEC-S02 (dataset metadata IDOR) | 1061-02 | `backend/app/modules/catalog/datasets/api/router.py` | `check_dataset_access` in 3 mutation handlers; owner-or-admin gate on delete |
| SEC-S03 (column DDL IDOR) | 1061-02 | `backend/app/modules/catalog/layers/router.py` | `check_dataset_access` in 4 DDL handlers |
| SEC-S04 (SSRF redirect) | 1061-04 | `backend/app/modules/catalog/sources/security.py` + 3 callsites | `make_safe_client()` + `_revalidate_redirect` event hook; `GDAL_HTTP_FOLLOWLOCATION=NO` |
| SEC-S05 (related-datasets IDOR) | 1061-03 | `backend/app/modules/catalog/datasets/api/router_data.py` | `check_dataset_access_or_anonymous` BEFORE `get_related_datasets` |
| SEC-S06 (demo credentials) | 1061-05 | `scripts/init-demo-env.sh`, `backend/app/core/config.py` | Per-deploy random credentials; guard refuses literal committed values |
| SEC-S07 (MinIO defaults) | 1061-05 | `docker-compose.yml` | `${VAR:?required}` fail-closed expansion |
| SEC-GUARD-01 (this) | 1061-06 | `AGENTS.md`, `.pre-commit-config.yaml`, this file | Pattern pinning + grep guardrails |

### Operator guidance — demo credential rotation (SEC-S06 follow-up)

`scripts/init-demo-env.sh` is idempotent — re-run with `--force` to rotate.

Rotation cadence recommendation:
- Public-internet demo deployments: rotate weekly or on every redeploy. Schedule a cron job that runs `--force` and restarts the stack.
- Local dev clones using the demo overlay: rotate when the workstation changes hands.

Capture the admin password from `scripts/init-demo-env.sh` stdout — it is the only output, and the password is hashed at-rest in the DB (not recoverable from the file).

### Deferred to follow-up phases

- **SEC-FU-01..FU-10** → Phase 1063 (LOW follow-up tickets).
- **SEC-S08..S16** → Phase 1062 (MEDIUM remediation).
- **SEC-CTRL-01** → Phase 1064 (close gate: regression suite + tag).
- **router_reupload.py IDOR** → Phase 1063 (pre-existing gap: `require_permission("edit_metadata")` is role-level only; any editor can reupload to any dataset by ID — `check_dataset_access` resource-level check missing). Tracked in `.pre-commit-config.yaml` exclude list until fixed.
- **Pre-resolve final URL before ogr2ogr spawn** — additional SSRF defense-in-depth; deferred to SEC-FU follow-up sweep.
- **Narrow `_load_self_record_and_embedding` to consume seed via visibility-filtered query** — eliminates reliance on caller-side gating; deferred to SEC-FU.
- **Aggregate metadata leakage in `get_collections` / `get_collection`** — bounded carve-out documented in Plan 1061-01 SUMMARY; narrow to per-user CollectionDataset visibility in SEC-FU.

---

## 2026-05-19 — Security audit: full repo

### Patterns found recurring
- **Visibility filter coverage is the project's #1 regression surface.** When new feature work adds a Record-derived endpoint (STAC, `/related/`, `/columns/`, `bulk-delete`), the writer reaches for `require_permission(...)` (role-level) and forgets `check_dataset_access(...)` / `apply_visibility_filter(...)` (resource-level). OGC Features pairs them correctly; the four 2026-Q1/Q2 additions do not.
- **One-shot URL validation followed by `follow_redirects=True`** is the SSRF pattern in this codebase. It appeared in three connector adapters and the manifest-driven ingest. Treat `validate_url_for_ssrf` as a per-hop hook, not a gate at submission time.
- **Identifier-only `WHERE` validation** loses the ability to reject UNION/subquery grammar. The repo already has a sqlglot-AST sandbox (`app.platform.sandbox.validator`); the export's `validate_where_clause` should reuse it.

### Patterns consistently clean
- Bound-parameter discipline on SQLAlchemy `text()` and `op.execute()`. ~40 raw-SQL sites; zero string interpolation of user input.
- `subprocess` argv discipline. 11 subprocess sites; zero `shell=True`.
- Token hygiene at rest. Share/embed/API-key tokens are all sha256-hashed; plaintext returned once at creation.
- Boot-time secret validators (`KNOWN_BAD_JWT_SECRETS`, `validate_demo_credentials_guard`, `SecretStr` requirements). Refusal to boot is consistently used as the enforcement mechanism — strong pattern.
- Container hardening: `cap_drop: ALL` + minimal allowlist + `no-new-privileges:true` + `read_only: true` + root-then-drop entrypoints. Best-in-class for an open-core product.

### Rules to add to AGENTS.md or a command playbook to prevent recurrence

1. **Record-derived endpoint checklist.** Any new handler that fetches a `Record`, `Dataset`, `Map`, or `RecordEmbedding` by ID must:
   - Call `check_dataset_access_or_anonymous` (read) or `check_dataset_access` + ownership check (write/destructive), OR
   - Apply `apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)` to the underlying query.
   Add a pre-commit grep that fails CI if a handler in `backend/app/modules/catalog/datasets/api/` or `backend/app/standards/` references `get_dataset(` without `check_dataset_access` or `apply_visibility_filter` in the same function body.

2. **SSRF-by-redirect.** Any new `httpx.AsyncClient(follow_redirects=True, ...)` in a route handler must pass through a `make_safe_client()` factory that installs the per-hop `_revalidate_redirect` event hook. Add a pre-commit grep that fails CI if `httpx.AsyncClient(.*follow_redirects=True` appears outside `app.modules.catalog.sources.security`.

3. **WHERE clause / dynamic SQL parser reuse.** When a route accepts an SQL-like expression (export `where`, custom filter, etc.), use `app.platform.sandbox.validator.validate_sql` — do not write a new identifier-only validator.

4. **Live MCP smoke for STAC/OGC.** The visibility regression on STAC (S01) would have been caught by a Playwright MCP smoke that fetches `/api/stac/items/{private_id}` without auth. Add to the same MCP gate that already covers v1011 builder milestones.

5. **Per-route rate limit on cost-sensitive AI calls.** Any new route that calls `generate_embedding(...)`, `llm.complete(...)`, or any OpenAI/Anthropic SDK method needs an explicit `@limiter.limit(...)` decorator. Global `60/sec/IP` is insufficient when external API calls have per-token cost.

6. **Demo credential rotation script.** Add `scripts/init-demo-env.sh` and document it in the demo-deploy README. Extend `validate_demo_credentials_guard` to refuse-boot on the literal committed `JWT_SECRET_KEY` value even in demo mode, forcing the script to run.

