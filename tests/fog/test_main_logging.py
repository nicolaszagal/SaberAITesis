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
