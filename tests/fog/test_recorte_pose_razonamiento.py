"""`/pose` y el razonamiento con el recorte de ventana ACTIVO (EDGE02, DEF-32, D-19).

Un clip de 8 s con el tocado a 5 s se recorta a [3,0 s; 5,5 s]: 76 fotogramas a 30 fps con el tocado en el
fotograma 60. La pose falsa sigue al clip recortado (un fotograma de pose por fotograma recibido, desde el lock),
así que `frame_inicio`, `frame_tocado` y los eventos del razonamiento deben estar todos en la línea de tiempo del
clip recortado, no en la del original.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import replace

import cv2
import numpy as np
import pytest

from fog.domain.models import TrackedFrame, TrackedSequence
from fog.ports.pose_estimator import PoseEstimatorPort, PoseTrackingSession
from tests.fog.conftest import VEREDICTO_DEFAULT
from tests.fog.fakes import FakeFeatureExtractor, FakeVerdictSubscriber
from tests.fog.test_api_razonamiento import _atencion, _persona, _serie

FPS = 30
LOCK = 3
SUBE_EN = 40  # el brazo de A empieza a extenderse en el fotograma de pose 40 (fotograma de clip 43)
T_TOCADO_MS = 5000  # en el clip original de 8 s
TOCADO_RECORTADO = 60  # 2.000 ms a 30 fps
PICO = 30


def _clip_largo() -> bytes:
    fd, ruta = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    w = cv2.VideoWriter(ruta, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (64, 64))
    for _ in range(8 * FPS):
        w.write(np.zeros((64, 64, 3), dtype=np.uint8))
    w.release()
    contenido = open(ruta, "rb").read()
    os.remove(ruta)
    return contenido


class PoseQueSigueAlClip(PoseEstimatorPort):
    """Un fotograma de pose por fotograma recibido, desde el lock: lo que haría el tracking real."""

    def __init__(self):
        self.recibidos: list[int] = []

    def start_session(self) -> PoseTrackingSession:
        estimador = self

        class _Sesion(PoseTrackingSession):
            def __init__(self):
                self.n = 0

            def add_frame(self, frame) -> None:
                self.n += 1

            def finish(self) -> TrackedSequence:
                estimador.recibidos.append(self.n)
                m = self.n - LOCK
                a, b = _serie(SUBE_EN, m), _serie(None, m)
                frames = [TrackedFrame(_persona("derecho", x), _persona("izquierdo", y)) for x, y in zip(a, b)]
                return TrackedSequence(frames=frames, frame_w=64, frame_h=64, locked=True, lock_frame=LOCK)

        return _Sesion()


@pytest.fixture
def revision(crear_app):
    pose = PoseQueSigueAlClip()
    n_pose = 76 - LOCK
    veredicto = replace(VEREDICTO_DEFAULT, atencion=_atencion(PICO, n_pose))
    app = crear_app(
        pose_estimator=pose, extractor=FakeFeatureExtractor(), subscriber=FakeVerdictSubscriber(veredicto),
    )
    r = app.client.post(
        f"/matches/{app.configurar()}/clip", files={"file": ("largo.mp4", _clip_largo(), "video/mp4")},
        data={"t_luz_a_ms": str(T_TOCADO_MS)},
    )
    assert r.status_code == 200, r.text
    return app, r.json()["revision_id"], pose


def test_la_pose_recibe_solo_el_clip_recortado(revision):
    _, _, pose = revision
    assert pose.recibidos == [pytest.approx(76, abs=2)]  # no los 240 fotogramas del original


def test_pose_con_el_recorte_activo_ubica_frame_inicio_y_frame_tocado_en_el_clip_recortado(revision):
    app, revision_id, _ = revision

    r = app.client.get(f"/revisiones/{revision_id}/pose")

    assert r.status_code == 200, r.text
    d = r.json()
    assert d["fps"] == FPS
    assert d["frame_inicio"] == LOCK  # el lock del tracking, en fotogramas del clip recortado
    assert d["frame_tocado"] == TOCADO_RECORTADO  # no 150 (5.000 ms a 30 fps del original)
    assert d["n_frames"] == pytest.approx(76 - LOCK, abs=2)
    # la línea de tiempo cierra: frame_inicio + n_frames es el final del clip recortado
    assert d["frame_inicio"] + d["n_frames"] == pytest.approx(76, abs=2)
    assert d["frame_inicio"] < d["frame_tocado"] < d["frame_inicio"] + d["n_frames"]
    a = d["tiradores"]["A"]
    # el trazo del ángulo del codo cae en el fotograma de pose esperado (índice relativo a frame_inicio)
    assert a["angulo_codo"][SUBE_EN] == pytest.approx(90.0, abs=1.0)
    assert a["angulo_codo"][SUBE_EN + 1] > a["angulo_codo"][SUBE_EN] + 5


def test_el_tocado_y_el_frame_guardados_son_relativos_al_clip_recortado(revision):
    app, revision_id, _ = revision
    fila = app.sql.filas(
        "SELECT t.t_tocado_ms, tc.frame_tocado, c.duracion_ms FROM sabre.revision_var r "
        "JOIN sabre.tocado t ON t.id = r.tocado_id JOIN sabre.tocado_clip tc ON tc.tocado_id = t.id "
        "JOIN sabre.clip c ON c.id = tc.clip_id WHERE r.id = :r", r=revision_id)[0]
    assert fila["t_tocado_ms"] == pytest.approx(2000, abs=34)
    assert fila["frame_tocado"] == TOCADO_RECORTADO
    assert fila["duracion_ms"] == pytest.approx(2500, abs=70)


def test_razonamiento_con_el_recorte_activo_mide_los_eventos_contra_el_tocado_recortado(revision):
    app, revision_id, _ = revision

    r = app.client.get(f"/revisiones/{revision_id}/razonamiento")

    assert r.status_code == 200, r.text
    d = r.json()
    assert d["estado"] not in ("no_calculado", "no_registrado")  # el razonamiento se calculó y se guardó
    inicio = next(e for e in d["eventos"] if e["tipo"] == "inicio_extension_brazo" and e["tirador"] == "A")
    # fotograma del clip = lock + índice de pose; el tiempo es relativo al tocado (fotograma 60), no al del original
    assert inicio["frame_idx"] == LOCK + SUBE_EN
    assert inicio["t_ms"] == pytest.approx((LOCK + SUBE_EN - TOCADO_RECORTADO) / FPS * 1000, abs=1)
    # la atención también se ubica con frame_inicio: frame clave y ventana en el clip recortado
    assert d["frame_clave"] == LOCK + PICO
    esperado = round((LOCK + PICO - TOCADO_RECORTADO) / FPS * 1000)
    assert d["ventana_atencion"]["desde_ms"] == pytest.approx(esperado, abs=34)
    assert d["ventana_atencion"]["hasta_ms"] == pytest.approx(esperado, abs=34)


def test_sin_el_recorte_la_misma_prueba_daria_otra_linea_de_tiempo(crear_app, monkeypatch):
    """Control: con la ventana desactivada el tocado cae en el fotograma 150; la prueba distingue ambos casos."""
    from shared import config

    monkeypatch.setattr(config, "VENTANA_PRE_MS", 10**9)
    monkeypatch.setattr(config, "VENTANA_POST_MS", 10**9)
    app = crear_app(pose_estimator=PoseQueSigueAlClip(), extractor=FakeFeatureExtractor())
    r = app.client.post(
        f"/matches/{app.configurar()}/clip", files={"file": ("largo.mp4", _clip_largo(), "video/mp4")},
        data={"t_luz_a_ms": str(T_TOCADO_MS)},
    )
    assert r.status_code == 200, r.text
    d = app.client.get(f"/revisiones/{r.json()['revision_id']}/pose").json()
    assert d["frame_tocado"] == 150 and d["n_frames"] == pytest.approx(240 - LOCK, abs=2)
