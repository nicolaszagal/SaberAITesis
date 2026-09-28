import numpy as np

from cloud.application.classify_and_publish import ClassifyAndPublish
from cloud.domain.models import (
    ActionClass, FeatureSequence, InvalidFeatureMessage, LuzSignal,
    MotivoNoDisponible, RawVerdict,
)
from shared import config
from tests.cloud.fakes import (
    FakeActionClassifier, FakeFeatureConsumer, FakeVerdictPublisher,
    IdentityArbitrationPolicy,
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
    assert verdict.disponible is True
    assert verdict.match_id == "m1"
    assert verdict.action_class is ActionClass.ATTACK_A
    assert verdict.fencer == "ROJ"  # side "A" -> ROJ, ver shared.config.FENCER_COLOR
    assert consumer.acked == ["0-1"]
    # DEF-09: datos de auditoría agregados al veredicto
    assert verdict.probs == {
        "AttackA": 0.8, "AttackB": 0.1, "ResponseA": 0.05, "ResponseB": 0.05,
    }
    assert isinstance(verdict.latencia_inferencia_ms, int)
    assert verdict.latencia_inferencia_ms >= 0
    assert verdict.modelo == config.MODEL_VERSION_NAME


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


async def test_run_forever_publishes_unavailable_verdict_for_invalid_message():
    """DEF-09: una entrada que el consumer no pudo parsear (ya movida a
    dead-letter y ACKeada por el adaptador) se traduce en un veredicto
    disponible=false, sin llamar al clasificador ni volver a acked()."""
    invalid = InvalidFeatureMessage(
        match_id="m3", motivo=MotivoNoDisponible.MENSAJE_INVALIDO,
        detalle="shape inesperado: (5, 10)",
    )
    consumer = FakeFeatureConsumer(items=[("0-1", invalid)])
    classifier = FakeActionClassifier()
    publisher = FakeVerdictPublisher()

    use_case = ClassifyAndPublish(
        consumer=consumer, classifier=classifier,
        arbitration=IdentityArbitrationPolicy(), publisher=publisher,
    )
    await use_case.run_forever()

    assert classifier.calls == []
    assert consumer.acked == []  # ya fue ACKeada por el consumer al mover a dead-letter
    assert len(publisher.published) == 1
    verdict = publisher.published[0]
    assert verdict.disponible is False
    assert verdict.match_id == "m3"
    assert verdict.motivo_no_disp == "mensaje_invalido"
    assert verdict.action_class is None


async def test_run_forever_skips_verdict_when_invalid_message_has_no_match_id():
    invalid = InvalidFeatureMessage(
        match_id=None, motivo=MotivoNoDisponible.MENSAJE_INVALIDO,
        detalle="sin match_id",
    )
    consumer = FakeFeatureConsumer(items=[("0-1", invalid)])
    publisher = FakeVerdictPublisher()
    use_case = ClassifyAndPublish(
        consumer=consumer, classifier=FakeActionClassifier(),
        arbitration=IdentityArbitrationPolicy(), publisher=publisher,
    )
    await use_case.run_forever()

    assert publisher.published == []


async def test_run_forever_continues_after_exception_processing_one_entry():
    """DEF-09: una falla procesando una entrada (acá, el clasificador)
    nunca detiene el loop — el siguiente mensaje válido se procesa."""

    class FlakyClassifier:
        def __init__(self, ok_result: RawVerdict):
            self.calls = 0
            self._ok_result = ok_result

        def classify(self, sequence, luz):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("modelo corrupto")
            return self._ok_result

    seq_bad = FeatureSequence(
        match_id="bad", sequence=np.zeros((5, 192), dtype=np.float32),
        luz=LuzSignal.none(), weapon_side_a="right", weapon_side_b="right",
    )
    seq_ok = FeatureSequence(
        match_id="ok", sequence=np.zeros((5, 192), dtype=np.float32),
        luz=LuzSignal.none(), weapon_side_a="right", weapon_side_b="right",
    )
    consumer = FakeFeatureConsumer(items=[("0-1", seq_bad), ("0-2", seq_ok)])
    classifier = FlakyClassifier(ok_result=RawVerdict(
        action_class=ActionClass.ATTACK_A, confidence=0.9,
        probs={"AttackA": 0.9, "AttackB": 0.05, "ResponseA": 0.03, "ResponseB": 0.02},
    ))
    publisher = FakeVerdictPublisher()

    use_case = ClassifyAndPublish(
        consumer=consumer, classifier=classifier,
        arbitration=IdentityArbitrationPolicy(), publisher=publisher,
    )
    await use_case.run_forever()

    assert classifier.calls == 2  # ambas entradas se intentaron procesar
    assert consumer.acked == ["0-2"]  # solo la segunda (exitosa) se ackea
    assert len(publisher.published) == 1
    assert publisher.published[0].match_id == "ok"
