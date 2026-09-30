"""ActionClassifierPort — clasificación de la acción a partir de las
features extraídas por Fog.

Implementación de referencia: infrastructure/classifier/lstm6class_adapter.py
(BiLSTM 192 features/6 clases, luz Favero opcional como input real del
modelo según `luz_size` de run_config.json, ver shared/lstm_classifier.py).
Migrar a otra arquitectura de modelo (otro tamaño de hidden, transformer,
etc.) es escribir un nuevo adaptador.
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
                 (concatenado al pooled LSTM, si `luz_size > 0`) y además
                 como filtro hard sobre los logits antes del softmax (ver
                 LSTM6ClassAdapter) — ambos usos viven en el adaptador, no
                 en ArbitrationPolicyPort.
        """
        raise NotImplementedError

    @abstractmethod
    def precalentar(self) -> None:
        """Ejecuta una inferencia de precalentamiento con entrada de ceros.

        La primera inferencia tras cargar el modelo es mucho más lenta que
        las siguientes (F-027). El resultado se descarta: quien llama no
        recibe nada y la implementación no debe publicar ni persistir.

        Raises:
            Exception: cualquier falla del modelo se propaga; Cloud no debe
                arrancar con un modelo que no puede inferir.
        """
        raise NotImplementedError
