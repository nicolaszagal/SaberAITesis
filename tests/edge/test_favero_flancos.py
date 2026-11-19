"""Flancos y lector serie del Favero (EDGE01), sin hardware."""

from __future__ import annotations

import os
import queue
import threading
import time

import pytest

from edge.favero.lector import (
    BIT_ROJA,
    BIT_VERDE,
    DetectorFlancos,
    Flanco,
    LectorFavero,
    Luces,
    ParserTramas,
    construir_trama,
)
from edge.favero.simulador import SimuladorFavero, abrir_pty


# ---------------------------------------------------------------- parser (casos de EDGE01)


def test_resincroniza_tras_basura_y_trama_cortada():
    parser = ParserTramas()
    tramas = parser.alimentar(b"\x00\x12\x34" + construir_trama(BIT_ROJA)[:4])  # basura + media trama
    assert tramas == []
    tramas = parser.alimentar(construir_trama(BIT_ROJA)[4:] + construir_trama(0))
    assert [t.valida for t in tramas] == [True, True]
    assert tramas[0].luces.roja and not tramas[1].luces.roja
    assert parser.bytes_descartados == 3


def test_checksum_invalido_se_descarta_y_se_recupera_la_siguiente():
    mala = bytearray(construir_trama(BIT_VERDE))
    mala[9] ^= 0x10
    tramas = ParserTramas().alimentar(bytes(mala) + construir_trama(BIT_ROJA))
    validas = [t for t in tramas if t.valida]
    assert len(validas) == 1 and validas[0].luces.roja


# ---------------------------------------------------------------- detector de flancos


def _luces(byte: int) -> Luces:
    return Luces(byte)


def test_flanco_de_subida_solo_en_el_cambio():
    d = DetectorFlancos()
    assert d.procesar(_luces(0), 1) == []
    assert d.procesar(_luces(BIT_ROJA), 2) == [Flanco("A", "ROJA", 2)]
    assert d.procesar(_luces(BIT_ROJA), 3) == []  # sigue encendida: sin flanco nuevo
    assert d.procesar(_luces(0), 4) == []  # la bajada no es flanco
    assert d.procesar(_luces(BIT_VERDE), 5) == [Flanco("B", "VERDE", 5)]


def test_dos_luces_separadas_por_n_tramas():
    d = DetectorFlancos()
    d.procesar(_luces(0), 0)
    a = d.procesar(_luces(BIT_ROJA), 100)
    d.procesar(_luces(BIT_ROJA), 142)
    b = d.procesar(_luces(BIT_ROJA | BIT_VERDE), 184)
    assert a == [Flanco("A", "ROJA", 100)]
    assert b == [Flanco("B", "VERDE", 184)]


def test_luces_simultaneas_salen_roja_primero():
    d = DetectorFlancos()
    d.procesar(_luces(0), 0)
    assert [f.lado for f in d.procesar(_luces(BIT_ROJA | BIT_VERDE), 9)] == ["A", "B"]


def test_la_primera_trama_no_genera_flanco_aunque_haya_luz():
    d = DetectorFlancos()
    assert d.procesar(_luces(BIT_ROJA), 1) == []
    d.reiniciar()
    assert d.procesar(_luces(BIT_VERDE), 2) == []


def test_blancas_y_amarillas_no_generan_flancos():
    d = DetectorFlancos()
    d.procesar(_luces(0), 0)
    assert d.procesar(_luces(0b110011), 1) == []


# ---------------------------------------------------------------- lector con puerto falso


class PuertoFalso:
    """Entrega bloques de bytes en orden; sin bloques, espera 10 ms y devuelve b''."""

    def __init__(self, bloques=(), error_al_final=None):
        self._q: queue.Queue[bytes] = queue.Queue()
        for b in bloques:
            self._q.put(b)
        self.error_al_final = error_al_final
        self.cerrado = False
        self.in_waiting = 0

    def read(self, n=1):
        try:
            return self._q.get_nowait()
        except queue.Empty:
            if self.error_al_final is not None:
                raise self.error_al_final
            time.sleep(0.01)
            return b""

    def reset_input_buffer(self):
        pass

    def close(self):
        self.cerrado = True


def _esperar(condicion, timeout=3.0):
    fin = time.monotonic() + timeout
    while time.monotonic() < fin:
        if condicion():
            return True
        time.sleep(0.005)
    return False


def _lector(fabrica, flancos, senales=None, **kw):
    return LectorFavero(
        "falso",
        flancos.append,
        al_cambio_senal=senales.append if senales is not None else None,
        abrir=fabrica,
        espera_arranque_s=0,
        backoff_inicial_s=0.01,
        backoff_max_s=0.05,
        **kw,
    )


def test_lector_emite_flancos_y_descarta_checksum_invalido():
    mala = bytearray(construir_trama(BIT_VERDE))
    mala[9] ^= 0x01
    puerto = PuertoFalso(
        [construir_trama(0), bytes(mala), construir_trama(BIT_ROJA), construir_trama(BIT_ROJA | BIT_VERDE)]
    )
    flancos: list[Flanco] = []
    lector = _lector(lambda ruta, baudios: puerto, flancos)
    lector.iniciar()
    assert _esperar(lambda: len(flancos) == 2)
    lector.detener()
    assert [f.lado for f in flancos] == ["A", "B"]
    assert flancos[0].t_ns <= flancos[1].t_ns
    estado = lector.estado()
    assert estado["tramas_validas"] == 3
    assert estado["tramas_invalidas"] >= 1  # la mala se descartó con aviso, sin flanco de VERDE antes que ROJA


def test_lector_marca_con_el_reloj_inyectado():
    t = iter(range(1_000, 10**9, 1_000))
    puerto = PuertoFalso([construir_trama(0), construir_trama(BIT_ROJA)])
    flancos: list[Flanco] = []
    lector = _lector(lambda r, b: puerto, flancos, reloj_ns=lambda: next(t))
    lector.iniciar()
    assert _esperar(lambda: len(flancos) == 1)
    lector.detener()
    assert flancos[0].t_ns % 1_000 == 0 and flancos[0].t_ns > 1_000


def test_sin_senal_en_el_umbral_y_recuperacion():
    puerto = PuertoFalso([construir_trama(0)])
    flancos, senales = [], []
    lector = _lector(lambda r, b: puerto, flancos, senales, umbral_sin_senal_s=0.1)
    lector.iniciar()
    assert _esperar(lambda: senales == [True, False])  # llegó una trama y luego silencio > 0,1 s
    puerto._q.put(construir_trama(0))
    assert _esperar(lambda: senales == [True, False, True])
    lector.detener()


def test_puerto_que_desaparece_se_reintenta_con_espera_creciente():
    intentos: list[float] = []

    def fabrica(ruta, baudios):
        intentos.append(time.monotonic())
        if len(intentos) < 4:
            raise OSError("no existe")
        return PuertoFalso([construir_trama(0), construir_trama(BIT_ROJA)])

    flancos, senales = [], []
    lector = _lector(fabrica, flancos, senales)
    lector.iniciar()
    assert _esperar(lambda: len(flancos) == 1)
    lector.detener()
    huecos = [b - a for a, b in zip(intentos, intentos[1:])]
    assert huecos[1] > huecos[0] * 1.5  # 0,01 -> 0,02 -> 0,04: crece
    assert senales[0] is False and senales[-1] is True


def test_desconexion_a_mitad_de_lectura_reabre_y_sigue():
    p1 = PuertoFalso([construir_trama(0)], error_al_final=OSError("desconectado"))
    p2 = PuertoFalso([construir_trama(0), construir_trama(BIT_VERDE)])
    puertos = iter([p1, p2])
    flancos, senales = [], []
    lector = _lector(lambda r, b: next(puertos), flancos, senales)
    lector.iniciar()
    assert _esperar(lambda: len(flancos) == 1)
    lector.detener()
    assert flancos[0].lado == "B"
    assert p1.cerrado
    assert lector.estado()["reconexiones"] == 1
    assert False in senales  # la caída se avisó


def test_hueco_entre_tramas_se_cuenta():
    class Lento(PuertoFalso):
        def __init__(self):
            super().__init__()
            self.paso = 0

        def read(self, n=1):
            self.paso += 1
            if self.paso == 1:
                return construir_trama(0)
            if self.paso == 2:
                time.sleep(0.3)  # 300 ms sin tramas: se perdieron varias
                return construir_trama(0)
            time.sleep(0.01)
            return b""

    puerto = Lento()
    lector = _lector(lambda r, b: puerto, [])
    lector.iniciar()
    assert _esperar(lambda: lector.estado()["huecos"] == 1)
    lector.detener()


def test_lector_con_simulador_por_pty():
    maestro, ruta = abrir_pty()
    sim = SimuladorFavero(lambda datos: os.write(maestro, datos))
    flancos: list[Flanco] = []
    lector = LectorFavero(ruta, flancos.append, baudios=2400, espera_arranque_s=0)
    sim.iniciar()
    lector.iniciar()
    time.sleep(0.4)
    sim.encender(BIT_ROJA, 10)
    assert _esperar(lambda: len(flancos) == 1)
    time.sleep(0.6)
    sim.encender(BIT_VERDE, 10)
    assert _esperar(lambda: len(flancos) == 2)
    lector.detener()
    sim.detener()
    assert [f.lado for f in flancos] == ["A", "B"]
    # el flanco se marca a menos de una trama (+ margen) de la primera trama emitida con la luz
    emitido = dict(sim.instantes_subida_ns)
    assert abs(flancos[0].t_ns - emitido[BIT_ROJA]) < 60e6
    assert lector.estado()["tramas_invalidas"] == 0
    os.close(maestro)
