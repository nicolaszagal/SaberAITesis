"""Registro de nodos Fog autorizados y limitador de peticiones por nodo (DEPLOY11).

Cloud no guarda tokens: solo el SHA-256 de cada uno, con el nombre del nodo, en la variable
`CLOUD_NODOS_SHA256`. Formato: entradas `nombre:hash` separadas por comas o saltos de línea
(`nombre`: minúsculas, dígitos, guion y guion bajo, 1 a 32; `hash`: 64 hexadecimales). Revocar
un token es quitar su entrada y redesplegar.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time
from collections import deque

_NOMBRE = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
_HASH = re.compile(r"[0-9a-f]{64}")


class NodosInvalidosError(RuntimeError):
    """La variable de nodos está mal formada. El mensaje nunca incluye hashes."""


def hash_token(token: str) -> str:
    """SHA-256 hexadecimal de un token.

    Args:
        token: token en claro, sin saltos de línea.

    Returns:
        El hash, en minúsculas.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class RegistroNodos:
    """Hashes de tokens por nodo, con comparación en tiempo constante."""

    def __init__(self, hashes_por_nodo: dict[str, str]):
        self._hashes = dict(hashes_por_nodo)

    @classmethod
    def desde_texto(cls, texto: str | None) -> "RegistroNodos":
        """Lee el valor de `CLOUD_NODOS_SHA256`.

        Args:
            texto: entradas `nombre:hash` separadas por comas o saltos de línea.

        Returns:
            El registro, con al menos un nodo.

        Raises:
            NodosInvalidosError: si no hay entradas, una está mal formada o se repite un nombre
                o un hash.
        """
        entradas = [e.strip() for e in re.split(r"[,\n]", texto or "") if e.strip()]
        if not entradas:
            raise NodosInvalidosError("CLOUD_NODOS_SHA256 no tiene ningún nodo.")
        hashes: dict[str, str] = {}
        for n, entrada in enumerate(entradas, start=1):
            nombre, sep, hash_hex = entrada.partition(":")
            nombre, hash_hex = nombre.strip(), hash_hex.strip().lower()
            if not sep or not _NOMBRE.fullmatch(nombre) or not _HASH.fullmatch(hash_hex):
                raise NodosInvalidosError(
                    f"CLOUD_NODOS_SHA256: la entrada {n} no tiene el formato nombre:hash "
                    "(nombre en minúsculas, hash SHA-256 de 64 hexadecimales)."
                )
            if nombre in hashes:
                raise NodosInvalidosError(f"CLOUD_NODOS_SHA256: nodo repetido ({nombre}).")
            if hash_hex in hashes.values():
                raise NodosInvalidosError(
                    f"CLOUD_NODOS_SHA256: el nodo {nombre} repite el hash de otro nodo."
                )
            hashes[nombre] = hash_hex
        return cls(hashes)

    @property
    def nombres(self) -> list[str]:
        """Nombres de los nodos registrados."""
        return sorted(self._hashes)

    def autenticar(self, token: str) -> str | None:
        """Busca el nodo dueño de un token.

        Args:
            token: valor del `Authorization: Bearer`.

        Returns:
            El nombre del nodo, o None si ningún hash coincide. Recorre todos los nodos y
            compara en tiempo constante.
        """
        candidato = hash_token(token)
        encontrado = None
        for nombre, hash_hex in self._hashes.items():
            if hmac.compare_digest(candidato, hash_hex):
                encontrado = nombre
        return encontrado


class LimitadorPeticiones:
    """Ventana deslizante en memoria: como máximo `maximo` peticiones por nodo y ventana."""

    def __init__(self, maximo: int, ventana_s: float, reloj=time.monotonic):
        self._maximo = maximo
        self._ventana_s = ventana_s
        self._reloj = reloj
        self._marcas: dict[str, deque[float]] = {}

    def permitir(self, nodo: str) -> bool:
        """Registra una petición del nodo si no supera el límite.

        Args:
            nodo: nombre del nodo autenticado.

        Returns:
            False si el nodo ya hizo `maximo` peticiones dentro de la ventana.
        """
        ahora = self._reloj()
        marcas = self._marcas.setdefault(nodo, deque())
        while marcas and ahora - marcas[0] >= self._ventana_s:
            marcas.popleft()
        if len(marcas) >= self._maximo:
            return False
        marcas.append(ahora)
        return True
