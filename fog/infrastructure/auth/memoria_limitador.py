"""Limitador de intentos de login por IP en la memoria del proceso de Fog (SEC02).

Vive solo en el proceso de Fog: ningún Redis, y por tanto ninguna credencial de
la nube, puede borrar o reiniciar los contadores. A cambio, reiniciar Fog los
pone en cero; eso solo lo puede hacer quien ya tiene el Mac.
"""

import time
from collections.abc import Callable

from fog.ports.limitador_intentos import LimitadorIntentosPort

# Tope de IPs distintas con contador abierto: evita que muchas IPs falsas
# agoten la memoria. Al superarlo se purgan primero las entradas vencidas.
MAX_ENTRADAS = 10_000


class MemoriaLimitador(LimitadorIntentosPort):
    """Cuenta fallos por IP en una ventana y bloquea al llegar al máximo.

    Args:
        max_fallos: fallos que bloquean la IP.
        ventana_s: segundos en que se cuentan los fallos desde el primero.
        bloqueo_s: segundos que dura el bloqueo.
        reloj: fuente de tiempo monotónica en segundos (inyectable en pruebas).
    """

    def __init__(
        self,
        max_fallos: int,
        ventana_s: int,
        bloqueo_s: int,
        reloj: Callable[[], float] = time.monotonic,
    ):
        self._max = max_fallos
        self._ventana_s = ventana_s
        self._bloqueo_s = bloqueo_s
        self._reloj = reloj
        self._fallos: dict[str, tuple[int, float]] = {}  # ip -> (cuenta, vence)
        self._bloqueos: dict[str, float] = {}  # ip -> instante en que termina

    def _purgar(self) -> None:
        ahora = self._reloj()
        self._fallos = {ip: v for ip, v in self._fallos.items() if v[1] > ahora}
        self._bloqueos = {ip: t for ip, t in self._bloqueos.items() if t > ahora}

    async def segundos_bloqueado(self, ip: str) -> int:
        restante = self._bloqueos.get(ip, 0.0) - self._reloj()
        return max(int(restante + 0.999), 0) if restante > 0 else 0

    async def registrar_fallo(self, ip: str) -> bool:
        ahora = self._reloj()
        if len(self._fallos) + len(self._bloqueos) >= MAX_ENTRADAS:
            self._purgar()
        cuenta, vence = self._fallos.get(ip, (0, 0.0))
        if vence <= ahora:
            cuenta, vence = 0, ahora + self._ventana_s
        cuenta += 1
        if cuenta < self._max:
            self._fallos[ip] = (cuenta, vence)
            return False
        self._bloqueos[ip] = ahora + self._bloqueo_s
        self._fallos.pop(ip, None)
        return True

    async def registrar_exito(self, ip: str) -> None:
        self._fallos.pop(ip, None)
