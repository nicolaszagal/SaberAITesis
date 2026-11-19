"""Tocados capturados por Edge: preproceso sin revisión, VAR, ritmo y decisión en pista (EDGE02)."""

from __future__ import annotations

import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from dependency_injector import providers

from fog.domain.models import TrackedSequence
from tests.fog.conftest import clip_de_prueba
from tests.fog.fakes import FakePoseEstimator, FakePoseTrackingSession


def _subir(app, match_id, **form):
    datos = {"t_luz_a_ms": "300", "fuente": "favero"}
    datos.update(form)
    datos = {k: v for k, v in datos.items() if v is not None}
    return app.client.post(
        f"/matches/{match_id}/tocados",
        files={"file": ("tocado.mp4", clip_de_prueba(), "video/mp4")},
        data=datos,
    )


def _lista(app, match_id):
    r = app.client.get(f"/matches/{match_id}/tocados")
    assert r.status_code == 200, r.text
    return r.json()


def _esperar_listos(app, match_id, n, timeout=10.0):
    fin = time.monotonic() + timeout
    while time.monotonic() < fin:
        lista = _lista(app, match_id)
        if len(lista) >= n and all(t["estado"] == "listo" for t in lista):
            return lista
        time.sleep(0.05)
    raise AssertionError(f"no quedaron listos: {_lista(app, match_id)}")


def _filas(app, sql, **p):
    return app.sql.filas(sql, **p)


def _revisiones(app, match_id):
    return _filas(
        app, "SELECT count(*) AS n FROM sabre.revision_var r JOIN sabre.tocado t ON t.id = r.tocado_id "
        "WHERE t.combate_id = :m", m=match_id)[0]["n"]


def test_tocado_se_registra_sin_revision_y_sin_auditoria(crear_app):
    """D-04: el preproceso guarda clip, tocado y clasificación, pero nunca abre revisión."""
    app = crear_app()
    match_id = app.configurar()
    r = _subir(app, match_id)
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "procesando"
    (item,) = _esperar_listos(app, match_id, 1)
    assert item["revisado"] is False and item["revision_id"] is None
    assert item["admite_var"] is True and item["tiene_clip"] is True
    assert "action" not in item and "confidence" not in item  # la sugerencia no sale en la lista
    assert _revisiones(app, match_id) == 0
    assert _filas(
        app, "SELECT count(*) AS n FROM sabre.registro_auditoria a JOIN sabre.revision_var r ON r.id = a.revision_id "
        "JOIN sabre.tocado t ON t.id = r.tocado_id WHERE t.combate_id = :m", m=match_id)[0]["n"] == 0
    assert _filas(
        app, "SELECT count(*) AS n FROM sabre.clasificacion c JOIN sabre.tocado t ON t.id = c.tocado_id "
        "WHERE t.combate_id = :m", m=match_id)[0]["n"] == 1
    clip = _filas(app, "SELECT origen, camara FROM sabre.clip WHERE combate_id = :m", m=match_id)[0]
    assert (clip["origen"], clip["camara"]) == ("captura", "frontal")


def test_solicitar_var_abre_la_revision_con_la_sugerencia_ya_calculada(crear_app):
    app = crear_app()
    match_id = app.configurar()
    tocado_id = _subir(app, match_id).json()["tocado_id"]
    _esperar_listos(app, match_id, 1)
    t0 = time.monotonic()
    r = app.client.post(f"/tocados/{tocado_id}/revision")
    assert r.status_code == 200, r.text
    assert time.monotonic() - t0 < 2.0  # sin esperar el pipeline: ya estaba listo
    cuerpo = r.json()
    assert cuerpo["disponible"] is True and cuerpo["action"] == "AttackA"
    revision_id = cuerpo["revision_id"]
    fila = _filas(
        app, "SELECT clasificacion_id, aceptada FROM sabre.revision_var WHERE tocado_id = :t", t=tocado_id)[0]
    assert fila["aceptada"] is True and fila["clasificacion_id"] is not None
    # con ese revision_id sigue el flujo actual
    assert app.client.get(f"/revisiones/{revision_id}").status_code == 200
    assert app.veredicto(revision_id).status_code == 200
    # idempotente: pedirlo otra vez devuelve la misma revisión
    assert app.client.post(f"/tocados/{tocado_id}/revision").json()["revision_id"] == revision_id
    assert _revisiones(app, match_id) == 1
    assert _lista(app, match_id)[0]["revisado"] is True


def test_fuente_simulado_del_boton_de_prueba(crear_app):
    app = crear_app()
    match_id = app.configurar()
    assert _subir(app, match_id, fuente="simulado", origen="boton").status_code == 200
    assert _filas(app, "SELECT fuente FROM sabre.tocado WHERE combate_id = :m", m=match_id)[0]["fuente"] == "simulado"
    assert _subir(app, match_id, fuente="otra").status_code == 422


def test_sin_luz_o_fuera_del_clip_es_422(crear_app):
    app = crear_app()
    match_id = app.configurar()
    assert _subir(app, match_id, t_luz_a_ms=None).status_code == 422
    assert _subir(app, match_id, t_luz_a_ms="99000").status_code == 422
    assert _subir(app, "00000000-0000-0000-0000-000000000000").status_code == 404


class _PoseConCompuerta(FakePoseEstimator):
    """Registra el orden de las sesiones; la primera espera `soltar` antes de terminar."""

    def __init__(self):
        super().__init__(TrackedSequence(frames=[], frame_w=64, frame_h=64, locked=True))
        self.soltar = threading.Event()
        self.orden: list[int] = []
        self._n = 0

    def start_session(self):
        self._n += 1
        numero = self._n
        self.orden.append(numero)
        estimador = self

        class _S(FakePoseTrackingSession):
            def finish(self):
                if numero == 1:
                    estimador.soltar.wait(10)
                return super().finish()

        return _S(self.tracked)


def test_ritmo_tres_tocados_seguidos(crear_app):
    """Decisión en pista inmediata en los tres; el más reciente se procesa primero; los
    anteriores quedan 'No revisado' y sin VAR; ninguno se pierde."""
    pose = _PoseConCompuerta()
    app = crear_app(pose_estimator=pose)
    app.container.executor.override(providers.Object(ThreadPoolExecutor(2)))
    match_id = app.configurar()
    ids = []
    for _ in range(3):
        ids.append(_subir(app, match_id).json()["tocado_id"])
        time.sleep(0.15)  # el primero queda atascado en la pose mientras llegan los otros
    # la decisión en pista no espera al procesamiento (el primero sigue procesándose)
    t0 = time.monotonic()
    for i, tid in enumerate(ids):
        r = app.client.post(f"/tocados/{tid}/decision-pista", json={"clase": "AttackA" if i != 1 else None, "anulado": i == 1})
        assert r.status_code == 200, r.text
    assert time.monotonic() - t0 < 2.0
    estados = {t["tocado_id"]: t for t in _lista(app, match_id)}
    assert estados[ids[0]]["estado"] == "procesando"
    assert [estados[i]["admite_var"] for i in ids] == [False, False, True]
    assert app.client.post(f"/tocados/{ids[0]}/revision").status_code == 409  # cerrado: No revisado
    pose.soltar.set()
    _esperar_listos(app, match_id, 3)
    assert pose.orden == [1, 2, 3]  # sesiones de pose iniciadas
    assert len(_filas(app, "SELECT id FROM sabre.tocado WHERE combate_id = :m", m=match_id)) == 3  # ninguno se perdió
    assert _revisiones(app, match_id) == 0
    # el VAR del último sí se acepta
    assert app.client.post(f"/tocados/{ids[2]}/revision").status_code == 200


def test_el_mas_reciente_se_procesa_antes_que_los_anteriores_pendientes(crear_app):
    pose = _PoseConCompuerta()
    app = crear_app(pose_estimator=pose)
    app.container.executor.override(providers.Object(ThreadPoolExecutor(2)))
    match_id = app.configurar()
    ids = [_subir(app, match_id).json()["tocado_id"] for _ in range(1)]
    time.sleep(0.2)
    ids += [_subir(app, match_id).json()["tocado_id"], _subir(app, match_id).json()["tocado_id"]]
    pose.soltar.set()
    _esperar_listos(app, match_id, 3)
    clasifs = _filas(
        app, "SELECT c.tocado_id::text AS t FROM sabre.clasificacion c JOIN sabre.tocado o ON o.id = c.tocado_id "
        "WHERE o.combate_id = :m ORDER BY c.creado_en", m=match_id,
    )
    assert [c["t"] for c in clasifs] == [ids[0], ids[2], ids[1]]  # 1.º, luego el más reciente, luego el anterior


def test_decision_pista_es_solo_adicion_y_la_ultima_manda(crear_app):
    app = crear_app()
    match_id = app.configurar()
    tid = _subir(app, match_id).json()["tocado_id"]
    r1 = app.client.post(f"/tocados/{tid}/decision-pista", json={"clase": "AttackA"})
    r2 = app.client.post(f"/tocados/{tid}/decision-pista", json={"clase": "RiposteB"})
    assert r1.status_code == r2.status_code == 200
    assert _lista(app, match_id)[0]["decision_pista"]["clase"] == "RiposteB"
    assert _filas(app, "SELECT count(*) AS n FROM sabre.decision_pista WHERE tocado_id = :t", t=tid)[0]["n"] == 2
    r3 = app.client.post(f"/tocados/{tid}/decision-pista", json={"anulado": True})
    assert r3.json()["anulado"] is True and r3.json()["clase"] is None
    assert app.client.post(f"/tocados/{tid}/decision-pista", json={}).status_code == 422
    assert app.client.post(f"/tocados/{tid}/decision-pista", json={"clase": "AttackA", "anulado": True}).status_code == 422
    with pytest.raises(Exception, match="no pueden modificarse"):
        app.sql.ejecutar("UPDATE sabre.decision_pista SET anulado = TRUE")
    with pytest.raises(Exception, match="no pueden modificarse"):
        app.sql.ejecutar("DELETE FROM sabre.decision_pista")


def test_clip_del_tocado_se_puede_reproducir_y_el_hash_coincide(crear_app):
    app = crear_app()
    match_id = app.configurar()
    tid = _subir(app, match_id).json()["tocado_id"]
    r = app.client.get(f"/tocados/{tid}/clip")
    assert r.status_code == 200 and r.headers["content-type"] == "video/mp4"
    sha = _filas(app, "SELECT sha256 FROM sabre.clip WHERE combate_id = :m", m=match_id)[0]["sha256"]
    assert hashlib.sha256(r.content).hexdigest() == sha
    assert app.client.get("/tocados/00000000-0000-0000-0000-000000000000/clip").status_code == 404


def test_pose_incompleta_deja_el_tocado_listo_como_no_disponible(crear_app):
    app = crear_app(extraccion_falla=True)
    match_id = app.configurar()
    tid = _subir(app, match_id).json()["tocado_id"]
    _esperar_listos(app, match_id, 1)
    r = app.client.post(f"/tocados/{tid}/revision").json()
    assert r["disponible"] is False and r["motivo"] == "pose_incompleta"


def test_purgar_clips_borra_los_archivos_pero_conserva_el_hash_y_la_auditoria(crear_app):
    """Tras cerrar la sesión no queda ningún video en el almacén; la cadena de auditoría sigue válida."""
    import asyncio

    app = crear_app()
    match_id = app.configurar()
    tid = _subir(app, match_id).json()["tocado_id"]
    _esperar_listos(app, match_id, 1)
    revision_id = app.client.post(f"/tocados/{tid}/revision").json()["revision_id"]
    assert app.veredicto(revision_id).status_code == 200  # deja registro de auditoría
    sha = _filas(app, "SELECT sha256 FROM sabre.clip WHERE combate_id = :m", m=match_id)[0]["sha256"]
    assert any(app.storage_dir.rglob("*.mp4"))

    purgados = asyncio.run(app.container.purgar_clips().execute())

    assert purgados >= 1
    assert not any(app.storage_dir.rglob("*.mp4")) and not any(app.storage_dir.rglob("*.mov"))
    assert app.client.get(f"/tocados/{tid}/clip").status_code == 404
    assert _lista(app, match_id)[0]["tiene_clip"] is False  # la lista deja de ofrecer la repetición
    assert _filas(app, "SELECT sha256 FROM sabre.clip WHERE combate_id = :m", m=match_id)[0]["sha256"] == sha
    assert _filas(app, "SELECT count(*) AS n FROM sabre.fn_verificar_auditoria()")[0]["n"] == 0
    assert asyncio.run(app.container.purgar_clips().execute()) == 0  # idempotente
