"""API-key hardening: optional expiry and owner key_epoch snapshot.

fix(#821): API keys had no expiry and no staleness check, so a key lived
forever unless manually revoked and a security event on the owner (role
change, password change) left previously minted keys working.

- ``api_keys.expires_at`` (timestamptz, nullable): NULL keeps the legacy
  forever-key behavior; resolution rejects expired keys exactly like invalid
  ones.
- ``users.key_epoch`` (int, NOT NULL, default 1): API-key revocation
  primitive, deliberately separate from ``token_version``. It is bumped only
  on security events (password change, role change, SAML-to-local
  conversion) — NOT on logout, which bumps ``token_version`` for JWT/session
  hygiene but must not kill long-lived API keys.
- ``api_keys.key_epoch`` (int, NOT NULL): snapshot of the owner's key_epoch
  at mint time, checked against the owner's current value at resolution.
  Existing keys are backfilled with each owner's CURRENT key_epoch so
  security events after this upgrade invalidate keys minted before it.

Revision ID: 0029_api_key_hardening
Revises: 0028_oauth_email_verified_backfill
Create Date: 2026-07-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision: str = "0029_api_key_hardening"
down_revision: Union[str, None] = "0028_oauth_email_verified_backfill"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# fix(#1016): the state the downgrade would silently discard.
#
# ``users.key_epoch > 1`` is the right coarse test for revocation state:
# ``api_keys.key_epoch`` is a mint-time snapshot of the owner's value, so if no
# owner has ever been bumped past the default of 1, no revocation has happened
# and there is nothing to lose.
_COUNT_KEY_STATE = """
SELECT
    (SELECT count(*) FROM catalog.api_keys WHERE expires_at IS NOT NULL),
    (SELECT count(*) FROM catalog.users WHERE key_epoch > 1),
    (SELECT count(*) FROM catalog.api_keys ak
       JOIN catalog.users u ON u.id = ak.user_id
      WHERE ak.expires_at IS NOT NULL OR ak.key_epoch <> u.key_epoch)
"""


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("key_epoch", sa.Integer(), server_default="1", nullable=False),
        schema="catalog",
    )
    op.add_column(
        "api_keys",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        schema="catalog",
    )
    op.add_column(
        "api_keys",
        sa.Column("key_epoch", sa.Integer(), nullable=True),
        schema="catalog",
    )
    # Every key has an owner (user_id is NOT NULL with ON DELETE CASCADE), so
    # this backfill covers all rows and the NOT NULL flip below cannot fail.
    # Owners were just stamped with key_epoch=1 by the server default above,
    # but joining keeps the backfill correct even if that default changes.
    op.execute(
        """
        UPDATE catalog.api_keys ak
        SET key_epoch = u.key_epoch
        FROM catalog.users u
        WHERE ak.user_id = u.id
        """
    )
    op.alter_column("api_keys", "key_epoch", nullable=False, schema="catalog")


def downgrade() -> None:
    # fix(#1016): refuse rather than drop. Both columns carry security state and
    # losing them fails in the unsafe direction — an expired key comes back as a
    # permanent one, and a key revoked by an epoch bump comes back live. Neither
    # raises: the downgrade succeeds, the schema is valid, and the deployment is
    # quietly less secure than the operator believes.
    #
    # This matters despite downgrades being rare, because the one documented
    # procedure that reaches this migration is the multi-tenant fresh-cluster DR
    # path (`alembic downgrade 0016`, RUNBOOK § disaster recovery) — run on
    # someone's worst day, usually for the first time. It is also not covered by
    # the later refusals: several migrations between here and 0020 do index work
    # inside `autocommit_block()`, which commits the DDL preceding it, so a
    # refusal at 0021 does not roll back what 0029 already dropped.
    bind = op.get_bind()
    # Lock before counting, or the count is only a snapshot: the ACCESS SHARE
    # a SELECT takes does not block an API-key insert or a key_epoch update, so
    # a writer could commit between the count and the DROP COLUMNs and have its
    # state discarded by a guard that never saw it. ACCESS EXCLUSIVE rather
    # than SHARE because the drops below need it anyway — taking it up front
    # avoids a lock upgrade, and env.py wraps the whole run in one transaction,
    # so it is held until the downgrade ends.
    op.execute("LOCK TABLE catalog.api_keys, catalog.users IN ACCESS EXCLUSIVE MODE")
    expiring, bumped, affected = bind.execute(text(_COUNT_KEY_STATE)).one()
    if expiring or bumped:
        raise RuntimeError(
            f"{expiring} API key(s) carry an expiry and {bumped} user(s) have "
            f"had their key_epoch bumped; {affected} key(s) would come back "
            "live or permanent if these columns were dropped. Dropping "
            "api_keys.expires_at removes the expiry check, so an already-"
            "expired key resolves as a forever key; dropping the key_epoch "
            "pair removes the revocation check (#821), so keys revoked by an "
            "epoch bump resolve again. Inspect the exact keys with:\n"
            "  SELECT ak.id, ak.user_id, ak.expires_at, ak.key_epoch,\n"
            "         u.key_epoch AS owner_epoch\n"
            "  FROM catalog.api_keys ak\n"
            "  JOIN catalog.users u ON u.id = ak.user_id\n"
            "  WHERE ak.expires_at IS NOT NULL OR ak.key_epoch <> u.key_epoch;\n"
            "Revoking them is almost always what you want, rather than "
            "accepting their resurrection. To do that and clear the epoch "
            "state, run this first, then re-run the downgrade:\n"
            "  DELETE FROM catalog.api_keys ak USING catalog.users u\n"
            "  WHERE ak.user_id = u.id\n"
            "    AND (ak.expires_at IS NOT NULL OR ak.key_epoch <> u.key_epoch);\n"
            "  UPDATE catalog.users SET key_epoch = 1;"
        )

    op.drop_column("api_keys", "key_epoch", schema="catalog")
    op.drop_column("api_keys", "expires_at", schema="catalog")
    op.drop_column("users", "key_epoch", schema="catalog")
