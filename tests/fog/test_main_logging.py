import importlib
import logging

from shared import config


def test_importing_fog_main_does_not_force_aioice_debug_logging(monkeypatch):
    """DEF-24: fog/main.py no debe forzar logging.DEBUG en aioice.ice.

    Era un diagnóstico temporal (ver historial de fog/main.py) que se
    quedó prendido y ensucia los logs de producción con el detalle interno
    de selección de candidatos ICE de aiortc.
    """
    monkeypatch.setattr(config, "FEATURE_STATS_PATH", "/tmp/feature_stats.npz")
    monkeypatch.setattr(config, "FEATURE_PREPROCESSING_PROFILE", "lstm_6class")
    logging.getLogger("aioice.ice").setLevel(logging.NOTSET)

    import fog.main

    importlib.reload(fog.main)

    assert logging.getLogger("aioice.ice").level != logging.DEBUG
