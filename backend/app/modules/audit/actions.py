"""Canonical registry of ``AuditEvent.action`` string literals.

#1230 ("action-registry drift"): the frontend's ``CURRENT_AUDIT_ACTIONS``
(``frontend/src/components/admin/AuditLogViewer.tsx``) had drifted from what
the backend actually emits — it listed four ``layer.*`` values nothing
writes to ``audit_logs`` (builder layer edits go to map edit history
instead) and was missing several real ones (``connector.discover``,
``connector.ingest_dispatch``, and the password-login/``dataset.create``
actions added by this same issue).

This module is the backend half of the fix: every literal passed as
``AuditEvent(action=...)`` anywhere in ``backend/app`` must be a member of
``AUDIT_ACTIONS``. ``backend/tests/test_audit_action_registry.py`` walks the
AST of ``backend/app`` and fails CI if an emit site uses a string this set
does not contain — so a new action is a one-line addition here, made in the
same commit that starts emitting it, rather than a silent drift for the next
audit sweep to rediscover.

This registry is NOT imported by emit sites (that would mean touching ~30
call sites across a dozen modules for no behavioral gain); it is the
independent source of truth the test checks emitted literals against. Keep
it alphabetically sorted so a diff shows exactly what changed.
"""

from __future__ import annotations

AUDIT_ACTIONS: frozenset[str] = frozenset(
    {
        "api_key.create",
        "api_key.revoke",
        # One row per ArcGIS sign-in attempt. Carries the portal host and the
        # outcome, never a username: the outcome keeps the invalid/locked
        # distinction the caller-facing message deliberately collapses, which
        # is what makes someone walking accounts visible to an operator.
        "arcgis_signin",
        "attribute.edit",
        "attribute.reset",
        "audit.export",
        "collection.add_datasets",
        "collection.create",
        "collection.delete",
        "collection.remove_dataset",
        "collection.update",
        "config_export",
        "config_import",
        "connector.discover",
        "connector.ingest_dispatch",
        # fix(#1230): previously no emit site existed anywhere. Emitted once,
        # inside create_dataset() (service_create.py), the function every
        # creation path (ingest registration, file-upload ingest,
        # layer/table creation, the empty-dataset endpoint) funnels through.
        "dataset.create",
        "dataset.delete",
        "dataset.download_cog",
        "dataset.export",
        "dataset.view",
        "embed_token.bulk_revoke",
        "embed_token.create",
        "embed_token.revoke",
        "embed_token.update",
        "embedding.backfill",
        "feature.delete",
        "feature.insert",
        "feature.replace",
        "feature.update",
        # feat(#1677): user-requested cancel of a pending/running ingest job
        # (imports, refreshes, analysis, embedding backfill — uniform scope).
        # Emitted by the cancel endpoint in platform/jobs/router.py.
        "job.cancel",
        "job.cleanup_stale",
        "job.retry",
        "layer.add_column",
        "layer.alter_column_type",
        "layer.drop_column",
        "layer.rename_column",
        "map.add_layer",
        "map.admin_share_revoke",
        "map.bulk_remove_layers",
        "map.create",
        "map.delete",
        "map.duplicate",
        "map.import_style",
        "map.patch_layers",
        "map.remove_layer",
        "map.revoke_share",
        "map.share",
        "map.update",
        "map.update_share_token",
        "metadata.edit",
        "notification.test_sent",
        "oauth.login.failure",
        "oauth.login.init",
        "oauth.login.success",
        "oauth_provider.create",
        "oauth_provider.delete",
        "oauth_provider.update",
        "preview_service_layer",
        "probe_service",
        # feat(#565): the raw sandbox SQL endpoint (POST /api/query/) records
        # every statement it runs or refuses — the durable trail for
        # programmatic SQL data access. Emitted in processing/ai/query_router.py.
        "query.execute",
        "query.reject",
        # feat(#1268) / ADR-002 Amendment A10: the refresh-run lifecycle. The
        # run table is mutable and cascades with its dataset, so it is a status
        # board rather than a ledger; these four are the append-only record.
        # `abandoned` is the stale-run sweep's bookkeeping correction and is
        # deliberately not spelled `failed`.
        "refresh.abandoned",
        # feat(#1677): the explicit-cancel counterpart to `abandoned` — a
        # person asked in-flight work to stop, vs. the sweep's bookkeeping
        # correction for a task proven gone.
        "refresh.cancelled",
        "refresh.dispatch",
        "refresh.failed",
        "refresh.succeeded",
        # PersistentConfig.reset() — generic/unprefixed; resource_type="setting"
        # plus details.setting_key already carry the specificity.
        "reset",
        "reupload.commit",
        "stac_connect",
        "stac_import",
        # PersistentConfig.set() — generic/unprefixed, same rationale as "reset".
        "update",
        "user.approve",
        "user.change_password",
        "user.convert_saml_to_local",
        "user.create",
        "user.deactivate",
        "user.delete",
        "user.export",
        # fix(#1230): password-login success/failure and logout were the
        # other structural gap — only the OAuth path emitted login events.
        # Named to mirror oauth.login.success/failure under the existing
        # user.* prefix (user.change_password, user.register, ...) rather
        # than introducing a separate "auth." prefix for one code path.
        "user.login.failure",
        "user.login.success",
        "user.logout",
        "user.register",
        "user.reject",
        "user.update",
        "user.verify_email",
    }
)
