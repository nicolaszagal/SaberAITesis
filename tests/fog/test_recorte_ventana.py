"""Recorte del clip a la ventana compartida alrededor del tocado (EDGE02, DEF-32)."""

from __future__ import annotations

import os
import tempfile

import cv2
import numpy as np
import pytest

from fog.infrastructure.clips.clip_file_reader import TocadoFueraDelClipError, recortar_ventana

FPS = 30


def _video(n_frames: int) -> str:
    """MP4 de 64x64 a 30 fps; el brillo del frame i es 4*i (para saber cuál quedó)."""
    fd, ruta = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    w = cv2.VideoWriter(ruta, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (64, 64))
    for i in range(n_frames):
        w.write(np.full((64, 64, 3), min(255, 4 * i), np.uint8))
    w.release()
    return ruta


def _frames(ruta: str) -> list[float]:
    cap = cv2.VideoCapture(ruta)
    brillos = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        brillos.append(float(f.mean()))
    cap.release()
    return brillos


def test_clip_largo_se_recorta_a_2s_antes_y_05s_despues():
    ruta = _video(60)  # 2 s
    try:
        t = 1000  # tocado a 1 s
        r = recortar_ventana(ruta, {"t_luz_a_ms": t}, 500, 300)
        assert r is not None
        salida, desfase = r
        assert desfase == 500  # el recorte empieza 500 ms antes del tocado
        n = len(_frames(salida))
        assert n == pytest.approx((500 + 300) * FPS / 1000, abs=2)  # ~24 frames
        os.remove(salida)
    finally:
        os.remove(ruta)


def test_ventana_por_defecto_deja_2_5_s():
    ruta = _video(240)  # 8 s
    try:
        salida, desfase = recortar_ventana(ruta, {"t_luz_a_ms": 5000}, 2000, 500)
        assert desfase == 3000
        assert len(_frames(salida)) == pytest.approx(75, abs=2)
        os.remove(salida)
    finally:
        os.remove(ruta)


def test_es_idempotente_con_un_clip_ya_recortado():
    ruta = _video(75)  # lo que entrega Edge: 2 s antes + 0,5 s después
    try:
        assert recortar_ventana(ruta, {"t_luz_a_ms": 2000}, 2000, 500) is None
        assert recortar_ventana(ruta, {"t_luz_a_ms": 1967}, 2000, 500) is None  # a 1 frame de tolerancia
    finally:
        os.remove(ruta)


def test_la_luz_mas_temprana_manda_en_un_doble():
    ruta = _video(240)
    try:
        salida, desfase = recortar_ventana(ruta, {"t_luz_a_ms": 5100, "t_luz_b_ms": 5000}, 2000, 500)
        assert desfase == 3000
        os.remove(salida)
    finally:
        os.remove(ruta)


def test_instante_fuera_del_clip_se_rechaza():
    ruta = _video(30)
    try:
        with pytest.raises(TocadoFueraDelClipError):
            recortar_ventana(ruta, {"t_luz_a_ms": 9000}, 2000, 500)
    finally:
        os.remove(ruta)


def test_archivo_ilegible_no_se_recorta():
    fd, ruta = tempfile.mkstemp(suffix=".mp4")
    os.write(fd, b"no es un video")
    os.close(fd)
    try:
        assert recortar_ventana(ruta, {"t_luz_a_ms": 100}, 2000, 500) is None
    finally:
        os.remove(ruta)
