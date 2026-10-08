"""LimitadorIntentosPort — bloqueo temporal por IP tras fallos de login."""

from abc import ABC, abstractmethod


class LimitadorIntentosPort(ABC):
    @abstractmethod
    async def segundos_bloqueado(self, ip: str) -> int:
        """Segundos que faltan de bloqueo para la IP (0 si no está bloqueada)."""
        raise NotImplementedError

    @abstractmethod
    async def registrar_fallo(self, ip: str) -> bool:
        """Cuenta un intento fallido.

        Args:
            ip: IP del cliente.

        Returns:
            True si con este fallo la IP queda bloqueada.
        """
        raise NotImplementedError

    @abstractmethod
    async def registrar_exito(self, ip: str) -> None:
        """Borra el contador de fallos de la IP."""
        raise NotImplementedError
