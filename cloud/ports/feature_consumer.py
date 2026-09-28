"""FeatureStreamConsumerPort — lectura de features publicadas por Fog."""

from abc import ABC, abstractmethod
from typing import AsyncIterator

from cloud.domain.models import FeatureSequence, InvalidFeatureMessage


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
        debe invocar `ack(entry_id)` después de procesarla exitosamente."""
        raise NotImplementedError

    @abstractmethod
    async def ack(self, entry_id: str) -> None:
        raise NotImplementedError
