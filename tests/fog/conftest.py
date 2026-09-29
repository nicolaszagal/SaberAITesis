"""Fixtures compartidas para pruebas de Fog contra PostgreSQL real.

Base de pruebas: TEST_DATABASE_URL (servicio de CI, base vacía, formato
postgresql+asyncpg://...) o, si no está, un contenedor postgres:16-alpine
vía testcontainers. Sin ninguna de las dos (sin Docker), se omiten las
pruebas que dependan de estas fixtures.
"""

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from fog.infrastructure.persistence.database import build_engine, build_session_factory
from shared import config

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def database_url():
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        yield url
        return
    try:
        from testcontainers.community.postgres import PostgresContainer

        container = PostgresContainer("postgres:16-alpine", driver="asyncpg")
        container.start()
    except Exception as exc:  # Docker no disponible
        pytest.skip(f"Sin base de pruebas (TEST_DATABASE_URL o Docker): {exc}")
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


@pytest.fixture
def alembic_cfg(database_url, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", database_url)
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(BACKEND / "fog/infrastructure/persistence/migrations")
    )
    return cfg


@pytest.fixture
async def migrated_engine(database_url, alembic_cfg):
    """Base con la migración `head` aplicada; engine listo para usar.

    `command.upgrade` corre en un hilo aparte (usa asyncio.run internamente,
    y no puede anidarse dentro del loop de la prueba).
    """
    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
    engine = build_engine(database_url, pooled=False)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(migrated_engine):
    return build_session_factory(migrated_engine)
