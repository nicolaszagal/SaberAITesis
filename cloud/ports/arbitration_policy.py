"""ArbitrationPolicyPort — convierte el veredicto crudo del clasificador en
el veredicto final, aplicando reglas que no son parte del modelo de ML.

Decisión de Nicolas (ver PLAN_ARQUITECTURA_DDD.md sección 1): "definir el
puerto ahora, implementar después". Implementación inicial:
FaveroHardMaskPolicy, que solo aplica la máscara hard de luz Favero
(equivalente a `apply_favero_mask` de dataset/lstm_4class/08_evaluate.py).
Las reglas de prioridad FIE (t.101-t.106) son una implementación futura
de este mismo puerto — el "Scoring Híbrido" del diagrama de arquitectura.
"""

from abc import ABC, abstractmethod

from cloud.domain.models import LuzSignal, RawVerdict


class ArbitrationPolicyPort(ABC):
    @abstractmethod
    def resolve(self, raw: RawVerdict, luz: LuzSignal | None) -> RawVerdict:
        """Devuelve el veredicto (posiblemente ajustado) que se publicará
        como final. No decide a quién corresponde ROJ/VER — eso lo hace
        application/classify_and_publish.py con shared.config.FENCER_COLOR."""
        raise NotImplementedError
