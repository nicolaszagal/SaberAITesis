import numpy as np
import pytest

from fog.domain.models import PersonPose, TrackedFrame, TrackedSequence, WeaponSide
from fog.infrastructure.features.new192_feature_extractor import New192FeatureExtractor
from fog.infrastructure.features.preprocessing_profile import PreprocessingProfile
from shared.feature_extractor import BIO_OFFSET, TOTAL_FEATURES

# Perfil de prueba explícito (no depende del JSON de perfiles): mismos recortes
# que lstm_6class, ablando las dos columnas vel_elbow_angle para probar la ablación.
_CLAMP_COLS = tuple(list(range(51, 85)) + list(range(147, 181)) + list(range(91, 94))
                    + list(range(187, 190)) + [95, 191])
PROFILE_ABLATE = PreprocessingProfile("test", 5.0, _CLAMP_COLS, (95, 191))
PROFILE_NO_ABLATE = PreprocessingProfile("test", 5.0, _CLAMP_COLS, ())


def _make_tracked_sequence(n_frames: int, locked: bool = True) -> TrackedSequence:
    rng = np.random.default_rng(0)
    frames = []
    for _ in range(n_frames):
        kxy = rng.uniform(50, 400, size=(17, 2)).astype(np.float32)
        conf = np.full(17, 0.9, dtype=np.float32)
        box = np.array([10, 10, 200, 400], dtype=np.float32)
        person_a = PersonPose(keypoints_xy=kxy, keypoints_conf=conf, box_xyxy=box, detected=True)
        person_b = PersonPose(keypoints_xy=kxy + 5, keypoints_conf=conf, box_xyxy=box, detected=True)
        frames.append(TrackedFrame(person_a=person_a, person_b=person_b))
    return TrackedSequence(frames=frames, frame_w=640, frame_h=480, locked=locked, lock_frame=0)


def test_rejects_mean_std_with_wrong_shape():
    with pytest.raises(ValueError):
        New192FeatureExtractor(mean=np.zeros(10), std=np.ones(10), profile=PROFILE_NO_ABLATE)


def test_extract_returns_error_when_not_locked():
    extractor = New192FeatureExtractor(
        mean=np.zeros(TOTAL_FEATURES), std=np.ones(TOTAL_FEATURES), profile=PROFILE_ABLATE
    )
    tracked = _make_tracked_sequence(5, locked=False)

    out = extractor.extract(tracked, WeaponSide.RIGHT, WeaponSide.RIGHT)

    assert out.sequence is None
    assert "tracking" in out.stats["error"]


def test_extract_returns_error_when_too_short():
    extractor = New192FeatureExtractor(
        mean=np.zeros(TOTAL_FEATURES), std=np.ones(TOTAL_FEATURES), profile=PROFILE_ABLATE
    )
    tracked = _make_tracked_sequence(2, locked=True)

    out = extractor.extract(tracked, WeaponSide.RIGHT, WeaponSide.RIGHT, min_frames=3)

    assert out.sequence is None
    assert "muy corta" in out.stats["error"]


def test_extract_produces_192_dim_sequence_with_profile_ablation():
    extractor = New192FeatureExtractor(
        mean=np.zeros(TOTAL_FEATURES), std=np.ones(TOTAL_FEATURES), profile=PROFILE_ABLATE
    )
    tracked = _make_tracked_sequence(10, locked=True)

    out = extractor.extract(tracked, WeaponSide.RIGHT, WeaponSide.RIGHT, min_frames=3)

    assert out.stats["error"] is None
    assert out.sequence.shape == (10, TOTAL_FEATURES)
    # columnas de ablación (vel_elbow_angle A/B) deben quedar en 0
    assert np.all(out.sequence[:, [95, 191]] == 0.0)


def test_extract_does_not_ablate_when_profile_has_no_ablate_indices():
    extractor = New192FeatureExtractor(
        mean=np.zeros(TOTAL_FEATURES), std=np.ones(TOTAL_FEATURES), profile=PROFILE_NO_ABLATE
    )
    tracked = _make_tracked_sequence(10, locked=True)

    out = extractor.extract(tracked, WeaponSide.RIGHT, WeaponSide.RIGHT, min_frames=3)

    # sin ablación, al menos alguna de las dos columnas debería tener valores no nulos
    # en esta secuencia sintética (el ángulo del codo varía entre frames)
    assert not np.all(out.sequence[:, [95, 191]] == 0.0)


def test_extract_clamps_velocity_slices_to_five_sigma():
    # std muy chico -> cualquier desviación cruda se dispara a un z-score enorme,
    # debe quedar clampeado a ±5 en las slices de velocidad.
    mean = np.zeros(TOTAL_FEATURES, dtype=np.float32)
    std = np.full(TOTAL_FEATURES, 1e-3, dtype=np.float32)
    extractor = New192FeatureExtractor(mean=mean, std=std, profile=PROFILE_NO_ABLATE)
    tracked = _make_tracked_sequence(10, locked=True)

    out = extractor.extract(tracked, WeaponSide.RIGHT, WeaponSide.RIGHT, min_frames=3)

    vel_a = out.sequence[:, 51:85]
    vel_b = out.sequence[:, 147:181]
    cmvel_a = out.sequence[:, 91:94]
    cmvel_b = out.sequence[:, 187:190]
    for block in (vel_a, vel_b, cmvel_a, cmvel_b):
        assert np.all(block >= -5.0) and np.all(block <= 5.0)


def test_extract_clamps_vel_elbow_angle_when_profile_clamps_it():
    """El modelo de 6 clases recorta también vel_elbow_angle (cols 95 y 191)."""
    std = np.full(TOTAL_FEATURES, 1e-3, dtype=np.float32)
    extractor = New192FeatureExtractor(
        mean=np.zeros(TOTAL_FEATURES, dtype=np.float32), std=std, profile=PROFILE_NO_ABLATE
    )
    tracked = _make_tracked_sequence(10, locked=True)

    out = extractor.extract(tracked, WeaponSide.RIGHT, WeaponSide.RIGHT, min_frames=3)

    assert np.all(np.abs(out.sequence[:, [95, 191]]) <= 5.0)
    assert np.any(np.abs(out.sequence[:, [95, 191]]) == 5.0)


def test_profile_without_elbow_clamp_leaves_vel_elbow_angle_unclamped():
    cols = tuple(c for c in _CLAMP_COLS if c not in (95, 191))
    profile = PreprocessingProfile("test", 5.0, cols, ())
    extractor = New192FeatureExtractor(
        mean=np.zeros(TOTAL_FEATURES, dtype=np.float32),
        std=np.full(TOTAL_FEATURES, 1e-3, dtype=np.float32),
        profile=profile,
    )
    tracked = _make_tracked_sequence(10, locked=True)

    out = extractor.extract(tracked, WeaponSide.RIGHT, WeaponSide.RIGHT, min_frames=3)

    assert np.any(np.abs(out.sequence[:, [95, 191]]) > 5.0)


# ── Corrección de velocidad relativa del CM (DEF-27) ─────────────────────────

def _person(dx: float = 0.0, dy: float = 0.0) -> PersonPose:
    """Persona con caderas en (200+dx, 300+dy) y bbox de altura 400."""
    kxy = np.zeros((17, 2), dtype=np.float32)
    kxy[:, 0] = 200.0
    kxy[:, 1] = 300.0
    kxy[:, 0] += dx
    kxy[:, 1] += dy
    return PersonPose(
        keypoints_xy=kxy,
        keypoints_conf=np.full(17, 0.9, dtype=np.float32),
        box_xyxy=np.array([100, 100, 300, 500], dtype=np.float32),
        detected=True,
    )


def _tracked(frames: list[tuple[PersonPose, PersonPose]]) -> TrackedSequence:
    return TrackedSequence(
        frames=[TrackedFrame(person_a=a, person_b=b) for a, b in frames],
        frame_w=640, frame_h=480, locked=True, lock_frame=0,
    )


def _raw(frames) -> np.ndarray:
    extractor = New192FeatureExtractor(
        mean=np.zeros(TOTAL_FEATURES), std=np.ones(TOTAL_FEATURES), profile=PROFILE_NO_ABLATE
    )
    raw, _ = extractor.extract_raw(_tracked(frames), WeaponSide.RIGHT, WeaponSide.RIGHT)
    return raw


def test_cm_velocity_is_half_the_difference_between_fencers():
    # A avanza 40 px en x, B retrocede 20 px: abs_A=0.1, abs_B=-0.05 (bbox_h=400)
    raw = _raw([(_person(), _person()), (_person(dx=40), _person(dx=-20))])

    a, b = raw[1, BIO_OFFSET:BIO_OFFSET + 3], raw[1, 96 + BIO_OFFSET:96 + BIO_OFFSET + 3]
    assert a[0] == pytest.approx(0.5 * (0.1 - (-0.05)), abs=1e-6)
    assert b[0] == pytest.approx(-a[0], abs=1e-6)
    assert a[2] == pytest.approx(abs(a[0]), abs=1e-6)  # body_speed = |rel_vel|


def test_cm_velocity_cancels_pure_camera_pan():
    # Paneo: ambos se desplazan igual en pixeles → velocidad relativa = 0
    raw = _raw([(_person(), _person()), (_person(dx=30, dy=10), _person(dx=30, dy=10))])

    assert np.allclose(raw[1, BIO_OFFSET:BIO_OFFSET + 3], 0.0)
    assert np.allclose(raw[1, 96 + BIO_OFFSET:96 + BIO_OFFSET + 3], 0.0)


def test_cm_velocity_is_zero_when_rival_not_detected():
    # Entrenamiento sobrescribe con 0 (incl. body_speed) si falta alguno de los dos.
    raw = _raw([(_person(), _person()), (_person(dx=40), PersonPose.empty())])

    assert np.all(raw[1, BIO_OFFSET:BIO_OFFSET + 3] == 0.0)


def test_cm_velocity_is_zero_on_first_frame_after_rival_reappears():
    # t=1: B ausente → prev_cm_b=0 en t=2 → no se corrige en t=2 (solo con ambos en t-1 y t).
    raw = _raw([
        (_person(), _person()),
        (_person(dx=10), PersonPose.empty()),
        (_person(dx=20), _person(dx=5)),
    ])

    assert np.all(raw[2, BIO_OFFSET:BIO_OFFSET + 3] == 0.0)
