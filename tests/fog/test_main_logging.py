import importlib
import logging
import sys

import pytest

from shared import config

AUTH = {
    "AUTH_USER": "u",
    "AUTH_PASSWORD_HASH": "$argon2id$v=19$m=65536,t=3,p=4$x$y",
    "AUTH_JWT_SECRET": "s" * 48,
}


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
    for nombre, valor in AUTH.items():
        monkeypatch.setattr(config, nombre, valor)
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
        **AUTH,
    }
    for nombre, valor in valores.items():
        monkeypatch.setattr(config, nombre, None if nombre == faltante else valor)
    monkeypatch.delitem(sys.modules, "fog.main", raising=False)

    with pytest.raises(RuntimeError, match=faltante):
        importlib.import_module("fog.main")


@pytest.mark.parametrize(
    "variable, valor, mensaje",
    [
        ("AUTH_JWT_SECRET", None, "AUTH_JWT_SECRET"),
        ("AUTH_JWT_SECRET", "corto" * 3, "al menos 32 bytes"),
        ("AUTH_USER", None, "AUTH_USER"),
        ("AUTH_PASSWORD_HASH", None, "AUTH_PASSWORD_HASH"),
    ],
)
def test_fog_no_arranca_sin_autenticacion_valida(monkeypatch, variable, valor, mensaje):
    """DEPLOY05: Fog no arranca sin AUTH_JWT_SECRET (o con uno de < 32 bytes),
    sin AUTH_USER o sin AUTH_PASSWORD_HASH."""
    valores = {
        "FEATURE_STATS_PATH": "/tmp/feature_stats.npz",
        "FEATURE_PREPROCESSING_PROFILE": "lstm_6class",
        "EVIDENCE_DIR": "/tmp/evidencia",
        "DATABASE_URL": "postgresql+asyncpg://u:c@localhost/x",
        **AUTH,
        variable: valor,
    }
    for nombre, v in valores.items():
        monkeypatch.setattr(config, nombre, v)
    monkeypatch.delitem(sys.modules, "fog.main", raising=False)

    with pytest.raises(RuntimeError, match=mensaje) as exc:
        importlib.import_module("fog.main")
    assert "sss" not in str(exc.value)  # el mensaje nunca incluye el secreto
