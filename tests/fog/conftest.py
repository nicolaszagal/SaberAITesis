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


# ---------------------------------------------------------------------------
# Flujo auditable (D03): app de Fog completa contra PostgreSQL real.
# Solo se doblan pose, extractor de features, Redis y Cloud.
# ---------------------------------------------------------------------------
import hashlib  # noqa: E402
import tempfile  # noqa: E402
import uuid  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from datetime import date  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from dependency_injector import providers  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from fog.composition import Container  # noqa: E402
from fog.domain.models import ExtractedFeatures, TrackedSequence, VerdictView  # noqa: E402
from fog.infrastructure.api import routes  # noqa: E402
from fog.infrastructure.persistence.in_memory_match_repository import (  # noqa: E402
    InMemoryMatchRepository,
)
from fog.infrastructure.persistence.postgres.modelo_version_repository import (  # noqa: E402
    PostgresModeloVersionRepository,
)
from fog.infrastructure.webrtc.session_registry import SessionRegistry  # noqa: E402
from tests.fog.fakes import (  # noqa: E402
    FakeFeatureExtractor,
    FakeFeaturePublisher,
    FakePoseEstimator,
    FakeVerdictSubscriber,
    InlineExecutor,
)

VEREDICTO_DEFAULT = VerdictView(
    match_id="unused",
    revision_id="unused",
    fencer="ROJ",
    action="AttackA",
    confidence=0.74,
    probs={
        "AttackA": 0.74, "AttackB": 0.0, "ContrattackA": 0.16,
        "ContrattackB": 0.0, "RiposteA": 0.10, "RiposteB": 0.0,
    },
    latencia_inferencia_ms=12,
    modelo="lstm_6class/run/best_model.pt",
)


def clip_de_prueba(n_frames: int = 5) -> bytes:
    """Genera un .mp4 mínimo (n_frames, 64x64, 10 fps) y devuelve sus bytes.

    `process_uploaded_clip` usa cv2.VideoCapture real, así que el archivo
    tiene que ser un video decodificable; el contenido no importa (la pose
    está doblada).
    """
    fd, path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    try:
        writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 64))
        for _ in range(n_frames):
            writer.write(np.zeros((64, 64, 3), dtype=np.uint8))
        writer.release()
        with open(path, "rb") as f:
            return f.read()
    finally:
        os.remove(path)


class SQL:
    """Acceso síncrono directo a la base de pruebas (sembrado y consultas)."""

    def __init__(self, url: str):
        self._url = url

    def _correr(self, coro_fn):
        async def main():
            engine = build_engine(self._url, pooled=False)
            try:
                return await coro_fn(engine)
            finally:
                await engine.dispose()

        return asyncio.run(main())

    def filas(self, sql: str, **params) -> list[dict]:
        async def q(engine):
            async with engine.begin() as conn:
                return [dict(r._mapping) for r in await conn.execute(text(sql), params)]

        return self._correr(q)

    def ejecutar(self, sql: str, **params) -> None:
        async def q(engine):
            async with engine.begin() as conn:
                await conn.execute(text(sql), params)

        self._correr(q)

    def escalar(self, sql: str, **params):
        return self.filas(sql, **params)[0].popitem()[1]

    def asegurar_modelo_activo(self) -> uuid.UUID:
        async def q(engine):
            repo = PostgresModeloVersionRepository(build_session_factory(engine))
            activo = await repo.obtener_activo()
            if activo is not None:
                return activo.id
            modelo = await repo.registrar(
                nombre="lstm6class-prueba", checkpoint_uri="local://modelo.pt",
                checkpoint_sha256="a" * 64, pose_modelo="yolov8x-pose",
                num_features=192, num_clases=6,
            )
            return modelo.id

        return self._correr(q)

    def sembrar_evento_y_arbitro(self) -> tuple[uuid.UUID, uuid.UUID]:
        arbitro = self.escalar(
            "INSERT INTO sabre.usuario (nombre, rol) VALUES ('Árbitro', 'arbitro') RETURNING id"
        )
        evento = self.escalar(
            "INSERT INTO sabre.evento (nombre, fecha, tipo) "
            "VALUES ('Piloto', :f, 'piloto') RETURNING id", f=date(2026, 9, 29),
        )
        return evento, arbitro


@dataclass
class AppAuditable:
    client: TestClient
    container: Container
    sql: SQL
    storage_dir: Path
    evidencia_dir: Path
    evento_id: uuid.UUID
    arbitro_id: uuid.UUID

    def body_config(self, **cambios) -> dict:
        body = {
            "evento_id": str(self.evento_id), "pista": "P1", "arbitro_id": str(self.arbitro_id),
            "alias_A": "Rojo", "weapon_side_A": "right",
            "alias_B": "Verde", "weapon_side_B": "left",
        }
        body.update(cambios)
        return {k: v for k, v in body.items() if v is not None}

    def configurar(self, **cambios) -> str:
        resp = self.client.post("/matches/config", json=self.body_config(**cambios))
        assert resp.status_code == 200, resp.text
        return resp.json()["match_id"]

    def subir_clip(self, match_id: str, clip: bytes | None = None, **form):
        datos = {"has_luz_A": "true", "has_luz_B": "false", "t_tocado_ms": "300"}
        datos.update(form)
        datos = {k: v for k, v in datos.items() if v is not None}
        return self.client.post(
            f"/matches/{match_id}/clip",
            files={"file": ("clip.mp4", clip or clip_de_prueba(), "video/mp4")},
            data=datos,
        )

    def veredicto(self, revision_id: str, **cuerpo):
        """POST del veredicto. Por defecto `mantener` con `clase_final`
        (obligatoria salvo con `anular`); pasar `clase_final=None` la omite."""
        decision = cuerpo.get("decision", "mantener")
        body = {
            "decision": decision,
            "clase_final": None if decision == "anular" else "AttackA",
            "arbitro_id": str(self.arbitro_id),
        }
        body.update(cuerpo)
        body = {k: v for k, v in body.items() if v is not None}
        return self.client.post(f"/revisiones/{revision_id}/veredicto", json=body)


@pytest.fixture
def crear_app(database_url, alembic_cfg, tmp_path):
    """Fábrica de `AppAuditable`: migra la base, siembra árbitro, evento y
    modelo activo, y arma la app con pose/Redis/Cloud doblados."""
    command.upgrade(alembic_cfg, "head")
    sql = SQL(database_url)
    sql.asegurar_modelo_activo()
    evento_id, arbitro_id = sql.sembrar_evento_y_arbitro()
    abiertos: list = []

    def _crear(
        *, locked: bool = True, extraccion_falla: bool = False, subscriber=None,
        verdict_timeout_s: float = 30.0, clip_max_mb: float = 200.0,
        clip_timeout_s: float = 60.0, pose_estimator=None,
    ) -> AppAuditable:
        container = Container()
        container.config.database_url.from_value(database_url)
        container.config.storage_dir.from_value(str(tmp_path / "storage"))
        container.config.evidence_dir.from_value(str(tmp_path / "evidencia"))
        container.config.min_frames.from_value(3)
        container.config.clip_upload_verdict_timeout_s.from_value(verdict_timeout_s)
        container.config.clip_upload_timeout_s.from_value(clip_timeout_s)
        container.config.luz_timeout_s.from_value(2.0)
        container.config.clip_max_mb.from_value(clip_max_mb)

        container.db_engine.override(
            providers.Singleton(build_engine, database_url=database_url, pooled=False)
        )
        container.pose_estimator.override(
            pose_estimator
            or FakePoseEstimator(tracked=TrackedSequence(frames=[], frame_w=64, frame_h=64, locked=locked))
        )
        resultado = (
            ExtractedFeatures(sequence=None, stats={"error": "tracking no pudo asignar IDs A/B"})
            if extraccion_falla else None
        )
        container.feature_extractor.override(FakeFeatureExtractor(result=resultado))
        container.feature_publisher.override(FakeFeaturePublisher())
        container.verdict_subscriber.override(subscriber or FakeVerdictSubscriber(VEREDICTO_DEFAULT))
        container.match_repository.override(InMemoryMatchRepository())
        container.executor.override(InlineExecutor())
        container.sessions.override(SessionRegistry())
        container.wire(modules=[routes])

        app = FastAPI()
        app.include_router(routes.router)
        client_cm = TestClient(app, raise_server_exceptions=False)
        client = client_cm.__enter__()
        abiertos.append((client_cm, container))
        return AppAuditable(
            client, container, sql, tmp_path / "storage", tmp_path / "evidencia", evento_id, arbitro_id
        )

    yield _crear
    for client_cm, container in abiertos:
        client_cm.__exit__(None, None, None)
        container.unwire()


def sha256_de(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()
