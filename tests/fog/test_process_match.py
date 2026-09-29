import numpy as np

from fog.application.process_match import ProcessIncomingMatch
from fog.domain.models import ExtractedFeatures, LuzSignal, MotivoNoDisponible, TrackedSequence, WeaponSide
from fog.infrastructure.persistence.in_memory_match_repository import InMemoryMatchRepository
from fog.infrastructure.webrtc.session_registry import SessionRegistry
from tests.fog.fakes import FakeFeatureExtractor, FakeFeaturePublisher, InlineExecutor

# Nota: ProcessIncomingMatch ya no depende de PoseEstimatorPort — pose+
# tracking corre antes (en track_consumer.py / clip_file_reader.py) y
# execute() recibe directamente la TrackedSequence ya calculada. Ver
# fog/application/process_match.py.


class FakeWebSocket:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


async def test_execute_publishes_and_saves_match_on_success():
    tracked = TrackedSequence(frames=[], frame_w=640, frame_h=480, locked=True)
    extractor = FakeFeatureExtractor(
        result=ExtractedFeatures(sequence=np.zeros((5, 192), dtype=np.float32), stats={"error": None})
    )
    publisher = FakeFeaturePublisher()
    repository = InMemoryMatchRepository()

    use_case = ProcessIncomingMatch(
        feature_extractor=extractor,
        publisher=publisher,
        repository=repository,
        sessions=SessionRegistry(),
        executor=InlineExecutor(),
        min_frames=3,
    )

    result = await use_case.execute(
        match_id="m1",
        revision_id="r1",
        tracked=tracked,
        weapon_side_a=WeaponSide.RIGHT,
        weapon_side_b=WeaponSide.LEFT,
        luz=LuzSignal(has_luz_a=True, has_luz_b=False),
    )

    assert result is None
    assert len(publisher.published) == 1
    match_id, revision_id, features, luz, side_a, side_b = publisher.published[0]
    assert (match_id, revision_id) == ("m1", "r1")
    assert luz.has_luz_a is True and luz.has_luz_b is False
    assert side_a is WeaponSide.RIGHT and side_b is WeaponSide.LEFT

    saved = await repository.get("m1")
    assert saved is not None
    assert saved.match_id == "m1"


async def test_execute_defaults_to_no_luz_when_none():
    tracked = TrackedSequence(frames=[], frame_w=0, frame_h=0, locked=True)
    extractor = FakeFeatureExtractor()
    publisher = FakeFeaturePublisher()
    repository = InMemoryMatchRepository()

    use_case = ProcessIncomingMatch(
        feature_extractor=extractor, publisher=publisher,
        repository=repository, sessions=SessionRegistry(), executor=InlineExecutor(),
    )

    await use_case.execute("m2", "r2", tracked, WeaponSide.RIGHT, WeaponSide.RIGHT, luz=None)

    _, _, _, luz, _, _ = publisher.published[0]
    assert luz == LuzSignal.none()


async def test_execute_does_not_publish_when_extraction_fails():
    tracked = TrackedSequence(frames=[], frame_w=0, frame_h=0, locked=True)
    extractor = FakeFeatureExtractor(
        result=ExtractedFeatures(sequence=None, stats={"error": "secuencia muy corta"})
    )
    publisher = FakeFeaturePublisher()
    repository = InMemoryMatchRepository()

    use_case = ProcessIncomingMatch(
        feature_extractor=extractor, publisher=publisher,
        repository=repository, sessions=SessionRegistry(), executor=InlineExecutor(),
    )

    result = await use_case.execute("m3", "r3", tracked, WeaponSide.RIGHT, WeaponSide.RIGHT, luz=None)

    assert publisher.published == []
    assert await repository.get("m3") is None
    assert result is not None
    assert (result.match_id, result.revision_id) == ("m3", "r3")
    assert result.motivo is MotivoNoDisponible.POSE_INCOMPLETA


async def test_execute_sets_unavailable_on_session_and_sends_ws_when_connected():
    """DEF-08: si el extractor falla (sin lock A/B o secuencia corta), la
    sesión debe quedar marcada como no disponible y, si el front ya está
    conectado por WebSocket, recibir el mensaje de inmediato — sin
    esperar los 30 s del timeout de Cloud."""
    tracked = TrackedSequence(frames=[], frame_w=0, frame_h=0, locked=False)
    extractor = FakeFeatureExtractor(
        result=ExtractedFeatures(sequence=None, stats={"error": "tracking no pudo asignar IDs A/B"})
    )
    publisher = FakeFeaturePublisher()
    repository = InMemoryMatchRepository()
    sessions = SessionRegistry()
    session = sessions.create("m4", "r4", WeaponSide.RIGHT, WeaponSide.RIGHT)
    session.ws = FakeWebSocket()

    use_case = ProcessIncomingMatch(
        feature_extractor=extractor, publisher=publisher,
        repository=repository, sessions=sessions, executor=InlineExecutor(),
    )

    result = await use_case.execute("m4", "r4", tracked, WeaponSide.RIGHT, WeaponSide.RIGHT, luz=None)

    assert result.motivo is MotivoNoDisponible.POSE_INCOMPLETA
    assert session.unavailable == result
    assert session.unavailable_event.is_set()
    assert session.ws.sent == [
        {"type": "no_disponible", "match_id": "m4", "revision_id": "r4", "motivo": "pose_incompleta"}
    ]
    # DEF-16: tras entregar el "no disponible", la sesión queda marcada
    # como cerrada para que SessionRegistry.sweep_expired la libere pasado
    # SESSION_TTL_S.
    assert session.closed_at is not None


async def test_execute_unavailable_no_op_when_session_missing():
    tracked = TrackedSequence(frames=[], frame_w=0, frame_h=0, locked=False)
    extractor = FakeFeatureExtractor(
        result=ExtractedFeatures(sequence=None, stats={"error": "tracking no pudo asignar IDs A/B"})
    )
    use_case = ProcessIncomingMatch(
        feature_extractor=extractor, publisher=FakeFeaturePublisher(),
        repository=InMemoryMatchRepository(), sessions=SessionRegistry(), executor=InlineExecutor(),
    )

    result = await use_case.execute("m404", "r404", tracked, WeaponSide.RIGHT, WeaponSide.RIGHT, luz=None)

    assert result.motivo is MotivoNoDisponible.POSE_INCOMPLETA
