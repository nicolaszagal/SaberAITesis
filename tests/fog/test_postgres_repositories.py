"""D02 — adaptadores SQLAlchemy de los puertos de auditoría, contra
PostgreSQL real (ver tests/fog/conftest.py).

Cubre las PRUEBAS de D02: inserción del flujo completo (combate -> clip ->
tocado -> clasificación -> revisión -> veredicto -> auditoría), UPDATE
sobre veredicto falla (RNF-05), y solo una versión de modelo activa a la vez.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text, update
from sqlalchemy.exc import DBAPIError

from fog.infrastructure.persistence.postgres.auditoria_repository import (
    PostgresAuditoriaRepository,
)
from fog.infrastructure.persistence.postgres.clasificacion_repository import (
    PostgresClasificacionRepository,
)
from fog.infrastructure.persistence.postgres.clip_repository import (
    PostgresClipRepository,
)
from fog.infrastructure.persistence.postgres.combate_repository import (
    PostgresCombateRepository,
)
from fog.infrastructure.persistence.postgres.modelo_version_repository import (
    PostgresModeloVersionRepository,
)
from fog.infrastructure.persistence.postgres.revision_repository import (
    PostgresRevisionRepository,
)
from fog.infrastructure.persistence.postgres.tables import veredicto as veredicto_tabla
from fog.infrastructure.persistence.postgres.tocado_repository import (
    PostgresTocadoRepository,
)
from fog.infrastructure.persistence.postgres.veredicto_repository import (
    PostgresVeredictoRepository,
)


@pytest.fixture
async def personas(session_factory):
    """usuario (árbitro) + 2 tirador, insertados con SQL directo: D02 no
    define UsuarioRepositoryPort ni TiradorRepositoryPort (fuera del
    alcance de la tarea — ver fog/ports/combate_repository.py)."""
    async with session_factory() as session, session.begin():
        arbitro_id = (
            await session.execute(
                text(
                    "INSERT INTO sabre.usuario (nombre, rol) "
                    "VALUES ('Árbitro de prueba', 'arbitro') RETURNING id"
                )
            )
        ).scalar_one()
        tirador_a_id = (
            await session.execute(
                text(
                    "INSERT INTO sabre.tirador (alias, brazo_habitual, es_menor) "
                    "VALUES ('Tirador A', 'diestro', false) RETURNING id"
                )
            )
        ).scalar_one()
        tirador_b_id = (
            await session.execute(
                text(
                    "INSERT INTO sabre.tirador (alias, brazo_habitual, es_menor) "
                    "VALUES ('Tirador B', 'zurdo', false) RETURNING id"
                )
            )
        ).scalar_one()
    return {
        "arbitro_id": arbitro_id,
        "tirador_a_id": tirador_a_id,
        "tirador_b_id": tirador_b_id,
    }


async def test_flujo_completo_de_revision(session_factory, personas):
    combate = await PostgresCombateRepository(session_factory).crear(
        pista="pista-1",
        tirador_a_id=personas["tirador_a_id"],
        tirador_b_id=personas["tirador_b_id"],
        brazo_a="diestro",
        brazo_b="zurdo",
        arbitro_id=personas["arbitro_id"],
        configurado_por=personas["arbitro_id"],
    )

    clip = await PostgresClipRepository(session_factory).crear(
        combate_id=combate.id,
        origen="carga",
        camara="unica",
        uri="file:///clips/1.mp4",
        sha256="a" * 64,
        fps=30.0,
        ancho_px=1920,
        alto_px=1080,
        duracion_ms=5000,
    )

    tocado_repo = PostgresTocadoRepository(session_factory)
    tocado = await tocado_repo.crear(
        combate_id=combate.id,
        fuente="simulado",
        luz_a=True,
        luz_b=False,
        t_tocado_ms=4200,
        registrado_por=personas["arbitro_id"],
    )
    await tocado_repo.vincular_clip(tocado.id, clip.id, frame_tocado=126)

    modelo = await PostgresModeloVersionRepository(session_factory).registrar(
        nombre=f"lstm6class-test-{uuid.uuid4()}",
        checkpoint_uri="/tmp/best_model.pt",
        checkpoint_sha256="b" * 64,
        pose_modelo="yolov8x-pose",
        num_features=192,
        num_clases=6,
        f1_macro_test=0.5249,
    )
    assert modelo.activo is True

    clasificacion = await PostgresClasificacionRepository(session_factory).crear(
        tocado_id=tocado.id,
        modelo_version_id=modelo.id,
        disponible=True,
        clase="AtaqueA",
        tirador="A",
        confianza=0.83,
        probabilidades={
            "AtaqueA": 0.83,
            "AtaqueB": 0.0,
            "ContraataqueA": 0.1,
            "ContraataqueB": 0.0,
            "RiposteA": 0.05,
            "RiposteB": 0.02,
        },
        keypoints_uri="file:///keypoints/1.npz",
        keypoints_sha256="c" * 64,
        latencia_ms=42,
    )

    revision_repo = PostgresRevisionRepository(session_factory)
    revision = await revision_repo.crear(
        tocado_id=tocado.id, aceptada=True, arbitro_id=personas["arbitro_id"]
    )
    await revision_repo.asignar_clasificacion(revision.id, clasificacion.id)

    veredicto = await PostgresVeredictoRepository(session_factory).crear(
        revision_id=revision.id, decision="mantener", arbitro_id=personas["arbitro_id"]
    )

    await revision_repo.cerrar(revision.id, datetime.now(timezone.utc))

    snapshot = {
        "revision_id": str(revision.id),
        "clase_sugerida": clasificacion.clase,
        "veredicto": veredicto.decision,
        "modelo": modelo.nombre,
    }
    auditoria = await PostgresAuditoriaRepository(session_factory).registrar(
        revision_id=revision.id, snapshot=snapshot
    )
    assert len(auditoria.hash) == 64

    revision_final = await revision_repo.obtener(revision.id)
    assert revision_final.cerrada_en is not None
    assert revision_final.clasificacion_id == clasificacion.id


async def test_actualizar_veredicto_falla(session_factory, personas):
    combate = await PostgresCombateRepository(session_factory).crear(
        pista="pista-1",
        tirador_a_id=personas["tirador_a_id"],
        tirador_b_id=personas["tirador_b_id"],
        brazo_a="diestro",
        brazo_b="zurdo",
        arbitro_id=personas["arbitro_id"],
        configurado_por=personas["arbitro_id"],
    )
    tocado = await PostgresTocadoRepository(session_factory).crear(
        combate_id=combate.id,
        fuente="simulado",
        luz_a=True,
        luz_b=False,
        t_tocado_ms=1000,
    )
    revision = await PostgresRevisionRepository(session_factory).crear(
        tocado_id=tocado.id, aceptada=True, arbitro_id=personas["arbitro_id"]
    )
    veredicto = await PostgresVeredictoRepository(session_factory).crear(
        revision_id=revision.id, decision="mantener", arbitro_id=personas["arbitro_id"]
    )

    async with session_factory() as session:
        with pytest.raises(DBAPIError, match="no pueden modificarse"):
            async with session.begin():
                await session.execute(
                    update(veredicto_tabla)
                    .where(veredicto_tabla.c.id == veredicto.id)
                    .values(decision="cambiar")
                )


async def test_solo_una_version_de_modelo_activa(session_factory):
    modelo_repo = PostgresModeloVersionRepository(session_factory)
    primera = await modelo_repo.registrar(
        nombre=f"lstm6class-test-{uuid.uuid4()}",
        checkpoint_uri="/tmp/a.pt",
        checkpoint_sha256="d" * 64,
        pose_modelo="yolov8x-pose",
        num_features=192,
        num_clases=6,
        f1_macro_test=0.40,
    )
    assert primera.activo is True

    segunda = await modelo_repo.registrar(
        nombre=f"lstm6class-test-{uuid.uuid4()}",
        checkpoint_uri="/tmp/b.pt",
        checkpoint_sha256="e" * 64,
        pose_modelo="yolov8x-pose",
        num_features=192,
        num_clases=6,
        f1_macro_test=0.50,
    )
    assert segunda.activo is True

    primera_actual = await modelo_repo.obtener(primera.id)
    assert primera_actual.activo is False

    activo = await modelo_repo.obtener_activo()
    assert activo is not None
    assert activo.id == segunda.id
