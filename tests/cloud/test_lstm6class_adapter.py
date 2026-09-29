"""Test del adaptador real (no de un fake): construye un run sintético
(run_config.json + checkpoint con la arquitectura desplegada,
shared/lstm_classifier.py) y verifica que LSTM6ClassAdapter lo carga y
produce un RawVerdict válido, sin depender del checkpoint real de
producción (pesado, no determinístico para un test unitario).

También cubre el filtro Favero sobre logits (equivalente a
`apply_favero_logit_mask` de dataset/lstm_6class/evaluate.py): con una
sola luz encendida, las clases del lado sin luz quedan en probabilidad
exactamente 0.
"""

import json

import numpy as np
import pytest
import torch

from cloud.domain.models import CLASSES, LuzSignal
from cloud.infrastructure.classifier.lstm6class_adapter import (
    CHECKPOINT_FILENAME, LSTM6ClassAdapter,
)
from shared.lstm_classifier import LSTMClassifier

_RUN_CONFIG = {
    "hidden_size": 64,
    "num_layers": 1,
    "dropout": 0.4,
    "luz_size": 0,
    "use_attention": True,
    "n_classes": 6,
    "classes": CLASSES,
}


def _write_synthetic_run(run_dir, run_config=None) -> None:
    run_config = run_config or _RUN_CONFIG
    with open(run_dir / "run_config.json", "w") as f:
        json.dump(run_config, f)

    model = LSTMClassifier(
        input_size=192,
        hidden_size=run_config["hidden_size"],
        num_layers=run_config["num_layers"],
        num_classes=run_config["n_classes"],
        dropout=0.0,
        luz_size=run_config["luz_size"],
        use_attention=run_config["use_attention"],
    )
    torch.save(model.state_dict(), run_dir / CHECKPOINT_FILENAME)


def test_classify_returns_valid_raw_verdict(tmp_path):
    _write_synthetic_run(tmp_path)
    adapter = LSTM6ClassAdapter(run_dir=str(tmp_path), device=torch.device("cpu"))
    sequence = np.random.default_rng(0).normal(size=(20, 192)).astype(np.float32)

    raw = adapter.classify(sequence, LuzSignal(has_luz_a=True, has_luz_b=False))

    assert raw.action_class.value in CLASSES
    assert 0.0 <= raw.confidence <= 1.0
    assert set(raw.probs.keys()) == set(CLASSES)
    assert abs(sum(raw.probs.values()) - 1.0) < 1e-5


def test_classify_defaults_to_no_luz_when_none(tmp_path):
    _write_synthetic_run(tmp_path)
    adapter = LSTM6ClassAdapter(run_dir=str(tmp_path), device=torch.device("cpu"))
    sequence = np.zeros((10, 192), dtype=np.float32)

    # no debe lanzar al recibir luz=None
    raw = adapter.classify(sequence, None)
    assert raw.action_class.value in CLASSES


def test_uses_luz_size_from_run_config(tmp_path):
    """luz_size > 0 en run_config.json: el modelo se construye con la luz
    como input real (concatenada tras el pooling), no solo como filtro."""
    run_config = dict(_RUN_CONFIG, luz_size=2)
    _write_synthetic_run(tmp_path, run_config)

    adapter = LSTM6ClassAdapter(run_dir=str(tmp_path), device=torch.device("cpu"))
    sequence = np.zeros((10, 192), dtype=np.float32)

    raw = adapter.classify(sequence, LuzSignal(has_luz_a=True, has_luz_b=False))
    assert raw.action_class.value in CLASSES


def test_favero_mask_zeroes_out_side_without_light(tmp_path):
    _write_synthetic_run(tmp_path)
    adapter = LSTM6ClassAdapter(run_dir=str(tmp_path), device=torch.device("cpu"))
    sequence = np.random.default_rng(1).normal(size=(15, 192)).astype(np.float32)

    raw = adapter.classify(sequence, LuzSignal(has_luz_a=True, has_luz_b=False))

    b_side = [c for c in CLASSES if c.endswith("B")]
    a_side = [c for c in CLASSES if c.endswith("A")]
    assert all(raw.probs[c] == 0.0 for c in b_side)
    assert sum(raw.probs[c] for c in a_side) == pytest.approx(1.0, abs=1e-6)
    assert raw.action_class.value in a_side


def test_favero_mask_no_op_when_both_lights_fired(tmp_path):
    _write_synthetic_run(tmp_path)
    adapter = LSTM6ClassAdapter(run_dir=str(tmp_path), device=torch.device("cpu"))
    sequence = np.random.default_rng(2).normal(size=(15, 192)).astype(np.float32)

    raw = adapter.classify(sequence, LuzSignal(has_luz_a=True, has_luz_b=True))

    assert all(p > 0.0 for p in raw.probs.values())


def test_rejects_run_config_with_mismatched_classes(tmp_path):
    run_config = dict(_RUN_CONFIG, classes=["AttackA", "AttackB"], n_classes=2)
    _write_synthetic_run(tmp_path, run_config)

    with pytest.raises(ValueError, match="clases"):
        LSTM6ClassAdapter(run_dir=str(tmp_path), device=torch.device("cpu"))


def test_model_version_name_derives_from_run_dir():
    name = LSTM6ClassAdapter.model_version_name("/data/dataset/lstm_6class/checkpoints/20260928_141021")
    assert name == "lstm_6class/20260928_141021/best_model.pt"
