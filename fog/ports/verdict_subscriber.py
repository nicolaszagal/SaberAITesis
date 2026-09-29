"""VerdictStreamSubscriberPort — espera bloqueante del veredicto de Cloud
para un match_id dado."""

from abc import ABC, abstractmethod

from fog.domain.models import UnavailableResult, VerdictView


class VerdictStreamSubscriberPort(ABC):
    @abstractmethod
    async def wait_for_verdict(self, match_id: str) -> VerdictView | UnavailableResult:
        """Bloquea hasta que Cloud publique el resultado de `match_id`.

        Returns:
            El veredicto, o `UnavailableResult` si Cloud publicó
            `disponible=false` (por ejemplo `mensaje_invalido`).
        """
        raise NotImplementedError
