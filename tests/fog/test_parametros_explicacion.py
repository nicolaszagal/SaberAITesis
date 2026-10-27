"""Carga y validación de los parámetros U1 a U6 del razonamiento (F-035)."""

import json

import pytest

from fog.infrastructure.explicacion.parametros_json import ParametrosExplicacionJson


def test_el_archivo_versionado_trae_los_valores_confirmados_por_el_autor():
    p = ParametrosExplicacionJson().cargar()

    assert p.version == "1"
    assert (p.u1_angulo_min, p.u1_incrementos_min) == (135.0, 3)
    assert (p.u2_umbral, p.u2_frames_sostenidos, p.u2_frames_censura) == (0.010, 3, 3)
    assert p.u3_margen_frames == 1
    assert p.u4_articulos == {
        "Attack": "t.101.2-4", "Contrattack": "t.106", "Riposte": "t.105",
    }
    assert p.u5_masa_atencion == 0.5
    assert (p.u6_max_frases, p.u6_max_caracteres) == (2, 220)


def _escribir(tmp_path, cambios):
    base = json.loads(
        (ParametrosExplicacionJson().__dict__["_ruta"]).read_text(encoding="utf-8")
    )
    base.update(cambios)
    ruta = tmp_path / "params.json"
    ruta.write_text(json.dumps(base), encoding="utf-8")
    return ruta


def test_un_parametro_faltante_falla_en_vez_de_asumir_un_valor(tmp_path):
    ruta = _escribir(tmp_path, {"u3": {}})
    with pytest.raises(ValueError, match="faltante"):
        ParametrosExplicacionJson(ruta).cargar()


@pytest.mark.parametrize(
    "cambios",
    [
        {"u2": {"umbral_rel_vel": 0, "frames_sostenidos": 3, "frames_censura": 3}},
        {"u5": {"masa_atencion": 1.5}},
        {"u4": {"articulos": {"Attack": "t.101.2-4"}}},
    ],
)
def test_valores_fuera_de_rango_fallan(tmp_path, cambios):
    with pytest.raises(ValueError):
        ParametrosExplicacionJson(_escribir(tmp_path, cambios)).cargar()
