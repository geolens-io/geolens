# Use bash with pipefail so `make sdks`'s
# `uvx openapi-python-client ... 2>&1 | tee /tmp/...log` propagates the
# generator's non-zero exit instead of `tee`'s 0. Applies to all recipes;
# existing recipes are pipefail-safe (no recipe relies on partial-pipeline
# tolerance).
SHELL := /bin/bash
.SHELLFLAGS := -o pipefail -c

.PHONY: dev dev-init down reset-db migrate migration alembic-check test test-sequential test-cov e2e logs logs-db logs-api status doctor preflight openapi openapi-check sdks sdks-check sdks-test manifest-contract-check publish-sdks-py publish-sdks-ts cli-build cli-test cli-check publish-cli audit-sink-discipline billing-extraction-discipline catalog-domain-discipline bump version-check public-surface-check deployed-surface-check

# Pre-flight: verify boot-required env vars are non-empty in .env before any
# `docker compose` build (which takes 5-10 minutes on a cold cache only to crash
# at startup if JWT_SECRET_KEY / GEOLENS_ADMIN_USERNAME / GEOLENS_ADMIN_PASSWORD
# are empty). Skip with `make dev SKIP_PREFLIGHT=1` if you know your .env is good.
preflight:
ifndef SKIP_PREFLIGHT
	@bash scripts/preflight-env.sh
endif

dev: preflight
	docker compose up --build

# One-shot contributor bootstrap: scripts/install.sh generates .env with dev
# creds + secrets and starts the stack. It prints how to retrieve the generated
# admin password (`grep '^GEOLENS_ADMIN_PASSWORD=' .env`) rather than echoing the
# secret itself (SEC-011 no-echo policy).
dev-init: ## One-shot contributor bootstrap (.env + secrets + start stack)
	@bash scripts/install.sh

# Friendly per-service health view + URL crib sheet.
status:
	@docker compose ps --format "table {{.Service}}\t{{.State}}\t{{.Status}}" 2>/dev/null
	@echo ""
	@echo "URLs (defaults — override via .env):"
	@echo "  Frontend:  http://localhost:8080"
	@echo "  API docs:  http://localhost:8080/api/docs"
	@echo "  OpenAPI:   http://localhost:8080/api/openapi.json"

# Post-flight health probe: env vars + db connectivity + GDAL availability.
# Requires the stack to be running.
doctor:
	@bash scripts/check-env.sh

down:
	docker compose down

reset-db:
	docker compose down -v
	docker compose up --build

migrate:
	docker compose exec api uv run alembic upgrade heads

migration:
	docker compose exec api uv run alembic revision --autogenerate -m "$(msg)"

# MIG-03: autogenerate drift gate. `alembic check` exits non-zero if the ORM
# models have drifted from the migration scripts (a model column added without
# a matching migration, etc.). Run against a DB that is already at head — the
# migrate target / `docker compose up` brings it there. Mirrors the drift gate
# already baked into scripts/test_alembic_upgrade_clean_db.sh, exposed here as
# a one-liner and wired into CI (.github/workflows/ci.yml, Backend Tests job).
alembic-check:
	# Requires an OSS-clean DB at head. A dev DB that carries cloud c-chain revisions
	# (from prior overlay work) can't be resolved by the OSS image and will report a
	# missing revision — reset the dev DB or use a clean OSS DB. UV_CACHE_DIR points at a
	# writable path because the running container's default ~/.cache/uv is read-only.
	docker compose exec -T -e UV_CACHE_DIR=/tmp/uv-cache api uv run --no-sync alembic check

# Defaults to parallel execution (the -n value was chosen from xdist benchmarking).
# Use `make test-sequential` to opt into sequential debugging mode.
test:
	docker compose exec api env UV_CACHE_DIR=/app/staging/uv-cache UV_PROJECT_ENVIRONMENT=/app/staging/geolens-api-test-venv uv run pytest -o cache_dir=/app/staging/.pytest_cache -n 4 -v --tb=short

test-sequential:
	docker compose exec api env UV_CACHE_DIR=/app/staging/uv-cache UV_PROJECT_ENVIRONMENT=/app/staging/geolens-api-test-venv uv run pytest -o cache_dir=/app/staging/.pytest_cache -v --tb=short

test-cov:
	docker compose exec api env UV_CACHE_DIR=/app/staging/uv-cache UV_PROJECT_ENVIRONMENT=/app/staging/geolens-api-test-venv uv run pytest -o cache_dir=/app/staging/.pytest_cache -v --tb=short --cov=app --cov-report=term-missing

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

# ----- SDK generation -----
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
	  --config sdks/python/.openapi-python-client.yaml \
	  2>&1 | tee /tmp/openapi-python-client.log
	# PEP 561 marker — generator with --meta none doesn't emit it; touch so
	# typecheckers consume the inline annotations on consumers' machines.
	touch sdks/python/geolens/py.typed
	# fix(#441): run the generator from the LOCAL lockfile-pinned install, not a
	# fresh `npx @hey-api/openapi-ts@…` resolve. openapi-ts declares an
	# open-ended `typescript >=5.5.3 || >=6.0.0` peer, so a cold npx resolve
	# pulls typescript 7 (published 2026-07-08), whose changed compiler API
	# crashes the generator (`ts.NewLineKind` undefined) — and npm lets the peer
	# range beat even an explicit `-p typescript@5.9.x`. package.json pins the
	# generator + typescript exactly; package-lock.json makes it reproducible.
	cd sdks/typescript && npm install --silent && ./node_modules/.bin/openapi-ts -i /tmp/openapi-flat.json
	-cp /tmp/_geolens_auth.py sdks/python/geolens/auth.py 2>/dev/null
	-cp /tmp/_geolens_init.py sdks/python/geolens/__init__.py 2>/dev/null
	-cp /tmp/_geolens_auth.ts sdks/typescript/src/auth.ts 2>/dev/null
	-cp /tmp/_geolens_index.ts sdks/typescript/src/index.ts 2>/dev/null
	uv run --no-project python scripts/sync_sdk_versions.py
	# SDK-gen gate: openapi-python-client emits `WARNING parsing <METHOD> <ROUTE>`
	# when a route's body shape is unparseable (e.g., text/plain), and silently drops the
	# endpoint from the generated Python SDK. The gate fails the build on any such line.
	# Pattern is anchored to openapi-python-client's literal emission format to avoid
	# false-positives on AuthlibDeprecationWarning / uv VIRTUAL_ENV / other env noise.
	#
	# Explicitly assert the log file exists before grep, so
	# a missing log (e.g., generator crashed before tee opened the file, or
	# the build env wiped /tmp between recipe lines) prints a clear error
	# rather than the misleading "emitted  warning(s)" with empty count.
	@if [ ! -f /tmp/openapi-python-client.log ]; then \
	    echo "ERROR: /tmp/openapi-python-client.log missing — openapi-python-client did not run or its output was discarded." >&2; \
	    exit 1; \
	  fi; \
	  _count=$$(grep -c '^WARNING parsing' /tmp/openapi-python-client.log || true); \
	  if [ "$$_count" != "0" ]; then \
	    echo "" >&2; \
	    echo "ERROR: openapi-python-client emitted $$_count warning(s) — endpoint(s) silently dropped from Python SDK:" >&2; \
	    grep '^WARNING parsing' /tmp/openapi-python-client.log >&2; \
	    echo "" >&2; \
	    echo "Fix the FastAPI route schema at the source (typically by replacing a non-JSON body shape with a Pydantic JSON body)." >&2; \
	    exit 1; \
	  fi

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

# `make sdks-test` runs the SDK round-trip integration test.
sdks-test:
	cd backend && PYTHONPATH=. uv run pytest tests/test_sdks_round_trip.py -v

manifest-contract-check:
	cd cli && uv run --extra dev python -m pytest tests/test_manifest_schema.py tests/test_manifest_validate.py tests/test_manifest_apply.py tests/test_manifest_examples.py tests/test_manifest_cli_offline.py -q
	cd backend && PYTHONPATH=. POSTGRES_HOST=localhost POSTGRES_PORT="$${DB_PORT:-5434}" JWT_SECRET_KEY=test-secret-key-for-ci-padding-32chars GEOLENS_ADMIN_USERNAME=admin GEOLENS_ADMIN_PASSWORD=geolens-ci-admin-password uv run pytest tests/test_manifest_apply_api.py tests/test_manifest_apply_service.py tests/test_manifest_apply_vrt.py tests/test_manifest_apply_roundtrip.py tests/test_layering.py::test_manifest_apply_backend_has_no_cli_sdk_or_enterprise_imports tests/test_layering.py::test_manifest_apply_router_uses_upload_permission -q
	$(MAKE) openapi-check
	$(MAKE) sdks-check

# Publish targets — require local registry credentials. Running them is a
# manual maintainer action.
publish-sdks-py:
	cd sdks/python && uv build && uv publish

publish-sdks-ts:
	cd sdks/typescript && npm install && npm run build && npm publish --access public

# ----- CLI -----
# `make cli-build` builds the geolens CLI wheel + sdist.
cli-build: ## Build the geolens CLI wheel + sdist
	cd cli && uv build

# `make cli-test` runs CLI unit tests + the round-trip integration test.
cli-test: ## Run CLI unit tests + round-trip integration test
	cd cli && uv run --extra dev python -m pytest -v
	cd backend && PYTHONPATH=. POSTGRES_HOST=localhost POSTGRES_PORT="$${DB_PORT:-5434}" POSTGRES_USER=geolens POSTGRES_PASSWORD=geolens POSTGRES_DB=geolens JWT_SECRET_KEY=test-secret-key-for-ci-padding-32chars GEOLENS_ADMIN_USERNAME=admin GEOLENS_ADMIN_PASSWORD=geolens-ci-admin-password uv run pytest tests/test_cli_round_trip.py -v

# `make cli-check` — version drift in cli/pyproject.toml is caught by sdks-check.
cli-check: sdks-check ## Alias — version drift in cli/pyproject.toml is caught by sdks-check
	@echo "cli-check OK (drift gate is sdks-check; sync_sdk_versions extension catches CLI version drift)"

# `make publish-cli` — manual user action; requires PyPI credentials outside CI.
publish-cli: ## Build + publish geolens-cli to PyPI
	cd cli && uv build && uv publish

# Invariant: log_action() is called only by DefaultAuditSink.emit().
# All 65 historical emit sites must route through audit_emit(session, AuditEvent(...)) instead.
# This target runs the architecture-guard test in isolation — quick local verification
# without spinning up the full pytest suite.
audit-sink-discipline: ## Verify no `await log_action(` calls exist outside audit/service.py + extensions/defaults.py
	cd backend && PYTHONPATH=. uv run pytest tests/test_layering.py::test_no_log_action_calls_outside_audit_service -v

# Invariants:
#   - app.core.marketplace must not exist as a module under backend/app/
#   - No `from app.core.marketplace` import anywhere in backend/app/
#   - The production dispatch loop in api/main.py uses literal timeout=10.0 (D-11)
# This target runs both architecture-guard tests in isolation — quick local
# verification without spinning up the full pytest suite.
billing-extraction-discipline: ## Verify app.core.marketplace is absent + dispatch hardcodes timeout=10.0
	cd backend && PYTHONPATH=. uv run pytest tests/test_layering.py::test_no_core_marketplace_import tests/test_layering.py::test_billing_dispatch_uses_hardcoded_timeout -v

# Invariant: no external module imports from the
# catalog/datasets/domain/service_X sub-modules directly. The 1407-LOC
# god-module was split into 5 cohesive sub-modules behind a thin re-export
# façade in service.py. All 22 consumer files in backend/app/ must continue
# to import via the façade — sub-module bypasses are forbidden (cross-imports
# BETWEEN the 5 sub-modules are permitted, D-05).
# This target runs the architecture-guard test in isolation — quick local
# verification without spinning up the full pytest suite (uses git grep,
# no DB required).
catalog-domain-discipline: ## Verify no external imports of catalog/datasets/domain/service_X sub-modules
	cd backend && PYTHONPATH=. uv run pytest tests/test_layering.py::test_no_external_imports_of_dataset_domain_submodules -v

# ----- Version management (REL-05) -----
# `make bump VERSION=X.Y.Z` rewrites EVERY version site atomically (backend +
# cli + sdks×2 + root/frontend package.json + openapi.json info.version + the
# metadata fallback constant in main.py). The write side of the version
# contract; `make version-check` is the read/verify side.
bump: ## Rewrite all version sites to VERSION=X.Y.Z (single source of truth)
ifndef VERSION
	$(error VERSION is required: make bump VERSION=X.Y.Z)
endif
	uv run --no-project python scripts/bump_version.py "$(VERSION)"

# `make version-check` — version-coherence gate (REL-04). Reads every version
# site (backend/cli/sdks×2/root+frontend package.json/openapi.json info.version/
# main.py fallback constant) and exits non-zero if any disagree. Run in CI to
# block a release where one site silently drifted from the rest.
version-check: ## Assert all version sites agree (CI gate)
	uv run --no-project python scripts/check_version_coherence.py

# `make env-doc-check` — env-doc-drift gate (DOC-01). Parses the env keys
# install.sh persists (update_env_value <KEY>) and exits non-zero if any are
# absent from .env.example. Keeps the hand-copy `.env.example` template honest
# against what the installer actually writes. Plain python3 — no project deps.
env-doc-check: ## Assert install.sh-written env keys are documented in .env.example
	python3 scripts/check_env_doc_drift.py

# `make public-surface-check` — public launch-surface wording gate. Plain
# python3; no project dependencies or package install required.
public-surface-check: ## Assert public source surfaces avoid launch-sensitive terms
	python3 scripts/check_public_surface.py

# `make deployed-surface-check` — live marketing/docs deploy drift gate. Plain
# python3; no project dependencies or package install required.
deployed-surface-check: ## Assert deployed marketing/docs pages match launch-surface expectations
	python3 scripts/check_deployed_surface.py
