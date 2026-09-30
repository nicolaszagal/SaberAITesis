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
        assert version == "0006"


async def test_downgrade_y_reaplicacion(alembic_cfg, engine):
    import asyncio

    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
    await asyncio.to_thread(command.downgrade, alembic_cfg, "base")
    async with engine.connect() as conn:
        consulta = text("SELECT count(*) FROM pg_namespace WHERE nspname = 'sabre'")
        esquemas = (await conn.execute(consulta)).scalar_one()
        assert esquemas == 0
    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")


async def test_0003_redefine_la_etiqueta_de_la_vista_y_es_reversible(alembic_cfg, engine):
    """0003: la etiqueta pasa de derivarse de la clase sugerida (CASE sobre
    la decisión) a ser `veredicto.clase_final`; la bajada restaura la vista
    anterior y volver a subir la deja como en el esquema documentado."""
    import asyncio

    consulta = text("SELECT pg_get_viewdef('sabre.v_muestras_confirmadas'::regclass)")

    async def definicion() -> str:
        async with engine.connect() as conn:
            return (await conn.execute(consulta)).scalar_one()

    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
    vigente = await definicion()
    assert "v.clase_final AS etiqueta" in vigente
    assert "CASE" not in vigente

    await asyncio.to_thread(command.downgrade, alembic_cfg, "0002")
    anterior = await definicion()
    assert "CASE" in anterior

    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
    assert await definicion() == vigente


async def test_0004_agrega_latencia_inferencia_con_check_y_es_reversible(alembic_cfg, engine):
    """0004: `clasificacion.latencia_inferencia_ms` es INT NULL con CHECK >= 0;
    la bajada la quita y volver a subir la deja igual que el esquema."""
    import asyncio

    from sqlalchemy.exc import DBAPIError

    consulta = text(
        "SELECT data_type, is_nullable FROM information_schema.columns "
        "WHERE table_schema = 'sabre' AND table_name = 'clasificacion' "
        "AND column_name = 'latencia_inferencia_ms'"
    )

    async def columna():
        async with engine.connect() as conn:
            return (await conn.execute(consulta)).one_or_none()

    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
    fila = await columna()
    assert fila is not None
    assert tuple(fila) == ("integer", "YES")

    async with engine.connect() as conn:
        restricciones = (
            await conn.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = 'sabre.clasificacion'::regclass AND contype = 'c'"
                )
            )
        ).scalars().all()
    assert any("latencia_inferencia_ms >= 0" in r for r in restricciones)

    await asyncio.to_thread(command.downgrade, alembic_cfg, "0003")
    assert await columna() is None

    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
    assert tuple(await columna()) == ("integer", "YES")


async def test_0005_precarga_eventos_y_usuarios_y_es_idempotente(alembic_cfg, engine):
    """0005 (V01): inserta 2 eventos y 2 usuarios solo si no existen por nombre;
    aplicarla dos veces no duplica filas ni toca las existentes."""
    import asyncio

    esperados_eventos = {("Evento de prueba", "formativo"), ("Validación 1", "piloto")}
    esperados_usuarios = {("Árbitro de prueba", "arbitro"), ("Operador de prueba", "operador")}

    async def leer(sql: str):
        async with engine.connect() as conn:
            return [tuple(r) for r in await conn.execute(text(sql))]

    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
    assert set(await leer("SELECT nombre, tipo FROM sabre.evento")) == esperados_eventos
    assert set(await leer("SELECT nombre, rol FROM sabre.usuario")) == esperados_usuarios

    # Un dato ya existente no se toca: se desactiva un usuario y se reaplica.
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE sabre.usuario SET activo = FALSE WHERE nombre = 'Árbitro de prueba'")
        )
    await asyncio.to_thread(command.downgrade, alembic_cfg, "0004")
    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")

    assert len(await leer("SELECT 1 FROM sabre.evento")) == 2
    assert len(await leer("SELECT 1 FROM sabre.usuario")) == 2
    assert await leer(
        "SELECT activo FROM sabre.usuario WHERE nombre = 'Árbitro de prueba'"
    ) == [(False,)]


async def test_0006_instante_por_luz_rellena_filas_existentes_y_aplica_los_check(alembic_cfg, engine):
    """0006 (V02): las filas existentes toman `t_tocado_ms` en cada luz encendida;
    `luz_x` es verdadera si y solo si `t_luz_x_ms` no es NULL."""
    import asyncio

    from sqlalchemy.exc import IntegrityError

    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
    await asyncio.to_thread(command.downgrade, alembic_cfg, "0005")
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO sabre.usuario (nombre, rol) VALUES ('u0006', 'arbitro')"))
        await conn.execute(text(
            "INSERT INTO sabre.tirador (alias, brazo_habitual, es_menor) "
            "VALUES ('a0006', 'diestro', TRUE), ('b0006', 'zurdo', TRUE)"))
        await conn.execute(text(
            "INSERT INTO sabre.combate (pista, tirador_a_id, tirador_b_id, brazo_a, brazo_b, "
            "arbitro_id, configurado_por) "
            "SELECT 'P0006', a.id, b.id, 'diestro', 'zurdo', u.id, u.id "
            "FROM sabre.tirador a, sabre.tirador b, sabre.usuario u "
            "WHERE a.alias = 'a0006' AND b.alias = 'b0006' AND u.nombre = 'u0006'"))
        await conn.execute(text(
            "INSERT INTO sabre.tocado (combate_id, fuente, luz_a, luz_b, t_tocado_ms) "
            "SELECT id, 'simulado', TRUE, FALSE, 700 FROM sabre.combate WHERE pista = 'P0006'"))

    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")

    async def fila():
        async with engine.connect() as conn:
            return tuple((await conn.execute(text(
                "SELECT t.luz_a, t.luz_b, t.t_luz_a_ms, t.t_luz_b_ms, t.t_tocado_ms "
                "FROM sabre.tocado t JOIN sabre.combate c ON c.id = t.combate_id "
                "WHERE c.pista = 'P0006'"))).one())

    assert await fila() == (True, False, 700, None, 700)

    # CHECK: una luz encendida exige su instante y una apagada no puede tenerlo.
    insertar = (
        "INSERT INTO sabre.tocado (combate_id, fuente, luz_a, luz_b, t_tocado_ms, t_luz_a_ms, t_luz_b_ms) "
        "SELECT id, 'simulado', {a}, {b}, 100, {ta}, {tb} FROM sabre.combate WHERE pista = 'P0006'"
    )
    for a, b, ta, tb in (("TRUE", "FALSE", "NULL", "NULL"), ("TRUE", "TRUE", "100", "NULL"),
                         ("TRUE", "FALSE", "100", "100"), ("TRUE", "FALSE", "-1", "NULL")):
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(text(insertar.format(a=a, b=b, ta=ta, tb=tb)))
    async with engine.begin() as conn:  # y la combinación válida pasa
        await conn.execute(text(insertar.format(a="TRUE", b="TRUE", ta="100", tb="150")))
