"""NullArbitrationPolicy — implementación de ArbitrationPolicyPort para el
pipeline de 6 clases: no modifica el veredicto crudo.

El filtro de luz Favero ya se aplicó sobre los logits dentro de
LSTM6ClassAdapter (antes del softmax, equivalente a `apply_favero_logit_mask`
de dataset/lstm_6class/evaluate.py) para reproducir bit a bit `pred_sistema`,
la métrica reportada para RNF-03. Este archivo deja el puerto ocupado sin
volver a tocar el veredicto — reemplaza a FaveroHardMaskPolicy (pipeline de
4 clases, donde el filtro sí vivía acá). Las reglas de prioridad FIE
(t.101-t.106) son la próxima implementación real de este mismo puerto.
"""

from __future__ import annotations

from cloud.domain.models import LuzSignal, RawVerdict
from cloud.ports.arbitration_policy import ArbitrationPolicyPort


class NullArbitrationPolicy(ArbitrationPolicyPort):
    def resolve(self, raw: RawVerdict, luz: LuzSignal | None) -> RawVerdict:
        return raw
