"""EmisorTokensPort — emite y valida los tokens de acceso de Fog."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class TokenEmitido:
    access_token: str
    expires_in: int


class EmisorTokensPort(ABC):
    @abstractmethod
    def emitir(self, usuario: str) -> TokenEmitido:
        """Emite un token de acceso para el usuario.

        Args:
            usuario: identificador que va en el claim `sub`.

        Returns:
            El token y su vigencia en segundos.
        """
        raise NotImplementedError

    @abstractmethod
    def validar(self, token: str) -> str:
        """Valida firma, expiración y claims obligatorios.

        Args:
            token: token recibido en `Authorization: Bearer`.

        Returns:
            El usuario (`sub`) del token.

        Raises:
            TokenInvalido: si el token es inválido, vencido o está alterado.
        """
        raise NotImplementedError
