from cloud.domain.models import ActionClass, LuzSignal, RawVerdict
from cloud.infrastructure.arbitration.null_arbitration_policy import NullArbitrationPolicy

_RAW = RawVerdict(
    action_class=ActionClass.ATTACK_B, confidence=0.7,
    probs={"AttackA": 0.1, "AttackB": 0.7, "ContrattackA": 0.05, "ContrattackB": 0.1,
           "RiposteA": 0.03, "RiposteB": 0.02},
)


def test_returns_raw_verdict_unchanged_regardless_of_luz():
    policy = NullArbitrationPolicy()

    assert policy.resolve(_RAW, None) is _RAW
    assert policy.resolve(_RAW, LuzSignal(has_luz_a=True, has_luz_b=False)) is _RAW
    assert policy.resolve(_RAW, LuzSignal(has_luz_a=True, has_luz_b=True)) is _RAW
