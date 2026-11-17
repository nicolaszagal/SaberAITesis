"""Parser de las tramas del Favero Full-Arm-05 / FA-07.

Protocolo (documento de Favero; verificar contra el aparato real):
    * 2400 baudios, 8N1. Tramas de 10 bytes enviadas continuamente (~24 por segundo).
    * Byte 1 = 0xFF (cabecera).
    * Byte 6 = luces: D2 roja (izquierda), D3 verde (derecha), D0 y D1 blancas,
      D4 y D5 amarillas.
    * Byte 10 = checksum: suma de los bytes 1 a 9, módulo 256.

Este módulo no toca puertos ni relojes: solo convierte bytes en tramas, para poder
probarlo sin hardware y reutilizarlo desde EDGE01.
"""

from __future__ import annotations

from dataclasses import dataclass

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
