import numpy as np
import pytest

from fog.domain.models import PersonPose, TrackedFrame, TrackedSequence, WeaponSide
from fog.infrastructure.features.new192_feature_extractor import New192FeatureExtractor
from shared.feature_extractor import TOTAL_FEATURES


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
        New192FeatureExtractor(mean=np.zeros(10), std=np.ones(10))


def test_extract_returns_error_when_not_locked():
    extractor = New192FeatureExtractor(mean=np.zeros(TOTAL_FEATURES), std=np.ones(TOTAL_FEATURES))
    tracked = _make_tracked_sequence(5, locked=False)

    out = extractor.extract(tracked, WeaponSide.RIGHT, WeaponSide.RIGHT)

    assert out.sequence is None
    assert "tracking" in out.stats["error"]


def test_extract_returns_error_when_too_short():
    extractor = New192FeatureExtractor(mean=np.zeros(TOTAL_FEATURES), std=np.ones(TOTAL_FEATURES))
    tracked = _make_tracked_sequence(2, locked=True)

    out = extractor.extract(tracked, WeaponSide.RIGHT, WeaponSide.RIGHT, min_frames=3)

    assert out.sequence is None
    assert "muy corta" in out.stats["error"]


def test_extract_produces_192_dim_sequence_with_default_ablation():
    extractor = New192FeatureExtractor(mean=np.zeros(TOTAL_FEATURES), std=np.ones(TOTAL_FEATURES))
    tracked = _make_tracked_sequence(10, locked=True)

    out = extractor.extract(tracked, WeaponSide.RIGHT, WeaponSide.RIGHT, min_frames=3)

    assert out.stats["error"] is None
    assert out.sequence.shape == (10, TOTAL_FEATURES)
    # columnas de ablación (vel_elbow_angle A/B) deben quedar en 0
    assert np.all(out.sequence[:, [95, 191]] == 0.0)


def test_extract_disables_ablation_when_indices_empty():
    extractor = New192FeatureExtractor(
        mean=np.zeros(TOTAL_FEATURES), std=np.ones(TOTAL_FEATURES), ablate_indices=[]
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
    extractor = New192FeatureExtractor(mean=mean, std=std)
    tracked = _make_tracked_sequence(10, locked=True)

    out = extractor.extract(tracked, WeaponSide.RIGHT, WeaponSide.RIGHT, min_frames=3)

    vel_a = out.sequence[:, 51:85]
    vel_b = out.sequence[:, 147:181]
    cmvel_a = out.sequence[:, 91:94]
    cmvel_b = out.sequence[:, 187:190]
    for block in (vel_a, vel_b, cmvel_a, cmvel_b):
        assert np.all(block >= -5.0) and np.all(block <= 5.0)
