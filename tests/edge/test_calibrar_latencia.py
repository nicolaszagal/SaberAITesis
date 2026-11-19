"""Calibración del desfase serie ↔ video (EDGE01) con datos sintéticos de desfase conocido."""

from __future__ import annotations

import json

import numpy as np
import pytest

from edge.calibrar_latencia import (
    brillo_roi,
    calibrar,
    emparejar,
    guardar,
    resumir,
    subidas_camara,
    umbral_automatico,
)
from edge.captura.tocados import cargar_desfase_ms
from edge.favero.lector import Flanco

PERIODO_NS = 1_000_000_000 // 30


def _sesion(n_toques: int, desfase_ms: float, ruido_serie_ms: float = 0.0, semilla: int = 7):
    """Flancos serie y brillo de cámara de una lámpara que el video ve `desfase_ms` después del serie."""
    rng = np.random.default_rng(semilla)
    flancos, serie = [], []
    luz_encendida_en: list[tuple[int, int]] = []
    for k in range(n_toques):
        s = 2_000_000_000 + k * 3_000_000_000
        s_medido = s + int(rng.uniform(-ruido_serie_ms, ruido_serie_ms) * 1e6)
        flancos.append(Flanco("A", "ROJA", s_medido))
        luz_encendida_en.append((s + int(desfase_ms * 1e6), s + int(desfase_ms * 1e6) + 1_000_000_000))
    t = 0
    fin = 2_000_000_000 + n_toques * 3_000_000_000
    while t < fin:
        encendida = any(a <= t < b for a, b in luz_encendida_en)
        serie.append((t, 230.0 if encendida else 15.0))
        t += PERIODO_NS
    return flancos, serie


def test_recupera_el_desfase_conocido_dentro_de_un_frame():
    flancos, serie = _sesion(20, desfase_ms=120.0)
    r = calibrar(flancos, {"ROJA": serie}, {})
    assert r["n"] == 20
    # la cámara muestrea cada 33 ms: el error de cuantización es < 1 frame
    assert r["desfase_ms"] == pytest.approx(120.0, abs=1000 / 30)
    assert r["desviacion_ms"] < 1000 / 30
    assert r["por_luz"]["ROJA"]["sin_pareja"] == 0


def test_desfase_negativo_cuando_el_serie_llega_despues_que_el_video():
    flancos, serie = _sesion(20, desfase_ms=-60.0)
    r = calibrar(flancos, {"ROJA": serie}, {})
    assert r["desfase_ms"] == pytest.approx(-60.0, abs=1000 / 30)


def test_el_ruido_del_serie_se_ve_en_la_dispersion():
    """Con ±21 ms de incertidumbre serie (media trama) la desviación sube respecto del caso limpio."""
    limpio = calibrar(*_solo(_sesion(40, 100.0)), {})
    ruidoso = calibrar(*_solo(_sesion(40, 100.0, ruido_serie_ms=21.0)), {})
    assert ruidoso["desviacion_ms"] > limpio["desviacion_ms"]
    assert ruidoso["residuo_max_ms"] < 21 + 1000 / 30 + 1


def _solo(sesion):
    flancos, serie = sesion
    return flancos, {"ROJA": serie}


def test_toque_sin_pareja_se_cuenta():
    flancos, serie = _sesion(5, 100.0)
    flancos.append(Flanco("A", "ROJA", 900_000_000_000))  # luz que la cámara nunca vio
    r = calibrar(flancos, {"ROJA": serie}, {})
    assert r["n"] == 5 and r["por_luz"]["ROJA"]["sin_pareja"] == 1


def test_sin_toques_emparejados_falla_con_valueerror():
    with pytest.raises(ValueError):
        calibrar([Flanco("A", "ROJA", 5_000_000_000)], {"ROJA": [(t * PERIODO_NS, 10.0) for t in range(100)]}, {})


def test_subidas_y_umbral_automatico():
    serie = [(0, 10.0), (1, 10.0), (2, 200.0), (3, 210.0), (4, 12.0), (5, 220.0)]
    assert umbral_automatico([b for _, b in serie]) == 115.0
    assert subidas_camara(serie, 115.0) == [2, 5]
    assert subidas_camara(serie, 250.0) == []


def test_emparejar_usa_cada_subida_una_vez():
    d, sin = emparejar([0, 100_000_000], [50_000_000])
    assert d == [50.0] and sin == 1


def test_resumen_estadistico():
    r = resumir([10.0, 20.0, 30.0])
    assert r["desfase_ms"] == 20.0 and r["minimo_ms"] == 10.0 and r["maximo_ms"] == 30.0
    assert r["residuo_max_ms"] == 10.0 and r["desviacion_ms"] == pytest.approx(10.0)
    with pytest.raises(ValueError):
        resumir([])


def test_brillo_roi_mide_solo_la_region():
    img = np.zeros((100, 100, 3), np.uint8)
    img[10:20, 30:40] = 200
    assert brillo_roi(img, (30, 10, 10, 10)) == 200.0
    assert brillo_roi(img, (0, 0, 10, 10)) == 0.0


def test_guardar_por_camara_y_leerlo_en_la_captura(tmp_path):
    archivo = tmp_path / "datos" / "lat.json"
    guardar(archivo, "frontal", {"desfase_ms": 87.5, "n": 20})
    guardar(archivo, "otra", {"desfase_ms": 10.0, "n": 20})
    guardar(archivo, "frontal", {"desfase_ms": 90.0, "n": 25})  # recalibrar reemplaza solo esa
    assert json.loads(archivo.read_text())["otra"]["desfase_ms"] == 10.0
    assert cargar_desfase_ms(archivo, "frontal") == 90.0
