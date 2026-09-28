"""Engine y sesiones SQLAlchemy 2 (async, asyncpg) para la base `sabre`."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

# El esquema `sabre` (y la extensión pgcrypto, instalada dentro de él) no está
# en el search_path por defecto; las funciones y triggers del esquema
# referencian tablas y digest() sin calificar, así que cada conexión lo fija.
SEARCH_PATH = "sabre,public"


def build_engine(database_url: str | None, *, pooled: bool = True) -> AsyncEngine:
    """Crea el engine async con el search_path del esquema `sabre`.

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
    return create_async_engine(
        database_url,
        connect_args={"server_settings": {"search_path": SEARCH_PATH}},
        **options,
    )


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Fábrica de sesiones async (expire_on_commit=False)."""
    return async_sessionmaker(engine, expire_on_commit=False)
