"""Fakes de los puertos de Fog, para tests unitarios de application/ sin
tocar ultralytics, redis."""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from fog.domain.models import ExtractedFeatures, LuzSignal, TrackedSequence, VerdictView, WeaponSide
from fog.ports.feature_extractor import FeatureExtractorPort
from fog.ports.feature_publisher import FeatureStreamPublisherPort
from fog.ports.pose_estimator import PoseEstimatorPort, PoseTrackingSession
from fog.ports.verdict_subscriber import VerdictStreamSubscriberPort


class FakePoseTrackingSession(PoseTrackingSession):
    """Sesión fake: junta los frames que le pasan con add_frame y, al
    llamar finish(), devuelve el TrackedSequence fijo que le configuró
    FakePoseEstimator (no corre ningún tracking real)."""

    def __init__(self, tracked: TrackedSequence):
        self._tracked = tracked
        self.frames: list = []
        self.finished = False

    def add_frame(self, frame) -> None:
        self.frames.append(frame)

    def finish(self) -> TrackedSequence:
        self.finished = True
        return self._tracked


class FakePoseEstimator(PoseEstimatorPort):
    def __init__(self, tracked: TrackedSequence | None = None):
        self.tracked = tracked or TrackedSequence(frames=[], frame_w=0, frame_h=0, locked=True)
        self.sessions: list[FakePoseTrackingSession] = []

    def start_session(self) -> FakePoseTrackingSession:
        session = FakePoseTrackingSession(self.tracked)
        self.sessions.append(session)
        return session


class FakeFeatureExtractor(FeatureExtractorPort):
    def __init__(self, result: ExtractedFeatures | None = None, raw: np.ndarray | None = None):
        self.result = result or ExtractedFeatures(
            sequence=np.zeros((5, 192), dtype=np.float32), stats={"error": None}
        )
        self.raw = raw  # features crudas que devuelve extract_raw; None = ceros
        self.calls: list[tuple] = []

    def extract(self, tracked, weapon_side_a, weapon_side_b, min_frames=3) -> ExtractedFeatures:
        self.calls.append((tracked, weapon_side_a, weapon_side_b, min_frames))
        return self.result

    def extract_raw(self, tracked, weapon_side_a, weapon_side_b) -> tuple[np.ndarray, int]:
        if self.raw is not None:
            return self.raw, 0
        return np.zeros((len(tracked.frames), 192), dtype=np.float32), 0


class FakeFeaturePublisher(FeatureStreamPublisherPort):
    def __init__(self):
        self.published: list[tuple] = []

    async def publish(self, match_id, revision_id, features, luz, weapon_side_a, weapon_side_b) -> None:
        self.published.append((match_id, revision_id, features, luz, weapon_side_a, weapon_side_b))


class FakeVerdictSubscriber(VerdictStreamSubscriberPort):
    def __init__(self, verdict: VerdictView):
        self._verdict = verdict

    async def wait_for_verdict(self, revision_id: str, aceptar=None) -> VerdictView:
        # Igual que RedisVerdictSubscriber: el resultado lleva el revision_id
        # del stream del que se leyó y pasa por el filtro `aceptar` (SEC02).
        resultado = replace(self._verdict, revision_id=revision_id)
        if aceptar is not None and not await aceptar(resultado):
            raise SinMasEntradas(revision_id)
        return resultado


class SinMasEntradas(Exception):
    """El stream simulado se agotó sin un resultado aceptable (el real seguiría esperando)."""


class FakeSecuenciaSubscriber(VerdictStreamSubscriberPort):
    """Entrega en orden varios resultados y devuelve el primero que `aceptar` admita."""

    def __init__(self, *resultados):
        self._resultados = resultados

    async def wait_for_verdict(self, revision_id: str, aceptar=None):
        for r in self._resultados:
            r = replace(r, revision_id=revision_id)
            if aceptar is None or await aceptar(r):
                return r
        raise SinMasEntradas(revision_id)


class InlineExecutor:
    """Reemplaza ThreadPoolExecutor en tests: corre el callable inline, sin
    hilos, para que loop.run_in_executor no necesite un loop real con I/O."""

    def submit(self, fn, *args):
        import concurrent.futures
        future = concurrent.futures.Future()
        try:
            future.set_result(fn(*args))
        except Exception as e:  # pragma: no cover
            future.set_exception(e)
        return future


class FakeModelos:
    """ModeloVersionRepositoryPort mínimo: solo `obtener_activo`."""

    def __init__(self, checkpoint_uri: str | None = "/ckpt/checkpoints/run/best_model.pt"):
        from types import SimpleNamespace

        self._activo = (
            None
            if checkpoint_uri is None
            else SimpleNamespace(nombre="lstm6class-run", checkpoint_uri=checkpoint_uri)
        )

    async def obtener_activo(self):
        return self._activo
