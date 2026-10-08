"""VerificadorCredencialesPort — comprueba usuario y contraseña del usuario maestro."""

from abc import ABC, abstractmethod


class VerificadorCredencialesPort(ABC):
    @abstractmethod
    def verificar(self, usuario: str, password: str) -> bool:
        """Compara las credenciales en tiempo constante.

        Args:
            usuario: usuario enviado por el cliente.
            password: contraseña en claro enviada por el cliente.

        Returns:
            True solo si usuario y contraseña son correctos. No distingue
            cuál de los dos falló.
        """
        raise NotImplementedError
