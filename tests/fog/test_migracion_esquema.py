"""La migración inicial aplica sobre una base limpia y crea el esquema `sabre`.

Base de pruebas: TEST_DATABASE_URL (servicio de CI, base vacía, formato
postgresql+asyncpg://...) o, si no está, un contenedor postgres:16-alpine
vía testcontainers (fixtures compartidas en tests/fog/conftest.py). Sin
ninguna de las dos (sin Docker), se omite.
"""

from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import text

from fog.infrastructure.persistence.database import build_engine

BACKEND = Path(__file__).resolve().parents[2]
SQL_COPIA = (
    BACKEND / "fog/infrastructure/persistence/migrations/sql/0001_esquema_sabre.sql"
)
SQL_DOCS = BACKEND.parent / "docs_claude" / "sabre_ai_schema.sql"


@pytest.fixture
async def engine(database_url):
    engine = build_engine(database_url, pooled=False)
    yield engine
    await engine.dispose()


def test_copia_del_sql_es_identica_al_esquema_documentado():
    if not SQL_DOCS.exists():
        pytest.skip("docs_claude/ no está junto a backend/")
    assert SQL_COPIA.read_bytes() == SQL_DOCS.read_bytes()


async def test_migracion_aplica_sobre_base_limpia(alembic_cfg, engine):
    # command.* usa asyncio.run: se ejecuta en un hilo, fuera del loop de la prueba.
    import asyncio

    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")

    async with engine.connect() as conn:
        funcion = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM pg_proc p "
                    "JOIN pg_namespace n ON n.oid = p.pronamespace "
                    "WHERE n.nspname = 'sabre' AND p.proname = 'fn_verificar_auditoria'"
                )
            )
        ).scalar_one()
        assert funcion == 1
        # La función corre y, sin registros, no reporta alteraciones.
        alterados = await conn.execute(
            text("SELECT * FROM sabre.fn_verificar_auditoria()")
        )
        assert alterados.all() == []
        vista = (
            await conn.execute(
                text("SELECT count(*) FROM sabre.v_muestras_confirmadas")
            )
        ).scalar_one()
        assert vista == 0
        triggers = {
            r[0]
            for r in await conn.execute(
                text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
            )
        }
        assert {
            "tg_auditoria_hash",
            "tg_auditoria_inmutable",
            "tg_veredicto_inmutable",
            "tg_clasificacion_inmutable",
        } <= triggers
        version = (
            await conn.execute(text("SELECT version_num FROM public.alembic_version"))
        ).scalar_one()
        assert version == "0002"


async def test_downgrade_y_reaplicacion(alembic_cfg, engine):
    import asyncio

    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
    await asyncio.to_thread(command.downgrade, alembic_cfg, "base")
    async with engine.connect() as conn:
        consulta = text("SELECT count(*) FROM pg_namespace WHERE nspname = 'sabre'")
        esquemas = (await conn.execute(consulta)).scalar_one()
        assert esquemas == 0
    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
