# Admin Settings — Operator Notes

This document describes operationally relevant behaviors of GeoLens admin
settings that are easy to miss from the UI alone. The settings catalog itself
lives in `backend/app/core/persistent_config.py` (the `_registry` list); this
document captures per-setting caveats that operators need to know before
flipping a value in a production deployment.

For the public API of the settings router, see `backend/app/modules/settings/router.py`.

## Source-of-truth precedence

Each setting's effective value is resolved in this order, highest precedence
first:

1. Environment variable override (e.g. `LOG_LEVEL=DEBUG`) — only applies
   when the deployment is in env-only mode (`GET /settings/config-mode/` →
   `{"env_only": true}`).
2. Database row in `catalog.app_setting` (the value the admin last wrote
   through the Settings UI). This is the path used by single-binary +
   docker-compose deployments.
3. The hardcoded `env_default` declared at registration time in
   `persistent_config.py`.

Restart picks up the persisted value at boot — the database is the durable
source. In-memory caches in long-running workers are refreshed on every
read for hot-reloadable settings.

## LOG_LEVEL behavior

Setting `LOG_LEVEL` via the admin Settings UI calls
`logging.getLogger().setLevel(value.upper())` synchronously in the worker
process that handles the PUT request. The change is in-memory and applies
to that worker's root logger only. This means:

- The new log level takes effect immediately for that worker.
- **Other uvicorn workers in the same deployment do NOT receive the change**
  until they are restarted (rolling restart, deploy, container recycle, etc.).
- The change is in-memory only — restart picks up the new value from the
  `app_setting` table at boot time, so the persisted setting is correct.

Operationally this is acceptable for development and small single-worker
deployments. For multi-worker production deployments where uniform log
levels across all workers are required, restart the API service after
changing `LOG_LEVEL` (e.g. `docker compose restart api`).

A future enhancement may broadcast log-level changes to all workers via the
existing Valkey/Redis pub/sub channel so the change propagates without
restart. This is tracked as a v13.13+ follow-up; for now restart-on-change
is the canonical operator runbook for cluster-wide log level updates.

The hook lives in `_LogLevelConfig._on_change` at
`backend/app/core/persistent_config.py:286` — any future per-process broadcast
implementation will plug in there.

## Embedding settings (model + dimensions)

Changing `embedding_model` triggers an auto-detect probe of the new model's
output dimensions and persists `embedding_dims` automatically. Changing
`embedding_dims` directly triggers a column rebuild of
`catalog.record_embeddings.embedding` plus an HNSW index rebuild. If the
DDL fails, the persisted `embedding_dims` is rolled back to the previous
value and the request returns `503` — the response payload says
"Embedding column rebuild failed. The embedding_dims setting has been reverted."

Operators should expect a brief read-failure window during the DDL — the
table is locked while the column type changes and the index rebuilds.

## Enterprise-only settings

Settings whose `tab` falls in the `_ENTERPRISE_ONLY_TABS` frozenset
(see `backend/app/modules/settings/router.py`) are gated to enterprise
deployments. Community editions return `404` (not `403`) when a write
hits one of those keys, matching the `require_enterprise()` contract that
hides paid features without leaking their existence.

The canonical list is exposed at `GET /admin/settings/enterprise-tabs/`
so the frontend AdminSidebar renders identically across editions.
