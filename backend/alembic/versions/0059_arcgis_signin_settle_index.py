"""Let PostgreSQL enforce one settled audit row per ArcGIS sign-in attempt.

fix(#1889): one settled row per ``attempt_id`` is a schema invariant, as in
0051, not a read-then-write in the finaliser.

The predicate pins ``action = 'arcgis_signin'`` and a present ``attempt_id``,
so no other audit action is constrained, and rows written before #1887 carry
no ``attempt_id`` and sit outside it. The finaliser's INSERT names this index
in its ``ON CONFLICT`` clause; the model mirrors it for ``alembic check``.

Plain, as 0051 built its index on this table. An instance already holding
two settle rows for one attempt fails this build, and that is the loud and
correct outcome: it is the state the index exists to prevent, and an operator
settles the duplicates first.

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
