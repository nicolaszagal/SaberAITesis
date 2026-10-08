"""Emisor y validador de tokens JWT HS256 (PyJWT)."""

import time
import uuid

import jwt

from fog.domain.errors import TokenInvalido
from fog.ports.emisor_tokens import EmisorTokensPort, TokenEmitido

ALGORITMO = "HS256"


class JwtEmisor(EmisorTokensPort):
    def __init__(self, secreto: str, ttl_s: int):
        self._secreto = secreto
        self._ttl_s = ttl_s

    def emitir(self, usuario: str) -> TokenEmitido:
        ahora = int(time.time())
        claims = {
            "sub": usuario,
            "iat": ahora,
            "exp": ahora + self._ttl_s,
            "jti": uuid.uuid4().hex,
        }
        token = jwt.encode(claims, self._secreto, algorithm=ALGORITMO)
        return TokenEmitido(token, self._ttl_s)

    def validar(self, token: str) -> str:
        try:
            claims = jwt.decode(
                token,
                self._secreto,
                algorithms=[ALGORITMO],
                options={"require": ["sub", "iat", "exp", "jti"]},
            )
        except jwt.PyJWTError as exc:
            raise TokenInvalido() from exc
        return str(claims["sub"])
