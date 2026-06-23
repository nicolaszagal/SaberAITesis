"""LSTM4ClassAdapter — implementación de ActionClassifierPort que envuelve
el checkpoint `dataset/lstm_4class/checkpoints/best_model.pt`: 192
features, 4 clases, luz Favero como input real del modelo, attention
pooling (ver shared/lstm_classifier.py, copia literal de
dataset/lstm_4class/models/lstm_classifier.py).

No aplica la máscara hard de luz Favero — eso es ArbitrationPolicyPort
(FaveroHardMaskPolicy), una etapa posterior y explícitamente separada del
modelo (ver PLAN_ARQUITECTURA_DDD.md sección 1: "definir el puerto ahora").
"""

from __future__ import annotations

import numpy as np
import torch

from cloud.domain.models import ActionClass, CLASSES, LuzSignal, RawVerdict
from cloud.ports.action_classifier import ActionClassifierPort
from shared.lstm_classifier import LSTMClassifier


class LSTM4ClassAdapter(ActionClassifierPort):
    def __init__(self, checkpoint_path: str, device: "torch.device"):
        self._device = device
        self._model = LSTMClassifier(
            input_size=192,
            hidden_size=64,
            num_layers=1,
            num_classes=4,
            dropout=0.0,  # sin dropout en inferencia, igual que 08_evaluate.py
            luz_size=2,
            use_attention=True,
        ).to(device)
        self._model.load_state_dict(torch.load(checkpoint_path, map_location=device))
        self._model.eval()

    def classify(self, sequence: np.ndarray, luz: LuzSignal | None) -> RawVerdict:
        """sequence: (T, 192) float32, ya estandarizada/clampeada/ablada por
        FeatureExtractorPort en Fog (no se reprocesa aquí)."""
        effective_luz = luz if luz is not None else LuzSignal.none()

        x = torch.tensor(sequence, dtype=torch.float32, device=self._device).unsqueeze(0)  # (1, T, 192)
        lengths = torch.tensor([sequence.shape[0]], dtype=torch.long)
        luz_t = torch.tensor(
            [[float(effective_luz.has_luz_a), float(effective_luz.has_luz_b)]],
            dtype=torch.float32, device=self._device,
        )

        with torch.no_grad():
            logits = self._model(x, lengths, luz_t)
            probs = torch.softmax(logits, dim=1)[0].cpu().numpy()

        idx = int(probs.argmax())
        return RawVerdict(
            action_class=ActionClass(CLASSES[idx]),
            confidence=float(probs[idx]),
            probs={cls: float(p) for cls, p in zip(CLASSES, probs)},
        )
