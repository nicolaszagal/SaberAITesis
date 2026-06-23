"""FeatureStreamConsumerPort — lectura de features publicadas por Fog."""

from abc import ABC, abstractmethod
from typing import AsyncIterator

from cloud.domain.models import FeatureSequence


class FeatureStreamConsumerPort(ABC):
    @abstractmethod
    def consume(self) -> AsyncIterator[tuple[str, FeatureSequence]]:
        """Yields (entry_id, FeatureSequence). El llamador debe invocar
        `ack(entry_id)` después de procesar exitosamente la entrada."""
        raise NotImplementedError

    @abstractmethod
    async def ack(self, entry_id: str) -> None:
        raise NotImplementedError
