"""Verificador de credenciales del usuario maestro con Argon2id (argon2-cffi)."""

import hmac

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from fog.ports.verificador_credenciales import VerificadorCredencialesPort

_hasher = PasswordHasher()
# Hash de relleno para gastar el mismo tiempo cuando el usuario no coincide.
_HASH_RELLENO = _hasher.hash("relleno-tiempo-constante")


class Argon2Verificador(VerificadorCredencialesPort):
    def __init__(self, usuario: str, password_hash: str):
        self._usuario = usuario.encode()
        self._hash = password_hash

    def verificar(self, usuario: str, password: str) -> bool:
        usuario_ok = hmac.compare_digest(usuario.encode(), self._usuario)
        # Siempre se verifica un hash, para no revelar por tiempo qué falló.
        try:
            _hasher.verify(self._hash if usuario_ok else _HASH_RELLENO, password)
            password_ok = usuario_ok
        except (VerificationError, InvalidHashError):
            password_ok = False
        return usuario_ok and password_ok
