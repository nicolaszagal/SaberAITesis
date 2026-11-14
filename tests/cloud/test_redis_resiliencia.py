"""Cloud no se queda colgado si pierde Redis (FIX04, Parte 2).

Con la tailnet cortada o el Redis del Mac reiniciado, el consumidor debe salir con error tras N fallos
seguidos de conexión, para que la política de reinicio de Railway actúe y el servicio quede en FAILED
si el problema persiste. Antes del cambio el cliente no tenía tiempo de espera y el proceso se quedaba
bloqueado sin escribir nada.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from cloud.infrastructure.messaging.redis_feature_consumer import RedisFeatureConsumer
from cloud.ports.feature_consumer import ColaPerdidaError
from shared import config
from tests.shared.conftest import terminar_grupo

BACKEND = Path(__file__).resolve().parents[2]
RUN_DIR = BACKEND.parent / "dataset" / "lstm_6class" / "checkpoints" / "20260928_141021"


class ClienteQueFalla:
    """Cliente de Redis falso: `xreadgroup` sigue un guion de resultados o excepciones."""

    def __init__(self, guion):
        self._guion = list(guion)
        self.llamadas = 0

    async def xgroup_create(self, *a, **k):
        return True

    async def xautoclaim(self, *a, **k):
        return (b"0-0", [], [])

    async def xreadgroup(self, *a, **k):
        self.llamadas += 1
        paso = self._guion.pop(0)
        if isinstance(paso, Exception):
            raise paso
        return paso


def _consumidor(guion, fallos_max=3):
    cliente = ClienteQueFalla(guion)
    return cliente, RedisFeatureConsumer(cliente, fallos_max=fallos_max, espera_s=0.0)


async def test_sale_con_error_tras_n_fallos_seguidos():
    cliente, consumidor = _consumidor([RedisConnectionError("caído")] * 5)

    with pytest.raises(ColaPerdidaError, match="3"):
        await consumidor.consume().__anext__()

    assert cliente.llamadas == 3


async def test_un_timeout_cuenta_como_fallo():
    cliente, consumidor = _consumidor([RedisTimeoutError("sin respuesta")] * 5, fallos_max=2)

    with pytest.raises(ColaPerdidaError):
        await consumidor.consume().__anext__()

    assert cliente.llamadas == 2


async def test_un_exito_reinicia_la_cuenta_de_fallos():
    guion = [RedisConnectionError("x"), RedisConnectionError("x"), None,
             RedisConnectionError("x"), RedisConnectionError("x"), None]
    cliente, consumidor = _consumidor(guion + [RedisConnectionError("x")] * 3)

    with pytest.raises(ColaPerdidaError):
        await consumidor.consume().__anext__()

    # 2 fallos + éxito + 2 fallos + éxito no alcanzan N=3 seguidos; el 3.er bloque sí.
    assert cliente.llamadas == 9


def test_los_tiempos_de_redis_dejan_margen_sobre_el_bloqueo_del_xreadgroup():
    kwargs = config.cloud_redis_kwargs()

    assert kwargs["socket_timeout"] * 1000 >= config.CLOUD_XREAD_BLOCK_MS + 1000
    assert kwargs["socket_connect_timeout"] > 0
    assert kwargs["health_check_interval"] > 0


def test_tiempos_incoherentes_se_rechazan(monkeypatch):
    monkeypatch.setattr(config, "CLOUD_XREAD_BLOCK_MS", 5000)
    monkeypatch.setattr(config, "REDIS_SOCKET_TIMEOUT_S", 5.0)

    with pytest.raises(RuntimeError, match="REDIS_SOCKET_TIMEOUT_S"):
        config.cloud_redis_kwargs()


# --- Integración: Cloud real contra un redis-server que se detiene a mitad ----------------------

requiere_redis = pytest.mark.skipif(
    shutil.which("redis-server") is None or not RUN_DIR.exists(),
    reason="requiere redis-server y el checkpoint del modelo",
)


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _esperar(condicion, limite_s):
    fin = time.monotonic() + limite_s
    while time.monotonic() < fin:
        if condicion():
            return True
        time.sleep(0.2)
    return False


@requiere_redis
@pytest.mark.parametrize("corte", ["muerte", "congelado"])
def test_cloud_termina_con_error_en_menos_de_30_s_si_redis_se_detiene(tmp_path, corte):
    puerto = _puerto_libre()
    redis_proc = subprocess.Popen(
        [shutil.which("redis-server"), "--port", str(puerto), "--bind", "127.0.0.1", "--save", "",
         "--dir", str(tmp_path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    log = tmp_path / "cloud.log"
    entorno = {**os.environ, "REDIS_URL": f"redis://127.0.0.1:{puerto}/0", "MODEL_RUN_DIR": str(RUN_DIR),
               "PYTHONPATH": str(BACKEND)}
    for k in ("ENTORNO", "REDIS_TLS_CA", "REDIS_TLS_CERT", "REDIS_TLS_KEY"):
        entorno.pop(k, None)
    cloud = None
    try:
        assert _esperar(lambda: socket.socket().connect_ex(("127.0.0.1", puerto)) == 0, 10)
        with log.open("w") as f:
            cloud = subprocess.Popen([sys.executable, "-m", "cloud.main"], cwd=BACKEND, env=entorno,
                                     stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
        assert _esperar(lambda: "Cloud escuchando" in log.read_text(), 60), log.read_text()[-800:]
        time.sleep(1)  # que quede bloqueado en el XREADGROUP

        t0 = time.monotonic()
        if corte == "muerte":
            os.killpg(redis_proc.pid, signal.SIGKILL)
            redis_proc.wait(timeout=5)  # recoge el proceso: sin zombi
        else:
            os.killpg(redis_proc.pid, signal.SIGSTOP)  # el socket sigue abierto y no contesta
        salio = _esperar(lambda: cloud.poll() is not None, 30)
        tardo = time.monotonic() - t0

        assert salio, f"Cloud sigue colgado a los {tardo:.0f} s\n{log.read_text()[-800:]}"
        assert cloud.returncode != 0
        assert "Redis" in log.read_text()
    finally:
        if cloud is not None and cloud.poll() is None:
            terminar_grupo(cloud)
        try:
            os.killpg(redis_proc.pid, signal.SIGCONT)
        except (ProcessLookupError, PermissionError):
            pass  # ya murió (zombi hasta que terminar_grupo lo recoja)
        terminar_grupo(redis_proc)
