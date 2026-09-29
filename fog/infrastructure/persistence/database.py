"""Engine y sesiones SQLAlchemy 2 (async, asyncpg) para la base `sabre`."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool


def build_engine(database_url: str | None, *, pooled: bool = True) -> AsyncEngine:
    """Crea el engine async de la base `sabre`.

    No fija `search_path` en la conexión (migración 0002): las funciones y
    triggers del esquema fijan su propio `search_path = sabre, pg_temp`
    (`ALTER FUNCTION ... SET search_path`), y el resto del código (Core,
    adaptadores SQLAlchemy) califica `sabre.<tabla>` explícitamente en vez
    de depender del search_path de la sesión.

    Args:
        database_url: URL `postgresql+asyncpg://...`.
        pooled: False usa NullPool (migraciones y pruebas).

    Returns:
        AsyncEngine configurado.

    Raises:
        RuntimeError: si `database_url` está vacía.
    """
    if not database_url:
        raise RuntimeError(
            "Falta la variable de entorno DATABASE_URL "
            "(postgresql+asyncpg://usuario:clave@host:5432/base)."
        )
    options = {"poolclass": NullPool} if not pooled else {"pool_pre_ping": True}
    return create_async_engine(database_url, **options)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Fábrica de sesiones async (expire_on_commit=False)."""
    return async_sessionmaker(engine, expire_on_commit=False)
