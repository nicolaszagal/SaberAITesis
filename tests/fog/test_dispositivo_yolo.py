"""DEPLOY10 — `FOG_DEVICE` llega a YOLO y se valida (ultralytics no elige el dispositivo solo)."""

import numpy as np
import pytest

from fog.infrastructure.pose.yolo_pose_adapter import YoloV8PoseAdapter
from shared import config


class _Corte(Exception):
    pass


class _ModeloEspia:
    """Registra los argumentos de predict() y corta antes del tracker."""

    def __init__(self):
        self.kwargs = None

    def predict(self, frame, **kwargs):
        self.kwargs = kwargs
        raise _Corte


def _frame():
    return np.zeros((8, 8, 3), dtype=np.uint8)


def test_adaptador_pasa_el_dispositivo_a_predict():
    modelo = _ModeloEspia()
    sesion = YoloV8PoseAdapter(modelo, device="mps").start_session()
    with pytest.raises(_Corte):
        sesion.add_frame(_frame())
    assert modelo.kwargs["device"] == "mps"


def test_adaptador_usa_cpu_por_defecto():
    modelo = _ModeloEspia()
    sesion = YoloV8PoseAdapter(modelo).start_session()
    with pytest.raises(_Corte):
        sesion.add_frame(_frame())
    assert modelo.kwargs["device"] == "cpu"


@pytest.mark.parametrize("valor", ["cpu", "mps", "cuda", "cuda:0", "cuda:1"])
def test_validar_dispositivo_acepta_los_admitidos(valor):
    assert config.validar_dispositivo(valor) == valor


@pytest.mark.parametrize("valor", ["gpu", "CUDA", "cuda:", "cuda:x", "cpu:0", "mps:1", ""])
def test_validar_dispositivo_rechaza_el_resto(valor):
    with pytest.raises(RuntimeError, match="FOG_DEVICE"):
        config.validar_dispositivo(valor)
