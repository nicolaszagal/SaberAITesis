"""ActionClassifierPort — clasificación de la acción a partir de las
features extraídas por Fog.

Implementación de referencia: infrastructure/classifier/lstm4class_adapter.py
(BiLSTM 192 features/4 clases/luz Favero como input real del modelo, ver
shared/lstm_classifier.py). Migrar a otra arquitectura de modelo (otro
tamaño de hidden, transformer, etc.) es escribir un nuevo adaptador.
"""

from abc import ABC, abstractmethod

from cloud.domain.models import LuzSignal, RawVerdict
import numpy as np


class ActionClassifierPort(ABC):
    @abstractmethod
    def classify(self, sequence: np.ndarray, luz: LuzSignal | None) -> RawVerdict:
        """
        Args:
            sequence: (T, 192) float32, ya estandarizada por Fog.
            luz: señal de luz Favero del clip, o None si no llegó. El
                 modelo subyacente puede usar `luz` como input real
                 (concatenado al pooled LSTM) — no es solo un filtro
                 posterior, eso lo hace ArbitrationPolicyPort.
        """
        raise NotImplementedError
