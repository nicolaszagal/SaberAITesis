"""FaveroHardMaskPolicy — implementación de ArbitrationPolicyPort. Copia
literal de la lógica `apply_favero_mask` de
dataset/lstm_4class/08_evaluate.py (verificado por lectura directa):
cuando se encendió exactamente una luz Favero, anula las probabilidades
del lado imposible y re-normaliza/re-argmax; si se encendieron ambas o
ninguna, la señal es ambigua y no se toca el veredicto.

Implementación inicial del puerto (ver PLAN_ARQUITECTURA_DDD.md sección 1)
— las reglas de prioridad FIE (t.101-t.106) son una implementación futura
de este mismo puerto, no de este archivo.
"""

from __future__ import annotations

import numpy as np

from cloud.domain.models import ActionClass, CLASSES, LuzSignal, RawVerdict
from cloud.ports.arbitration_policy import ArbitrationPolicyPort

# Índices: 0=AttackA, 1=AttackB, 2=ResponseA, 3=ResponseB (igual orden que CLASSES)
_MASK_ONLY_A = np.array([1, 0, 1, 0], dtype=np.float32)  # B imposible
_MASK_ONLY_B = np.array([0, 1, 0, 1], dtype=np.float32)  # A imposible


class FaveroHardMaskPolicy(ArbitrationPolicyPort):
    def resolve(self, raw: RawVerdict, luz: LuzSignal | None) -> RawVerdict:
        if luz is None:
            return raw

        has_a, has_b = luz.has_luz_a, luz.has_luz_b
        if has_a and not has_b:
            mask = _MASK_ONLY_A
        elif has_b and not has_a:
            mask = _MASK_ONLY_B
        else:
            return raw  # ambas o ninguna: ambiguo, sin cambio

        probs = np.array([raw.probs[c] for c in CLASSES], dtype=np.float32)
        masked = probs * mask
        s = masked.sum()
        if s <= 0:
            return raw  # fallback si todas las probabilidades válidas son 0

        masked = masked / s
        idx = int(masked.argmax())
        return RawVerdict(
            action_class=ActionClass(CLASSES[idx]),
            confidence=float(masked[idx]),
            probs={cls: float(p) for cls, p in zip(CLASSES, masked)},
        )
