import importlib
import logging
import sys

import pytest

from shared import config


def test_importing_fog_main_does_not_force_aioice_debug_logging(monkeypatch):
    """DEF-24: fog/main.py no debe forzar logging.DEBUG en aioice.ice.

    Era un diagnóstico temporal (ver historial de fog/main.py) que se
    quedó prendido y ensucia los logs de producción con el detalle interno
    de selección de candidatos ICE de aiortc.
    """
    monkeypatch.setattr(config, "FEATURE_STATS_PATH", "/tmp/feature_stats.npz")
    monkeypatch.setattr(config, "FEATURE_PREPROCESSING_PROFILE", "lstm_6class")
    monkeypatch.setattr(config, "EVIDENCE_DIR", "/tmp/evidencia")
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql+asyncpg://u:c@localhost/x")
    logging.getLogger("aioice.ice").setLevel(logging.NOTSET)

    import fog.main

    importlib.reload(fog.main)

    assert logging.getLogger("aioice.ice").level != logging.DEBUG


@pytest.mark.parametrize("faltante", ["DATABASE_URL", "EVIDENCE_DIR"])
def test_fog_no_arranca_sin_variable_obligatoria(monkeypatch, faltante):
    """Fog exige DATABASE_URL y EVIDENCE_DIR al arrancar: sin ellas no
    importa fog.main (uvicorn no levanta la app)."""
    valores = {
        "FEATURE_STATS_PATH": "/tmp/feature_stats.npz",
        "FEATURE_PREPROCESSING_PROFILE": "lstm_6class",
        "EVIDENCE_DIR": "/tmp/evidencia",
        "DATABASE_URL": "postgresql+asyncpg://u:c@localhost/x",
    }
    for nombre, valor in valores.items():
        monkeypatch.setattr(config, nombre, None if nombre == faltante else valor)
    monkeypatch.delitem(sys.modules, "fog.main", raising=False)

    with pytest.raises(RuntimeError, match=faltante):
        importlib.import_module("fog.main")
