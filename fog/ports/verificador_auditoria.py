"""VerificadorAuditoriaPort — verificación de la cadena de hashes de
`sabre.registro_auditoria` (CU-12, RNF-05). Solo lectura.
"""

from abc import ABC, abstractmethod

from fog.domain.audit_models import RegistroAlterado


class VerificadorAuditoriaPort(ABC):
    @abstractmethod
    async def verificar(self) -> list[RegistroAlterado]:
        """Ejecuta `sabre.fn_verificar_auditoria()`.

        Returns:
            Los registros cuyo hash no coincide; vacío si la cadena es íntegra.
        """
        raise NotImplementedError
