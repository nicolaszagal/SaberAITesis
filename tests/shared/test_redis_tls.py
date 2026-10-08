"""TLS mutuo hacia Redis (DEPLOY07): construcción del cliente y tope de streams."""

import numpy as np
import pytest
import fakeredis.aioredis

from shared import config


def _fijar(monkeypatch, ca=None, cert=None, key=None):
    monkeypatch.setattr(config, "REDIS_TLS_CA", ca)
    monkeypatch.setattr(config, "REDIS_TLS_CERT", cert)
    monkeypatch.setattr(config, "REDIS_TLS_KEY", key)


def test_sin_variables_tls_no_cambia_el_cliente(monkeypatch):
    _fijar(monkeypatch)
    assert config.redis_tls_kwargs() == {}


def test_con_variables_tls_exige_verificacion_del_servidor(monkeypatch):
    _fijar(monkeypatch, "/ca.pem", "/c.pem", "/c.key")
    kw = config.redis_tls_kwargs()
    assert kw["ssl_ca_certs"] == "/ca.pem"
    assert kw["ssl_certfile"] == "/c.pem"
    assert kw["ssl_keyfile"] == "/c.key"
    assert kw["ssl_cert_reqs"] == "required"
    assert kw["ssl_check_hostname"] is True


def test_configuracion_tls_parcial_falla(monkeypatch):
    _fijar(monkeypatch, ca="/ca.pem")
    with pytest.raises(RuntimeError, match="REDIS_TLS_CERT"):
        config.redis_tls_kwargs()


@pytest.mark.parametrize("modulo", ["fog.composition", "cloud.composition"])
def test_cliente_rediss_usa_conexion_ssl(monkeypatch, modulo):
    import importlib

    _fijar(monkeypatch, "/ca.pem", "/c.pem", "/c.key")
    comp = importlib.import_module(modulo)
    cliente = comp._build_redis_client("rediss://sabre:x@redis.example:6379/0")
    kw = cliente.connection_pool.connection_kwargs
    assert kw["ssl_ca_certs"] == "/ca.pem"
    assert kw["ssl_certfile"] == "/c.pem"
    assert kw["ssl_keyfile"] == "/c.key"
    assert kw["ssl_cert_reqs"] == "required"
    assert kw["ssl_check_hostname"] is True


async def test_publicador_de_features_acota_el_stream(monkeypatch):
    from fog.domain.models import ExtractedFeatures, LuzSignal, WeaponSide
    from fog.infrastructure.messaging.redis_feature_publisher import RedisFeaturePublisher

    monkeypatch.setattr(config, "STREAM_MAXLEN", 5)
    cliente = fakeredis.aioredis.FakeRedis()
    pub = RedisFeaturePublisher(cliente)
    feats = ExtractedFeatures(sequence=np.zeros((3, 192), dtype=np.float32))
    for i in range(50):
        await pub.publish(
            "m", f"r{i}", feats, LuzSignal(has_luz_a=True, has_luz_b=False),
            WeaponSide.RIGHT, WeaponSide.RIGHT,
        )
    # MAXLEN aproximado: Redis recorta por bloques; debe quedar muy por debajo de 50.
    assert await cliente.xlen(config.STREAM_FEATURES) < 50
