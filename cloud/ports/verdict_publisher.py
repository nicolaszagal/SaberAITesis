"""VerdictPublisherPort — publicación del veredicto final hacia Fog."""

from abc import ABC, abstractmethod

from cloud.domain.models import Verdict


class VerdictPublisherPort(ABC):
    @abstractmethod
    async def publish(self, verdict: Verdict) -> None:
        raise NotImplementedError
