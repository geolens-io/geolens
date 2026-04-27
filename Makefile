.PHONY: dev down reset-db migrate migration test test-cov e2e logs logs-db logs-api openapi openapi-check sdks sdks-check sdks-test publish-sdks-py publish-sdks-ts

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
	-cp sdks/python/geolens_sdk/auth.py /tmp/_geolens_auth.py 2>/dev/null
	-cp sdks/typescript/src/auth.ts /tmp/_geolens_auth.ts 2>/dev/null
	-cp sdks/typescript/src/index.ts /tmp/_geolens_index.ts 2>/dev/null
	uvx openapi-python-client@0.28.3 generate \
	  --path /tmp/openapi-flat.json \
	  --output-path sdks/python/geolens_sdk \
	  --overwrite --meta none \
	  --config sdks/python/.openapi-python-client.yaml
	# PEP 561 marker — generator with --meta none doesn't emit it; touch so
	# typecheckers consume the inline annotations on consumers' machines.
	touch sdks/python/geolens_sdk/py.typed
	cd sdks/typescript && npm install --silent && npx --yes @hey-api/openapi-ts@0.96.1 -i /tmp/openapi-flat.json
	-cp /tmp/_geolens_auth.py sdks/python/geolens_sdk/auth.py 2>/dev/null
	-cp /tmp/_geolens_auth.ts sdks/typescript/src/auth.ts 2>/dev/null
	-cp /tmp/_geolens_index.ts sdks/typescript/src/index.ts 2>/dev/null
	uv run --no-project python scripts/sync_sdk_versions.py

# `make sdks-check` regenerates and fails if anything changed.
# Hand-written wrappers + READMEs + LICENSE are excluded via :! pathspecs.
sdks-check:
	$(MAKE) sdks
	git diff --exit-code -- sdks/ \
	  ':!sdks/python/geolens_sdk/auth.py' \
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

# Publish targets — require user-managed tokens (UV_PUBLISH_TOKEN, NPM_TOKEN).
# Phase 215 ships the recipe; running it is a manual user action (D-16).
publish-sdks-py:
	cd sdks/python && uv build && uv publish

publish-sdks-ts:
	cd sdks/typescript && npm install && npm run build && npm publish --access public
