"""Community-edition defaults for the extension-seam protocols.

Split from the former single-module ``defaults.py`` (#836): this sub-module
owns the policy/no-op defaults for the extension seams (branding, auth,
permission, workflow, identity, audit sink, notification sink, billing,
connectors, data serving, entitlement). Import these names via the
``app.platform.extensions.defaults`` facade, never from this sub-module.
"""

from __future__ import annotations


class DefaultBrandingExtension:
    """Default branding: shows community badge."""

    def get_branding_defaults(self) -> dict[str, object]:
        return {"show_badge": True}


class DefaultAuthExtension:
    """Default auth: no additional auth methods."""

    def get_auth_methods(self) -> list[str]:
        return []


class DefaultPermissionExtension:
    """Community-edition default permission policy (Phase 232 / PERM-02).

    This class owns the baseline behavior for the PermissionExtension seam.
    Imports stay inside methods so the platform extension package does not
    take module-layer dependencies at import time.
    """

    async def check_permission(
        self,
        db,
        user,
        capability,
        *,
        user_roles,
        permission_matrix=None,
        resource=None,
    ):  # type: ignore[no-untyped-def]
        del user, resource
        matrix = permission_matrix
        if matrix is None:
            from app.modules.auth.permissions import get_effective_permissions

            matrix = await get_effective_permissions(db)
        return any(matrix.get(role, {}).get(capability, False) for role in user_roles)

    def filter_visible(self, stmt, user, user_roles, record_cls, grant_cls=None):  # type: ignore[no-untyped-def]
        from sqlalchemy import and_, or_, select

        from app.modules.auth.models import UserRole

        if "admin" in user_roles:
            return stmt

        if user is None:
            return stmt.where(
                record_cls.visibility == "public",
                record_cls.record_status == "published",
            )

        conditions = [
            record_cls.visibility == "public",
            and_(
                record_cls.visibility == "private",
                record_cls.created_by == user.id,
            ),
            # fix(#930): internal = any signed-in user, on a published record.
            # Bare like `public` above, and for the same reason: `status_filter`
            # below is ANDed over every condition and already carries the
            # published gate. Adding an inner `record_status == "published"`
            # here looks stricter and is wrong — `status_filter` is an OR with
            # `created_by == <caller>`, so it already hides someone else's
            # unpublished internal record from the team, while the inner check
            # would additionally hide an owner's own draft from the owner. That
            # is the list/detail split this issue exists to close, and private
            # and public drafts stay visible to their owner today.
            record_cls.visibility == "internal",
        ]

        if grant_cls is not None:
            # fix(#515): grants key catalog.datasets.id, not records.id — route
            # through Dataset.record_id so granted restricted records resolve.
            from app.modules.catalog.datasets.domain.models import Dataset

            conditions.append(
                and_(
                    record_cls.visibility == "restricted",
                    or_(
                        # fix(#929): creator exemption — without it, a non-admin
                        # owner who sets their own dataset to restricted loses
                        # read access to it (grants have no write path).
                        record_cls.created_by == user.id,
                        record_cls.id.in_(
                            select(Dataset.record_id)
                            .join(grant_cls, grant_cls.dataset_id == Dataset.id)
                            .join(UserRole, grant_cls.role_id == UserRole.role_id)
                            .where(UserRole.user_id == user.id)
                        ),
                    ),
                )
            )

        status_filter = or_(
            record_cls.record_status == "published",
            record_cls.created_by == user.id,
        )
        return stmt.where(and_(or_(*conditions), status_filter))

    async def can_access_dataset(
        self,
        db,
        dataset,
        dataset_id,
        user,
        *,
        user_roles,
    ):  # type: ignore[no-untyped-def]
        from sqlalchemy import select

        from app.modules.auth.models import UserRole
        from app.modules.catalog.datasets.domain.models import DatasetGrant

        record = dataset.record

        if user is None:
            return record.visibility == "public" and record.record_status == "published"

        if "admin" in user_roles:
            return True

        if record.record_status != "published" and record.created_by != user.id:
            return False

        if record.visibility == "private" and record.created_by != user.id:
            return False

        if record.visibility == "restricted":
            # fix(#929): creator exemption — restricted means "owner, admins,
            # and grant holders"; the owner must never be locked out of their
            # own dataset.
            if record.created_by == user.id:
                return True
            grant_result = await db.execute(
                select(DatasetGrant.dataset_id)
                .join(UserRole, DatasetGrant.role_id == UserRole.role_id)
                .where(
                    DatasetGrant.dataset_id == dataset_id,
                    UserRole.user_id == user.id,
                )
            )
            return grant_result.scalar_one_or_none() is not None

        if record.visibility == "internal":
            # fix(#930): internal = any signed-in user, matching MapVisibility.
            # Behaviourally this is what the fall-through below already did, so
            # it looks deletable; it is not. Before this branch existed the
            # outcome was an accident of an unhandled value rather than a
            # policy, and nothing pinned it. The `record_status` gate above
            # keeps unpublished internal records owner-only.
            return True

        return True

    async def record_audience(self, query, user_cls, *, grant_cls=None):  # type: ignore[no-untyped-def]
        """The same ladder as ``filter_visible``, read from the user end.

        ``filter_visible`` asks which RECORDS a user may read; this asks which
        USERS may read a record, at whatever visibility the caller names. One
        rule, two directions, changed as a pair — ``test_permission_audience.py``
        compares them account by account across every visibility, status and
        role, so a change to one that is not mirrored here fails there instead of
        quietly making the shared-map guard disagree with what viewers see.
        """
        from sqlalchemy import and_, false, or_, select, true

        from app.modules.auth.models import Role, UserRole
        from app.platform.extensions.protocols import RecordAudience

        # `filter_visible` returns the statement unchanged for an admin, so an
        # admin is in every audience. Resolved against the role table because
        # there is no user here to read a `user_roles` set off.
        is_admin = user_cls.id.in_(
            select(UserRole.user_id)
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.name == "admin")
        )
        # A record with no recorded owner matches no owner branch: over there
        # `created_by == user.id` is NULL for every row.
        is_owner = false() if query.owner_id is None else user_cls.id == query.owner_id

        if query.visibility in ("public", "internal"):
            # fix(#930): internal = any signed-in user. Bare, like `public`, for
            # the reason spelled out over there — the status gate below is ANDed
            # across every rung and already carries the published check.
            reaches = true()
        elif query.visibility == "private":
            reaches = is_owner
        elif query.visibility == "restricted" and grant_cls is not None:
            # fix(#929): creator exemption, then the grant. `filter_visible`
            # walks record -> dataset -> grant -> role -> user; this is the same
            # edge traversed from the user end.
            reaches = or_(
                is_owner,
                user_cls.id.in_(
                    select(UserRole.user_id)
                    .join(grant_cls, grant_cls.role_id == UserRole.role_id)
                    .where(grant_cls.dataset_id == query.dataset_id)
                ),
            )
        else:
            # Restricted without a grant class, and any value the ladder does
            # not name: both reach nobody in `filter_visible` too, where the
            # condition is simply absent rather than denied.
            reaches = false()

        # `record_status == "published" OR created_by == <caller>`.
        published = true() if query.record_status == "published" else is_owner
        return RecordAudience(
            users=or_(is_admin, and_(reaches, published)),
            includes_anonymous=(
                query.visibility == "public" and query.record_status == "published"
            ),
        )


class DefaultWorkflowExtension:
    """Community-edition default publication workflow policy."""

    DEFAULT_STATUS_ORDER = ("draft", "ready", "internal", "published")
    DEFAULT_ALLOWED_TRANSITIONS = {
        "draft": {"ready"},
        "ready": {"draft", "internal"},
        "internal": {"ready", "published"},
        "published": {"internal"},
    }

    def status_order(self) -> tuple[str, ...]:
        return self.DEFAULT_STATUS_ORDER

    async def allowed_transitions(self, context):  # type: ignore[no-untyped-def]
        statuses = set(self.DEFAULT_STATUS_ORDER)
        if context.from_status not in statuses or context.to_status not in statuses:
            return set()

        if context.mode == "metadata_patch":
            return statuses - {context.from_status}

        return set(self.DEFAULT_ALLOWED_TRANSITIONS.get(context.from_status, set()))

    async def on_transition(self, context) -> None:  # type: ignore[no-untyped-def]
        del context
        return


class DefaultIdentityExtension:
    """Default identity: no alternate backend registered (Phase 214 D-14).

    Returning None from ``resolve_identity_from_token`` signals the auth
    dep chain (``get_optional_user`` / ``get_current_user``, retyped in
    Plan 02) to fall through to the existing JWT decode + DB lookup path.
    Community edition behavior is exactly today's behavior — one async
    method call returning None per request.

    The async signature is intentional (Pitfall 8). Enterprise auth
    overlays may perform DB lookups; the dep wire-in does
    ``await ext.resolve_identity_from_token(token, request, db)``, so
    all implementations — community and enterprise — MUST be async.
    """

    async def resolve_identity_from_token(self, token, request, db):  # type: ignore[no-untyped-def]
        return None


class DefaultAuditSink:
    """Community-edition default: writes one audit_logs row via log_action().

    log_action() is preserved as an internal helper (Phase 222 D-04 / AUDIT-02
    option a). Application code does NOT call log_action() directly post-Phase-222;
    only this sink does.

    Does NOT swallow exceptions internally (D-07) — only the audit_emit() facade
    swallows. Internal swallowing would silently lose session.flush() constraint
    failures that today's tests expect to surface.

    The async signature is intentional: enterprise overlays may perform non-blocking
    I/O (S3 PutObject, SIEM HTTP POST). All sinks — community and enterprise — are
    awaited by ``audit_emit()``.
    """

    async def emit(self, session, event) -> None:  # type: ignore[no-untyped-def]
        # Deferred import: log_action lives in app.modules.audit.service.
        # extensions/ is platform-level and should not pull modules-level
        # imports at module load (Phase 214 deferred-import discipline).
        from app.modules.audit.service import log_action

        await log_action(
            session,
            user_id=event.user_id,
            action=event.action,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            details=event.details,
            ip_address=event.ip_address,
        )


class DefaultNotificationSink:
    """Community-edition default: no-op notification delivery (Phase 1229 NOTIF-04).

    Mirrors ``DefaultBillingExtension``: an async ``deliver`` whose entire body
    is ``return`` (literal no-op). Docstring: community-edition default is
    byte-identical to today — zero outbound send, zero side effects.

    The async signature is intentional so enterprise overlays may perform
    non-blocking I/O (SMTP STARTTLS handshake, HTTP POST to webhook URL).
    All sink implementations — community and enterprise — are awaited by
    ``notify()`` in ``app.platform.notifications``.
    """

    async def deliver(self, notification) -> None:  # type: ignore[no-untyped-def]
        return


class DefaultBillingExtension:
    """Community-edition default — no-op startup hook (Phase 223 D-07 / BILLING-01).

    Mirrors ``DefaultIdentityExtension``: an async no-op that lets the dispatch
    loop iterate over a non-empty ``[DefaultBillingExtension()]`` list when no
    overlay is registered. Empty-list-as-default would also work but breaks
    symmetry with the four existing single-slot Protocols (each has a
    ``Default*`` class).

    The async signature is intentional (D-08): enterprise overlays may perform
    non-blocking I/O (HTTP calls to billing APIs, async DB writes for audit).
    All extensions — community and enterprise — are awaited by the lifespan
    dispatch loop (Plan 02).
    """

    async def on_startup(self, app) -> None:  # type: ignore[no-untyped-def]
        return


class DefaultConnectorExtension:
    """Community-edition default: no persistent connectors."""

    def list_connectors(self) -> list:
        return []

    async def validate_config(self, connector_name, config):  # type: ignore[no-untyped-def]
        del config
        raise ValueError(f"Unknown connector: {connector_name}")

    async def get_credential_ref(self, db, connector_name, credential_id):  # type: ignore[no-untyped-def]
        del db, connector_name, credential_id
        return None

    async def discover_resources(self, db, connector_name, credential_ref, config):  # type: ignore[no-untyped-def]
        del db, credential_ref, config
        raise ValueError(f"Unknown connector: {connector_name}")

    async def dispatch_ingest(
        self,
        db,
        connector_name,
        credential_ref,
        resource_id,
        config,
        user_id,
    ):  # type: ignore[no-untyped-def]
        del db, credential_ref, resource_id, config, user_id
        raise ValueError(f"Unknown connector: {connector_name}")


class DefaultDataServingExtension:
    """Community default: no preparation, concurrency, or cache override."""

    async def prepare_table_for_read(self, *, table_name, tenant_id):  # type: ignore[no-untyped-def]
        del table_name, tenant_id
        return None

    def get_tile_concurrency_limiter(self, tenant_id):  # type: ignore[no-untyped-def]
        del tenant_id
        return None

    def get_tile_cache_control(self) -> None:
        return None


class DefaultEntitlementPort:
    """Community/Enterprise default: grant-all entitlement port (Phase 1207 / ENTSEAM-01).

    This is intentionally fail-OPEN — ``has_feature`` returns ``True`` for any
    feature and ``enforce_limit`` never raises. This is CORRECT for OSS and
    Enterprise because neither has per-tenant tiering; real enforcement is the
    cloud overlay's job (Phase 1213) backed by the ``tenant_entitlements`` table
    (webhook-synced from Stripe). Deploying this default in OSS/Enterprise does
    NOT weaken security because:

    1. ``require_enterprise()`` (binary edition gate) remains orthogonal and
       guards all enterprise-only endpoints independently.
    2. ``PermissionExtension`` (per-user RBAC) remains orthogonal and guards
       all capability checks independently.
    3. OSS/Enterprise are not multi-tenant-tiered; there is no plan to enforce.

    The cloud overlay (Phase 1213) REPLACES this with a real implementation
    by registering under the ``"entitlement"`` single-slot key. The
    ExtensionSlotConflictError guard prevents two overlays from claiming the
    same slot (SLOT-01). See ``protocols.EntitlementPort`` for the full contract.
    """

    async def has_feature(self, feature: str) -> bool:
        """Return True for any feature — grant-all (fail-OPEN by design; see class docstring)."""
        return True

    async def enforce_limit(self, dimension: str, n: int) -> None:
        """No-op — never raises. Grant-all default; real limits enforced by cloud overlay."""
        return None
