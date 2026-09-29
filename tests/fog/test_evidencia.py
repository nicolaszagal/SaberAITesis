"""L01 — log de evidencia (`sabre.evidencia`) y log técnico.

La prueba de punta a punta usa la app completa con PostgreSQL real
(ver conftest.py: `crear_app`); las de la línea y del log técnico no
necesitan base.
"""

import json
import logging
import uuid
from datetime import datetime, timezone

import pytest

from fog.domain.audit_models import (
    Auditoria,
    Clasificacion,
    ModeloVersion,
    Revision,
    Tocado,
    Veredicto,
)
from fog.domain.evidencia import construir_linea
from fog.infrastructure.evidencia.registro_jsonl import RegistroEvidenciaJsonl
from shared.logging_config import configurar_logging_tecnico

CAMPOS = [
    "ts", "evento_id", "revision_id", "validacion", "modelo", "luz_A", "luz_B",
    "disponible", "motivo", "clase_sugerida", "confianza", "latencia_ms",
    "decision", "clase_final_arbitro", "concordancia", "hash_auditoria",
]


def _lineas(app, evento_id) -> list[dict]:
    ruta = app.evidencia_dir / f"{evento_id}.jsonl"
    return [json.loads(x) for x in ruta.read_text(encoding="utf-8").splitlines()]


def test_revision_cerrada_produce_una_linea_con_los_campos_exactos(crear_app):
    app = crear_app()
    match_id = app.configurar()
    clip = app.subir_clip(match_id, has_luz_A="true", has_luz_B="false").json()
    revision_id = clip["revision_id"]
    assert not (app.evidencia_dir / f"{app.evento_id}.jsonl").exists()  # revisión abierta: nada

    resp = app.veredicto(revision_id, decision="mantener", clase_final="AttackA")
    assert resp.status_code == 200, resp.text

    lineas = _lineas(app, app.evento_id)
    assert len(lineas) == 1
    linea = lineas[0]
    assert list(linea) == CAMPOS  # exactamente estos campos, sin extras
    assert linea["evento_id"] == str(app.evento_id)
    assert linea["revision_id"] == revision_id
    assert linea["validacion"] == "V1"
    assert (linea["luz_A"], linea["luz_B"]) == (True, False)
    assert linea["disponible"] is True
    assert linea["motivo"] is None
    assert linea["clase_sugerida"] == "AttackA"
    assert linea["confianza"] == pytest.approx(0.74)
    assert linea["latencia_ms"] is not None
    assert (linea["decision"], linea["clase_final_arbitro"]) == ("mantener", "AttackA")
    assert linea["concordancia"] is True
    # Fuente de verdad: la base
    assert linea["hash_auditoria"] == resp.json()["auditoria_hash"]
    assert linea["ts"] == app.sql.filas(
        "SELECT registrado_en FROM sabre.veredicto WHERE revision_id = :r", r=revision_id
    )[0]["registrado_en"].isoformat()
    modelo = app.sql.filas("SELECT nombre FROM sabre.modelo_version WHERE activo")[0]["nombre"]
    assert linea["modelo"] == modelo


def test_cada_revision_de_un_combate_produce_su_linea(crear_app):
    app = crear_app()
    match_id = app.configurar()
    r1 = app.subir_clip(match_id).json()["revision_id"]
    r2 = app.subir_clip(match_id).json()["revision_id"]

    assert app.veredicto(r1, decision="cambiar", clase_final="RiposteB").status_code == 200
    assert app.veredicto(r2, decision="anular").status_code == 200

    lineas = _lineas(app, app.evento_id)
    assert [x["revision_id"] for x in lineas] == [r1, r2]
    assert lineas[0]["concordancia"] is False  # sugerida AttackA, final RiposteB
    assert lineas[1]["clase_final_arbitro"] is None
    assert lineas[1]["concordancia"] is None  # anulada


def test_clasificacion_no_disponible_tambien_deja_su_linea(crear_app):
    app = crear_app(extraccion_falla=True)
    match_id = app.configurar()
    clip = app.subir_clip(match_id).json()
    assert clip["disponible"] is False

    assert app.veredicto(clip["revision_id"], decision="mantener", clase_final="AttackB").status_code == 200

    (linea,) = _lineas(app, app.evento_id)
    assert list(linea) == CAMPOS
    assert linea["disponible"] is False
    assert linea["motivo"] == "pose_incompleta"
    assert (linea["clase_sugerida"], linea["confianza"]) == (None, None)
    assert linea["clase_final_arbitro"] == "AttackB"
    assert linea["concordancia"] is None


def test_veredicto_rechazado_no_deja_linea(crear_app):
    app = crear_app()
    match_id = app.configurar()
    revision_id = app.subir_clip(match_id).json()["revision_id"]

    assert app.veredicto(revision_id, decision="anular", clase_final="AttackA").status_code == 422

    assert not (app.evidencia_dir / f"{app.evento_id}.jsonl").exists()


def test_fallo_de_escritura_no_revierte_el_veredicto(crear_app):
    app = crear_app()
    match_id = app.configurar()
    revision_id = app.subir_clip(match_id).json()["revision_id"]
    (app.evidencia_dir / f"{app.evento_id}.jsonl").mkdir(parents=True)  # no se puede abrir como archivo

    resp = app.veredicto(revision_id)

    assert resp.status_code == 200, resp.text
    assert app.sql.escalar("SELECT count(*) FROM sabre.registro_auditoria") >= 1


def _entidades(fuente: str, disponible: bool = True):
    ahora = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
    uid = uuid.uuid4
    tocado = Tocado(uid(), uid(), fuente, True, True, None, 300, None, ahora)
    modelo = ModeloVersion(uid(), "m-1", "u", "a" * 64, "yolov8x-pose", 192, 6, "FIE 2026",
                           None, None, None, True, ahora)
    clasificacion = Clasificacion(
        uid(), tocado.id, modelo.id, disponible,
        None if disponible else "confianza_baja",
        "RiposteA" if disponible else None, "A" if disponible else None,
        0.5 if disponible else None, None, "k", "h", None, 40, ahora,
    )
    revision = Revision(uid(), tocado.id, True, uid(), clasificacion.id, ahora, ahora)
    veredicto = Veredicto(uid(), revision.id, "mantener", "RiposteA", uid(), ahora)
    auditoria = Auditoria(1, revision.id, {}, None, "b" * 64, ahora)
    return dict(revision=revision, tocado=tocado, clasificacion=clasificacion,
                veredicto=veredicto, modelo=modelo, auditoria=auditoria)


@pytest.mark.parametrize("fuente,validacion", [("simulado", "V1"), ("favero", "V2")])
def test_validacion_se_deriva_de_tocado_fuente(fuente, validacion):
    linea = construir_linea(evento_id=uuid.uuid4(), **_entidades(fuente))

    assert linea.validacion == validacion
    assert linea.concordancia is True


def test_concordancia_es_null_si_no_disponible():
    linea = construir_linea(evento_id=uuid.uuid4(), **_entidades("simulado", disponible=False))

    assert linea.concordancia is None
    assert linea.motivo == "confianza_baja"


def test_log_tecnico_info_por_defecto_y_librerias_en_warning(monkeypatch):
    monkeypatch.setattr("shared.config.LOG_LEVEL", "INFO")
    for nombre in ("aioice", "aiortc", "uvicorn.access", "ultralytics"):
        logging.getLogger(nombre).setLevel(logging.NOTSET)

    configurar_logging_tecnico()

    assert logging.getLogger().level == logging.INFO
    for nombre in ("aioice", "aiortc", "uvicorn.access", "ultralytics"):
        assert logging.getLogger(nombre).level == logging.WARNING


def test_log_de_evidencia_no_propaga_al_log_tecnico(tmp_path):
    RegistroEvidenciaJsonl(tmp_path)

    assert logging.getLogger("sabre.evidencia").propagate is False
