import numpy as np

from cloud.application.classify_and_publish import ClassifyAndPublish
from cloud.domain.models import ActionClass, FeatureSequence, LuzSignal, RawVerdict
from tests.cloud.fakes import (
    FakeActionClassifier, FakeFeatureConsumer, FakeVerdictPublisher, IdentityArbitrationPolicy,
)


async def test_run_forever_classifies_publishes_and_acks_each_entry():
    luz = LuzSignal.none()
    seq = FeatureSequence(
        match_id="m1", sequence=np.zeros((5, 192), dtype=np.float32),
        luz=luz, weapon_side_a="right", weapon_side_b="right",
    )
    consumer = FakeFeatureConsumer(items=[("0-1", seq)])
    classifier = FakeActionClassifier(
        result=RawVerdict(action_class=ActionClass.ATTACK_A, confidence=0.8, probs={
            "AttackA": 0.8, "AttackB": 0.1, "ResponseA": 0.05, "ResponseB": 0.05,
        })
    )
    publisher = FakeVerdictPublisher()

    use_case = ClassifyAndPublish(
        consumer=consumer, classifier=classifier,
        arbitration=IdentityArbitrationPolicy(), publisher=publisher,
    )

    await use_case.run_forever()

    assert len(publisher.published) == 1
    verdict = publisher.published[0]
    assert verdict.match_id == "m1"
    assert verdict.action_class is ActionClass.ATTACK_A
    assert verdict.fencer == "ROJ"  # side "A" -> ROJ, ver shared.config.FENCER_COLOR
    assert consumer.acked == ["0-1"]


async def test_run_forever_resolves_fencer_color_for_side_b():
    seq = FeatureSequence(
        match_id="m2", sequence=np.zeros((5, 192), dtype=np.float32),
        luz=LuzSignal.none(), weapon_side_a="right", weapon_side_b="left",
    )
    consumer = FakeFeatureConsumer(items=[("0-1", seq)])
    classifier = FakeActionClassifier(
        result=RawVerdict(action_class=ActionClass.RESPONSE_B, confidence=0.6, probs={})
    )
    publisher = FakeVerdictPublisher()

    use_case = ClassifyAndPublish(
        consumer=consumer, classifier=classifier,
        arbitration=IdentityArbitrationPolicy(), publisher=publisher,
    )
    await use_case.run_forever()

    assert publisher.published[0].fencer == "VER"  # side "B" -> VER
