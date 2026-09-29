"""VerdictStreamSubscriberPort — espera bloqueante del veredicto de Cloud
para una revisión dada."""

from abc import ABC, abstractmethod

from fog.domain.models import UnavailableResult, VerdictView


class VerdictStreamSubscriberPort(ABC):
    @abstractmethod
    async def wait_for_verdict(self, revision_id: str) -> VerdictView | UnavailableResult:
        """Bloquea hasta que Cloud publique el resultado de `revision_id`.

        Args:
            revision_id: revisión cuyo veredicto se espera
                (`cloud:verdicts:{revision_id}`).

        Returns:
            El veredicto, o `UnavailableResult` si Cloud publicó
            `disponible=false` (por ejemplo `mensaje_invalido`).
        """
        raise NotImplementedError
