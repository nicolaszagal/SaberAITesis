"""GET /revisiones/{revision_id}/pose (F-031, CU-08, D-14, D-18).

App completa contra PostgreSQL real (ver conftest.py: `crear_app`). La pose se
dobla con una TrackedSequence conocida; el .npz que se lee es el que Fog guarda
de verdad con `RegistrarClasificacion`.
"""

from __future__ import annotations

import math
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from fog.domain.models import PersonPose, TrackedFrame, TrackedSequence
from shared.feature_extractor import CONF_THR, angle_three_points
from tests.fog.conftest import clip_de_prueba
from tests.fog.fakes import FakePoseEstimator
from tests.fog.test_routes_clip_upload import _PoseLenta

# Combate de prueba (conftest.body_config): A diestro (brazo derecho: 6, 8, 10)
# y B zurdo (brazo izquierdo: 5, 7, 9). El clip de prueba dura 5 frames a 10 fps
# y el tocado simulado cae en 300 ms, es decir, en el frame 3 del clip.
HOMBRO_D, CODO_D, MUNECA_D = 6, 8, 10
HOMBRO_I, CODO_I, MUNECA_I = 5, 7, 9
LOCK_FRAME = 1


def _persona(puntos: dict[int, tuple[float, float]], conf: float = 0.9) -> PersonPose:
    xy = np.zeros((17, 2), dtype=np.float32)
    cf = np.zeros(17, dtype=np.float32)
    for idx, (x, y) in puntos.items():
        xy[idx] = (x, y)
        cf[idx] = conf
    return PersonPose(keypoints_xy=xy, keypoints_conf=cf, box_xyxy=np.array([1, 2, 30, 60], np.float32), detected=True)


def _brazo_derecho(codo=(20.0, 10.0), muneca=(20.0, 20.0)) -> dict:
    return {HOMBRO_D: (10.0, 10.0), CODO_D: codo, MUNECA_D: muneca}


def _brazo_izquierdo() -> dict:
    return {HOMBRO_I: (40.0, 10.0), CODO_I: (50.0, 10.0), MUNECA_I: (60.0, 10.0)}  # extendido: 180°


def _secuencia() -> TrackedSequence:
    """4 frames (clip frames 1 a 4 de 5, porque el lock fue en el 1).

    - t0: A y B con el brazo armado visible (A en 90°, B en 180°).
    - t1: A con el codo desplazado; B sin detectar.
    - t2: A detectado pero la muñeca bajo el umbral de confianza.
    - t3: A y B como en t0.
    """
    muneca_baja = _persona(_brazo_derecho())
    muneca_baja.keypoints_conf[MUNECA_D] = 0.1
    frames = [
        TrackedFrame(_persona(_brazo_derecho()), _persona(_brazo_izquierdo())),
        TrackedFrame(_persona(_brazo_derecho(codo=(25.0, 12.55))), PersonPose.empty()),
        TrackedFrame(muneca_baja, _persona(_brazo_izquierdo())),
        TrackedFrame(_persona(_brazo_derecho()), _persona(_brazo_izquierdo())),
    ]
    return TrackedSequence(frames=frames, frame_w=64, frame_h=64, locked=True, lock_frame=LOCK_FRAME)


def _revision_con_pose(crear_app) -> tuple:
    app = crear_app(pose_estimator=FakePoseEstimator(tracked=_secuencia()))
    match_id = app.configurar()
    resp = app.subir_clip(match_id)
    assert resp.status_code == 200, resp.text
    return app, resp.json()["revision_id"]


def test_pose_devuelve_forma_y_largos_coherentes(crear_app):
    app, revision_id = _revision_con_pose(crear_app)

    resp = app.client.get(f"/revisiones/{revision_id}/pose")

    assert resp.status_code == 200, resp.text
    assert resp.headers["cache-control"] == "no-store"
    d = resp.json()
    assert d["revision_id"] == revision_id
    assert (d["fps"], d["frame_w"], d["frame_h"]) == (10.0, 64, 64)
    assert d["frame_inicio"] == LOCK_FRAME  # el .npz arranca en el frame del lock, no en el 0
    assert d["frame_tocado"] == 3
    assert d["n_frames"] == 4
    assert d["conf_min_keypoint"] == CONF_THR == 0.3
    assert "motivo" not in d or d["motivo"] is None
    assert set(d["tiradores"]) == {"A", "B"}
    a, b = d["tiradores"]["A"], d["tiradores"]["B"]
    assert (a["color"], a["brazo"]) == ("ROJ", "diestro")
    assert (b["color"], b["brazo"]) == ("VER", "zurdo")
    for t in (a, b):
        assert len(t["xy"]) == len(t["conf"]) == len(t["detectado"]) == len(t["angulo_codo"]) == 4
        assert all(len(f) == 17 and all(len(p) == 2 for p in f) for f in t["xy"])
        assert all(len(f) == 17 for f in t["conf"])
    # Coordenadas en píxeles redondeadas a 1 decimal.
    assert a["xy"][1][CODO_D] == [25.0, 12.6]


def test_angulo_codo_es_el_de_la_funcion_del_extractor(crear_app):
    app, revision_id = _revision_con_pose(crear_app)
    secuencia = _secuencia()

    d = app.client.get(f"/revisiones/{revision_id}/pose").json()["tiradores"]

    for t, (persona, ids) in enumerate([(f.person_a, (HOMBRO_D, CODO_D, MUNECA_D)) for f in secuencia.frames]):
        if d["A"]["angulo_codo"][t] is None:
            continue
        p = persona.keypoints_xy
        esperado = math.degrees(angle_three_points(tuple(p[ids[0]]), tuple(p[ids[1]]), tuple(p[ids[2]])))
        assert d["A"]["angulo_codo"][t] == round(esperado, 1)
    assert d["A"]["angulo_codo"][0] == 90.0
    assert d["B"]["angulo_codo"][0] == 180.0  # brazo izquierdo de B, zurdo


def test_sin_deteccion_o_keypoint_bajo_umbral_el_angulo_es_null(crear_app):
    app, revision_id = _revision_con_pose(crear_app)

    d = app.client.get(f"/revisiones/{revision_id}/pose").json()["tiradores"]

    assert d["B"]["detectado"] == [True, False, True, True]
    assert d["B"]["angulo_codo"][1] is None
    assert d["A"]["detectado"] == [True, True, True, True]
    assert d["A"]["angulo_codo"][2] is None  # detectado, pero la muñeca no pasa CONF_THR
    assert d["A"]["angulo_codo"][1] is not None


def test_timeout_con_keypoints_vacios_responde_n_frames_cero_y_motivo(crear_app):
    app = crear_app(pose_estimator=_PoseLenta(demora_s=0.3), clip_timeout_s=0.4)
    app.container.executor.override(ThreadPoolExecutor(max_workers=2))
    resp = app.subir_clip(app.configurar(), clip_de_prueba(n_frames=20))
    revision_id = resp.json()["revision_id"]
    time.sleep(0.5)

    r = app.client.get(f"/revisiones/{revision_id}/pose")

    assert r.status_code == 200, r.text
    d = r.json()
    assert d["n_frames"] == 0
    assert d["motivo"] == "timeout"
    assert d["tiradores"] is None
    assert r.headers["cache-control"] == "no-store"


def test_npz_modificado_responde_409_y_no_sirve_datos(crear_app, caplog):
    app, revision_id = _revision_con_pose(crear_app)
    ruta = next((app.storage_dir / "keypoints").rglob("*.npz"))
    ruta.write_bytes(ruta.read_bytes() + b"\x00")  # el contenido ya no coincide con el SHA-256

    with caplog.at_level("ERROR"):
        r = app.client.get(f"/revisiones/{revision_id}/pose")

    assert r.status_code == 409
    assert r.json() == {"detail": "keypoints alterados", "codigo": "keypoints_alterados"}
    assert any("keypoints alterados" in m for m in caplog.messages)


def test_revision_inexistente_404_e_id_invalido_422(crear_app):
    app = crear_app()

    assert app.client.get(f"/revisiones/{uuid.uuid4()}/pose").status_code == 404
    assert app.client.get("/revisiones/no-es-uuid/pose").status_code == 422


def test_sin_token_responde_401(crear_app):
    app = crear_app(autenticado=False)

    assert app.client.get(f"/revisiones/{uuid.uuid4()}/pose").status_code == 401
