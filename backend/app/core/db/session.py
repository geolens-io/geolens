from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import settings

_engine_kwargs: dict = {
    "connect_args": settings.database_connect_args,
    "pool_pre_ping": settings.database_pool_pre_ping,
    "echo": False,
    # Keep bound parameters out of StatementError.__str__. Otherwise SQLAlchemy
    # renders "[SQL: ...] [parameters: (...)]" into the exception message that
    # api/main.py's DB error handler logs with a traceback, and the log redactor in
    # core/logging_config.py only rewrites top-level event_dict keys by name: a
    # connection reset mid-INSERT on catalog.users would put password_hash, email
    # and username in stdout, and any feature write would leak tenant row data.
    # Statement text still reaches the log, as the handler's docstring requires.
    "hide_parameters": True,
}

if settings.db_use_external_pooler:
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs.update(
        {
            "pool_size": settings.db_pool_size,
            "max_overflow": settings.db_max_overflow,
            "pool_timeout": settings.db_pool_timeout,
            "pool_recycle": settings.db_pool_recycle,
        }
    )

engine = create_async_engine(settings.database_url, **_engine_kwargs)
async_session = async_sessionmaker(engine, expire_on_commit=False)

# Register the tenant GUC hook on the global engine
# so every transaction (get_db, raw async_session, worker) picks it up.
# single_tenant: the hook is an unconditional no-op (one check, no SQL).
from app.core.db.tenant_session import install_tenant_session_hook  # noqa: E402

install_tenant_session_hook(engine)


async def release_connection(session: AsyncSession) -> None:
    """Return ``session``'s pooled connection before a long wait on something else.

    Commits rather than rolls back so loaded ORM instances stay readable
    (the factory does not expire on commit); the next statement checks a
    connection out again. Holds on when the session has unflushed changes or
    an open savepoint, since ending the transaction there would persist or
    break work the caller has not finished.
    """
    if session.new or session.dirty or session.deleted:
        return
    if session.in_nested_transaction():
        return
    await session.commit()


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models in the catalog schema."""

    pass
