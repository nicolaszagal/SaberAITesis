"""Simulador de la señal Favero (EDGE01): emite tramas reales de 10 bytes sin el aparato.

Las tramas salen con el mismo formato y ritmo que el aparato (una cada ~41,67 ms, continuas),
con checksum correcto. Sirve para probar el lector y la captura de punta a punta.

Uso desde la línea de comandos (crea un puerto virtual y muestra su ruta):

    python -m edge.favero.simulador --toques roja,verde,doble --cada 4

y en otra terminal:

    python -m edge.favero.diagnostico --puerto <ruta que imprimió>
"""

from __future__ import annotations

import argparse
import logging
import os
import threading
import time
from collections.abc import Callable

from edge.favero.lector import BIT_ROJA, BIT_VERDE, PERIODO_TRAMA_S, construir_trama

logger = logging.getLogger(__name__)

LUCES_POR_NOMBRE = {
    "roja": BIT_ROJA,
    "verde": BIT_VERDE,
    "doble": BIT_ROJA | BIT_VERDE,
}


class SimuladorFavero:
    """Emite tramas continuas; las luces se encienden y apagan con `encender`/`apagar`.

    La emisión respeta el reloj (una trama cada `periodo_s`, corrigiendo la deriva), igual que el
    aparato, que no se detiene entre toques.
    """

    def __init__(
        self,
        escribir: Callable[[bytes], object],
        *,
        periodo_s: float = PERIODO_TRAMA_S,
        reloj_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        """Prepara el simulador (no emite hasta `iniciar`).

        Args:
            escribir: recibe los 10 bytes de cada trama (p. ej. `os.write` sobre un pty).
            periodo_s: segundos entre tramas.
            reloj_ns: reloj monótono en nanosegundos.
        """
        self._escribir = escribir
        self._periodo_ns = int(periodo_s * 1e9)
        self._reloj_ns = reloj_ns
        self._luces = 0
        self._tramas_restantes: int | None = None
        self._lock = threading.Lock()
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None
        self.tramas_emitidas = 0
        self.instantes_subida_ns: list[tuple[int, int]] = []  # (bits, instante de la 1.ª trama con ellos)

    def encender(self, luces: int, tramas: int | None = None) -> None:
        """Enciende luces desde la próxima trama.

        Args:
            luces: bits del byte 6 (`BIT_ROJA`, `BIT_VERDE`, o ambos).
            tramas: tras cuántas tramas se apagan solas; `None` = hasta `apagar()`.
        """
        with self._lock:
            self._luces = luces
            self._tramas_restantes = tramas

    def apagar(self) -> None:
        """Apaga todas las luces desde la próxima trama."""
        self.encender(0)

    def iniciar(self) -> None:
        """Arranca el hilo emisor."""
        self._parar.clear()
        self._hilo = threading.Thread(target=self._bucle, name="simulador-favero", daemon=True)
        self._hilo.start()

    def detener(self, timeout_s: float = 2.0) -> None:
        """Detiene el hilo emisor."""
        self._parar.set()
        if self._hilo is not None:
            self._hilo.join(timeout_s)

    def _bucle(self) -> None:
        proximo = self._reloj_ns()
        previas = 0
        while not self._parar.is_set():
            with self._lock:
                luces = self._luces
                if self._tramas_restantes is not None and luces:
                    self._tramas_restantes -= 1
                    if self._tramas_restantes <= 0:
                        self._luces = 0
                        self._tramas_restantes = None
            antes = self._reloj_ns()
            try:
                self._escribir(construir_trama(luces))
            except OSError:
                logger.info("[Simulador] El puerto se cerró; termino")
                return
            if luces & ~previas:
                self.instantes_subida_ns.append((luces & ~previas, antes))
            previas = luces
            self.tramas_emitidas += 1
            proximo += self._periodo_ns
            pausa = (proximo - self._reloj_ns()) / 1e9
            if pausa > 0:
                self._parar.wait(pausa)
            else:
                proximo = self._reloj_ns()  # nos atrasamos: no acumular ráfagas


def abrir_pty() -> tuple[int, str]:
    """Crea un puerto serie virtual (pty).

    Returns:
        (descriptor del extremo maestro para escribir, ruta del extremo esclavo para abrir
        con pyserial).
    """
    maestro, esclavo = os.openpty()
    return maestro, os.ttyname(esclavo)


def _argumentos(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulador de la señal Favero (tramas reales por un pty).")
    parser.add_argument("--toques", default="roja,verde,doble", help="secuencia que se repite: roja, verde, doble")
    parser.add_argument("--cada", type=float, default=4.0, help="segundos entre toques")
    parser.add_argument("--tramas-luz", type=int, default=24, help="tramas que dura la luz encendida (24 = ~1 s)")
    parser.add_argument("--segundos", type=float, default=None, help="duración total; sin valor, hasta Ctrl+C")
    return parser.parse_args(argv)


def principal(argv: list[str] | None = None) -> int:
    """Corre el simulador sobre un pty y escribe la ruta en la salida estándar."""
    args = _argumentos(argv)
    secuencia = [LUCES_POR_NOMBRE[n.strip()] for n in args.toques.split(",")]
    maestro, ruta = abrir_pty()
    simulador = SimuladorFavero(lambda datos: os.write(maestro, datos))
    simulador.iniciar()
    print(f"Puerto virtual: {ruta}  (ábrelo a cualquier velocidad; Ctrl+C para terminar)", flush=True)
    fin = None if args.segundos is None else time.monotonic() + args.segundos
    try:
        i = 0
        while fin is None or time.monotonic() < fin:
            time.sleep(args.cada)
            luces = secuencia[i % len(secuencia)]
            simulador.encender(luces, args.tramas_luz)
            print(f"toque {i + 1}: luces {luces:#04x}", flush=True)
            i += 1
    except KeyboardInterrupt:
        pass
    finally:
        simulador.detener()
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
