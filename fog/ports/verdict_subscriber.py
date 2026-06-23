"""VerdictStreamSubscriberPort — espera bloqueante del veredicto de Cloud
para un match_id dado."""

from abc import ABC, abstractmethod

from fog.domain.models import VerdictView


class VerdictStreamSubscriberPort(ABC):
    @abstractmethod
    async def wait_for_verdict(self, match_id: str) -> VerdictView:
        """Bloquea hasta que Cloud publique el veredicto de `match_id`."""
        raise NotImplementedError
