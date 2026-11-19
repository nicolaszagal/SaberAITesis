"""Parser de las tramas del Favero Full-Arm-05 / FA-07.

Protocolo (documento de Favero; verificar contra el aparato real):
    * 2400 baudios, 8N1. Tramas de 10 bytes enviadas continuamente (~24 por segundo).
    * Byte 1 = 0xFF (cabecera).
    * Byte 6 = luces: D2 roja (izquierda), D3 verde (derecha), D0 y D1 blancas,
      D4 y D5 amarillas.
    * Byte 10 = checksum: suma de los bytes 1 a 9, módulo 256.

Contenido:
    * `ParserTramas`: bytes -> tramas, con resincronización por 0xFF y checksum (sin puertos
      ni relojes, para probarlo sin hardware).
    * `DetectorFlancos`: tramas válidas -> flancos de subida de la luz roja y la verde.
    * `LectorFavero` (EDGE01): hilo que lee el puerto del Arduino puente, marca cada flanco con
      `time.monotonic_ns()` en cuanto llega el último byte de la trama, avisa si no llega una
      trama válida en 2 s (RNF-09) y reintenta el puerto con espera creciente.
"""

from __future__ import annotations

import glob
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

LARGO_TRAMA = 10
CABECERA = 0xFF
INDICE_LUCES = 5  # byte 6 (índice 5 al contar desde 0)

# Bits del byte de luces.
BIT_BLANCA_D0 = 1 << 0
BIT_BLANCA_D1 = 1 << 1
BIT_ROJA = 1 << 2
BIT_VERDE = 1 << 3
BIT_AMARILLA_D4 = 1 << 4
BIT_AMARILLA_D5 = 1 << 5

_NOMBRES_LUCES = (
    (BIT_ROJA, "ROJA"),
    (BIT_VERDE, "VERDE"),
    (BIT_BLANCA_D0, "BLANCA D0"),
    (BIT_BLANCA_D1, "BLANCA D1"),
    (BIT_AMARILLA_D4, "AMARILLA D4"),
    (BIT_AMARILLA_D5, "AMARILLA D5"),
)


@dataclass(frozen=True)
class Luces:
    """Estado de las 6 luces según el byte 6 de una trama.

    Attributes:
        byte: valor crudo del byte 6. Los bits 6 y 7 no están documentados y se ignoran.
    """

    byte: int

    @property
    def roja(self) -> bool:
        return bool(self.byte & BIT_ROJA)

    @property
    def verde(self) -> bool:
        return bool(self.byte & BIT_VERDE)

    @property
    def blanca_d0(self) -> bool:
        return bool(self.byte & BIT_BLANCA_D0)

    @property
    def blanca_d1(self) -> bool:
        return bool(self.byte & BIT_BLANCA_D1)

    @property
    def amarilla_d4(self) -> bool:
        return bool(self.byte & BIT_AMARILLA_D4)

    @property
    def amarilla_d5(self) -> bool:
        return bool(self.byte & BIT_AMARILLA_D5)

    @property
    def estado(self) -> int:
        """Solo los 6 bits de luces documentados (D0 a D5)."""
        return self.byte & 0x3F

    @property
    def doble(self) -> bool:
        """True si la roja y la verde están encendidas a la vez."""
        return self.roja and self.verde

    def texto(self) -> str:
        """Descripción legible: 'ROJA', 'ROJA + VERDE (doble)' o 'ninguna'."""
        nombres = [nombre for bit, nombre in _NOMBRES_LUCES if self.byte & bit]
        if not nombres:
            return "ninguna"
        texto = " + ".join(nombres)
        return f"{texto} (doble)" if self.doble and len(nombres) == 2 else texto


@dataclass(frozen=True)
class Trama:
    """Una trama de 10 bytes ya evaluada.

    Attributes:
        valida: True si empezaba con 0xFF y el checksum coincide.
        crudo: los 10 bytes tal como llegaron.
        luces: estado de las luces; `None` si la trama no es válida (no se confía en ella).
    """

    valida: bool
    crudo: bytes
    luces: Luces | None


def calcular_checksum(primeros_nueve: bytes) -> int:
    """Suma de los bytes 1 a 9, módulo 256.

    Args:
        primeros_nueve: los 9 primeros bytes de la trama.

    Returns:
        El valor que debe tener el byte 10.
    """
    return sum(primeros_nueve) % 256


def construir_trama(luces: int) -> bytes:
    """Arma una trama válida (para simuladores y pruebas).

    Los bytes cuyo significado no está documentado (2 a 5 y 7 a 9) se dejan en 0.

    Args:
        luces: valor del byte 6.

    Returns:
        Los 10 bytes, con checksum correcto.
    """
    cuerpo = bytearray(LARGO_TRAMA - 1)
    cuerpo[0] = CABECERA
    cuerpo[INDICE_LUCES] = luces & 0xFF
    return bytes(cuerpo) + bytes([calcular_checksum(bytes(cuerpo))])


class ParserTramas:
    """Convierte un flujo de bytes en tramas, resincronizando por 0xFF.

    Reglas:
        * Los bytes anteriores a un 0xFF se descartan en silencio (cuentan en
          `bytes_descartados`, no como trama inválida).
        * Si desde un 0xFF hay 10 bytes pero el checksum falla, se informa una trama
          inválida y se avanza un solo byte (el 0xFF falso puede estar dentro de basura
          y la trama buena empezar más adelante).
        * Si faltan bytes para completar 10, espera la siguiente llamada.

    Attributes:
        bytes_descartados: bytes tirados por no estar alineados con un 0xFF.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()
        self.bytes_descartados = 0

    def alimentar(self, datos: bytes) -> list[Trama]:
        """Agrega bytes y devuelve las tramas que quedaron completas.

        Args:
            datos: bytes recién leídos del puerto (cualquier cantidad, incluso partidos
                a la mitad de una trama).

        Returns:
            Tramas válidas e inválidas, en orden de llegada.
        """
        self._buffer.extend(datos)
        tramas: list[Trama] = []
        while True:
            inicio = self._buffer.find(CABECERA)
            if inicio < 0:
                self.bytes_descartados += len(self._buffer)
                self._buffer.clear()
                break
            if inicio > 0:
                self.bytes_descartados += inicio
                del self._buffer[:inicio]
            if len(self._buffer) < LARGO_TRAMA:
                break
            crudo = bytes(self._buffer[:LARGO_TRAMA])
            if calcular_checksum(crudo[:-1]) == crudo[-1]:
                tramas.append(Trama(True, crudo, Luces(crudo[INDICE_LUCES])))
                del self._buffer[:LARGO_TRAMA]
            else:
                tramas.append(Trama(False, crudo, None))
                del self._buffer[:1]
        return tramas


# --------------------------------------------------------------------------- flancos (EDGE01)

# Mapeo fijo de v1 (a confirmar en la pista con un toque de cada lado): roja = izquierda = A
# = ROJ; verde = derecha = B = VER.
MAPEO_LADOS = {"ROJA": "A", "VERDE": "B"}

PERIODO_TRAMA_S = LARGO_TRAMA * 10 / 2400  # 10 bytes x 10 bits / 2400 baudios = 41,67 ms
UMBRAL_SIN_SENAL_S = 2.0  # RNF-09: sin trama válida en este tiempo = "sin señal Favero"
UMBRAL_HUECO_S = 2 * PERIODO_TRAMA_S  # entre dos tramas válidas más que esto = se perdió alguna
BAUDIOS_USB = 115200  # lado USB del puente (el lado Favero es 2400 y lo lee el Arduino)
ESPERA_ARRANQUE_S = 2.0  # al abrir el puerto el Arduino se reinicia solo


@dataclass(frozen=True)
class Flanco:
    """Subida de una luz (apagada en la trama válida anterior, encendida en esta).

    Attributes:
        lado: "A" (roja, izquierda) o "B" (verde, derecha), según `MAPEO_LADOS`.
        luz: "ROJA" o "VERDE".
        t_ns: `time.monotonic_ns()` al llegar el último byte de la trama.
        fuente: 'favero' o 'simulado'; `None` = la de la captura (el lector serie no la fija).
        origen: de dónde salió la señal si no es el aparato (p. ej. 'boton'); `None` si es el aparato.
    """

    lado: str
    luz: str
    t_ns: int
    fuente: str | None = None
    origen: str | None = None


class DetectorFlancos:
    """Detecta flancos de subida de las luces roja y verde entre tramas válidas.

    Solo se le deben pasar tramas válidas: las inválidas se descartan antes y no cambian el
    estado. La primera trama válida (y la primera tras una reconexión) fija el estado de
    partida sin generar flanco: si la luz ya estaba encendida no se sabe cuándo subió.
    """

    def __init__(self) -> None:
        self._previo: int | None = None

    def reiniciar(self) -> None:
        """Olvida el estado anterior (p. ej. tras reabrir el puerto)."""
        self._previo = None

    def procesar(self, luces: Luces, t_ns: int) -> list[Flanco]:
        """Compara con la trama válida anterior.

        Args:
            luces: luces de la trama válida recién llegada.
            t_ns: instante de llegada (`time.monotonic_ns()`).

        Returns:
            Los flancos de subida, la roja (A) antes que la verde (B) si suben juntas.
        """
        actual = luces.estado
        previo, self._previo = self._previo, actual
        if previo is None:
            return []
        subieron = actual & ~previo
        flancos = []
        for bit, luz in ((BIT_ROJA, "ROJA"), (BIT_VERDE, "VERDE")):
            if subieron & bit:
                flancos.append(Flanco(MAPEO_LADOS[luz], luz, t_ns))
        return flancos


# --------------------------------------------------------------------------- lector serie (EDGE01)


class LectorFavero:
    """Lee el puerto serie del Arduino puente en un hilo y emite flancos.

    Cada flanco se marca con `reloj_ns()` justo después de que `read()` devuelve los bytes que
    completan la trama. Si una lectura trae varias tramas (el hilo se atrasó), todas reciben
    ese mismo instante y se cuenta en `rafagas`.

    Tolerancia a fallos (RNF-09): si en `umbral_sin_senal_s` no llega una trama válida avisa
    `al_cambio_senal(False)`; si el puerto desaparece lo reintenta con espera creciente
    (`backoff_inicial_s` x2 hasta `backoff_max_s`).
    """

    def __init__(
        self,
        puerto: str,
        al_flanco: Callable[[Flanco], None],
        *,
        baudios: int = BAUDIOS_USB,
        al_cambio_senal: Callable[[bool], None] | None = None,
        abrir: Callable[[str, int], Any] | None = None,
        reloj_ns: Callable[[], int] = time.monotonic_ns,
        espera_arranque_s: float = ESPERA_ARRANQUE_S,
        umbral_sin_senal_s: float = UMBRAL_SIN_SENAL_S,
        backoff_inicial_s: float = 0.5,
        backoff_max_s: float = 8.0,
    ) -> None:
        """Prepara el lector (no abre nada hasta `iniciar`).

        Args:
            puerto: ruta del dispositivo o patrón (`/dev/cu.usbmodem*`: se usa el primero).
            al_flanco: se llama, desde el hilo del lector, por cada flanco de subida.
            baudios: velocidad del lado USB del puente (configurable).
            al_cambio_senal: se llama con `True`/`False` cuando cambia "hay señal Favero".
            abrir: fábrica `(ruta, baudios) -> puerto` para pruebas; por defecto pyserial.
            reloj_ns: reloj monótono en nanosegundos.
            espera_arranque_s: pausa tras abrir (el Arduino se reinicia al abrir el puerto).
            umbral_sin_senal_s: segundos sin trama válida para declarar "sin señal".
            backoff_inicial_s: primera espera antes de reintentar el puerto.
            backoff_max_s: tope de la espera creciente.
        """
        self._puerto_cfg = puerto
        self._al_flanco = al_flanco
        self._al_cambio_senal = al_cambio_senal
        self._baudios = baudios
        self._abrir = abrir or _abrir_pyserial
        self._reloj_ns = reloj_ns
        self._espera_arranque_s = espera_arranque_s
        self._umbral_ns = int(umbral_sin_senal_s * 1e9)
        self._backoff_inicial_s = backoff_inicial_s
        self._backoff_max_s = backoff_max_s
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None
        self._lock = threading.Lock()
        self._senal: bool | None = None
        self.tramas_validas = 0
        self.tramas_invalidas = 0
        self.huecos = 0
        self.rafagas = 0
        self.reconexiones = 0
        self.bytes_descartados = 0

    # ---- ciclo de vida

    def iniciar(self) -> None:
        """Arranca el hilo de lectura (no hace nada si ya corre)."""
        if self._hilo is not None and self._hilo.is_alive():
            return
        self._parar.clear()
        self._hilo = threading.Thread(target=self._bucle, name="lector-favero", daemon=True)
        self._hilo.start()

    def detener(self, timeout_s: float = 2.0) -> None:
        """Pide al hilo que termine y espera hasta `timeout_s`."""
        self._parar.set()
        if self._hilo is not None:
            self._hilo.join(timeout_s)

    def estado(self) -> dict[str, Any]:
        """Instantánea para el log o el futuro `/estado` de Edge.

        Returns:
            Diccionario con `senal` (True/False/None si aún no se sabe) y los contadores.
        """
        with self._lock:
            return {
                "senal": self._senal,
                "tramas_validas": self.tramas_validas,
                "tramas_invalidas": self.tramas_invalidas,
                "huecos": self.huecos,
                "rafagas": self.rafagas,
                "reconexiones": self.reconexiones,
                "bytes_descartados": self.bytes_descartados,
            }

    # ---- internos

    def _fijar_senal(self, hay: bool) -> None:
        with self._lock:
            if self._senal is hay:
                return
            self._senal = hay
        if hay:
            logger.info("[Favero] Señal Favero recuperada")
        else:
            logger.warning("[Favero] Sin señal Favero (RNF-09): la revisión sigue como repetición convencional")
        if self._al_cambio_senal is not None:
            try:
                self._al_cambio_senal(hay)
            except Exception:  # noqa: BLE001 - un callback ajeno no debe matar el hilo
                logger.exception("[Favero] Falló al_cambio_senal")

    def _bucle(self) -> None:
        espera = self._backoff_inicial_s
        primera = True
        while not self._parar.is_set():
            try:
                puerto = self._abrir(self._resolver_ruta(), self._baudios)
            except Exception as error:  # noqa: BLE001 - serial.SerialException, OSError, ErrorPuerto
                self._fijar_senal(False)
                logger.warning("[Favero] No se pudo abrir el puerto (%s); reintento en %.1f s", error, espera)
                self._parar.wait(espera)
                espera = min(espera * 2, self._backoff_max_s)
                continue
            if not primera:
                with self._lock:
                    self.reconexiones += 1
            primera = False
            logger.info("[Favero] Puerto abierto: %s", self._puerto_cfg)
            try:
                if self._parar.wait(self._espera_arranque_s):
                    break
                if hasattr(puerto, "reset_input_buffer"):
                    puerto.reset_input_buffer()
                if self._leer(puerto):
                    espera = self._backoff_inicial_s  # se leyó algo válido: no seguir creciendo
            except Exception as error:  # noqa: BLE001
                logger.warning("[Favero] Se perdió el puerto (%s)", error)
            finally:
                try:
                    puerto.close()
                except Exception:  # noqa: BLE001
                    pass
            if self._parar.is_set():
                break
            self._fijar_senal(False)
            self._parar.wait(espera)
            espera = min(espera * 2, self._backoff_max_s)

    def _resolver_ruta(self) -> str:
        if any(c in self._puerto_cfg for c in "*?["):
            candidatos = sorted(glob.glob(self._puerto_cfg))
            if not candidatos:
                raise FileNotFoundError(f"no hay dispositivo que coincida con {self._puerto_cfg}")
            return candidatos[0]
        return self._puerto_cfg

    def _leer(self, puerto: Any) -> bool:
        """Lee hasta que falle el puerto o se pida parar.

        Returns:
            True si llegó al menos una trama válida en esta sesión.
        """
        parser = ParserTramas()
        detector = DetectorFlancos()
        base_descartados = self.bytes_descartados
        ultima_valida_ns = self._reloj_ns()
        hubo_valida = False
        while not self._parar.is_set():
            datos = puerto.read(max(1, getattr(puerto, "in_waiting", 0) or 0))
            ahora_ns = self._reloj_ns()
            if datos:
                tramas = parser.alimentar(datos)
                validas = [t for t in tramas if t.valida]
                invalidas = len(tramas) - len(validas)
                with self._lock:
                    self.tramas_invalidas += invalidas
                    self.bytes_descartados = base_descartados + parser.bytes_descartados
                    if len(validas) > 1:
                        self.rafagas += 1
                if invalidas:
                    logger.warning("[Favero] %d trama(s) con checksum inválido descartada(s)", invalidas)
                if validas and hubo_valida and ahora_ns - ultima_valida_ns > UMBRAL_HUECO_S * 1e9:
                    with self._lock:
                        self.huecos += 1
                    logger.warning(
                        "[Favero] Hueco de %.0f ms entre tramas válidas (¿se perdieron tramas?)",
                        (ahora_ns - ultima_valida_ns) / 1e6,
                    )
                for trama in validas:
                    hubo_valida = True
                    ultima_valida_ns = ahora_ns
                    with self._lock:
                        self.tramas_validas += 1
                    self._fijar_senal(True)
                    for flanco in detector.procesar(trama.luces, ahora_ns):
                        try:
                            self._al_flanco(flanco)
                        except Exception:  # noqa: BLE001 - un callback ajeno no debe matar el hilo
                            logger.exception("[Favero] Falló al_flanco")
            if ahora_ns - ultima_valida_ns > self._umbral_ns:
                self._fijar_senal(False)
        return hubo_valida


def _abrir_pyserial(ruta: str, baudios: int) -> Any:
    """Abre el puerto con pyserial (acepta URLs como `loop://`), con lectura de 50 ms."""
    import serial  # import local: las pruebas del parser no necesitan pyserial

    return serial.serial_for_url(ruta, baudrate=baudios, timeout=0.05)
