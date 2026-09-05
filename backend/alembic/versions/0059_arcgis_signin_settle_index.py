"""Let PostgreSQL enforce one settled audit row per ArcGIS sign-in attempt.

fix(#1889). The sign-in settle finaliser deduplicated on ``attempt_id`` with a
SELECT before its INSERT, and a commit the cancellation interrupted can become
visible between the two. The invariant belongs in the schema, as in 0051.

The predicate pins ``action = 'arcgis_signin'`` and a present ``attempt_id``,
so no other audit action is constrained, and rows written before #1887 carry
no ``attempt_id`` and sit outside it. The finaliser's INSERT names this index
in its ``ON CONFLICT`` clause; the model mirrors it for ``alembic check``.

Plain rather than ``CONCURRENTLY``: ``env.py`` runs the upgrade as one
transaction, which a concurrent build cannot join, and a failed concurrent
build leaves an INVALID index behind. No tagged release writes ``attempt_id``
yet, so no upgraded instance holds a row this index covers.

Revision ID: 0059_arcgis_signin_settle_index
Revises: 0058_arcgis_signin_user_scope
Create Date: 2026-09-05
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0059_arcgis_signin_settle_index"
down_revision: Union[str, None] = "0058_arcgis_signin_user_scope"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEX_NAME = "uq_audit_logs_arcgis_signin_attempt"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE UNIQUE INDEX {_INDEX_NAME}
        ON catalog.audit_logs ((details ->> 'attempt_id'))
        WHERE (
            action = 'arcgis_signin'
            AND details ->> 'attempt_id' IS NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS catalog.{_INDEX_NAME}")
