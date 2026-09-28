"""Pruebas de integración (TestClient) de POST /matches/{match_id}/clip —
DEF-08: un clip sin tiradores debe responder de inmediato con
disponible=false y motivo=pose_incompleta, en vez de esperar los 30 s del
timeout de Cloud. Dobla el estimador de pose (no corre YOLO real) y todo
lo que toca Redis (publisher/subscriber), igual que tests/fog/fakes.py
para las pruebas unitarias de application/.
"""

from __future__ import annotations

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
from tests.fog.fakes import (
    FakeFeatureExtractor,
    FakeFeaturePublisher,
    FakePoseEstimator,
    FakeVerdictSubscriber,
    InlineExecutor,
)


def _tiny_clip_bytes() -> bytes:
    """Genera un .mp4 mínimo (5 frames, 64x64) en disco y devuelve sus
    bytes — process_uploaded_clip usa cv2.VideoCapture real, así que el
    archivo subido tiene que ser un video decodificable, aunque el
    contenido no importe (el pose_estimator está doblado)."""
    fd, path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    try:
        writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 64))
        for _ in range(5):
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
