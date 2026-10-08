"""Casos de uso de autenticación del usuario maestro (DEPLOY05).

Los eventos se registran en el log técnico (`sabre.auth`) con IP y usuario;
nunca la contraseña ni el token. No se mezclan con la auditoría de revisiones.
"""

from __future__ import annotations

import logging

from fog.domain.errors import CredencialesInvalidas, DemasiadosIntentos, TokenInvalido
from fog.ports.emisor_tokens import EmisorTokensPort, TokenEmitido
from fog.ports.limitador_intentos import LimitadorIntentosPort
from fog.ports.verificador_credenciales import VerificadorCredencialesPort

log = logging.getLogger("sabre.auth")

_MAX_USUARIO_LOG = 64


def _usuario_para_log(usuario: str) -> str:
    """Acota y escapa un usuario del cliente (evita inyección en el log)."""
    return repr(usuario[:_MAX_USUARIO_LOG])


class IniciarSesion:
    """Valida credenciales con bloqueo por IP y emite el token de acceso."""

    def __init__(
        self,
        verificador: VerificadorCredencialesPort,
        emisor: EmisorTokensPort,
        limitador: LimitadorIntentosPort,
    ):
        self._verificador = verificador
        self._emisor = emisor
        self._limitador = limitador

    async def execute(self, usuario: str, password: str, ip: str) -> TokenEmitido:
        """Inicia sesión.

        Args:
            usuario: usuario enviado por el cliente.
            password: contraseña en claro enviada por el cliente.
            ip: IP del cliente (ya resuelta según el proxy confiable).

        Returns:
            El token y su vigencia.

        Raises:
            DemasiadosIntentos: si la IP está bloqueada (aunque la contraseña
                sea correcta).
            CredencialesInvalidas: si usuario o contraseña son incorrectos.
        """
        restante = await self._limitador.segundos_bloqueado(ip)
        if restante > 0:
            raise DemasiadosIntentos(restante)

        if not self._verificador.verificar(usuario, password):
            quien = _usuario_para_log(usuario)
            log.warning("auth.login_fallo ip=%s usuario=%s", ip, quien)
            if await self._limitador.registrar_fallo(ip):
                log.warning("auth.bloqueo ip=%s usuario=%s", ip, quien)
            raise CredencialesInvalidas()

        await self._limitador.registrar_exito(ip)
        token = self._emisor.emitir(usuario)
        log.info("auth.login_ok ip=%s usuario=%s", ip, _usuario_para_log(usuario))
        return token


class ValidarToken:
    """Valida el token de una petición y devuelve el usuario."""

    def __init__(self, emisor: EmisorTokensPort):
        self._emisor = emisor

    def execute(self, token: str | None, ip: str) -> str:
        """Valida un token.

        Args:
            token: token Bearer, o None si la petición no lo trajo.
            ip: IP del cliente, solo para el registro.

        Returns:
            El usuario del token.

        Raises:
            TokenInvalido: si falta, está vencido o fue alterado.
        """
        try:
            if not token:
                raise TokenInvalido()
            return self._emisor.validar(token)
        except TokenInvalido:
            log.warning("auth.token_invalido ip=%s", ip)
            raise
