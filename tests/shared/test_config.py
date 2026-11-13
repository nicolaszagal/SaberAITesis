import pytest

from shared import config


def test_require_paths_raises_with_missing_variable_name_when_unset(monkeypatch):
    monkeypatch.setattr(config, "MODEL_RUN_DIR", None)

    with pytest.raises(RuntimeError, match="MODEL_RUN_DIR"):
        config.require_paths("MODEL_RUN_DIR")


def test_require_paths_lists_every_missing_variable(monkeypatch):
    monkeypatch.setattr(config, "MODEL_RUN_DIR", None)
    monkeypatch.setattr(config, "FEATURE_STATS_PATH", None)

    with pytest.raises(RuntimeError) as exc_info:
        config.require_paths("MODEL_RUN_DIR", "FEATURE_STATS_PATH")

    assert "MODEL_RUN_DIR" in str(exc_info.value)
    assert "FEATURE_STATS_PATH" in str(exc_info.value)


def test_require_paths_passes_when_variable_is_set(monkeypatch):
    monkeypatch.setattr(config, "MODEL_RUN_DIR", "/tmp/20260928_141021")

    config.require_paths("MODEL_RUN_DIR")


# --- DEPLOY09: Redis remoto sin valores por defecto --------------------------


def _remoto_completo(monkeypatch):
    monkeypatch.setattr(config, "ENTORNO", "remoto")
    monkeypatch.setattr(config, "REDIS_URL_ENV", "rediss://cloud:x@localhost:6379/0")
    monkeypatch.setattr(config, "REDIS_TLS_CA", "/dev/shm/ca.crt")
    monkeypatch.setattr(config, "REDIS_TLS_CERT", "/dev/shm/client.crt")
    monkeypatch.setattr(config, "REDIS_TLS_KEY", "/dev/shm/client.key")


def test_require_redis_remoto_falla_sin_redis_url(monkeypatch):
    _remoto_completo(monkeypatch)
    monkeypatch.setattr(config, "REDIS_URL_ENV", None)

    with pytest.raises(RuntimeError, match="REDIS_URL"):
        config.require_redis_remoto()


def test_require_redis_remoto_falla_si_redis_url_no_es_rediss(monkeypatch):
    _remoto_completo(monkeypatch)
    monkeypatch.setattr(config, "REDIS_URL_ENV", "redis://cloud:secreto@localhost:6379/0")

    with pytest.raises(RuntimeError, match="rediss://") as exc_info:
        config.require_redis_remoto()

    assert "secreto" not in str(exc_info.value)


@pytest.mark.parametrize("faltante", ["REDIS_TLS_CA", "REDIS_TLS_CERT", "REDIS_TLS_KEY"])
def test_require_redis_remoto_nombra_el_tls_que_falta(monkeypatch, faltante):
    _remoto_completo(monkeypatch)
    monkeypatch.setattr(config, faltante, None)

    with pytest.raises(RuntimeError, match=faltante):
        config.require_redis_remoto()


def test_require_redis_remoto_pasa_con_la_configuracion_completa(monkeypatch):
    _remoto_completo(monkeypatch)

    config.require_redis_remoto()


def test_require_redis_remoto_no_exige_nada_en_local(monkeypatch):
    monkeypatch.setattr(config, "ENTORNO", "local")
    monkeypatch.setattr(config, "REDIS_URL_ENV", None)
    monkeypatch.setattr(config, "REDIS_TLS_CA", None)

    config.require_redis_remoto()


def test_cloud_no_arranca_en_remoto_sin_redis_url(monkeypatch):
    import asyncio

    from cloud import main as cloud_main

    monkeypatch.setattr(config, "ENTORNO", "remoto")
    monkeypatch.setattr(config, "REDIS_URL_ENV", None)
    monkeypatch.setattr(config, "MODEL_RUN_DIR", "/tmp/modelo")

    with pytest.raises(RuntimeError, match="REDIS_URL"):
        asyncio.run(cloud_main.main())


def test_fog_no_arranca_en_remoto_sin_redis_url():
    import os
    import subprocess
    import sys

    env = {
        k: v for k, v in os.environ.items()
        if k not in ("REDIS_URL", "REDIS_TLS_CA", "REDIS_TLS_CERT", "REDIS_TLS_KEY")
    }
    env.update(
        ENTORNO="remoto", FEATURE_STATS_PATH="/x", FEATURE_PREPROCESSING_PROFILE="lstm_6class",
        EVIDENCE_DIR="/x", DATABASE_URL="postgresql+asyncpg://u:p@127.0.0.1/db",
        AUTH_USER="u", AUTH_PASSWORD_HASH="h", AUTH_JWT_SECRET="x" * 40,
    )

    r = subprocess.run(
        [sys.executable, "-c", "import fog.main"],
        env=env, cwd=os.getcwd(), capture_output=True, text=True, timeout=60,
    )

    assert r.returncode != 0
    assert "REDIS_URL" in r.stderr
