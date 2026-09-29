"""SondaSaludPort — comprobación de que una dependencia responde
(GET /health)."""

from abc import ABC, abstractmethod


class SondaSaludPort(ABC):
    @abstractmethod
    async def responde(self) -> bool:
        """Comprueba la dependencia.

        Returns:
            True si respondió a tiempo; False si falló o expiró. No lanza.
        """
        raise NotImplementedError
