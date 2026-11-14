"""FeatureStreamConsumerPort — lectura de features publicadas por Fog."""

from abc import ABC, abstractmethod
from typing import AsyncIterator

from cloud.domain.models import FeatureSequence, InvalidFeatureMessage


class ColaPerdidaError(Exception):
    """La cola de features dejó de responder tras varios fallos seguidos de conexión (FIX04).

    El proceso debe terminar con error en vez de quedarse esperando: así la política de reinicio de
    la plataforma actúa y, si el problema persiste, el servicio queda en FAILED a la vista.
    """


class FeatureStreamConsumerPort(ABC):
    @abstractmethod
    def consume(
        self,
    ) -> AsyncIterator[tuple[str, FeatureSequence | InvalidFeatureMessage]]:
        """Yields (entry_id, FeatureSequence | InvalidFeatureMessage).

        Una entrada que no respeta el contrato (DEF-09) llega como
        `InvalidFeatureMessage` — ya fue movida a dead-letter y ACKeada por
        el adaptador, así que el llamador no debe volver a invocar `ack`
        para ella; solo debe publicar el veredicto "no disponible"
        correspondiente. Para una `FeatureSequence` válida, el llamador
        debe invocar `ack(entry_id)` después de procesarla exitosamente.

        Raises:
            ColaPerdidaError: tras varios fallos de conexión seguidos con la cola."""
        raise NotImplementedError

    @abstractmethod
    async def ack(self, entry_id: str) -> None:
        raise NotImplementedError
