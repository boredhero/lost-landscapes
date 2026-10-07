"""FastAPI dependency injection."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from lost_landscapes.db.engine import async_session_factory
from lost_landscapes.utils.log_manager import log


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    try:
        async with async_session_factory() as session:
            yield session
    except Exception as exc:
        log.error("db_session_error", error=str(exc), exception=exc)
        raise
