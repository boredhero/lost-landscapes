"""Async SQLAlchemy engine and session factory."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from lost_landscapes.config import settings
from lost_landscapes.utils.log_manager import log

_db_url_display = settings.database_url.split("@")[-1] if "@" in settings.database_url else settings.database_url
log.info("db_engine_creating", pool_size=10, max_overflow=20, host=_db_url_display)

try:
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=10,
        max_overflow=20,
    )
    log.info("db_engine_created", dialect=str(engine.dialect.name), driver=str(engine.dialect.driver))
except Exception as e:
    log.critical("db_engine_creation_failed", error=str(e), exception=True)
    raise

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
log.debug("db_session_factory_configured", expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    log.debug("db_session_opening")
    try:
        async with async_session_factory() as session:
            yield session
    except Exception as e:
        log.error("db_session_error", error=str(e), exception=True)
        raise
    finally:
        log.debug("db_session_closed")
