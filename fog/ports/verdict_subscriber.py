"""VerdictStreamSubscriberPort — espera bloqueante del veredicto de Cloud
para una revisión dada."""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from fog.domain.models import UnavailableResult, VerdictView

Resultado = VerdictView | UnavailableResult


class VerdictStreamSubscriberPort(ABC):
    @abstractmethod
    async def wait_for_verdict(
        self,
        revision_id: str,
        aceptar: Callable[[Resultado], Awaitable[bool]] | None = None,
    ) -> Resultado:
        """Bloquea hasta que Cloud publique un resultado aceptable de `revision_id`.

        Args:
            revision_id: revisión cuyo veredicto se espera
                (`cloud:verdicts:{revision_id}`).
            aceptar: decide si un resultado leído vale (SEC02). Si devuelve
                False la entrada se descarta y se sigue esperando la siguiente.
                Sin él se acepta la primera.

        Returns:
            El veredicto, o `UnavailableResult` si Cloud publicó
            `disponible=false` (por ejemplo `mensaje_invalido`).
        """
        raise NotImplementedError
