import json

import numpy as np
import pytest

from fog.infrastructure.features.preprocessing_profile import (
    PreprocessingProfile,
    clamp_and_ablate,
    load_profile,
)


def test_bundled_lstm_6class_profile_matches_training_dataset():
    """Valores de dataset/lstm_6class/dataset.py: ±5σ en vel. articular, cm_vel/
    body_speed y vel_elbow_angle (95, 191); sin ablación."""
    profile = load_profile("lstm_6class")

    expected = set(range(51, 85)) | set(range(147, 181)) | set(range(91, 94)) \
        | set(range(187, 190)) | {95, 191}
    assert set(profile.clamp_indices) == expected
    assert profile.clamp_sigma == 5.0
    assert profile.ablate_indices == ()


def test_unknown_profile_lists_available(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"a": {"clamp_sigma": 5, "clamp_columns": [], "ablate_indices": []}}))

    with pytest.raises(ValueError, match="'b'.*\\['a'\\]"):
        load_profile("b", path)


def test_profile_can_be_defined_in_custom_file(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"otro": {"clamp_sigma": 3, "clamp_columns": [[0, 2]], "ablate_indices": [7]}}))

    profile = load_profile("otro", path)

    assert profile.clamp_indices == (0, 1)
    assert profile.clamp_sigma == 3.0
    assert profile.ablate_indices == (7,)


@pytest.mark.parametrize("data", [
    {"clamp_sigma": 5, "clamp_columns": []},                                       # falta ablate_indices
    {"clamp_sigma": 0, "clamp_columns": [], "ablate_indices": []},                 # sigma <= 0
    {"clamp_sigma": 5, "clamp_columns": [[10, 10]], "ablate_indices": []},         # rango vacío
    {"clamp_sigma": 5, "clamp_columns": [[190, 193]], "ablate_indices": []},       # fuera de 192
    {"clamp_sigma": 5, "clamp_columns": [], "ablate_indices": [192]},              # ablate fuera
])
def test_invalid_profiles_are_rejected(data):
    with pytest.raises(ValueError):
        PreprocessingProfile.from_dict("x", data)


def test_clamp_and_ablate_only_touch_declared_columns():
    profile = PreprocessingProfile("t", 5.0, (0, 1), (2,))
    x = np.full((3, 192), 9.0, dtype=np.float32)

    clamp_and_ablate(x, profile)

    assert np.all(x[:, :2] == 5.0)
    assert np.all(x[:, 2] == 0.0)
    assert np.all(x[:, 3:] == 9.0)
