"""Entorno de Alembic: ejecuta las migraciones sobre un engine async (asyncpg)."""

import asyncio

from alembic import context
from sqlalchemy.engine import Connection

from fog.infrastructure.persistence.database import build_engine
from shared import config

# Sin MetaData a propósito: el esquema vive en SQL (docs_claude/sabre_ai_schema.sql)
# y no hay autogenerate.
target_metadata = None

# La migración inicial hace SET search_path TO sabre; la tabla de versiones
# vive en public para no depender del search_path de la sesión.
VERSION_TABLE_SCHEMA = "public"


def _run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema=VERSION_TABLE_SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    engine = build_engine(config.DATABASE_URL, pooled=False)
    async with engine.connect() as connection:
        await connection.run_sync(_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    """Aplica las migraciones pendientes contra DATABASE_URL.

    Raises:
        RuntimeError: si DATABASE_URL no está definida.
    """
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    raise RuntimeError("Las migraciones solo corren en modo online (alembic upgrade head).")
run_migrations_online()
