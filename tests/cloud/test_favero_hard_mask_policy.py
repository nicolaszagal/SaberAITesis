from cloud.domain.models import ActionClass, LuzSignal, RawVerdict
from cloud.infrastructure.arbitration.favero_hard_mask_policy import FaveroHardMaskPolicy

_RAW = RawVerdict(
    action_class=ActionClass.ATTACK_B, confidence=0.7,
    probs={"AttackA": 0.1, "AttackB": 0.7, "ResponseA": 0.05, "ResponseB": 0.15},
)


def test_no_change_when_luz_is_none():
    policy = FaveroHardMaskPolicy()
    resolved = policy.resolve(_RAW, None)
    assert resolved is _RAW


def test_no_change_when_both_lights_fired_ambiguous():
    policy = FaveroHardMaskPolicy()
    resolved = policy.resolve(_RAW, LuzSignal(has_luz_a=True, has_luz_b=True))
    assert resolved is _RAW


def test_no_change_when_neither_light_fired_ambiguous():
    policy = FaveroHardMaskPolicy()
    resolved = policy.resolve(_RAW, LuzSignal(has_luz_a=False, has_luz_b=False))
    assert resolved is _RAW


def test_masks_out_side_b_when_only_a_fired():
    policy = FaveroHardMaskPolicy()
    resolved = policy.resolve(_RAW, LuzSignal(has_luz_a=True, has_luz_b=False))

    assert resolved.action_class is ActionClass.ATTACK_A
    assert resolved.probs["AttackB"] == 0.0
    assert resolved.probs["ResponseB"] == 0.0
    assert abs(sum(resolved.probs.values()) - 1.0) < 1e-6


def test_masks_out_side_a_when_only_b_fired():
    policy = FaveroHardMaskPolicy()
    resolved = policy.resolve(_RAW, LuzSignal(has_luz_a=False, has_luz_b=True))

    assert resolved.action_class is ActionClass.ATTACK_B
    assert resolved.probs["AttackA"] == 0.0
    assert resolved.probs["ResponseA"] == 0.0
    assert abs(sum(resolved.probs.values()) - 1.0) < 1e-6


def test_fallback_to_raw_when_masked_probs_all_zero():
    raw = RawVerdict(
        action_class=ActionClass.ATTACK_B, confidence=0.99,
        probs={"AttackA": 0.0, "AttackB": 0.99, "ResponseA": 0.0, "ResponseB": 0.01},
    )
    policy = FaveroHardMaskPolicy()
    # solo B tiene mass, pero la luz solo permite el lado A -> mask*probs = todo 0
    resolved = policy.resolve(raw, LuzSignal(has_luz_a=True, has_luz_b=False))
    assert resolved is raw
