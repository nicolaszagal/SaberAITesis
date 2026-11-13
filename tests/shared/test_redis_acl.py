"""SEC02: un usuario de Redis por nodo, con el mínimo de claves y comandos.

Levanta un redis-server real (sin TLS: la ACL es independiente del transporte)
con el archivo que genera redis/generar_acl.sh, y ejercita los adaptadores
reales de Fog y Cloud con cada usuario. Se omite sin `redis-server` (Redis 7+).
"""

import asyncio
import pathlib
import secrets
import shutil
import socket
import subprocess
import time

import numpy as np
import pytest
import redis
import redis.asyncio as aredis
from redis.backoff import NoBackoff
from redis.exceptions import AuthenticationError, NoPermissionError, ResponseError
from redis.retry import Retry

from cloud.domain.models import ActionClass, Verdict
from cloud.infrastructure.messaging.redis_feature_consumer import RedisFeatureConsumer
from cloud.infrastructure.messaging.redis_verdict_publisher import RedisVerdictPublisher
from fog.domain.models import ExtractedFeatures, LuzSignal, WeaponSide
from fog.infrastructure.messaging.redis_feature_publisher import RedisFeaturePublisher
from fog.infrastructure.messaging.redis_verdict_subscriber import RedisVerdictSubscriber
from tests.shared.conftest import terminar_grupo

BACKEND = pathlib.Path(__file__).resolve().parents[2]
GENERADOR = BACKEND / "redis" / "generar_acl.sh"
SERVIDOR = shutil.which("redis-server")

pytestmark = pytest.mark.skipif(SERVIDOR is None, reason="requiere redis-server")

PASS_FOG = secrets.token_urlsafe(48)
PASS_CLOUD = secrets.token_urlsafe(48)


@pytest.fixture(scope="module")
def puerto(tmp_path_factory):
    carpeta = tmp_path_factory.mktemp("redis_acl")
    acl = carpeta / "users.acl"
    subprocess.run(
        ["sh", str(GENERADOR), str(acl)],
        check=True,
        env={"PATH": "/usr/bin:/bin", "REDIS_PASSWORD_FOG": PASS_FOG, "REDIS_PASSWORD_CLOUD": PASS_CLOUD},
    )
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    proc = subprocess.Popen(
        [SERVIDOR, "--port", str(puerto), "--bind", "127.0.0.1", "--aclfile", str(acl),
         "--save", "", "--appendonly", "no", "--dir", str(carpeta)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    try:
        for _ in range(50):
            try:
                redis.Redis(port=puerto, username="fog", password=PASS_FOG).ping()
                break
            except redis.ConnectionError:
                time.sleep(0.1)
        else:
            pytest.fail("redis-server no arrancó")
        yield puerto
    finally:
        terminar_grupo(proc)


def _cliente(puerto, usuario, clave):
    return redis.Redis(port=puerto, username=usuario, password=clave)


def _acliente(puerto, usuario, clave):
    return aredis.Redis(port=puerto, username=usuario, password=clave, decode_responses=False)


def test_flujo_completo_con_los_adaptadores_reales_y_solo_sus_permisos(puerto):
    """Fog publica features, Cloud las consume y responde, Fog lee el veredicto."""

    async def escenario():
        fog = _acliente(puerto, "fog", PASS_FOG)
        cloud = _acliente(puerto, "cloud", PASS_CLOUD)
        await RedisFeaturePublisher(fog).publish(
            "m1", "rev-acl", ExtractedFeatures(sequence=np.zeros((3, 192), dtype=np.float32)),
            LuzSignal(has_luz_a=True, has_luz_b=False), WeaponSide.RIGHT, WeaponSide.LEFT,
        )
        consumidor = RedisFeatureConsumer(cloud).consume()
        entrada_id, secuencia = await asyncio.wait_for(anext(consumidor), timeout=10)
        assert secuencia.revision_id == "rev-acl"
        await RedisFeatureConsumer(cloud).ack(entrada_id)
        await RedisVerdictPublisher(cloud).publish(Verdict(
            match_id="m1", revision_id="rev-acl", disponible=True, action_class=ActionClass.ATTACK_A,
            confidence=0.9, fencer="ROJ", probs={"AttackA": 0.9}, latencia_inferencia_ms=5,
            modelo="lstm_6class/run/best_model.pt",
        ))
        recibido = await asyncio.wait_for(RedisVerdictSubscriber(fog).wait_for_verdict("rev-acl"), timeout=10)
        assert recibido.action == "AttackA"
        # Cloud también manda al dead-letter lo que no cumple el contrato.
        await cloud.xadd("fog:features:dead", {"motivo": "prueba"})
        assert await fog.ping()
        await consumidor.aclose()
        await fog.aclose()
        await cloud.aclose()

    asyncio.run(escenario())


@pytest.mark.parametrize("comando", [
    ("XADD", "cloud:verdicts:rev-acl", "*", "a", "b"),          # no escribe veredictos
    ("XADD", "fog:features:dead", "*", "a", "b"),
    ("XREAD", "STREAMS", "fog:features", "0"),                   # no lee sus propias features
    ("XREAD", "STREAMS", "fog:features:dead", "0"),
    ("XGROUP", "CREATE", "fog:features", "g", "0"),
    ("XREADGROUP", "GROUP", "g", "c", "STREAMS", "fog:features", ">"),
    ("DEL", "fog:features"),
    ("DEL", "cloud:verdicts:rev-acl"),
    ("EXPIRE", "cloud:verdicts:rev-acl", "10"),
    ("XADD", "auth:x", "*", "a", "b"),                           # claves ajenas
    ("SET", "fog:features", "x"),
    ("GET", "fog:features"),
    ("KEYS", "*"),
    ("FLUSHALL",),
    ("CONFIG", "GET", "*"),
    ("ACL", "LIST"),
    ("XTRIM", "fog:features", "MAXLEN", "0"),
])
def test_fog_es_rechazado_fuera_de_lo_suyo(puerto, comando):
    with pytest.raises(NoPermissionError):
        _cliente(puerto, "fog", PASS_FOG).execute_command(*comando)


@pytest.mark.parametrize("comando", [
    ("XADD", "fog:features", "*", "a", "b"),                     # no inyecta features
    ("XREAD", "STREAMS", "cloud:verdicts:rev-acl", "0"),         # no lee veredictos
    ("XREAD", "STREAMS", "fog:features", "0"),                   # solo por grupo de consumidores
    ("XTRIM", "fog:features", "MAXLEN", "0"),
    ("XGROUP", "DESTROY", "fog:features", "cloud_workers"),
    ("XADD", "auth:x", "*", "a", "b"),
    ("XADD", "otra:clave", "*", "a", "b"),
    ("EXPIRE", "fog:features", "1"),
    ("DEL", "fog:features"),
    ("DEL", "cloud:verdicts:rev-acl"),
    ("SET", "cloud:verdicts:x", "x"),
    ("GET", "cloud:verdicts:x"),
    ("KEYS", "*"),
    ("FLUSHALL",),
    ("CONFIG", "GET", "*"),
    ("ACL", "LIST"),
])
def test_cloud_es_rechazado_fuera_de_lo_suyo(puerto, comando):
    with pytest.raises(NoPermissionError):
        _cliente(puerto, "cloud", PASS_CLOUD).execute_command(*comando)


def test_sin_credenciales_o_con_usuario_default_no_entra(puerto):
    # redis-py reintenta 3 veces con espera creciente los ConnectionError (incluido el rechazo de
    # credenciales); aquí el rechazo es el resultado esperado, así que sin reintentos ni esperas.
    corto = {"retry": Retry(NoBackoff(), 0), "socket_connect_timeout": 2, "socket_timeout": 2}
    for usuario, clave in [("default", ""), ("default", PASS_FOG), ("sabre", PASS_FOG),
                           ("fog", PASS_CLOUD), ("cloud", PASS_FOG), ("fog", "mala")]:
        with pytest.raises((AuthenticationError, ResponseError)):
            redis.Redis(port=puerto, username=usuario, password=clave, **corto).ping()
    with pytest.raises((AuthenticationError, ResponseError)):
        redis.Redis(port=puerto, **corto).ping()
