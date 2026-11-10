"""GET /revisiones/{id}/razonamiento (F-035, CU-09, CU-11, D-15 a D-17) y los
códigos de los 409.

App completa contra PostgreSQL real (conftest: `crear_app`). La pose, el
extractor de features y Cloud se doblan; el razonamiento, la base y el endpoint
son los reales.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import replace

import numpy as np

from fog.domain.models import (
    MotivoNoDisponible,
    PersonPose,
    TrackedFrame,
    TrackedSequence,
    UnavailableResult,
)
from shared.feature_extractor import BIO_OFFSET
from tests.fog.conftest import VEREDICTO_DEFAULT, clip_de_prueba
from tests.fog.fakes import FakeFeatureExtractor, FakePoseEstimator, FakeVerdictSubscriber

# Combate de prueba (conftest.body_config): A diestro (kpts 6, 8, 10) y B zurdo
# (kpts 5, 7, 9). El clip dura 4 s a 10 fps y el tocado cae en 3000 ms: frame 30.
FPS = 10.0
T_TOCADO_MS = "3000"
FRAME_TOCADO = 30
N = 24  # frames de la pose, desde el lock


def _persona(brazo: str, angulo: float | None) -> PersonPose:
    """Persona con el brazo armado en `angulo` grados; None = sin detectar."""
    if angulo is None:
        return PersonPose.empty()
    xy = np.zeros((17, 2), dtype=np.float32)
    cf = np.zeros(17, dtype=np.float32)
    hombro, codo, muneca = (6, 8, 10) if brazo == "derecho" else (5, 7, 9)
    phi = math.radians(180.0 - angulo)  # el ángulo hombro-codo-muñeca es 180° - phi
    sx = 10.0 if brazo == "derecho" else 40.0
    xy[hombro], xy[codo] = (sx, 10.0), (sx + 10.0, 10.0)
    xy[muneca] = (sx + 10.0 + 10.0 * math.cos(phi), 10.0 + 10.0 * math.sin(phi))
    cf[[hombro, codo, muneca]] = 0.9
    return PersonPose(
        keypoints_xy=xy, keypoints_conf=cf,
        box_xyxy=np.array([1, 2, 30, 60], np.float32), detected=True,
    )


def _serie(sube_en: int | None, n: int = N, huecos: tuple[int, ...] = ()) -> list[float | None]:
    angulos: list[float | None] = [90.0] * n
    if sube_en is not None:
        for k in range(1, 5):
            for t in range(sube_en + k, n):
                angulos[t] = 90.0 + 15.0 * k
    for t in huecos:
        angulos[t] = None
    return angulos


def _tracked(a: list, b: list, lock_frame: int) -> TrackedSequence:
    frames = [TrackedFrame(_persona("derecho", x), _persona("izquierdo", y)) for x, y in zip(a, b)]
    return TrackedSequence(frames=frames, frame_w=64, frame_h=64, locked=True, lock_frame=lock_frame)


def _atencion(pico: int, n: int = N) -> list[float]:
    pesos = [0.01] * n
    pesos[pico] = 1.0
    total = sum(pesos)
    return [round(p / total, 4) for p in pesos]


def _subir(crear_app, a, b, *, lock_frame=3, veredicto=None, cierre=None, **opciones):
    raw = np.zeros((len(a), 192), dtype=np.float32)
    if cierre is not None:
        raw[:, BIO_OFFSET] = cierre
    app = crear_app(
        pose_estimator=FakePoseEstimator(tracked=_tracked(a, b, lock_frame)),
        extractor=FakeFeatureExtractor(raw=raw),
        subscriber=FakeVerdictSubscriber(veredicto or replace(VEREDICTO_DEFAULT, atencion=_atencion(8))),
        **opciones,
    )
    match_id = app.configurar()
    resp = app.subir_clip(match_id, clip_de_prueba(40), t_tocado_ms=T_TOCADO_MS)
    assert resp.status_code == 200, resp.text
    return app, resp.json()["revision_id"]


def _filas(app, revision_id, tipo=None) -> list[dict]:
    """Filas de `evidencia` de la clasificación de la revisión (la base se comparte entre pruebas)."""
    return app.sql.filas(
        "SELECT e.tipo, e.tirador, e.frame_idx, e.t_ms, e.articulo_fie, e.detalle "
        "FROM sabre.evidencia e JOIN sabre.revision_var r ON r.clasificacion_id = e.clasificacion_id "
        "WHERE r.id = :i AND (CAST(:t AS text) IS NULL OR e.tipo = :t)", i=revision_id, t=tipo,
    )


def _borrar_evidencia(app, revision_id) -> None:
    app.sql.ejecutar(
        "DELETE FROM sabre.evidencia WHERE clasificacion_id = "
        "(SELECT clasificacion_id FROM sabre.revision_var WHERE id = :i)", i=revision_id,
    )


def _razonamiento(app, revision_id):
    return app.client.get(f"/revisiones/{revision_id}/razonamiento")


def test_clip_nuevo_escribe_evidencia_y_el_endpoint_devuelve_lo_mismo(crear_app):
    app, rev = _subir(crear_app, _serie(5), _serie(9), cierre=[0.0] * 10 + [0.02] * 14)

    filas = _filas(app, rev)
    assert sorted(f["tipo"] for f in filas) == sorted([
        "tocado", "inicio_extension_brazo", "inicio_extension_brazo",
        "inicio_desplazamiento", "frame_clave", "criterio_fie",
    ])

    resp = _razonamiento(app, rev)

    assert resp.status_code == 200, resp.text
    assert resp.headers["cache-control"] == "no-store"
    d = resp.json()
    assert d["revision_id"] == rev
    assert d["estado"] == "respaldada"
    assert d["frases"] == [
        "ROJ inició la extensión del brazo 400 ms antes que VER.",
        "Criterio FIE t.101.2-4: la extensión del brazo precede al ataque.",
    ]
    assert d["criterio_fie"] == {"articulo": "t.101.2-4", "clase": "AttackA"}  # vocabulario del modelo
    assert d["confianza"] == 0.74
    assert d["params_version"] == "1"
    # Lock en el frame 3: el índice 5 de la pose es el frame 8 del clip.
    por_tipo = {(e["tipo"], e.get("tirador")): e for e in d["eventos"]}
    assert por_tipo[("inicio_extension_brazo", "A")]["frame_idx"] == 8
    assert por_tipo[("inicio_extension_brazo", "A")]["t_ms"] == (8 - FRAME_TOCADO) * 100
    assert por_tipo[("inicio_extension_brazo", "B")]["frame_idx"] == 12
    desplazamiento = por_tipo[("inicio_desplazamiento", None)]
    assert desplazamiento["frame_idx"] == 13 and desplazamiento["censurado_inicio"] is False
    assert por_tipo[("tocado", None)] == {"tipo": "tocado", "frame_idx": 30, "t_ms": 0}
    # Cada fila de la base aparece en la respuesta con los mismos valores.
    for f in filas:
        if f["tipo"] in ("inicio_extension_brazo", "inicio_desplazamiento", "tocado"):
            e = por_tipo[(f["tipo"], f["tirador"])]
            assert (e["frame_idx"], e["t_ms"]) == (f["frame_idx"], f["t_ms"])
    criterio = next(f for f in filas if f["tipo"] == "criterio_fie")
    assert criterio["articulo_fie"] == "t.101.2-4"
    assert criterio["detalle"]["frases"] == d["frases"]


def test_la_clase_se_guarda_en_el_vocabulario_del_esquema_y_sale_en_el_del_modelo(crear_app):
    app, rev = _subir(crear_app, _serie(5), _serie(9))
    assert app.sql.escalar(
        "SELECT c.clase FROM sabre.clasificacion c JOIN sabre.revision_var r ON r.clasificacion_id = c.id "
        "WHERE r.id = :i", i=rev,
    ) == "AtaqueA"
    assert _razonamiento(app, rev).json()["criterio_fie"]["clase"] == "AttackA"


def test_lock_tardio_el_evento_y_la_atencion_caen_en_el_mismo_frame_que_los_trazos(crear_app):
    lock = 7
    app, rev = _subir(
        crear_app, _serie(5), _serie(9), lock_frame=lock,
        veredicto=replace(VEREDICTO_DEFAULT, atencion=_atencion(5)),
    )

    pose = app.client.get(f"/revisiones/{rev}/pose").json()
    d = _razonamiento(app, rev).json()

    assert pose["frame_inicio"] == lock
    evento_a = next(e for e in d["eventos"] if e["tipo"] == "inicio_extension_brazo" and e["tirador"] == "A")
    angulos = pose["tiradores"]["A"]["angulo_codo"]
    t = evento_a["frame_idx"] - pose["frame_inicio"]
    # En los trazos, ese frame es donde empieza a subir el codo de A.
    assert evento_a["frame_idx"] == lock + 5
    assert angulos[t] == 90.0 and angulos[t + 1] > angulos[t]
    # La atención apunta al índice 5: el frame clave es el mismo frame del evento.
    assert d["frame_clave"] == evento_a["frame_idx"]


def test_hueco_de_deteccion_en_la_subida_da_insuficiente_aunque_el_interpolado_exista(crear_app):
    # A deja de detectarse en pleno ascenso; el extractor lo interpolaría, el ángulo crudo no existe.
    app, rev = _subir(crear_app, _serie(5, huecos=(7,)), _serie(9))

    d = _razonamiento(app, rev).json()

    assert d["estado"] == "insuficiente"
    assert d["frases"] == ["Evidencia insuficiente: falta la detección de ROJ en el tramo clave."]
    assert not any(e["tipo"] == "inicio_extension_brazo" and e["tirador"] == "A" for e in d["eventos"])


def test_desplazamiento_que_arranca_sobre_el_umbral_sale_censurado(crear_app):
    app, rev = _subir(crear_app, _serie(5), _serie(9), cierre=[0.02] * N)

    d = _razonamiento(app, rev).json()

    desplazamiento = next(e for e in d["eventos"] if e["tipo"] == "inicio_desplazamiento")
    assert desplazamiento["censurado_inicio"] is True
    assert desplazamiento["frame_idx"] == 3  # el primer frame de la secuencia (lock)
    assert "tirador" not in desplazamiento
    assert _filas(app, rev, "inicio_desplazamiento")[0]["detalle"] == {"censurado_inicio": True}


def test_sin_atencion_la_ventana_es_nula_y_no_hay_frame_clave(crear_app):
    app, rev = _subir(crear_app, _serie(5), _serie(9), veredicto=VEREDICTO_DEFAULT)

    d = _razonamiento(app, rev).json()

    assert d["estado"] == "respaldada"
    assert "ventana_atencion" not in d and "frame_clave" not in d
    assert _filas(app, rev, "frame_clave") == []


def test_con_atencion_la_ventana_y_el_frame_clave_salen_en_la_respuesta(crear_app):
    app, rev = _subir(crear_app, _serie(5), _serie(9))

    d = _razonamiento(app, rev).json()

    # Pico en el índice 8 (frame 11 del clip): 1,9 s... el tramo de la mitad del peso es ese frame.
    assert d["frame_clave"] == 11
    assert d["ventana_atencion"] == {"desde_ms": -1900, "hasta_ms": -1900}


def test_clasificacion_no_disponible_no_escribe_razonamiento(crear_app):
    resultado = UnavailableResult(match_id="x", revision_id="x", motivo=MotivoNoDisponible.POSE_INCOMPLETA)

    class _Sub(FakeVerdictSubscriber):
        async def wait_for_verdict(self, revision_id, aceptar=None):
            return resultado

    app, rev = _subir(crear_app, _serie(5), _serie(9), veredicto=VEREDICTO_DEFAULT)
    app2 = crear_app(
        pose_estimator=FakePoseEstimator(tracked=_tracked(_serie(5), _serie(9), 3)),
        subscriber=_Sub(VEREDICTO_DEFAULT),
    )
    rev2 = app2.subir_clip(app2.configurar(), clip_de_prueba(40), t_tocado_ms=T_TOCADO_MS).json()["revision_id"]

    d = _razonamiento(app2, rev2).json()

    assert d["estado"] == "no_disponible" and d["motivo"] == "pose_incompleta"
    assert d["frases"] == []
    assert app2.sql.escalar(
        "SELECT count(*) FROM sabre.evidencia e JOIN sabre.revision_var r "
        "ON r.clasificacion_id = e.clasificacion_id WHERE r.id = :i", i=rev2,
    ) == 0


def test_revision_anterior_al_registro_responde_no_registrado(crear_app):
    app, rev = _subir(crear_app, _serie(5), _serie(9))
    _borrar_evidencia(app, rev)  # como una revisión previa a EXP03 (D-17)

    d = _razonamiento(app, rev).json()

    assert d["estado"] == "no_registrado"
    assert d["frases"] == []
    assert "criterio_fie" not in d


def test_el_snapshot_de_auditoria_trae_la_justificacion(crear_app):
    app, rev = _subir(crear_app, _serie(5), _serie(9))
    esperado = _razonamiento(app, rev).json()

    assert app.veredicto(rev).status_code == 200

    snapshot = app.sql.filas("SELECT snapshot FROM sabre.registro_auditoria WHERE revision_id = :i", i=rev)[0]["snapshot"]
    assert snapshot["justificacion"] == {
        "estado": "respaldada",
        "frases": esperado["frases"],
        "articulo_fie": "t.101.2-4",
        "params_version": "1",
    }
    # El hash cubre la justificación: este registro no figura entre los alterados
    # (la base se comparte con otros módulos, que sí alteran registros a propósito).
    seq = app.sql.escalar("SELECT seq FROM sabre.registro_auditoria WHERE revision_id = :i", i=rev)
    assert seq not in [f["seq"] for f in app.sql.filas("SELECT * FROM sabre.fn_verificar_auditoria()")]
    for campo in ("revision", "tocado", "clasificacion", "veredicto", "modelo", "reglamento", "vocabulario"):
        assert campo in snapshot


def test_el_snapshot_de_una_revision_antigua_no_lleva_justificacion(crear_app):
    app, rev = _subir(crear_app, _serie(5), _serie(9))
    _borrar_evidencia(app, rev)

    assert app.veredicto(rev).status_code == 200

    snapshot = app.sql.filas("SELECT snapshot FROM sabre.registro_auditoria WHERE revision_id = :i", i=rev)[0]["snapshot"]
    assert "justificacion" not in snapshot


def test_un_fallo_del_razonamiento_no_impide_guardar_la_clasificacion(crear_app, caplog):
    class _Rota(FakeFeatureExtractor):
        def extract_raw(self, *args):
            raise RuntimeError("falla simulada")

    app = crear_app(
        pose_estimator=FakePoseEstimator(tracked=_tracked(_serie(5), _serie(9), 3)),
        extractor=_Rota(),
        subscriber=FakeVerdictSubscriber(VEREDICTO_DEFAULT),
    )
    rev = app.subir_clip(app.configurar(), clip_de_prueba(40), t_tocado_ms=T_TOCADO_MS).json()["revision_id"]

    assert app.sql.escalar(
        "SELECT count(*) FROM sabre.revision_var WHERE id = :i AND clasificacion_id IS NOT NULL", i=rev
    ) == 1
    d = _razonamiento(app, rev).json()
    assert d["estado"] == "no_calculado"
    assert d["frases"] == [] and d["eventos"] == []
    assert any("razonamiento.error" in r.getMessage() and rev in r.getMessage() for r in caplog.records)
    # El error queda en la evidencia (no se confunde con una revisión anterior a EXP03).
    assert [f["tipo"] for f in _filas(app, rev)] == ["criterio_fie"]


def test_un_fallo_del_razonamiento_queda_en_la_justificacion_del_snapshot(crear_app):
    class _Rota(FakeFeatureExtractor):
        def extract_raw(self, *args):
            raise RuntimeError("falla simulada")

    app = crear_app(
        pose_estimator=FakePoseEstimator(tracked=_tracked(_serie(5), _serie(9), 3)),
        extractor=_Rota(),
        subscriber=FakeVerdictSubscriber(VEREDICTO_DEFAULT),
    )
    rev = app.subir_clip(app.configurar(), clip_de_prueba(40), t_tocado_ms=T_TOCADO_MS).json()["revision_id"]

    assert app.veredicto(rev).status_code == 200

    snapshot = app.sql.filas("SELECT snapshot FROM sabre.registro_auditoria WHERE revision_id = :i", i=rev)[0]["snapshot"]
    assert snapshot["justificacion"]["estado"] == "no_calculado"


def test_brazo_ya_extendido_al_inicio_sale_censurado_en_la_api_y_en_la_evidencia(crear_app):
    app, rev = _subir(crear_app, [150.0] * N, _serie(9))

    d = _razonamiento(app, rev).json()

    ext = {e["tirador"]: e for e in d["eventos"] if e["tipo"] == "inicio_extension_brazo"}
    assert ext["A"]["censurado_inicio"] is True and ext["A"]["frame_idx"] == 3  # primer frame desde el lock
    assert ext["B"]["censurado_inicio"] is False
    assert d["estado"] == "respaldada"
    fila = next(f for f in _filas(app, rev, "inicio_extension_brazo") if f["tirador"] == "A")
    assert fila["detalle"] == {"censurado_inicio": True}



def test_revision_inexistente_404_e_id_invalido_422_y_sin_token_401(crear_app):
    app = crear_app()
    assert _razonamiento(app, uuid.uuid4()).status_code == 404
    assert app.client.get("/revisiones/no-es-uuid/razonamiento").status_code == 422
    sin_token = crear_app(autenticado=False)
    assert sin_token.client.get(f"/revisiones/{uuid.uuid4()}/razonamiento").status_code == 401


# --- Errores con código (los 409 no se distinguen por el texto de `detail`) ---


def _quitar_clasificacion(app, revision_id):
    app.sql.ejecutar("UPDATE sabre.revision_var SET clasificacion_id = NULL WHERE id = :i", i=revision_id)


def test_409_sin_clasificacion_trae_su_codigo_en_pose_razonamiento_y_veredicto(crear_app):
    app, rev = _subir(crear_app, _serie(5), _serie(9))
    _quitar_clasificacion(app, rev)
    detalle = "la revisión aún no tiene una clasificación registrada"

    for r in (
        app.client.get(f"/revisiones/{rev}/pose"),
        _razonamiento(app, rev),
        app.veredicto(rev),
    ):
        assert r.status_code == 409
        assert r.json() == {"detail": detalle, "codigo": "sin_clasificacion"}


def test_409_de_keypoints_alterados_trae_su_codigo(crear_app):
    app, rev = _subir(crear_app, _serie(5), _serie(9))
    ruta = next((app.storage_dir / "keypoints").rglob("*.npz"))
    ruta.write_bytes(ruta.read_bytes() + b"\x00")

    r = app.client.get(f"/revisiones/{rev}/pose")

    assert r.status_code == 409
    assert r.json() == {"detail": "keypoints alterados", "codigo": "keypoints_alterados"}


def test_409_de_veredicto_ya_registrado_trae_su_codigo(crear_app):
    app, rev = _subir(crear_app, _serie(5), _serie(9))
    assert app.veredicto(rev).status_code == 200

    r = app.veredicto(rev)

    assert r.status_code == 409
    assert r.json() == {
        "detail": "la revisión ya tiene un veredicto registrado",
        "codigo": "veredicto_ya_registrado",
    }
