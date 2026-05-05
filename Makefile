.PHONY: dev down reset-db migrate migration test test-cov e2e logs logs-db logs-api openapi openapi-check sdks sdks-check sdks-test manifest-contract-check publish-sdks-py publish-sdks-ts cli-build cli-test cli-check publish-cli audit-sink-discipline billing-extraction-discipline catalog-domain-discipline

dev:
	docker compose up --build

down:
	docker compose down

reset-db:
	docker compose down -v
	docker compose up --build

migrate:
	docker compose exec api uv run alembic upgrade head

migration:
	docker compose exec api uv run alembic revision --autogenerate -m "$(msg)"

test:
	docker compose exec api uv run pytest -v --tb=short

test-cov:
	docker compose exec api uv run pytest -v --tb=short --cov=app --cov-report=term-missing

e2e:
	npx playwright test

logs:
	docker compose logs -f

logs-db:
	docker compose logs -f db

logs-api:
	docker compose logs -f api

# Snapshot the OpenAPI schema. Commit backend/openapi.json with the route changes;
# CI runs `openapi-check` to fail builds when the snapshot drifts from runtime.
openapi:
	cd backend && PYTHONPATH=. uv run python scripts/dump_openapi.py

openapi-check:
	cd backend && PYTHONPATH=. uv run python scripts/dump_openapi.py --check

# ----- SDK generation (Phase 215) -----
# `make sdks` regenerates Python + TypeScript SDKs from backend/openapi.json.
#
# Pipeline:
#   1. dump_openapi.py refreshes backend/openapi.json (the committed snapshot).
#   2. flatten_openapi_defs.py reads that snapshot and writes a generator-only
#      intermediate at /tmp/openapi-flat.json. FastAPI/pydantic v2 emits
#      OpenAPI 3.1 with inline `$defs` blocks that @hey-api/openapi-ts cannot
#      resolve (TypeError) and openapi-python-client silently omits endpoints
#      from. The flatten script rewrites every `#/$defs/X` reference into
#      `#/components/schemas/X`, promoting non-matching inline schemas under
#      deterministic synthetic names (`X__inline_<sha1[:8]>`). The committed
#      backend/openapi.json snapshot is NEVER modified — it stays as the
#      contract source-of-truth, and only the SDK generators consume the
#      flattened intermediate. See scripts/flatten_openapi_defs.py docstring.
#   3. cp-stash hand-written auth wrappers to /tmp before generation so
#      openapi-python-client's --overwrite (Pitfall 6) doesn't delete them.
#      The 2>/dev/null silences "no such file" on the FIRST run when auth.py
#      doesn't exist yet.
#   4. Run the Python + TypeScript generators against the flat intermediate.
#   5. Restore stashed auth wrappers.
#   6. sync_sdk_versions.py pins both SDK package versions to the OpenAPI
#      info.version (closes Pitfall 9 — version drift caught alongside code
#      drift in `make sdks-check`).
sdks:
	cd backend && PYTHONPATH=. uv run python scripts/dump_openapi.py
	uv run --no-project python scripts/flatten_openapi_defs.py \
	  --input backend/openapi.json \
	  --output /tmp/openapi-flat.json
	-cp sdks/python/geolens/auth.py /tmp/_geolens_auth.py 2>/dev/null
	-cp sdks/python/geolens/__init__.py /tmp/_geolens_init.py 2>/dev/null
	-cp sdks/typescript/src/auth.ts /tmp/_geolens_auth.ts 2>/dev/null
	-cp sdks/typescript/src/index.ts /tmp/_geolens_index.ts 2>/dev/null
	uvx openapi-python-client@0.28.3 generate \
	  --path /tmp/openapi-flat.json \
	  --output-path sdks/python/geolens \
	  --overwrite --meta none \
	  --config sdks/python/.openapi-python-client.yaml
	# PEP 561 marker — generator with --meta none doesn't emit it; touch so
	# typecheckers consume the inline annotations on consumers' machines.
	touch sdks/python/geolens/py.typed
	cd sdks/typescript && npm install --silent && npx --yes @hey-api/openapi-ts@0.96.1 -i /tmp/openapi-flat.json
	-cp /tmp/_geolens_auth.py sdks/python/geolens/auth.py 2>/dev/null
	-cp /tmp/_geolens_init.py sdks/python/geolens/__init__.py 2>/dev/null
	-cp /tmp/_geolens_auth.ts sdks/typescript/src/auth.ts 2>/dev/null
	-cp /tmp/_geolens_index.ts sdks/typescript/src/index.ts 2>/dev/null
	uv run --no-project python scripts/sync_sdk_versions.py

# `make sdks-check` regenerates and fails if anything changed.
# Hand-written wrappers + READMEs + LICENSE are excluded via :! pathspecs.
sdks-check:
	$(MAKE) sdks
	git diff --exit-code -- sdks/ \
	  ':!sdks/python/geolens/auth.py' \
	  ':!sdks/python/geolens/__init__.py' \
	  ':!sdks/typescript/src/auth.ts' \
	  ':!sdks/typescript/src/index.ts' \
	  ':!sdks/python/README.md' \
	  ':!sdks/typescript/README.md' \
	  ':!sdks/python/LICENSE' \
	  ':!sdks/typescript/LICENSE'

# `make sdks-test` runs the round-trip integration test (added in Plan 04).
# Stub today; Plan 04 creates backend/tests/test_sdks_round_trip.py.
sdks-test:
	cd backend && PYTHONPATH=. uv run pytest tests/test_sdks_round_trip.py -v

manifest-contract-check:
	cd cli && uv run pytest tests/test_manifest_schema.py tests/test_manifest_validate.py tests/test_manifest_apply.py tests/test_manifest_examples.py tests/test_manifest_cli_offline.py -q
	cd backend && PYTHONPATH=. POSTGRES_HOST=localhost POSTGRES_PORT="$${DB_PORT:-5434}" JWT_SECRET_KEY=test-secret-key-for-ci-padding-32chars GEOLENS_ADMIN_USERNAME=admin GEOLENS_ADMIN_PASSWORD=admin uv run pytest tests/test_manifest_apply_api.py tests/test_manifest_apply_service.py tests/test_manifest_apply_vrt.py tests/test_manifest_apply_roundtrip.py tests/test_layering.py::test_manifest_apply_backend_has_no_cli_sdk_or_enterprise_imports tests/test_layering.py::test_manifest_apply_router_uses_upload_permission -q
	$(MAKE) openapi-check
	$(MAKE) sdks-check

# Publish targets — require local registry credentials.
# Phase 215 ships the recipe; running it is a manual user action (D-16).
publish-sdks-py:
	cd sdks/python && uv build && uv publish

publish-sdks-ts:
	cd sdks/typescript && npm install && npm run build && npm publish --access public

# ----- CLI (Phase 216) -----
# `make cli-build` builds the geolens CLI wheel + sdist.
cli-build: ## Build the geolens CLI wheel + sdist
	cd cli && uv build

# `make cli-test` runs CLI unit tests + round-trip integration test (round-trip lands in Plan 06).
cli-test: ## Run CLI unit tests + round-trip integration test (round-trip lands in Plan 06)
	cd cli && uv run pytest -v
	cd backend && PYTHONPATH=. POSTGRES_HOST=localhost POSTGRES_PORT="$${DB_PORT:-5434}" POSTGRES_USER=geolens POSTGRES_PASSWORD=geolens POSTGRES_DB=geolens JWT_SECRET_KEY=test-secret-key-for-ci-padding-32chars GEOLENS_ADMIN_USERNAME=admin GEOLENS_ADMIN_PASSWORD=admin uv run pytest tests/test_cli_round_trip.py -v

# `make cli-check` — version drift in cli/pyproject.toml is caught by sdks-check
# (sync_sdk_versions extension lands in Plan 06).
cli-check: sdks-check ## Alias — version drift in cli/pyproject.toml is caught by sdks-check
	@echo "cli-check OK (drift gate is sdks-check; sync_sdk_versions extension catches CLI version drift)"

# `make publish-cli` — manual user action; requires PyPI credentials outside CI.
publish-cli: ## Build + publish geolens-cli to PyPI
	cd cli && uv build && uv publish

# Phase 222 AUDIT-02 invariant: log_action() is called only by DefaultAuditSink.emit().
# All 65 historical emit sites must route through audit_emit(session, AuditEvent(...)) instead.
# This target runs the architecture-guard test in isolation — quick local verification
# without spinning up the full pytest suite.
audit-sink-discipline: ## Verify no `await log_action(` calls exist outside audit/service.py + extensions/defaults.py (Phase 222 AUDIT-02)
	cd backend && PYTHONPATH=. uv run pytest tests/test_layering.py::test_no_log_action_calls_outside_audit_service -v

# Phase 223 BILLING-02 / BILLING-04 invariants:
#   - app.core.marketplace must not exist as a module under backend/app/
#   - No `from app.core.marketplace` import anywhere in backend/app/
#   - The production dispatch loop in api/main.py uses literal timeout=10.0 (D-11)
# This target runs both architecture-guard tests in isolation — quick local
# verification without spinning up the full pytest suite.
billing-extraction-discipline: ## Verify app.core.marketplace is absent + dispatch hardcodes timeout=10.0 (Phase 223 BILLING-02 / BILLING-04)
	cd backend && PYTHONPATH=. uv run pytest tests/test_layering.py::test_no_core_marketplace_import tests/test_layering.py::test_billing_dispatch_uses_hardcoded_timeout -v

# Phase 224 DECOUPLE-04 invariant: no external module imports from the
# catalog/datasets/domain/service_X sub-modules directly. The 1407-LOC
# god-module was split into 5 cohesive sub-modules behind a thin re-export
# façade in service.py. All 22 consumer files in backend/app/ must continue
# to import via the façade — sub-module bypasses are forbidden (cross-imports
# BETWEEN the 5 sub-modules are permitted, D-05).
# This target runs the architecture-guard test in isolation — quick local
# verification without spinning up the full pytest suite (uses git grep,
# no DB required).
catalog-domain-discipline: ## Verify no external imports of catalog/datasets/domain/service_X sub-modules (Phase 224 DECOUPLE-04)
	cd backend && PYTHONPATH=. uv run pytest tests/test_layering.py::test_no_external_imports_of_dataset_domain_submodules -v
