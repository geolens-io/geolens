"""Canonical registry of ``AuditEvent.action`` string literals.

Every literal passed as ``AuditEvent(action=...)`` must be a member of
``AUDIT_ACTIONS``. ``backend/tests/test_audit_action_registry.py`` walks the
AST of ``backend/app`` and fails on an emit site using a string not in this
set, on an entry nothing emits, and on a mismatch with the frontend's
``CURRENT_AUDIT_ACTIONS``.

Emit sites don't import it; it is the independent source of truth the test
checks against. Sorted alphabetically so a diff shows exactly what changed.
"""

from __future__ import annotations

AUDIT_ACTIONS: frozenset[str] = frozenset(
    {
        "api_key.create",
        "api_key.revoke",
        # One row per ArcGIS sign-in attempt: portal host + outcome, never a
        # username. The outcome preserves the invalid/locked distinction the
        # caller-facing message deliberately collapses.
        "arcgis_signin",
        "attribute.edit",
        "attribute.reset",
        "audit.export",
        "audit.prune",
        "collection.add_datasets",
        "collection.create",
        "collection.delete",
        "collection.remove_dataset",
        "collection.update",
        "config_export",
        "config_import",
        "connector.discover",
        "connector.ingest_dispatch",
        # Emitted once inside create_dataset() (service_create.py), which
        # every creation path funnels through.
        "dataset.create",
        "dataset.delete",
        "dataset.download_cog",
        "dataset.export",
        "dataset.pointcloud_read",
        # A dataset's retained previous version: dropped on request, or
        # published again as its live data.
        "dataset.previous_version_dropped",
        "dataset.restore",
        # One row per dataset per retention run, with the number of rows the
        # run deleted. System-emitted, so it has no user.
        "dataset.retention_prune",
        "dataset.transfer_owner",
        "dataset.view",
        "embed_token.bulk_revoke",
        "embed_token.create",
        "embed_token.revoke",
        "embed_token.update",
        "embedding.backfill",
        "feature.bulk_delete",
        "feature.bulk_insert",
        "feature.delete",
        "feature.insert",
        "feature.replace",
        "feature.update",
        "group.add_members",
        "group.create",
        "group.delete",
        "group.remove_member",
        "group.rename",
        # User-requested cancel of a pending/running ingest job (imports,
        # refreshes, analysis, embedding backfill). Emitted by the cancel
        # endpoint in platform/jobs/router.py.
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
        "map.import_arcgis_webmap",
        "map.import_style",
        "map.patch_layers",
        "map.remove_layer",
        "map.revoke_share",
        "map.share",
        "map.transfer_owner",
        "map.update",
        "map.update_share_token",
        "metadata.edit",
        "notification.test_sent",
        "oauth.login.failure",
        "oauth.login.init",
        "oauth.login.success",
        # IdP group-role mapping applies on every OAuth login, not just
        # account creation, so a role can move without an admin touching it.
        # `changed` = role moved; `change_refused` = the last-admin rule kept
        # it. Neither carries a claim value.
        "oauth.role.change_refused",
        "oauth.role.changed",
        "oauth_provider.create",
        "oauth_provider.delete",
        "oauth_provider.update",
        "preview_service_layer",
        "probe_service",
        # The raw sandbox SQL endpoint (POST /api/query/) records every
        # statement it runs or refuses: the durable trail for programmatic SQL
        # data access. Emitted in processing/ai/query_router.py.
        "query.execute",
        "query.reject",
        # Refresh-run lifecycle (ADR-002 A10). The run table is mutable and
        # cascades with its dataset (a status board, not a ledger); these
        # entries are the append-only record. `abandoned` is the stale-run
        # sweep's correction, deliberately not spelled `failed`.
        "refresh.abandoned",
        "refresh.blocked",
        # The explicit-cancel counterpart to `abandoned`: a person asked
        # in-flight work to stop, vs. the sweep's correction for a task
        # proven gone.
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
        # A password-change budget filling up; one row per window.
        "user.change_password.throttled",
        "user.convert_saml_to_local",
        "user.create",
        "user.deactivate",
        "user.delete",
        "user.export",
        # Password-login success/failure/logout, named to mirror
        # oauth.login.success/failure under the user.* prefix.
        "user.login.failure",
        "user.login.success",
        # A sign-in budget filling up; one row per budget per window.
        "user.login.throttled",
        "user.logout",
        # An admin setting another account's password. Distinct from
        # user.change_password, the self-service path that proves possession
        # of the old value; this one records who acted on whom.
        "user.password_reset",
        "user.register",
        "user.reject",
        "user.update",
        "user.verify_email",
    }
)
