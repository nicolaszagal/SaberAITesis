"""Test del adaptador real (no de un fake): construye un checkpoint
sintético con la arquitectura desplegada (shared/lstm_classifier.py) y
verifica que LSTM4ClassAdapter lo carga y produce un RawVerdict válido.
No usa el checkpoint real de producción (pesado, no determinístico para
un test unitario) — solo valida el contrato de carga + forward + softmax.
"""

import numpy as np
import torch

from cloud.domain.models import CLASSES, LuzSignal
from cloud.infrastructure.classifier.lstm4class_adapter import LSTM4ClassAdapter
from shared.lstm_classifier import LSTMClassifier


def _write_synthetic_checkpoint(path) -> None:
    model = LSTMClassifier(
        input_size=192, hidden_size=64, num_layers=1, num_classes=4,
        dropout=0.0, luz_size=2, use_attention=True,
    )
    torch.save(model.state_dict(), path)


def test_classify_returns_valid_raw_verdict(tmp_path):
    ckpt_path = tmp_path / "synthetic.pt"
    _write_synthetic_checkpoint(ckpt_path)

    adapter = LSTM4ClassAdapter(checkpoint_path=str(ckpt_path), device=torch.device("cpu"))
    sequence = np.random.default_rng(0).normal(size=(20, 192)).astype(np.float32)

    raw = adapter.classify(sequence, LuzSignal(has_luz_a=True, has_luz_b=False))

    assert raw.action_class.value in CLASSES
    assert 0.0 <= raw.confidence <= 1.0
    assert set(raw.probs.keys()) == set(CLASSES)
    assert abs(sum(raw.probs.values()) - 1.0) < 1e-5


def test_classify_defaults_to_no_luz_when_none(tmp_path):
    ckpt_path = tmp_path / "synthetic.pt"
    _write_synthetic_checkpoint(ckpt_path)

    adapter = LSTM4ClassAdapter(checkpoint_path=str(ckpt_path), device=torch.device("cpu"))
    sequence = np.zeros((10, 192), dtype=np.float32)

    # no debe lanzar al recibir luz=None
    raw = adapter.classify(sequence, None)
    assert raw.action_class.value in CLASSES
