"""Pruebas del parser de tramas Favero (HW01), sin hardware."""

from __future__ import annotations

from edge.favero.lector import (
    BIT_ROJA,
    BIT_VERDE,
    ParserTramas,
    calcular_checksum,
    construir_trama,
)


def test_trama_valida_sin_luces():
    tramas = ParserTramas().alimentar(construir_trama(0))
    assert len(tramas) == 1
    assert tramas[0].valida
    assert tramas[0].luces.texto() == "ninguna"


def test_checksum_es_suma_modulo_256():
    assert calcular_checksum(bytes([0xFF] * 9)) == (0xFF * 9) % 256
    trama = construir_trama(BIT_ROJA)
    assert trama[9] == (0xFF + BIT_ROJA) % 256


def test_luz_roja_sola():
    (trama,) = ParserTramas().alimentar(construir_trama(BIT_ROJA))
    assert trama.luces.roja and not trama.luces.verde
    assert trama.luces.texto() == "ROJA"


def test_luz_verde_sola():
    (trama,) = ParserTramas().alimentar(construir_trama(BIT_VERDE))
    assert trama.luces.verde and not trama.luces.roja
    assert trama.luces.texto() == "VERDE"


def test_doble():
    (trama,) = ParserTramas().alimentar(construir_trama(BIT_ROJA | BIT_VERDE))
    assert trama.luces.doble
    assert "doble" in trama.luces.texto()


def test_blancas_y_amarillas():
    (trama,) = ParserTramas().alimentar(construir_trama(0b110011))
    assert trama.luces.blanca_d0 and trama.luces.blanca_d1
    assert trama.luces.amarilla_d4 and trama.luces.amarilla_d5
    assert not trama.luces.roja and not trama.luces.verde


def test_checksum_malo_es_invalida_y_sin_luces():
    mala = bytearray(construir_trama(BIT_ROJA))
    mala[9] ^= 0x01
    tramas = ParserTramas().alimentar(bytes(mala))
    assert len(tramas) == 1
    assert not tramas[0].valida
    assert tramas[0].luces is None


def test_basura_antes_del_ff_se_descarta_sin_contar_invalida():
    parser = ParserTramas()
    tramas = parser.alimentar(bytes([0x01, 0x02, 0x03]) + construir_trama(BIT_VERDE))
    assert [t.valida for t in tramas] == [True]
    assert parser.bytes_descartados == 3


def test_tramas_pegadas():
    datos = construir_trama(BIT_ROJA) + construir_trama(0) + construir_trama(BIT_VERDE)
    tramas = ParserTramas().alimentar(datos)
    assert [t.luces.estado for t in tramas] == [BIT_ROJA, 0, BIT_VERDE]


def test_trama_partida_en_dos_lecturas():
    trama = construir_trama(BIT_ROJA)
    parser = ParserTramas()
    assert parser.alimentar(trama[:4]) == []
    (completa,) = parser.alimentar(trama[4:])
    assert completa.valida and completa.luces.roja


def test_byte_a_byte():
    parser = ParserTramas()
    tramas = []
    for b in construir_trama(BIT_VERDE) + construir_trama(0):
        tramas += parser.alimentar(bytes([b]))
    assert [t.valida for t in tramas] == [True, True]


def test_resincroniza_tras_ff_falso_en_la_basura():
    """Un 0xFF suelto antes de una trama buena cuesta a lo más una inválida."""
    parser = ParserTramas()
    tramas = parser.alimentar(bytes([0xFF, 0x10, 0x20]) + construir_trama(BIT_ROJA))
    assert tramas[-1].valida and tramas[-1].luces.roja
    assert sum(1 for t in tramas if not t.valida) <= 1


def test_trama_con_ff_en_el_cuerpo_se_acepta_si_el_checksum_cuadra():
    cuerpo = bytearray(9)
    cuerpo[0] = 0xFF
    cuerpo[1] = 0xFF  # un 0xFF en medio de la trama no la rompe
    cuerpo[5] = BIT_ROJA
    trama = bytes(cuerpo) + bytes([calcular_checksum(bytes(cuerpo))])
    (resultado,) = ParserTramas().alimentar(trama)
    assert resultado.valida and resultado.luces.roja
