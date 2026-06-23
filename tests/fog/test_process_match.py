import numpy as np

from fog.application.process_match import ProcessIncomingMatch
from fog.domain.models import ExtractedFeatures, LuzSignal, TrackedSequence, WeaponSide
from fog.infrastructure.persistence.in_memory_match_repository import InMemoryMatchRepository
from tests.fog.fakes import FakeFeatureExtractor, FakeFeaturePublisher, InlineExecutor

# Nota: ProcessIncomingMatch ya no depende de PoseEstimatorPort — pose+
# tracking corre antes (en track_consumer.py / clip_file_reader.py) y
# execute() recibe directamente la TrackedSequence ya calculada. Ver
# fog/application/process_match.py.


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
        executor=InlineExecutor(),
        min_frames=3,
    )

    await use_case.execute(
        match_id="m1",
        tracked=tracked,
        weapon_side_a=WeaponSide.RIGHT,
        weapon_side_b=WeaponSide.LEFT,
        luz=LuzSignal(has_luz_a=True, has_luz_b=False),
    )

    assert len(publisher.published) == 1
    match_id, features, luz, side_a, side_b = publisher.published[0]
    assert match_id == "m1"
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
        repository=repository, executor=InlineExecutor(),
    )

    await use_case.execute("m2", tracked, WeaponSide.RIGHT, WeaponSide.RIGHT, luz=None)

    _, _, luz, _, _ = publisher.published[0]
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
        repository=repository, executor=InlineExecutor(),
    )

    await use_case.execute("m3", tracked, WeaponSide.RIGHT, WeaponSide.RIGHT, luz=None)

    assert publisher.published == []
    assert await repository.get("m3") is None
