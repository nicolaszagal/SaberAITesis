"""ESTRES01: los logs de tiempo solo existen con ESTRES_TIEMPOS=1 y no cambian el comportamiento."""

from __future__ import annotations

import logging

import numpy as np

from fog.infrastructure.pose.yolo_pose_adapter import _YoloTrackingSession
from shared import tiempos


def test_registrar_no_escribe_sin_la_variable(monkeypatch, caplog):
    monkeypatch.delenv("ESTRES_TIEMPOS", raising=False)
    with caplog.at_level(logging.INFO, logger="estres.tiempos"):
        tiempos.registrar("clip", archivo="a.mp4", total_s=1.23456)
    assert caplog.records == []
    assert tiempos.activo() is False


def test_registrar_escribe_una_linea_con_la_variable(monkeypatch, caplog):
    monkeypatch.setenv("ESTRES_TIEMPOS", "1")
    with caplog.at_level(logging.INFO, logger="estres.tiempos"):
        tiempos.registrar("clip", archivo="a.mp4", total_s=1.23456)
    assert [r.getMessage() for r in caplog.records] == [
        "ESTRES_TIEMPOS etapa=clip archivo=a.mp4 total_s=1.235"
    ]


def test_sesion_de_pose_acumula_espera_del_lock_solo_si_se_mide(monkeypatch):
    class _ModeloFalso:
        def predict(self, *a, **k):
            raise _Cortar

    class _Cortar(Exception):
        pass

    import threading

    sesion = _YoloTrackingSession(_ModeloFalso(), threading.Lock())
    monkeypatch.setenv("ESTRES_TIEMPOS", "1")
    try:
        sesion.add_frame(np.zeros((8, 8, 3), dtype=np.uint8))
    except _Cortar:
        pass
    # El lock se liberó y la espera quedó sin sumar (el predict falló antes de acumular).
    assert sesion._predict_lock.acquire(blocking=False)
    assert sesion.espera_lock_s == 0.0
