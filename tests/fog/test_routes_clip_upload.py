"""Pruebas de integración (TestClient) de POST /matches/{match_id}/clip y
POST /matches/config:

- DEF-08: un clip sin tiradores debe responder de inmediato con
  disponible=false y motivo=pose_incompleta, en vez de esperar los 30 s
  del timeout de Cloud.
- DEF-13: weapon_side_A/B inválido -> 422 (TC-NEG-01); archivo que no abre
  como video, clip por debajo de MIN_FRAMES o por encima de CLIP_MAX_MB ->
  400/413 en vez de 500 (TC-NEG-02 y afines).
- DEF-14: has_luz_A/has_luz_B (bool) reemplazan a luz_frame_a/b como forma
  primaria de reportar la luz Favero en la carga de clip; luz_frame_a/b
  quedan como alias obsoleto, y t_tocado_ms se guarda en la sesión sin
  usarse para recortar.

Dobla el estimador de pose (no corre YOLO real) y todo lo que toca Redis
(publisher/subscriber), igual que tests/fog/fakes.py para las pruebas
unitarias de application/.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time

import cv2
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fog.composition import Container
from fog.domain.models import ExtractedFeatures, TrackedSequence, VerdictView, WeaponSide
from fog.infrastructure.api import routes
from fog.infrastructure.persistence.in_memory_match_repository import InMemoryMatchRepository
from fog.infrastructure.webrtc.session_registry import SessionRegistry
from fog.ports.verdict_subscriber import VerdictStreamSubscriberPort
from tests.fog.fakes import (
    FakeFeatureExtractor,
    FakeFeaturePublisher,
    FakePoseEstimator,
    FakeVerdictSubscriber,
    InlineExecutor,
)


class _HangingVerdictSubscriber(VerdictStreamSubscriberPort):
    """Nunca resuelve: simula que Cloud no responde, para ejercitar la
    rama de timeout de POST /matches/{match_id}/clip (DEF-16)."""

    async def wait_for_verdict(self, match_id: str) -> VerdictView:
        await asyncio.Event().wait()


def _tiny_clip_bytes(n_frames: int = 5) -> bytes:
    """Genera un .mp4 mínimo (n_frames, 64x64) en disco y devuelve sus
    bytes — process_uploaded_clip usa cv2.VideoCapture real, así que el
    archivo subido tiene que ser un video decodificable, aunque el
    contenido no importe (el pose_estimator está doblado)."""
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


@pytest.fixture
def unlocked_tracking_client():
    """Cliente con dobles de pose (tracking sin lock A/B, ver
    FakePoseEstimator) y de Redis (publisher/subscriber nunca deberían
    llamarse en este escenario)."""
    container = Container()
    container.config.min_frames.from_value(3)
    container.config.clip_upload_verdict_timeout_s.from_value(30.0)
    container.config.luz_timeout_s.from_value(2.0)
    container.config.clip_max_mb.from_value(200.0)

    tracked = TrackedSequence(frames=[], frame_w=64, frame_h=64, locked=False)
    container.pose_estimator.override(FakePoseEstimator(tracked=tracked))
    container.feature_extractor.override(
        FakeFeatureExtractor(
            result=ExtractedFeatures(sequence=None, stats={"error": "tracking no pudo asignar IDs A/B"})
        )
    )
    container.feature_publisher.override(FakeFeaturePublisher())
    container.verdict_subscriber.override(
        FakeVerdictSubscriber(VerdictView(match_id="unused", fencer="ROJ", action="AttackA", confidence=0.0))
    )
    container.match_repository.override(InMemoryMatchRepository())
    container.executor.override(InlineExecutor())
    container.sessions.override(SessionRegistry())

    container.wire(modules=[routes])
    app = FastAPI()
    app.include_router(routes.router)

    with TestClient(app) as client:
        yield client, container

    container.unwire()


def test_clip_without_fencers_responds_fast_as_unavailable(unlocked_tracking_client):
    client, container = unlocked_tracking_client
    clip = _tiny_clip_bytes()

    start = time.monotonic()
    response = client.post(
        "/matches/m-def08/clip",
        files={"file": ("clip.mp4", clip, "video/mp4")},
    )
    elapsed = time.monotonic() - start

    assert elapsed < 2.0, f"tardó {elapsed:.2f}s, se esperaba respuesta inmediata (sin esperar a Cloud)"
    assert response.status_code == 200

    body = response.json()
    assert body["disponible"] is False
    assert body["motivo"] == "pose_incompleta"
    assert body["timed_out"] is False
    assert body["fencer"] is None
    assert body["action"] is None
    assert body["confidence"] is None

    publisher = container.feature_publisher()
    assert publisher.published == []


def test_upload_clip_below_min_frames_returns_400(unlocked_tracking_client):
    """DEF-13: un video real pero por debajo de MIN_FRAMES (fixture usa 3)
    se rechaza con 400 antes de correr pose/tracking."""
    client, container = unlocked_tracking_client
    clip = _tiny_clip_bytes(n_frames=1)

    response = client.post(
        "/matches/m-min-frames/clip",
        files={"file": ("corto.mp4", clip, "video/mp4")},
    )

    assert response.status_code == 400
    assert "detail" in response.json()

    publisher = container.feature_publisher()
    assert publisher.published == []


def test_upload_clip_over_max_size_returns_413(unlocked_tracking_client):
    """DEF-13: un clip por encima de CLIP_MAX_MB responde 413 sin llegar a
    escribirlo a disco ni a correr pose/tracking."""
    client, container = unlocked_tracking_client
    container.config.clip_max_mb.from_value(1e-6)  # ~1 byte, cualquier clip real lo supera
    clip = _tiny_clip_bytes()

    response = client.post(
        "/matches/m-max-mb/clip",
        files={"file": ("clip.mp4", clip, "video/mp4")},
    )

    assert response.status_code == 413
    assert "detail" in response.json()

    publisher = container.feature_publisher()
    assert publisher.published == []


def test_upload_clip_has_luz_fields_take_precedence_over_legacy_alias(unlocked_tracking_client):
    """DEF-14: has_luz_A/has_luz_B (bool) son la forma vigente; si vienen,
    ganan sobre luz_frame_a/b aunque el alias obsoleto también se envíe.
    También verifica que t_tocado_ms quede guardado en la sesión sin
    afectar la respuesta (no se usa para recortar)."""
    client, container = unlocked_tracking_client
    clip = _tiny_clip_bytes()

    response = client.post(
        "/matches/m-def14/clip",
        files={"file": ("clip.mp4", clip, "video/mp4")},
        data={
            "has_luz_A": "true",
            "has_luz_B": "false",
            "t_tocado_ms": "1234",
            # Alias obsoleto, con un valor que produciría el resultado
            # contrario si el endpoint todavía lo usara como fuente principal.
            "luz_frame_b": "0",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["has_luz_A"] is True
    assert body["has_luz_B"] is False

    session = container.sessions().get("m-def14")
    assert session.t_tocado_ms == 1234


def test_upload_clip_legacy_alias_used_when_new_fields_absent(unlocked_tracking_client):
    """DEF-14: sin has_luz_A/has_luz_B, luz_frame_a/b sigue funcionando
    como alias obsoleto para no romper clientes viejos."""
    client, _container = unlocked_tracking_client
    clip = _tiny_clip_bytes()

    response = client.post(
        "/matches/m-def14-legacy/clip",
        files={"file": ("clip.mp4", clip, "video/mp4")},
        data={"luz_frame_a": "0"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["has_luz_A"] is True
    assert body["has_luz_B"] is False


def test_weapon_side_invalid_value_returns_422(unlocked_tracking_client):
    """TC-NEG-01 (DEF-13): weapon_side_A/B ahora tipan Literal["right",
    "left"] en los esquemas, así que un valor fuera de ese enum ("zurdo")
    lo rechaza la validación de Pydantic antes de tocar el dominio."""
    client, _container = unlocked_tracking_client

    response = client.post(
        "/matches/config",
        json={"weapon_side_A": "zurdo", "weapon_side_B": "right"},
    )

    assert response.status_code == 422


def test_upload_clip_non_video_file_returns_400(unlocked_tracking_client):
    """TC-NEG-02 (DEF-13): un archivo que cv2 no puede abrir como video
    (texto plano con extensión .mp4) responde 400 con detail, en vez de un
    500 (DEF-13) o de esperar a Cloud."""
    client, container = unlocked_tracking_client

    response = client.post(
        "/matches/m-def13/clip",
        files={"file": ("no_es_video.mp4", b"esto no es un video", "video/mp4")},
    )

    assert response.status_code == 400
    assert "detail" in response.json()

    publisher = container.feature_publisher()
    assert publisher.published == []


@pytest.fixture
def cloud_timeout_client():
    """Cliente con pose+tracking exitosos (locked=True) pero Cloud que
    nunca responde, para ejercitar la rama de timeout de POST
    /matches/{match_id}/clip con un timeout de verdict_timeout_s chico."""
    container = Container()
    container.config.min_frames.from_value(3)
    container.config.clip_upload_verdict_timeout_s.from_value(0.05)
    container.config.luz_timeout_s.from_value(2.0)
    container.config.clip_max_mb.from_value(200.0)

    tracked = TrackedSequence(frames=[], frame_w=64, frame_h=64, locked=True)
    container.pose_estimator.override(FakePoseEstimator(tracked=tracked))
    container.feature_extractor.override(FakeFeatureExtractor())
    container.feature_publisher.override(FakeFeaturePublisher())
    container.verdict_subscriber.override(_HangingVerdictSubscriber())
    container.match_repository.override(InMemoryMatchRepository())
    container.executor.override(InlineExecutor())
    container.sessions.override(SessionRegistry())

    container.wire(modules=[routes])
    app = FastAPI()
    app.include_router(routes.router)

    with TestClient(app) as client:
        yield client, container

    container.unwire()


def test_upload_clip_marks_session_closed_when_cloud_times_out(cloud_timeout_client):
    """DEF-16: el timeout de Cloud es, para el front, otro caso de "no
    disponible" — la sesión debe quedar cerrada (closed_at) para que
    SessionRegistry.sweep_expired la libere pasado SESSION_TTL_S, en vez
    de acumularse para siempre."""
    client, container = cloud_timeout_client
    clip = _tiny_clip_bytes()

    response = client.post(
        "/matches/m-def16-timeout/clip",
        files={"file": ("clip.mp4", clip, "video/mp4")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["timed_out"] is True
    assert body["disponible"] is False
    assert body["motivo"] == "timeout"

    session = container.sessions().get("m-def16-timeout")
    assert session is not None
    assert session.closed_at is not None
    assert session.unavailable is not None
    assert session.unavailable.motivo.value == "timeout"
