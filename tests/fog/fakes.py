"""Fakes de los puertos de Fog, para tests unitarios de application/ sin
tocar ultralytics, redis ni aiortc."""

from __future__ import annotations

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
    def __init__(self, result: ExtractedFeatures | None = None):
        self.result = result or ExtractedFeatures(
            sequence=np.zeros((5, 192), dtype=np.float32), stats={"error": None}
        )
        self.calls: list[tuple] = []

    def extract(self, tracked, weapon_side_a, weapon_side_b, min_frames=3) -> ExtractedFeatures:
        self.calls.append((tracked, weapon_side_a, weapon_side_b, min_frames))
        return self.result


class FakeFeaturePublisher(FeatureStreamPublisherPort):
    def __init__(self):
        self.published: list[tuple] = []

    async def publish(self, match_id, features, luz, weapon_side_a, weapon_side_b) -> None:
        self.published.append((match_id, features, luz, weapon_side_a, weapon_side_b))


class FakeVerdictSubscriber(VerdictStreamSubscriberPort):
    def __init__(self, verdict: VerdictView):
        self._verdict = verdict

    async def wait_for_verdict(self, match_id: str) -> VerdictView:
        return self._verdict


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
