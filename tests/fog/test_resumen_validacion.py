"""L02 — resumen de validación, exportación de evidencia y GET
/validaciones/{evento_id}/resumen.

Las pruebas de métricas y de renderizado no necesitan base. Las de punta a
punta usan la app completa con PostgreSQL real (una base por módulo, ver
conftest.py: `crear_app`).
"""

import csv
import json
import math
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from fog.application.resumir_validacion import ResumirValidacion
from fog.domain.evidencia import LineaEvidencia
from fog.domain.resumen_validacion import (
    banda_landis_koch,
    cohen_kappa,
    matriz_confusion,
    resumen_latencia,
    resumen_latencia_inferencia,
    resumir_validacion,
)
from fog.domain.models import ExtractedFeatures
from fog.infrastructure.evidencia.exportador import (
    ExportadorEvidencia,
    _celda,
    renderizar_md,
)
from fog.infrastructure.evidencia.fuente_modelo_m01 import FuenteModeloM01
from tests.fog.conftest import VEREDICTO_DEFAULT

CAMPOS_L01 = [
    "ts", "evento_id", "revision_id", "validacion", "modelo", "luz_A", "luz_B",
    "disponible", "motivo", "clase_sugerida", "confianza", "latencia_ms",
    "decision", "clase_final_arbitro", "concordancia", "hash_auditoria",
    "latencia_inferencia_ms", "t_luz_a_ms", "t_luz_b_ms",
]
LOG_M01 = Path(__file__).resolve().parents[3] / "dataset/lstm_6class/EXPERIMENT_LOG.md"


def _linea(
    sugerida, final, *, validacion="V1", disponible=True, motivo=None,
    decision="mantener", latencia=100, inferencia=None,
) -> LineaEvidencia:
    return LineaEvidencia(
        ts="2026-09-29T12:00:00+00:00", evento_id="e", revision_id=str(uuid.uuid4()),
        validacion=validacion, modelo="m", luz_A=True, luz_B=False,
        disponible=disponible, motivo=motivo, clase_sugerida=sugerida,
        confianza=0.7 if disponible else None, latencia_ms=latencia,
        decision=decision, clase_final_arbitro=final,
        concordancia=None, hash_auditoria="h", latencia_inferencia_ms=inferencia,
        t_luz_a_ms=300, t_luz_b_ms=None,
    )


# ---------------------------------------------------------------------------
# κ de Cohen
# ---------------------------------------------------------------------------
def test_kappa_coincide_con_el_caso_calculado_a_mano():
    # 50 revisiones, dos clases. Sistema/árbitro: AA 20, AB 5, BA 10, BB 15.
    # po = 35/50 = 0.7; sistema A=25, B=25; árbitro A=30, B=20;
    # pe = (25·30 + 25·20) / 50² = 0.5; κ = (0.7 − 0.5) / (1 − 0.5) = 0.4.
    sistema = ["AttackA"] * 25 + ["RiposteB"] * 25
    arbitro = (
        ["AttackA"] * 20 + ["RiposteB"] * 5 + ["AttackA"] * 10 + ["RiposteB"] * 15
    )

    r = cohen_kappa(sistema, arbitro)

    assert r["calculable"] is True
    assert r["kappa"] == pytest.approx(0.4)
    assert r["banda"] == "aceptable"  # 0.21 a 0.40
    assert r["cumple"] is False
    assert r["umbral"] == 0.61


def test_kappa_de_seis_revisiones_a_mano():
    # Pares: AA, AA, A→RB, RB→RB, RB→RB, RB→A. n=6, aciertos=4 (po=2/3);
    # sistema A=3, RB=3; árbitro A=3, RB=3 → pe=0.5; κ=(2/3−1/2)/(1/2)=1/3.
    sistema = ["AttackA", "AttackA", "AttackA", "RiposteB", "RiposteB", "RiposteB"]
    arbitro = ["AttackA", "AttackA", "RiposteB", "RiposteB", "RiposteB", "AttackA"]

    r = cohen_kappa(sistema, arbitro)

    assert r["kappa"] == pytest.approx(1 / 3, abs=1e-4)
    assert r["banda"] == "aceptable"


def test_kappa_perfecto_y_negativo():
    dos = ["AttackA", "RiposteB"]
    assert cohen_kappa(dos, dos)["kappa"] == 1.0
    assert cohen_kappa(dos, dos)["banda"] == "casi perfecta"
    assert cohen_kappa(dos, dos)["cumple"] is True
    opuesto = cohen_kappa(dos, ["RiposteB", "AttackA"])
    assert opuesto["kappa"] == -1.0
    assert opuesto["banda"] == "pobre"


@pytest.mark.parametrize(
    "sistema, arbitro, texto",
    [
        ([], [], "N = 0"),
        (["AttackA"], ["AttackA"], "N = 1"),
        (["AttackA", "AttackA"], ["AttackA", "AttackA"], "una sola clase"),
    ],
)
def test_kappa_no_calculable_no_devuelve_nan_ni_cero(sistema, arbitro, texto):
    r = cohen_kappa(sistema, arbitro)

    assert r["calculable"] is False
    assert r["kappa"] is None and r["banda"] is None and r["cumple"] is None
    assert texto in r["motivo"]
    assert "NaN" not in json.dumps(r)


def test_kappa_con_clases_distintas_en_cada_lado_es_calculable():
    # Solo una clase por lado pero distinta: pe = 0 y κ = 0 está definido.
    r = cohen_kappa(["AttackA"] * 3, ["RiposteB"] * 3)

    assert r["calculable"] is True
    assert r["kappa"] == 0.0


@pytest.mark.parametrize(
    "kappa, banda",
    [
        (-0.01, "pobre"), (0.0, "leve"), (0.20, "leve"), (0.21, "aceptable"),
        (0.40, "aceptable"), (0.41, "moderada"), (0.60, "moderada"),
        (0.61, "sustancial"), (0.80, "sustancial"), (0.81, "casi perfecta"),
        (1.0, "casi perfecta"),
    ],
)
def test_bandas_de_landis_y_koch(kappa, banda):
    assert banda_landis_koch(kappa) == banda


def test_kappa_coincide_con_scikit_learn_si_esta_disponible():
    sklearn_metrics = pytest.importorskip("sklearn.metrics")
    sistema = ["AttackA", "AttackB", "RiposteA", "AttackA", "ContrattackB", "RiposteA"]
    arbitro = ["AttackA", "AttackA", "RiposteA", "RiposteA", "ContrattackB", "AttackB"]

    r = cohen_kappa(sistema, arbitro)

    assert r["kappa"] == pytest.approx(
        sklearn_metrics.cohen_kappa_score(sistema, arbitro), abs=1e-4
    )


# ---------------------------------------------------------------------------
# Latencia, matriz y resumen por validación
# ---------------------------------------------------------------------------
def test_latencia_mediana_p95_maximo_y_porcentaje():
    latencias = list(range(1000, 21000, 1000))  # 20 valores: 1 s ... 20 s
    latencias[-1] = 70_000  # uno por encima de 60 s

    r = resumen_latencia(latencias, 0)

    assert (r["n_total"], r["n_disponibles"], r["n_no_disponibles"]) == (20, 20, 0)
    assert r["mediana_ms"] == 10_500  # promedio de los dos centrales
    assert r["p95_ms"] == 19_000  # rango más cercano: ceil(0.95·20) = 19.º
    assert r["p95_excede_umbral"] is False
    assert r["max_ms"] == 70_000
    assert r["pct_le_60s"] == 95.0
    assert r["cumple"] is True  # p95 ≤ 60 s (RNF-04)


def test_latencia_inferencia_mediana_p95_maximo_y_porcentaje():
    # 20 valores: 11 ... 30 ms, más uno por encima de 50 ms en la cola.
    latencias = list(range(11, 31))
    latencias[-1] = 80
    r = resumen_latencia_inferencia(latencias)

    assert r["n_disponibles"] == 20 and r["n_medidas"] == 20 and r["sin_medicion"] == 0
    assert r["mediana_ms"] == 20.5  # promedio de los dos centrales (20 y 21)
    assert r["p95_ms"] == 29  # rango más cercano: ceil(0.95 * 20) = 19.º valor
    assert r["max_ms"] == 80
    assert r["pct_le_50ms"] == 95.0
    assert r["umbral_ms"] == 50
    assert r["cumple"] is True


def test_latencia_inferencia_p95_sobre_50ms_no_cumple():
    r = resumen_latencia_inferencia([10] * 18 + [60, 950])  # el 19.º es 60

    assert r["p95_ms"] == 60
    assert r["cumple"] is False
    assert r["pct_le_50ms"] == 90.0


def test_latencia_inferencia_sin_medicion_queda_fuera_y_sin_datos_es_nula():
    r = resumen_latencia_inferencia([12, None, 14])

    assert (r["n_disponibles"], r["n_medidas"], r["sin_medicion"]) == (3, 2, 1)
    assert r["mediana_ms"] == 13 and r["max_ms"] == 14 and r["p95_ms"] == 14

    vacio = resumen_latencia_inferencia([None, None])
    assert (vacio["n_medidas"], vacio["sin_medicion"]) == (0, 2)
    assert vacio["mediana_ms"] is None and vacio["p95_ms"] is None
    assert vacio["max_ms"] is None and vacio["pct_le_50ms"] is None
    assert vacio["cumple"] is None
    assert resumen_latencia_inferencia([])["cumple"] is None


def test_resumen_separa_la_latencia_de_inferencia_por_validacion():
    v1 = [_linea("AttackA", "AttackA", inferencia=x) for x in (10, 20, 30)]
    v1.append(_linea(None, "AttackB", disponible=False, motivo="timeout", inferencia=None))
    v2 = [_linea("AttackA", "AttackA", validacion="V2", inferencia=x) for x in (40, 70)]

    m1 = resumir_validacion(v1)["latencia_inferencia"]
    m2 = resumir_validacion(v2)["latencia_inferencia"]

    assert (m1["n_disponibles"], m1["mediana_ms"], m1["max_ms"]) == (3, 20, 30)
    assert m1["cumple"] is True and m1["pct_le_50ms"] == 100.0
    assert (m2["n_disponibles"], m2["mediana_ms"], m2["max_ms"]) == (2, 55, 70)
    assert m2["cumple"] is False and m2["pct_le_50ms"] == 50.0


def test_latencia_p95_sobre_60s_no_cumple_y_sin_datos_es_nula():
    r = resumen_latencia([1000] * 5 + [90_000] * 5, 0)
    assert r["cumple"] is False and r["p95_ms"] == 90_000
    vacio = resumen_latencia([], 0)
    assert vacio["n_total"] == 0 and vacio["p95_ms"] is None and vacio["cumple"] is None


def test_latencia_mediana_y_maximo_solo_sobre_disponibles():
    # Las no disponibles no aportan latencia a la mediana ni al máximo.
    r = resumen_latencia([1000, 2000, 3000], 1)

    assert r["mediana_ms"] == 2000 and r["max_ms"] == 3000
    assert (r["n_total"], r["n_disponibles"], r["n_no_disponibles"]) == (4, 3, 1)


def test_latencia_no_disponibles_cuentan_como_mas_de_60s_en_pct_y_p95():
    # 1 no disponible de 20 (5 %): el p95 (19.º) sigue siendo una disponible,
    # pero el % ≤ 60 s se calcula sobre las 20.
    r = resumen_latencia([1000] * 19, 1)

    assert r["p95_ms"] == 1000 and r["p95_excede_umbral"] is False
    assert r["pct_le_60s"] == 95.0
    assert r["cumple"] is True


def test_latencia_mas_del_5_por_ciento_no_disponible_reporta_p95_sobre_60s():
    # 2 no disponibles de 20 (10 %): el p95 cae en una no disponible.
    r = resumen_latencia([1000] * 18, 2)

    assert r["p95_ms"] is None and r["p95_excede_umbral"] is True
    assert r["pct_le_60s"] == 90.0
    assert r["cumple"] is False
    assert r["mediana_ms"] == 1000 and r["max_ms"] == 1000


def test_latencia_solo_no_disponibles_no_inventa_mediana_ni_maximo():
    r = resumen_latencia([], 3)

    assert r["mediana_ms"] is None and r["max_ms"] is None
    assert r["p95_excede_umbral"] is True and r["pct_le_60s"] == 0.0
    assert r["cumple"] is False


def test_latencia_disponible_sin_medicion_queda_fuera_y_se_cuenta():
    r = resumen_latencia([1000, None], 0)

    assert r["n_total"] == 2 and r["sin_medicion"] == 1
    assert r["mediana_ms"] == 1000 and r["pct_le_60s"] == 100.0


def test_matriz_de_confusion_6x6_con_sistema_en_filas():
    m = matriz_confusion(["AttackA", "AttackA", "RiposteB"], ["AttackA", "RiposteB", "AttackA"])

    assert m["clases"] == [
        "AttackA", "AttackB", "ContrattackA", "ContrattackB", "RiposteA", "RiposteB",
    ]
    assert len(m["matriz"]) == 6 and all(len(f) == 6 for f in m["matriz"])
    assert m["matriz"][0][0] == 1  # sistema AttackA, árbitro AttackA
    assert m["matriz"][0][5] == 1  # sistema AttackA, árbitro RiposteB
    assert m["matriz"][5][0] == 1  # sistema RiposteB, árbitro AttackA
    assert sum(map(sum, m["matriz"])) == 3


def test_resumen_de_validacion_excluye_anuladas_y_no_disponibles_del_kappa():
    lineas = [
        _linea("AttackA", "AttackA"),
        _linea("AttackA", "RiposteB", decision="cambiar"),
        _linea("AttackA", None, decision="anular"),
        _linea(None, "AttackB", disponible=False, motivo="pose_incompleta"),
        _linea(None, "AttackB", disponible=False, motivo="timeout", latencia=61_000),
    ]

    r = resumir_validacion(lineas)

    assert r["n_revisiones"] == 5 and r["disponibles"] == 3
    assert r["no_disponibles"]["n"] == 2
    assert r["no_disponibles"]["por_motivo"]["pose_incompleta"] == 1
    assert r["no_disponibles"]["por_motivo"]["timeout"] == 1
    assert set(r["no_disponibles"]["por_motivo"]) == {
        "pose_incompleta", "confianza_baja", "clase_fuera_mvp", "timeout",
        "sin_senal_favero", "mensaje_invalido",
    }
    assert r["kappa"]["n"] == 2
    assert r["concordancia"] == {"n": 2, "pct": 50.0}
    assert sum(map(sum, r["matriz_confusion"]["matriz"])) == 2
    # 3 disponibles (100 ms) y 2 no disponibles: el máximo es solo de disponibles.
    lat = r["latencia"]
    assert (lat["n_total"], lat["n_disponibles"], lat["n_no_disponibles"]) == (5, 3, 2)
    assert lat["max_ms"] == 100 and lat["p95_excede_umbral"] is True
    assert lat["pct_le_60s"] == 60.0 and lat["cumple"] is False


def test_resumen_sin_revisiones_no_inventa_valores():
    r = resumir_validacion([])

    assert r["n_revisiones"] == 0
    assert r["kappa"]["calculable"] is False
    assert r["concordancia"]["pct"] is None
    assert r["latencia"]["mediana_ms"] is None
    assert not any(isinstance(v, float) and math.isnan(v) for v in r["latencia"].values())


# ---------------------------------------------------------------------------
# Tabla M01
# ---------------------------------------------------------------------------
def test_tabla_m01_toma_solo_la_seccion_resumen(tmp_path):
    log = tmp_path / "EXPERIMENT_LOG.md"
    log.write_text(
        "# Log\n\n## Otra\ntexto\n\n---\n\n## Tabla resumen — T2 vs T3\n\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n\n---\n\n## Después\nno\n",
        encoding="utf-8",
    )

    tabla = FuenteModeloM01(log).tabla_resumen_m01()

    assert tabla.startswith("## Tabla resumen — T2 vs T3")
    assert "| 1 | 2 |" in tabla and "Después" not in tabla


def test_tabla_m01_ausente_o_ambigua_es_none(tmp_path):
    assert FuenteModeloM01(None).tabla_resumen_m01() is None
    assert FuenteModeloM01(tmp_path / "no_existe.md").tabla_resumen_m01() is None
    doble = tmp_path / "doble.md"
    doble.write_text("## Tabla resumen A\nx\n---\n## Tabla resumen B\ny\n", encoding="utf-8")
    assert FuenteModeloM01(doble).tabla_resumen_m01() is None


@pytest.mark.skipif(not LOG_M01.is_file(), reason="dataset/ no está junto al backend")
def test_tabla_m01_del_repositorio_se_localiza():
    tabla = FuenteModeloM01(LOG_M01).tabla_resumen_m01()

    assert tabla.startswith("## Tabla resumen — T2 (baseline, N=10) vs T3")
    assert "F1 macro sistema" in tabla


# ---------------------------------------------------------------------------
# Punta a punta: app completa con PostgreSQL real
# ---------------------------------------------------------------------------
def _revisar(app, sugerida, decision, final, *, disponible=True, fuente="simulado"):
    """Sube un clip con la sugerencia dada y registra el veredicto."""
    subscriber = app.container.verdict_subscriber()
    if sugerida is not None:
        lado = "ROJ" if sugerida.endswith("A") else "VER"
        subscriber._verdict = replace(
            VEREDICTO_DEFAULT, action=sugerida, fencer=lado, probs=None
        )
    extractor = app.container.feature_extractor()
    extractor.result = (
        ExtractedFeatures(sequence=None, stats={"error": "tracking no pudo asignar IDs A/B"})
        if not disponible
        else app.feature_ok
    )
    clip = app.subir_clip(app.match_id).json()
    assert clip["disponible"] is disponible
    revision_id = clip["revision_id"]
    if fuente == "favero":
        app.sql.ejecutar(
            "UPDATE sabre.tocado SET fuente = 'favero' WHERE id = "
            "(SELECT tocado_id FROM sabre.revision_var WHERE id = :r)",
            r=revision_id,
        )
    cuerpo = {"decision": decision, "clase_final": final}
    resp = app.veredicto(revision_id, **cuerpo)
    assert resp.status_code == 200, resp.text
    return revision_id


@pytest.fixture
def sesion(crear_app):
    """Sesión piloto con 8 revisiones: 6 comparables en V1 (κ = 1/3 a mano),
    una anulada y una no disponible en V1, y 2 en V2 (κ = 1)."""
    app = crear_app()
    app.feature_ok = app.container.feature_extractor().result
    app.match_id = app.configurar()
    ids = {}
    for etiqueta, sugerida, decision, final, extra in [
        ("v1_1", "AttackA", "mantener", "AttackA", {}),
        ("v1_2", "AttackA", "mantener", "AttackA", {}),
        ("v1_3", "AttackA", "cambiar", "RiposteB", {}),
        ("v1_4", "RiposteB", "mantener", "RiposteB", {}),
        ("v1_5", "RiposteB", "mantener", "RiposteB", {}),
        ("v1_6", "RiposteB", "cambiar", "AttackA", {}),
        ("v1_anulada", "AttackA", "anular", None, {}),
        ("v1_nodisp", None, "mantener", "AttackB", {"disponible": False}),
        ("v2_1", "AttackA", "mantener", "AttackA", {"fuente": "favero"}),
        ("v2_2", "RiposteB", "mantener", "RiposteB", {"fuente": "favero"}),
    ]:
        ids[etiqueta] = _revisar(app, sugerida, decision, final, **extra)
    app.ids = ids
    return app


def _resumen(app) -> dict:
    resp = app.client.get(f"/validaciones/{app.evento_id}/resumen")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_resumen_desde_la_base_separa_v1_y_v2(sesion):
    r = _resumen(sesion)

    v1, v2 = r["por_validacion"]["V1"], r["por_validacion"]["V2"]
    assert (v1["n_revisiones"], v1["disponibles"]) == (8, 7)
    assert v1["no_disponibles"] == {
        "n": 1,
        "por_motivo": {**dict.fromkeys(
            ["pose_incompleta", "confianza_baja", "clase_fuera_mvp", "timeout",
             "sin_senal_favero", "mensaje_invalido"], 0), "pose_incompleta": 1},
    }
    # κ sobre disponibles no anuladas: las 6 comparables de V1.
    assert v1["kappa"]["n"] == 6
    assert v1["kappa"]["kappa"] == pytest.approx(1 / 3, abs=1e-4)
    assert v1["kappa"]["banda"] == "aceptable" and v1["kappa"]["cumple"] is False
    assert v1["concordancia"] == {"n": 6, "pct": pytest.approx(66.67)}
    assert v1["matriz_confusion"]["matriz"][0][0] == 2  # AttackA / AttackA
    assert v1["matriz_confusion"]["matriz"][5][0] == 1  # RiposteB / AttackA
    assert v1["latencia"]["n_total"] == 8 and v1["latencia"]["n_disponibles"] == 7
    assert v1["latencia"]["n_no_disponibles"] == 1

    assert (v2["n_revisiones"], v2["disponibles"]) == (2, 2)
    assert v2["kappa"]["kappa"] == 1.0 and v2["kappa"]["cumple"] is True
    assert v2["kappa"]["banda"] == "casi perfecta"
    assert r["conciliacion"]["n_base"] == 10


def test_conciliacion_sin_diferencias_e_integridad_ok(sesion):
    r = _resumen(sesion)

    assert r["conciliacion"] == {
        "n_base": 10, "n_jsonl": 10, "jsonl_presente": True, "lineas_ilegibles": 0,
        "faltantes_en_jsonl": [], "sobrantes_en_jsonl": [],
    }
    assert r["integridad"]["fn_verificar_auditoria"] == "ok"
    assert r["integridad"]["integra"] is True and r["integridad"]["registros_alterados"] == 0


def test_conciliacion_reporta_faltantes_y_sobrantes_sin_corregir_el_jsonl(sesion):
    ruta = sesion.evidencia_dir / f"{sesion.evento_id}.jsonl"
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    perdida = json.loads(lineas[0])["revision_id"]
    intrusa = str(uuid.uuid4())
    editado = lineas[1:] + [json.dumps({"revision_id": intrusa}), "no es json"]
    ruta.write_text("\n".join(editado) + "\n", encoding="utf-8")
    antes = ruta.read_bytes()

    c = _resumen(sesion)["conciliacion"]

    assert c["n_base"] == 10 and c["n_jsonl"] == 10  # 9 originales + 1 intrusa
    assert c["faltantes_en_jsonl"] == [perdida]
    assert c["sobrantes_en_jsonl"] == [intrusa]
    assert c["lineas_ilegibles"] == 1
    assert ruta.read_bytes() == antes  # no se corrige el JSONL


def test_las_metricas_no_dependen_del_jsonl(sesion):
    con_jsonl = _resumen(sesion)["por_validacion"]
    (sesion.evidencia_dir / f"{sesion.evento_id}.jsonl").unlink()

    r = _resumen(sesion)

    assert r["por_validacion"] == con_jsonl
    assert r["conciliacion"]["jsonl_presente"] is False
    assert r["conciliacion"]["n_jsonl"] == 0
    assert len(r["conciliacion"]["faltantes_en_jsonl"]) == 10


def test_integridad_alterada_se_reporta(sesion):
    # La verificación recorre la cadena completa de la base del módulo: la
    # alteración se deshace al terminar para no afectar a las demás pruebas.
    def alterar(sql_snapshot: str) -> None:
        sesion.sql.ejecutar(
            "ALTER TABLE sabre.registro_auditoria DISABLE TRIGGER tg_auditoria_inmutable"
        )
        try:
            sesion.sql.ejecutar(
                f"UPDATE sabre.registro_auditoria SET snapshot = {sql_snapshot} "
                "WHERE seq = (SELECT max(seq) FROM sabre.registro_auditoria)"
            )
        finally:
            sesion.sql.ejecutar(
                "ALTER TABLE sabre.registro_auditoria ENABLE TRIGGER tg_auditoria_inmutable"
            )

    alterar("snapshot || '{\"x\": 1}'::jsonb")
    try:
        i = _resumen(sesion)["integridad"]
    finally:
        alterar("snapshot - 'x'")

    assert i["fn_verificar_auditoria"] == "alterada"
    assert i["integra"] is False and i["registros_alterados"] >= 1
    assert _resumen(sesion)["integridad"]["fn_verificar_auditoria"] == "ok"


def test_evidencia_del_modelo_sin_recalcular_f1(sesion):
    sesion.sql.ejecutar(
        "UPDATE sabre.modelo_version SET f1_macro_test = 0.4986, kappa_piloto = 0.5 "
        "WHERE activo"
    )

    m = _resumen(sesion)["modelo"]

    assert m["activo"]["f1_macro_test"] == pytest.approx(0.4986)
    assert m["activo"]["kappa_piloto"] == pytest.approx(0.5)
    assert m["activo"]["num_clases"] == 6
    assert m["modelos_en_revisiones"] == [m["activo"]["nombre"]]
    assert "test set" in m["nota"]
    assert "tabla_m01" in m  # None: la prueba no configura M01_EXPERIMENT_LOG
    # La cifra del checkpoint se rotula; la reportable es la media de la serie.
    assert m["activo"]["f1_macro_test_rotulo"] == "checkpoint desplegado (test)"
    assert "media de la serie" in m["nota"]


def test_md_rotula_el_f1_como_checkpoint_y_remite_a_la_media_de_la_serie(sesion):
    sesion.sql.ejecutar(
        "UPDATE sabre.modelo_version SET f1_macro_test = 0.5249 WHERE activo"
    )
    md = renderizar_md(_resumen(sesion))

    assert "F1 macro checkpoint desplegado (test) 0.5249" in md
    assert "cifra reportable de RNF-03: media de la serie (N = 10)" in md


def _resumidor(app, ahora: datetime) -> ResumirValidacion:
    c = app.container
    return ResumirValidacion(
        consulta=c.consulta_evidencia_repository(),
        lector=c.lector_evidencia(),
        verificador=c.verificador_auditoria(),
        modelos=c.modelo_version_repository(),
        fuente_modelo=c.fuente_evidencia_modelo(),
        reloj=lambda: ahora,
    )


async def test_exportacion_genera_los_tres_archivos_y_es_idempotente(sesion, tmp_path):
    exportador = ExportadorEvidencia(tmp_path / "salida")
    primero = await _resumidor(sesion, datetime(2026, 9, 29, 20, 0, tzinfo=timezone.utc)).execute(
        sesion.evento_id
    )
    carpeta = exportador.exportar(primero)

    assert carpeta == tmp_path / "salida" / str(sesion.evento_id)
    assert sorted(p.name for p in carpeta.iterdir()) == [
        "resumen.json", "resumen.md", "revisiones.csv",
    ]
    contenido_1 = {p.name: p.read_text(encoding="utf-8") for p in carpeta.iterdir()}

    segundo = await _resumidor(sesion, datetime(2026, 9, 29, 21, 30, tzinfo=timezone.utc)).execute(
        sesion.evento_id
    )
    exportador.exportar(segundo)
    contenido_2 = {p.name: p.read_text(encoding="utf-8") for p in carpeta.iterdir()}

    assert contenido_1["revisiones.csv"] == contenido_2["revisiones.csv"]
    for nombre in ("resumen.json", "resumen.md"):
        assert contenido_1[nombre] != contenido_2[nombre]
        assert contenido_1[nombre].replace("20:00:00", "21:30:00") == contenido_2[nombre]
    json_1, json_2 = (json.loads(c["resumen.json"]) for c in (contenido_1, contenido_2))
    assert {k for k in json_1 if json_1[k] != json_2[k]} == {"generado_en"}


async def test_revisiones_csv_tiene_los_16_campos_de_l01_desde_la_base(sesion, tmp_path):
    resultado = await _resumidor(sesion, datetime.now(timezone.utc)).execute(sesion.evento_id)
    carpeta = ExportadorEvidencia(tmp_path).exportar(resultado)

    with (carpeta / "revisiones.csv").open(encoding="utf-8") as f:
        filas = list(csv.DictReader(f))

    assert list(filas[0]) == CAMPOS_L01
    assert len(filas) == 10
    jsonl = [
        json.loads(x)
        for x in (sesion.evidencia_dir / f"{sesion.evento_id}.jsonl").read_text().splitlines()
    ]
    por_revision = {f["revision_id"]: f for f in filas}
    for linea in jsonl:  # con el JSONL completo, la base y el JSONL coinciden
        esperado = {k: _celda(v) for k, v in linea.items()}
        assert por_revision[linea["revision_id"]] == esperado
    assert {f["validacion"] for f in filas} == {"V1", "V2"}
    anulada = por_revision[sesion.ids["v1_anulada"]]
    assert (anulada["decision"], anulada["clase_final_arbitro"], anulada["concordancia"]) == (
        "anular", "", "",
    )


async def test_resumen_md_cabe_en_una_pantalla_y_lleva_los_umbrales(sesion):
    resultado = await _resumidor(sesion, datetime.now(timezone.utc)).execute(sesion.evento_id)

    md = renderizar_md(resultado.resumen)

    assert len(md.splitlines()) <= 50
    for esperado in (
        "## V1", "## V2", "κ de Cohen", "umbral 0.61", "p95 ≤ 60000 ms: cumple",
        "Conciliación", "Faltantes en JSONL: ninguno", "sabre.fn_verificar_auditoria: ok",
        "Latencia de inferencia", "umbral p95 ≤ 50 ms",
    ):
        assert esperado in md


def test_bloque_md_muestra_denominador_y_p95_sobre_60s():
    from fog.infrastructure.evidencia.exportador import _bloque_validacion

    lineas = [_linea("AttackA", "AttackA")] * 18 + [
        _linea(None, None, disponible=False, motivo="timeout")
    ] * 2

    texto = "\n".join(_bloque_validacion("V1", resumir_validacion(lineas)))

    assert "N total=20 · disponibles=18 · no disponibles=2" in texto
    assert "p95 > 60 s" in texto
    assert "p95 ≤ 60000 ms: no cumple" in texto


async def test_endpoint_devuelve_el_contenido_de_resumen_json(sesion, tmp_path):
    api = _resumen(sesion)

    resultado = await _resumidor(sesion, datetime.now(timezone.utc)).execute(sesion.evento_id)
    en_disco = json.loads(
        (ExportadorEvidencia(tmp_path).exportar(resultado) / "resumen.json").read_text(
            encoding="utf-8"
        )
    )

    api.pop("generado_en"), en_disco.pop("generado_en")
    assert api == en_disco


def test_evento_inexistente_devuelve_404_y_uuid_invalido_422(crear_app):
    app = crear_app()

    assert app.client.get(f"/validaciones/{uuid.uuid4()}/resumen").status_code == 404
    assert app.client.get("/validaciones/no-es-uuid/resumen").status_code == 422


def test_evento_sin_revisiones_no_calcula_kappa(crear_app):
    app = crear_app()

    r = app.client.get(f"/validaciones/{app.evento_id}/resumen").json()

    for v in ("V1", "V2"):
        assert r["por_validacion"][v]["n_revisiones"] == 0
        assert r["por_validacion"][v]["kappa"]["calculable"] is False
        assert r["por_validacion"][v]["kappa"]["kappa"] is None
    assert r["conciliacion"]["n_base"] == 0 and r["conciliacion"]["jsonl_presente"] is False


def test_script_exportar_evidencia(sesion, database_url, tmp_path, monkeypatch):
    from scripts import exportar_evidencia
    from shared import config

    monkeypatch.setattr(config, "DATABASE_URL", database_url)
    monkeypatch.setattr(config, "EVIDENCE_DIR", str(tmp_path))

    codigo = exportar_evidencia.main(["--evento", str(sesion.evento_id)])

    assert codigo == 0
    carpeta = tmp_path / str(sesion.evento_id)
    assert sorted(p.name for p in carpeta.iterdir()) == [
        "resumen.json", "resumen.md", "revisiones.csv",
    ]
    assert exportar_evidencia.main(["--evento", str(uuid.uuid4())]) == 1
