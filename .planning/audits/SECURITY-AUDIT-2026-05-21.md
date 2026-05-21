---
status: PASS
audit_date: 2026-05-21
findings_count: 0
critical_count: 0
high_count: 0
medium_count: 0
low_count: 0
compared_against: docs-internal/audits/sec-audit-20260519.md
scope: full repo (/Users/ishiland/Code/geolens) — post Phase 1071
routes_inventoried: 237
subagents_run: A–K (11 of 11)
stack: FastAPI · React · Postgres · SQLAlchemy(async) · Alembic · PostGIS · pg_trgm · pgvector · GDAL/OGR · MapLibre · Docker
framework: OWASP Top 10 (2021) + stack-specific threat modeling
---

# Security Audit Report — 2026-05-21 (v1016 Phase 1072 Re-audit)

**Compared against:** `docs-internal/audits/sec-audit-20260519.md` (16 findings: 7 HIGH + 9 MEDIUM, BLOCK).

**Milestones inspected for closure verification:**
- v1014 Security Audit Remediation (Phases 1061-1064, shipped 2026-05-20, public tag `v1.4.0`) — closed S01–S16 + 10 follow-ups.
- v1015 Ingest/Export Lifecycle Hardening (Phases 1065-1070, shipped 2026-05-20, public tag `v1.5.0`) — closed IA-P0/IA-P1 surfaces (download token, source_url SSRF revalidation at worker, heartbeat removal, export hardening, close-gate hygiene).
- v1016 Phase 1071 Known Items Closure (just shipped) — KNOWN-01..05, 08–13 closed inline (idna ≥ 3.15 bump, AST validator tightening, gdal_safe_env consolidation, VRT_VSI_ALLOWED_PREFIXES single source of truth, StacSearchBody bounds, revoked-viewer export 403 pin).

---

## Executive summary

Risk posture is **PASS**. The 16 findings (S01–S16) from the 2026-05-19 audit are **confirmed closed** in code, with regression tests pinning each fix. Phase 1071's 11 KNOWN closures (which read more like targeted hygiene than security findings — JWT consumer rewrites, env-overlay collision guards, AST allowlist tightening, dependency bump) further narrow the attack surface. No new exploitable HIGH or CRITICAL findings were identified across the 11 OWASP-aligned subagent passes. The codebase shows the same excellent baseline hygiene as the prior audit (boot-time secret validators, structlog redaction, bound-parameter discipline, root-then-drop entrypoints, dynamic CORS with no-wildcard guarantee, HMAC tile signing) plus the new defense-in-depth layers from v1014/v1015: per-hop SSRF redirect revalidation via `make_safe_client`, `apply_visibility_filter` + `check_dataset_access` paired at every Record-derived mutation, sqlglot AST allowlist on the export `where`, dynamic `frame-ancestors` resolved from `EmbedToken.allowed_origins`, JWT `token_version` revocation primitive with logout/change-password/SAML-conversion all invalidating, AST-level rejection of table-qualified column references in the where validator, and shared `gdal_safe_env()` helper across all four GDAL CLI subprocesses (`gdalbuildvrt`, `gdaladdo`, `gdalwarp`, `gdal_translate`).

**Merge gate: PASS.** No CRITICAL or HIGH findings present. Phase 1073 (Audit Remediation) can be a no-op for security severity; remediation requirements should be drawn from the parallel `/ingest-audit` if that produces findings, or skipped if it also passes.

---

## Merge gate: **PASS**

Blocking conditions assessed:
- [x] Critical findings: **0**
- [x] High findings: **0**
- [x] Secrets in git history: clean (only test fixtures + `.env.demo.example` template values)
- [x] Auth bypass possible (JWT alg=none, missing auth guard on sensitive route): **none**
- [x] Unauthenticated access to private spatial / vector data: **none** (STAC, OGC Features, `/datasets/{id}/related/`, vector tiles all verified gated)
- [x] Embedding vectors exposed in API responses: **none** (no response schema serializes `embedding`/`vector`)
- [x] Geometry DoS on public endpoint: **bounded** (GIN indexes + LIMIT caps + length caps + bbox arity check)
- [x] Share/embed/tile token bypass exposes private maps/assets: **none** (HMAC + scope + hashed-at-rest, dynamic `frame-ancestors`)
- [x] Geospatial ingest SSRF / unsafe archive extraction: **none** (per-hop revalidation + zip-bomb caps + no extractall)
- [x] Cross-user mutation of private resources: **none** (`check_dataset_access` paired at every editor-permission handler verified)

---

## Phase 1071 Verified Closures (11 KNOWN items — already shipped on `main`)

These are closed in code and do NOT need re-fix in Phase 1073:

| KNOWN | Surface | Closure | Commit |
|-------|---------|---------|--------|
| KNOWN-01 | `_resolve_download_user` consumes JWT sub → Identity\|None | Anonymous no-sub download tokens valid for public datasets; download_cog branches user=None | `e990a2d4`, `48503b43` |
| KNOWN-02 | Alembic clean-DB upgrade exercise | `backend/scripts/test_alembic_upgrade_clean_db.sh` (deferred CI wiring to 1074) | `6424bde2`, `88ea392f` |
| KNOWN-03 | `CPL_VSIL_CURL_ALLOWED_EXTENSIONS` clamp to all GDAL subprocesses | Shared `gdal_safe_env()` helper across `gdaladdo`/`gdalwarp`/`gdal_translate`/`gdalbuildvrt` | `405cd1a6`, `b07f3953`, `d7107932` |
| KNOWN-04 | VRT VSI allow-list single source of truth | `VRT_VSI_ALLOWED_PREFIXES` exported from `vrt.py`, consumed by `validate_vrt_body` | `447df82d`, `e1b49b94`, `f7c4c669` |
| KNOWN-05 | Export 403 for revoked-export-on-viewer parity | Regression test pin in `test_export_hardening.py` | `6ff24454` |
| KNOWN-08 | `.env.example` documents `PASSWORD_MIN_LENGTH` + `PASSWORD_REQUIRE_CLASSES` | Inline doc lines | Phase 1071 Plan B |
| KNOWN-09 | `validate_password_complexity` whitespace symbol-class | Docstring caveat (no behavior change) | `9399c0be` |
| KNOWN-10 | `where_validator.py` table-qualified rejection | `Column.table`/`Column.db`/`Column.catalog` inspection after allowlist | `3302769d`, `185da0d1` |
| KNOWN-11 | `_sanitize_authorization_token` 8-char minimum doc | Inline docstring | `d1533847` |
| KNOWN-12 | `StacSearchBody.limit/offset` Pydantic ge/le bounds | `ge=1, le=200` on limit, `ge=0` on offset | `965f056b`, `802537f0` |
| KNOWN-13 | `idna` bumped to ≥ 3.15 (CVE-2026-45409) | `backend/uv.lock` + pyproject constraint | `c8e2325b` |

Code-review followups from Phase 1071 also verified closed inline:
- **CR-01**: `gdal_safe_env` raises `ValueError` on security-clamp key collision (`extras={"CPL_VSIL_CURL_ALLOWED_EXTENSIONS": "..."}` cannot silently override the clamp). `e127f55c`
- **CR-02**: `_resolve_download_user` narrows `except ValueError` to wrap only the `uuid.UUID()` conversion, not the `db.execute()` call. `531e5809`
- **WR-01**: `StacSearchBody.limit` aligned to GET handler ceiling `le=200`. `802537f0`
- **WR-02**: `nc` fallback for `lsof` port-check portability on Linux. `89d48a6e`
- **WR-03/04/05**: docstring-only documentation closures (audit assertion rationale, missing `aud` claim check note, VRT module patch object identity).

---

## Diff vs prior audit (S01–S16 → 2026-05-21)

| Prior ID | Label | Prior Severity | Status | Verification |
|----------|-------|----------------|--------|--------------|
| S01 | AUTH-MISSING-STAC | HIGH 7.5 | **CLOSED** | `_published_raster_filters` + `_base_published_raster_query` threads `user`/`user_roles` through `apply_visibility_filter` at `backend/app/standards/stac/router.py:245`; 5 item-returning endpoints verified |
| S02 | IDOR-DATASET-META | HIGH 8.1 | **CLOSED** | `check_dataset_access` at `backend/app/modules/catalog/datasets/api/router.py:280, 359, 429`; bulk-delete iterates per-item |
| S03 | IDOR-COLUMN-DDL | HIGH 8.1 | **CLOSED** | `check_dataset_access` at `backend/app/modules/catalog/layers/router.py:109, 165, 221, 280` (4 column DDL handlers) |
| S04 | SSRF-REDIRECT | HIGH 8.5 | **CLOSED** | `_revalidate_redirect` event hook + `make_safe_client(timeout)` factory at `backend/app/modules/catalog/sources/security.py:70-111`; consumed at all 4 user-input sites (`router.py:100,185`, `adapters/stac.py:36`); ogr2ogr ingest has `GDAL_HTTP_FOLLOWLOCATION=NO` in `gdal_safe_env` |
| S05 | VEC-IDOR-RELATED | HIGH 7.5 | **CLOSED** | `check_dataset_access_or_anonymous` at `backend/app/modules/catalog/datasets/api/router_data.py:75, 216` |
| S06 | DEMO-CREDS-COMMIT | HIGH 7.5 | **CLOSED** | `.env.demo` → `.env.demo.example` with `REPLACE_ME_WITH_init-demo-env.sh` placeholders; `validate_demo_credentials_guard` refuses 3 literal values unconditionally even when `GEOLENS_DEMO_MODE=true` |
| S07 | MINIO-DEFAULT-CRED | HIGH 7.0 | **CLOSED** | `docker-compose.yml:510-511, 541-542` uses `${MINIO_ROOT_USER:?required}` fail-closed expansion |
| S08 | EMBED-FRAMING-GAP | MED 5.3 | **CLOSED** | `_build_frame_ancestors` at `maps/router.py:109` emits per-token CSP from `EmbedToken.allowed_origins`; `SecurityHeadersMiddleware` skips global `X-Frame-Options: DENY` when route emits its own CSP |
| S09 | INJECT-WHERE-OGR | MED 5.0 | **CLOSED** | `where_validator.py` sqlglot AST allowlist (deny-by-default, 16 node types); plus Phase 1071 KNOWN-10 closed `Column.table`/`Column.db`/`Column.catalog` bypass at line 134 |
| S10 | SECRET-BASEMAP-KEY | MED 5.3 | **CLOSED** | Public-key docstring + 120/min rate limit at `settings/router.py` |
| S11 | RATELIMIT-VEC | MED 5.3 | **CLOSED** | `@limiter.limit(_semantic_search_rate_limit)` at `search/router.py:617` + `router_data.py:65` |
| S12 | TRGM-INDEX-SIMPLE | MED 5.0 | **CLOSED** | `backend/alembic/versions/0020_records_simple_search_vector_idx.py` (GIN on `simple` regconfig); `catalog.immutable_text_array_join` IMMUTABLE wrapper |
| S13 | TRGM-INPUT-CAP | MED 4.3 | **CLOSED** | `max_length=1000` at `search/router.py:222, 543` |
| S14 | AUTH-JWT-STORAGE | MED 5.4 | **CLOSED** | ESLint `no-restricted-syntax` rule banning `localStorage.setItem('*token|jwt|auth*', ...)` in `frontend/eslint.config.js:55-67`; httpOnly migration ADR in `security-lessons.md` |
| S15 | AUTH-NO-JTI | MED 4.3 | **CLOSED** | `token_version` column on `User`; embedded in JWT; `revoke_all_tokens` atomically bumps on logout / change-password / SAML conversion; consumer check at `dependencies.py:120, 203` |
| S16 | AUTH-PWD-WEAK | MED 4.3 | **CLOSED** | `validate_password_complexity` in `password_policy.py` (12-char + 3-of-4 classes); `PASSWORD_MIN_LENGTH` + `PASSWORD_REQUIRE_CLASSES` configurable |

**Net change: 16 closed, 0 still open, 0 new.**

---

## Findings (current audit)

**No CRITICAL or HIGH findings. No MEDIUM findings. No LOW findings.**

(The audit ran the full 11-subagent surface inspection. Every category in the "Clean — checked and passed" section below was re-verified against the post-Phase-1071 source tree.)

---

## Clean — checked and passed

### Subagent A (Injection)
- SQLAlchemy `text()` interpolation across ~18 sites — all identifier interpolations gated through `_qtable()`/`_safe_table_ref()` (verified at `tasks_common.py:448, 903`; `metadata.py:92, 103, 137, 146, 215, 223, 337, 582, 1057, 1061, 1089`; `tasks_reupload.py:131, 445`; `service_lifecycle.py:112`; `executor.py:69`; `embeddings/helpers.py:31`).
- ORM mass assignment — all `*Update` schemas declare explicit fields; no `**body` to model constructors.
- Alembic migrations (170+ `op.execute(...)` calls) — zero f-string / %-format / `.format()` interpolation.
- PostGIS geometry constructors — always parameter-bound or pre-validated server-derived WKT.
- pg_trgm — `func.websearch_to_tsquery("english", q)` exclusively in catalog search (neutralizes operator abuse); `to_tsvector('simple', concat_ws(...))` paired with new GIN index for non-English path.
- pgvector — ORM operators (`.cosine_distance`); only `SET LOCAL hnsw.ef_search = {int(ef)}` interpolation is int-coerced.
- SSTI — zero `jinja2.Template` / `Template(` in app source.
- Command injection — all 12 subprocess sites use list-form `asyncio.create_subprocess_exec(*cmd)` / `subprocess.run([...])`; no `shell=True`; no `os.system`; no `os.popen`.
- Path traversal — `save_upload_file` strips directory components via `Path(file.filename).name`; export temp dirs use server-generated `uuid.uuid4().hex`.
- Sandbox SQL validator — sqlglot AST + blocked-function set + RBAC table allowlist + `SET LOCAL ROLE geolens_readonly` + `statement_timeout=30s` + `LIMIT 1001`.
- **NEW (Phase 1071):** `where_validator.py` AST allowlist now also rejects `exp.Column` with `table`/`db`/`catalog` arg set, defending against future regex-side refactor.

### Subagent B (Auth/AuthZ)
- JWT algorithm pinning — `algorithms=[settings.jwt_algorithm]` at every `jwt.decode` call (5 sites). `algorithm="none"` not accepted.
- JWT secret validation — `KNOWN_BAD_JWT_SECRETS` denylist, ≥32 char length check, `validate_demo_credentials_guard` boot-time refusal.
- **NEW since 2026-05-19:** `token_version` claim revocation (S15 closed) — `dependencies.py:119-121, 202-204` rejects stale access JWTs.
- 237 routes mapped via FastAPI introspection (3 net new since 2026-05-19: download-token mint endpoint + column DDL feed); 32 with explicit auth dep; 205 public/optional (most are OGC/STAC/DCAT/published-catalog discovery — verified against product invariants).
- Read-side IDOR clean — all `/datasets/{id}` GETs call `check_dataset_access_or_anonymous`; `/maps/{id}` calls `_check_map_read_access` / `check_map_ownership`.
- Spatial IDOR (OGC Features + STAC) — `apply_visibility_filter` applied before geometry serialization at both surfaces (STAC regression closed by S01).
- Vector IDOR (search + related) — `apply_visibility_filter` + `check_dataset_access_or_anonymous` paired at related-datasets seed; ranks intersected with already-visible record IDs.
- Password — pwdlib `BcryptHasher`, timing-attack `DUMMY_HASH` on missing user, `password_hash` excluded from `UserResponse`, 12-char + 3-of-4-class diversity via `validate_password_complexity` (S16 closed).
- API keys — sha256 hash at rest, plaintext returned only at creation, side-session for `last_used_at` updates (avoids early commit on request session).
- OAuth/OIDC — authlib with PKCE `code_challenge_method=S256`, server-side state via session, `redirect_uri` derived from `get_public_api_url(for_external_use=True)` (rejects `X-Forwarded-Host` spoofing).
- Share tokens — `secrets.token_urlsafe(32)`, sha256 hashed, scoped to map, `visibility=public` precondition on the map.
- Embed tokens — `et_` prefix + 32B entropy, sha256 hashed, dataset-scope check, allowed_origins enforced at API call AND HTML-shell (S08 closed).
- Tile signing — HMAC-SHA256 + `hmac.compare_digest`, expiry rounded to 15 min.
- **NEW (Phase 1071):** Download token consumer correctly handles 3-way auth: header JWT, header API key, `?token=` download-scoped JWT (with optional no-sub anonymous-for-public branch).

### Subagent C (Secrets)
- No production secrets in source — only test fixtures (`TestPass1234!`, `SAMLConvert5678#`) + `.env.demo.example` placeholder template values.
- Boot-time validators — `SecretStr` for all credential fields; `KNOWN_BAD_JWT_SECRETS` blocklist; `validate_demo_credentials_guard` (config.py:215+).
- Response schemas — `password_hash`, `client_secret_encrypted`, `idp_certificate`, `embedding`, `vector` all excluded from response models.
- `ApiKeyCreateResponse.key` shown once at creation; subsequent lists never include plaintext.
- Logging — structlog `_redact_sensitive_fields` processor covers jwt/token/access_token/refresh_token/password/password_hash/api_key/apikey/x_api_key/x-api-key/authorization/secret/client_secret.

### Subagent D (Frontend)
- `dangerouslySetInnerHTML` — zero occurrences in app code (only a `*.skip.tsx` regression fixture testing the ESLint ban).
- `innerHTML` / `document.write` / `eval` / `new Function` — zero.
- Map popup XSS — FeaturePopup renders feature properties via React text nodes; URL detection sanitizes via `startsWith('http://'|'https://')` + `rel="noopener noreferrer"`.
- Search result XSS — no server-side highlight snippets.
- CORS — `DynamicCORSMiddleware` reads PersistentConfig per request (30s cache), explicitly rejects wildcard, `Allow-Credentials: true` only for explicitly-listed origins.
- CSP — global `frame-ancestors 'self'` from `SecurityHeadersMiddleware`; per-route override via `Content-Security-Policy` when an embed-token route emits one (XFO suppression coordinated, S08 closed).
- Security headers — `nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `X-Frame-Options: DENY` on API (suppressed for embed-token routes), `Permissions-Policy: camera=(), microphone=(), geolocation=()`, HSTS conditional on `X-Forwarded-Proto: https`.
- ESLint `no-restricted-syntax` rule bans `localStorage.setItem('*token|jwt|auth*', ...)` (S14 closed).
- Map library versions — `maplibre-gl ^5.24.0`, `@vis.gl/react-maplibre ^8.1.0`, `@turf/* ^7.3.4` — all current.

### Subagent E (Dependencies)
- Python — 187 packages locked; `safety check`: **0 vulnerabilities** in `backend/.venv` (post-idna bump).
- npm — `npm audit --audit-level=high`: **found 0 vulnerabilities**.
- `idna` confirmed at 3.15 (CVE-2026-45409 closed by Dependabot #40, KNOWN-13).
- License — only LGPL items are `psycopg` and `pygeoif` (Apache 2.0 compatible as library).
- Lockfiles current.

### Subagent F (Docker/Infra)
- Base images pinned to specific tags (no `:latest`).
- Non-root `appuser` UID 1001 in backend (`Dockerfile:103, 117`); nginx-unprivileged for prod frontend.
- `security_opt: no-new-privileges:true` on every long-running service.
- `cap_drop: [ALL]` + minimal allowlist on every service.
- `read_only: true` root filesystems on api/worker/migrate/titiler with explicit tmpfs.
- `.dockerignore` default-deny with explicit excludes for `.env`, `.git`, `__pycache__`, `node_modules`.
- HEALTHCHECK coverage on every service.
- DB — PostGIS 17-3.5, pgvector pinned to v0.8.2, `geolens_reader` SELECT-only role.
- Port bindings — db/api/minio/valkey all bound to `127.0.0.1`; titiler internal-only.
- No host secret mounts; no docker socket exposure.
- MinIO `${MINIO_ROOT_USER:?required}` fail-closed (S07 closed).
- `.env.demo.example` placeholder template only (S06 closed).
- Titiler GDAL VSI clamps in compose env: `CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff,.cog,.vrt"`.

### Subagent G (Postgres/Alembic)
- No hardcoded DB URLs.
- SSL — `DATABASE_SSL_MODE` configurable; `verify-full` enforced via Pydantic `@model_validator` requiring CA cert.
- Pool — `pool_size=10`, `max_overflow=3`, `pool_timeout=30s`, `pool_recycle=1800s`, `pool_pre_ping=True`.
- Async session — all routes use `AsyncSession`; `boto3.Session()` is the only sync `Session(` match.
- `get_db` lifecycle — `async with` + try/yield/rollback shape.
- Privilege model — app role `geolens` is NOT superuser; `geolens_reader NOLOGIN` with SELECT-only on `data.*`.
- RLS not present (app-layer `apply_visibility_filter` is the enforcement; Community single-org product invariant).
- Alembic env.py pulls URL from `settings.database_url`; uses `NullPool` for migrations.
- All 20 migrations have non-stub `downgrade()`.
- **NEW (Phase 1071 KNOWN-02):** `backend/scripts/test_alembic_upgrade_clean_db.sh` provides clean-DB upgrade exercise (CI integration deferred to Phase 1074).

### Subagent H (API/Business logic)
- Rate limits — login `5/min`, register `5/min`, refresh `30/min`, download-token mint `60/min`, semantic search `_semantic_search_rate_limit` (30/min), global default `60/sec/IP`. SlowAPI globally installed.
- FastAPI docs — `docs_url=None`/`redoc_url=None` in production.
- Mass assignment — narrow Pydantic schemas, Pydantic v2 ignores extras by default.
- File upload — puremagic magic-byte content-type check, filenames sanitized, body cap enforced via `RequestBodyLimitMiddleware`, SVG defusedxml + active-content denylist.
- Zip-slip — no `ZipFile.extractall()` anywhere; shapefile zips read via GDAL `/vsizip/` (no disk extraction); `validate_zip_safety` caps compression ratio 500:1, 2GB decompressed, rejects nested archives.
- VRT external refs — `VrtCreateRequest` accepts only server-side `source_dataset_ids: list[UUID]`; no user-supplied VRT XML upload route; `VRT_VSI_ALLOWED_PREFIXES` single source of truth (KNOWN-04).
- Raster/SVG XML — defusedxml for parsing.
- **NEW (Phase 1066/1071):** SSRF defense-in-depth — `validate_url_for_ssrf` runs at submission AND at worker fetch time; `_revalidate_redirect` event hook re-validates every 3xx hop; `gdal_safe_env` sets `GDAL_HTTP_FOLLOWLOCATION=NO` + `CPL_VSIL_CURL_ALLOWED_EXTENSIONS` across all 4 GDAL CLIs (KNOWN-03 expanded).
- S3 — `S3_ALLOW_HTTP=false` default; credentials not in logs/audit/presigned URLs.
- Deserialization — zero `pickle.`/`marshal.`/`yaml.load`/`eval(` in app source.
- Error leakage — generic `"Internal server error"` 500s, full context to structlog only.

### Subagent I (PostGIS)
- No raw user-WKT entry points — every geometry constructor consumes server-derived geometry or validated WKT.
- bbox validation rejects arity != 4|6 and `miny < maxy` enforced; `math.isfinite()` guard rejects NaN/Inf (SEC-FU-06 closed in v1014).
- Precision — all `ST_AsGeoJSON` paths run through visibility/auth; no PII geometry columns exist.
- Tile auth — vector tiles HMAC-signed; raster tiles RBAC at nginx `auth_request`. Zoom bound `0 ≤ z ≤ 22`.
- SRID consistency — `Record.spatial_extent srid=4326`; per-dataset `geom_4326`; STAC/search `ST_SetSRID(..., 4326)` on any user-shape input.
- STAC `intersects` capped at `max_length=10000` (SEC-FU-05 closed in v1014); `StacSearchBody.limit` ge=1/le=200 + `offset` ge=0 (KNOWN-12).

### Subagent J (pg_trgm)
- `websearch_to_tsquery` for user input.
- Visibility filter applied before text-search filters.
- GIN/GIST coverage — `english` regconfig already indexed; `simple` regconfig now indexed via `0020_records_simple_search_vector_idx.py` (S12 closed).
- Search input length cap at 1000 chars (`SearchQueryParams.q`); facets `q` capped at 1000 (S13 closed).
- ILIKE wildcard escaping via shared `escape_ilike` helper (SEC-FU-07 closed in v1014).
- Anonymous response cache bounds repeat-query DoS.

### Subagent K (pgvector)
- Embedding never on any response schema.
- No client-supplied raw query vectors — server alone calls `generate_embedding(text)`.
- Visibility filter applied to both FTS base and vector-rank cap.
- Embedding model versioning — `RecordEmbedding.model_name` + `(record_id, model_name)` unique constraint.
- HNSW index with `vector_cosine_ops`, `m=16, ef_construction=64`.
- OpenAI/Anthropic API keys read via `SecretStr.reveal()` only at SDK-call time.

---

## Not blocking — follow-up tickets (defense-in-depth, optional)

These are NOT findings, but observations for future hardening:

1. **SEC-OBSV-01** — `_titiler_client` at `backend/app/processing/tiles/router.py:51` constructs `httpx.AsyncClient(follow_redirects=True)` at module load to proxy internal traffic to `http://titiler:8000`. Since Titiler is internal-only (no `ports:` block in compose) and the only URLs sent to it are server-derived raster URIs, this is safe — but if a future change exposes Titiler externally OR allows user-controlled URL pass-through, this client must move to `make_safe_client()`. Recommend a comment block documenting the safety contract at the construction site.
2. **SEC-OBSV-02** — `_fetch_cog_info` at `backend/app/modules/catalog/sources/stac_router.py:50` uses raw `httpx.AsyncClient` to call Titiler. SSRF protection here depends on (a) the caller validating the user-supplied `url` with `validate_url_for_ssrf` BEFORE calling `_fetch_cog_info` (currently true at line 454 in the import flow), and (b) Titiler's own `CPL_VSIL_CURL_ALLOWED_EXTENSIONS` clamp (currently `.tif,.tiff,.cog,.vrt` in compose env). The dual-gate pattern is robust, but a small docstring inside `_fetch_cog_info` enumerating both gates would prevent a future caller from skipping the SSRF check.
3. **SEC-OBSV-03** — KNOWN-02's `test_alembic_upgrade_clean_db.sh` ships in v1016 Phase 1071 but is not yet in any CI runner. Phase 1074 (close-gate) should wire it into the docker smoke step so a stale `alembic` head silently doesn't ship.

---

## Out of scope this run

- Penetration testing of running services (static + config audit only).
- Network architecture (firewalls, WAF, CDN) — outside repo.
- IaC (Terraform/Pulumi) — repo contains Helm chart only.
- Frontend bundle CVE scan post-build (npm audit covers source deps).
- Compliance frameworks (SOC2/HIPAA/GDPR) — not in scope.
- e2e regression spec generation — `e2e/sec-audit.spec.ts` already exists with 18 tests pinning S01–S16; skipped per Phase 1072 run instructions.

---

## Audit run notes

- 11 subagent passes executed sequentially within this agent's context (Phase 2 spawn pattern was executed serially since the calling agent IS already a subagent).
- Route count: 237 confirmed via FastAPI app introspection (was 234 on 2026-05-19; 3 net new = download-token mint endpoint + column DDL feed + 1 other administrative add-on from v1014 SEC-FU-08).
- Prior audit at `docs-internal/audits/sec-audit-20260519.md` (561 lines, 16 findings) — all 16 confirmed closed in code; commits cross-referenced above.
- Phase 1071 closures all sit on `main` post-commit `a57ae07d` (2026-05-21 ship).
- Output location override: `.planning/audits/SECURITY-AUDIT-2026-05-21.md` (v1016 milestone artifacts stay self-contained per Phase 1072 run instructions).
- `e2e/sec-audit.spec.ts` generation skipped — existing 18-test suite from v1014 covers S01–S16; Phase 1074 close-gate runs them.
- Lessons capture skipped — pulled into milestone audit instead.

---

## Recommendation for Phase 1073

**Phase 1073 (Audit Remediation) can be a no-op for security severity.** Suggested options:
- (a) Skip Phase 1073 entirely; advance directly to Phase 1074 close-gate.
- (b) Use Phase 1073 to absorb whatever `/ingest-audit` produces in parallel (if that audit lands findings).
- (c) Use Phase 1073 to close the three SEC-OBSV-01..03 observations above as defense-in-depth hardening (zero severity, ~1 hour total).

This is a planner-level decision and out of audit scope.
