from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import settings

_engine_kwargs: dict = {
    "connect_args": settings.database_connect_args,
    "pool_pre_ping": settings.database_pool_pre_ping,
    "echo": False,
    # fix(#1778): keep bound parameters out of StatementError.__str__. Without
    # this SQLAlchemy renders "[SQL: ...] [parameters: (...)]" into the
    # exception message, and the DB error handler in api/main.py logs that
    # message WITH a traceback. The SEC-03 redactor in core/logging_config.py
    # only rewrites top-level event_dict keys by name, so it cannot see values
    # embedded in the `exception` string: a connection reset mid-INSERT on
    # catalog.users would put password_hash, email and username in stdout, and
    # any feature write would put arbitrary tenant row data there. The
    # statement text still reaches the log, which is what the handler's
    # docstring asks for.
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

# ISO-01 (Phase 1208-01): register the tenant GUC hook on the global engine so
# EVERY transaction (get_db + raw async_session + worker) picks up the GUC.
# Single-tenant: the hook is an unconditional no-op (one boolean check, no SQL).
from app.core.db.tenant_session import install_tenant_session_hook  # noqa: E402

install_tenant_session_hook(engine)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models in the catalog schema."""

    pass
