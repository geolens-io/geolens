"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-03-22

Squashed from 12 incremental migrations into a single initial schema.
For fresh installs, this creates all tables, indexes, constraints, functions,
and triggers in the catalog schema. For existing databases, stamp this
revision: alembic stamp 0001_initial
"""

from pathlib import Path

from alembic import op
from sqlalchemy.util import await_only

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = Path(__file__).with_name("initial_schema.sql").read_text()

    # asyncpg's Connection.execute() supports multiple statements natively,
    # but SQLAlchemy wraps it with prepared statements (single-statement only).
    # Access the raw asyncpg connection and use SQLAlchemy's greenlet bridge
    # to await the coroutine from synchronous alembic code.
    bind = op.get_bind()
    asyncpg_conn = bind.connection.dbapi_connection._connection
    await_only(asyncpg_conn.execute(sql))


def downgrade() -> None:
    raise NotImplementedError("Initial migration cannot be reversed")
