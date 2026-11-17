"""Pruebas del diagnóstico Favero (HW01) con puertos falsos, sin hardware."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
import serial

from edge.favero.diagnostico import (
    Diagnostico,
    ErrorDiagnostico,
    RegistroCSV,
    abrir_puerto,
    elegir_puerto,
    principal,
    resumir_csv,
)
from edge.favero.lector import BIT_ROJA, BIT_VERDE, construir_trama

SEG = 1_000_000_000


class RelojFalso:
    def __init__(self) -> None:
        self.ns = 0

    def __call__(self) -> int:
        return self.ns


class PuertoFalso:
    """Puerto cuyo `read` avanza el reloj 100 ms y entrega lo que decida `generador(tick)`.

    Hace de firmware: `?` responde el estado y `I` alterna la lógica. Si `necesita_invertida`
    no coincide con la lógica actual, entrega basura en vez de tramas.
    """

    def __init__(self, reloj, generador, necesita_invertida=False, invertida_inicial=False, nunca_valida=False):
        self.reloj = reloj
        self.generador = generador
        self.necesita_invertida = necesita_invertida
        self.invertida = invertida_inicial
        self.nunca_valida = nunca_valida
        self.escrito: list[str] = []
        self._respuesta = b""
        self._tick = 0

    @property
    def in_waiting(self) -> int:
        return len(self._respuesta)

    def write(self, datos: bytes) -> int:
        for c in datos.decode():
            self.escrito.append(c)
            if c == "I":
                self.invertida = not self.invertida
            elif c == "?":
                self._respuesta += f"HW01 modo=P invertida={int(self.invertida)}\n".encode()
        return len(datos)

    def reset_input_buffer(self) -> None:
        self._respuesta = b""

    def read(self, size: int = 1) -> bytes:
        self.reloj.ns += SEG // 10
        if self._respuesta:
            datos, self._respuesta = self._respuesta, b""
            return datos
        self._tick += 1
        if self.nunca_valida or self.invertida != self.necesita_invertida:
            return bytes([0x80] * 20)
        return self.generador(self._tick)

    def close(self) -> None:
        pass


def _tramas_por_tick(luces: int = 0, n: int = 2) -> bytes:
    return construir_trama(luces) * n


def _correr(puerto, reloj, segundos, **kw):
    lineas: list[str] = []
    hora = lambda: datetime(2026, 11, 17, 12, 0, 0)  # noqa: E731
    d = Diagnostico(puerto, reloj_ns=reloj, salida=lineas.append, hora_local=hora, **kw)
    d.ejecutar(segundos)
    return d, lineas


def test_linea_ok_con_luz_roja():
    reloj = RelojFalso()
    puerto = PuertoFalso(reloj, lambda t: _tramas_por_tick(BIT_ROJA, 2))
    _, lineas = _correr(puerto, reloj, 2.05)
    # 10 lecturas por segundo x 2 tramas = 20 tramas válidas por segundo en el doble
    assert lineas[0] == "OK · 20 tramas/s válidas · 0 inválidas · luces: ROJA"


def test_luces_del_segundo_se_juntan():
    reloj = RelojFalso()
    puerto = PuertoFalso(reloj, lambda t: _tramas_por_tick(BIT_VERDE if t == 3 else 0, 1))
    _, lineas = _correr(puerto, reloj, 1.05)
    assert lineas[0].endswith("luces: VERDE")


def test_sin_datos():
    reloj = RelojFalso()
    puerto = PuertoFalso(reloj, lambda t: b"")
    _, lineas = _correr(puerto, reloj, 1.05)
    assert lineas[0] == "SIN DATOS · 0 bytes/s · revisa la conexión (Fase 6/7 del plan)"


def test_autodeteccion_invierte_y_avisa_cual_funciono():
    reloj = RelojFalso()
    puerto = PuertoFalso(reloj, lambda t: _tramas_por_tick(0, 2), necesita_invertida=True)
    d = Diagnostico(puerto, reloj_ns=reloj, salida=(lineas := []).append)
    assert d.consultar_estado() == ("P", False)
    d.ejecutar(8)
    assert puerto.escrito.count("I") == 1
    assert puerto.invertida is True
    assert any("Funcionó con la lógica INVERTIDA" in linea for linea in lineas)
    assert any("SEÑAL RARA" in linea for linea in lineas)


def test_autodeteccion_si_ya_funciona_no_envia_nada():
    reloj = RelojFalso()
    puerto = PuertoFalso(reloj, lambda t: _tramas_por_tick(0, 2))
    _, lineas = _correr(puerto, reloj, 6.05)
    assert "I" not in puerto.escrito
    assert not any("Funcionó" in linea for linea in lineas)


def test_autodeteccion_sin_exito_restaura_la_logica():
    reloj = RelojFalso()
    puerto = PuertoFalso(reloj, lambda t: b"", nunca_valida=True)
    _, lineas = _correr(puerto, reloj, 9.05)
    assert puerto.escrito.count("I") == 2  # invierte y vuelve a dejarla como estaba
    assert puerto.invertida is False
    assert any("Ni la lógica normal ni la invertida" in linea and "Fase 6" in linea for linea in lineas)


def test_sin_bytes_no_prueba_polaridad():
    reloj = RelojFalso()
    puerto = PuertoFalso(reloj, lambda t: b"")
    _correr(puerto, reloj, 8.05)
    assert "I" not in puerto.escrito


def test_autodeteccion_desactivada():
    reloj = RelojFalso()
    puerto = PuertoFalso(reloj, lambda t: b"", nunca_valida=True)
    _correr(puerto, reloj, 8.05, autodetectar_polaridad=False)
    assert "I" not in puerto.escrito


def test_consultar_estado_sin_respuesta():
    reloj = RelojFalso()
    puerto = PuertoFalso(reloj, lambda t: b"")
    puerto.write = lambda datos: None  # un Arduino sin el programa HW01 no contesta
    d = Diagnostico(puerto, reloj_ns=reloj, salida=lambda x: None)
    assert d.consultar_estado(espera_s=0.5) is None


def test_puerto_perdido_da_error_claro():
    class Roto(PuertoFalso):
        def read(self, size=1):
            raise serial.SerialException("device disconnected")

    reloj = RelojFalso()
    d = Diagnostico(Roto(reloj, lambda t: b""), reloj_ns=reloj, salida=lambda x: None)
    with pytest.raises(ErrorDiagnostico, match="Fase 1"):
        d.ejecutar(1)


def _escribir_toques(ruta: Path) -> None:
    """Secuencia: roja, verde, doble simultánea, doble escalonada, 2 inválidas, y una roja sin cerrar."""
    reloj = RelojFalso()
    registro = RegistroCSV(ruta)
    d = Diagnostico(PuertoFalso(reloj, lambda t: b""), reloj_ns=reloj, salida=lambda x: None, registro=registro,
                    hora_local=lambda: datetime(2026, 11, 17, 12, 0, 0))
    secuencia = [0, 0, BIT_ROJA, BIT_ROJA, 0, BIT_VERDE, 0, BIT_ROJA | BIT_VERDE, 0,
                 BIT_ROJA, BIT_ROJA | BIT_VERDE, BIT_VERDE, 0]
    for luces in secuencia:
        reloj.ns += 42_000_000
        d.procesar(construir_trama(luces))
    mala = bytearray(construir_trama(0))
    mala[9] ^= 1
    for _ in range(2):
        reloj.ns += 42_000_000
        d.procesar(bytes(mala))
    d.procesar(construir_trama(BIT_ROJA))
    registro.cerrar()


def test_registro_una_fila_por_cambio_y_resumen(tmp_path):
    ruta = tmp_path / "toques.csv"
    _escribir_toques(ruta)
    lineas = ruta.read_text().splitlines()
    assert lineas[0].startswith("monotonic_ns,hora_local,valida,roja,verde")
    # No hay filas repetidas seguidas con el mismo estado de luces entre las válidas.
    validas = [fila.split(",") for fila in lineas[1:] if fila.split(",")[2] == "1"]
    estados = [tuple(f[3:]) for f in validas]
    assert all(a != b for a, b in zip(estados, estados[1:]))
    assert "2026-11-17T12:00:00.000" in lineas[1]
    resumen = resumir_csv(ruta)
    assert (resumen.rojas, resumen.verdes, resumen.dobles, resumen.invalidas) == (2, 1, 2, 2)


def test_resumen_por_linea_de_comandos(tmp_path, capsys):
    ruta = tmp_path / "toques.csv"
    _escribir_toques(ruta)
    assert principal(["--resumen", str(ruta)]) == 0
    salida = capsys.readouterr().out
    assert "ROJOS" in salida and "Tramas inválidas:          2" in salida


def test_resumen_de_archivo_inexistente(tmp_path, capsys):
    assert principal(["--resumen", str(tmp_path / "no_existe.csv")]) == 1
    assert "--registrar" in capsys.readouterr().err


def test_elegir_puerto_ninguno_menciona_fase_1():
    with pytest.raises(ErrorDiagnostico, match="Fase 1"):
        elegir_puerto([])


def test_elegir_puerto_uno_solo():
    assert elegir_puerto(["/dev/cu.usbmodem1101"]) == "/dev/cu.usbmodem1101"


def test_elegir_puerto_varios_pregunta():
    puertos = ["/dev/cu.usbmodem2", "/dev/cu.usbmodem1"]
    assert elegir_puerto(puertos, preguntar=lambda _: "2", salida=lambda x: None) == "/dev/cu.usbmodem2"


def test_elegir_puerto_opcion_invalida():
    with pytest.raises(ErrorDiagnostico):
        elegir_puerto(["a", "b"], preguntar=lambda _: "7", salida=lambda x: None)


def test_abrir_puerto_inexistente_explica_que_hacer():
    with pytest.raises(ErrorDiagnostico, match="Monitor Serie"):
        abrir_puerto("/dev/cu.usbmodem_que_no_existe")


def test_con_puerto_serie_real_loop():
    """pyserial `loop://`: lo que se escribe se lee de vuelta, con el reloj real."""
    puerto = abrir_puerto("loop://")
    try:
        puerto.write(construir_trama(BIT_ROJA | BIT_VERDE) * 24)
        lineas: list[str] = []
        Diagnostico(puerto, salida=lineas.append).ejecutar(1.05)
    finally:
        puerto.close()
    assert lineas and lineas[0] == "OK · 24 tramas/s válidas · 0 inválidas · luces: ROJA + VERDE (doble)"
