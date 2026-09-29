"""LSTM6ClassAdapter — implementación de ActionClassifierPort que envuelve
el checkpoint desplegado en `dataset/lstm_6class/checkpoints/<run_id>/`
(ver docs_claude/contexto_sabre.md sección 8): BiLSTM + atención, 6 clases
(AttackA/B, ContrattackA/B, RiposteA/B, D-06), 192 features. Arquitectura
en shared/lstm_classifier.py (copia literal de dataset/lstm_6class/model.py).

Todos los hiperparámetros (hidden_size, num_layers, dropout, luz_size,
use_attention, n_classes) se leen de `run_config.json` dentro de
`MODEL_RUN_DIR` — nada queda fijo en este archivo, porque el checkpoint
activo puede cambiar tras un diagnóstico en curso (contexto_sabre.md
sección 8).

Filtro Favero sobre los logits, antes del softmax — equivalente a
`apply_favero_logit_mask` de dataset/lstm_6class/evaluate.py: el lado del
tirador sin luz queda en -inf (softmax lo deja en probabilidad exactamente
0). A diferencia del pipeline de 4 clases, este filtro vive acá adentro y
no en un ArbitrationPolicyPort separado, para reproducir bit a bit
`pred_sistema` de evaluate.py (la métrica reportada para RNF-03). Por eso
la política de arbitraje activa para este adaptador es
NullArbitrationPolicy — el puerto sigue existiendo para una futura
implementación de las reglas de prioridad FIE (t.101-t.106).
"""

from __future__ import annotations

import json
import os

import numpy as np
import torch

from cloud.domain.models import ActionClass, CLASSES, LuzSignal, RawVerdict
from cloud.ports.action_classifier import ActionClassifierPort
from shared.lstm_classifier import LSTMClassifier

RUN_CONFIG_FILENAME = "run_config.json"

# Archivo elegido para desplegar dentro de cada run (criterio de validación,
# no de test — ver "Checkpoint desplegado" en contexto_sabre.md sección 8).
# No es un valor "del run" (no cambia si cambia MODEL_RUN_DIR): es la
# convención de nombres que usa dataset/lstm_6class/train.py para todas
# las corridas (best_model.pt / best_acc_model.pt / last_model.pt).
CHECKPOINT_FILENAME = "best_model.pt"


class LSTM6ClassAdapter(ActionClassifierPort):
    def __init__(self, run_dir: str, device: "torch.device"):
        self._device = device

        with open(os.path.join(run_dir, RUN_CONFIG_FILENAME)) as f:
            run_config = json.load(f)

        if run_config["classes"] != CLASSES:
            raise ValueError(
                f"run_config.json de '{run_dir}' declara clases "
                f"{run_config['classes']}, distintas de cloud.domain.models.CLASSES "
                f"{CLASSES}. El checkpoint no corresponde a este dominio."
            )

        self._model = LSTMClassifier(
            input_size=192,
            hidden_size=run_config["hidden_size"],
            num_layers=run_config["num_layers"],
            num_classes=run_config["n_classes"],
            dropout=0.0,  # sin dropout en inferencia, igual que evaluate.py
            luz_size=run_config["luz_size"],
            use_attention=run_config["use_attention"],
        ).to(device)
        checkpoint_path = os.path.join(run_dir, CHECKPOINT_FILENAME)
        self._model.load_state_dict(torch.load(checkpoint_path, map_location=device))
        self._model.eval()

    @staticmethod
    def model_version_name(run_dir: str) -> str:
        """Nombre de versión publicado en cada veredicto (RF-22, DEF-09):
        `lstm_6class/<run_id>/<archivo>`. Se deriva de `MODEL_RUN_DIR` en
        vez de fijarse por variable de entorno separada, para que no pueda
        quedar desincronizado del checkpoint realmente cargado."""
        run_id = os.path.basename(os.path.normpath(run_dir))
        return f"lstm_6class/{run_id}/{CHECKPOINT_FILENAME}"

    def classify(self, sequence: np.ndarray, luz: LuzSignal | None) -> RawVerdict:
        """sequence: (T, 192) float32, ya estandarizada/recortada por
        FeatureExtractorPort en Fog (perfil `lstm_6class`, no se reprocesa acá)."""
        effective_luz = luz if luz is not None else LuzSignal.none()

        # x: (1, T, 192)
        x = torch.tensor(sequence, dtype=torch.float32, device=self._device).unsqueeze(0)
        lengths = torch.tensor([sequence.shape[0]], dtype=torch.long)
        luz_t = torch.tensor(
            [[float(effective_luz.has_luz_a), float(effective_luz.has_luz_b)]],
            dtype=torch.float32, device=self._device,
        )

        with torch.no_grad():
            logits = self._model(x, lengths, luz_t)
            logits = _apply_favero_logit_mask(logits, effective_luz)
            probs = torch.softmax(logits, dim=1)[0].cpu().numpy()

        idx = int(probs.argmax())
        return RawVerdict(
            action_class=ActionClass(CLASSES[idx]),
            confidence=float(probs[idx]),
            probs={cls: float(p) for cls, p in zip(CLASSES, probs)},
        )


def _apply_favero_logit_mask(logits: torch.Tensor, luz: LuzSignal) -> torch.Tensor:
    """Equivalente a `apply_favero_logit_mask` de dataset/lstm_6class/evaluate.py.

    Semántica de la luz (docs_claude/contexto_sabre.md sección 2): con
    exactamente una luz encendida, las clases del tirador sin luz son
    imposibles y quedan en -inf antes del softmax (probabilidad exacta 0).
    Con ambas luces o ninguna, la señal es ambigua y no desempata (D-06):
    logits sin cambios. El lado de cada clase se deriva de su sufijo
    ("...A"/"...B"), no de una posición fija en la lista.
    """
    if luz.has_luz_a and not luz.has_luz_b:
        side_sin_luz = "B"
    elif luz.has_luz_b and not luz.has_luz_a:
        side_sin_luz = "A"
    else:
        return logits

    masked = logits.clone()
    for i, cls in enumerate(CLASSES):
        if cls.endswith(side_sin_luz):
            masked[:, i] = float("-inf")
    return masked
