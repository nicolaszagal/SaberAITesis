"""Redis opcional en Cloud (DEPLOY11): arranque solo con HTTP, solo con Redis y con ambos."""

from __future__ import annotations

import pytest

from cloud import composition
from cloud import main as cloud_main
from cloud.composition import Container
from cloud.domain.models import ActionClass, RawVerdict
from cloud.infrastructure.api.nodos import hash_token
from shared import config
from tests.cloud.fakes import FakeActionClassifier

NODOS = f"ana:{hash_token('token-de-ana')}"


def _crudo() -> RawVerdict:
    return RawVerdict(action_class=ActionClass.ATTACK_A, confidence=0.8, probs={}, atencion=None)


@pytest.fixture
def sin_redis(monkeypatch):
    """Falla si algo intenta abrir una conexión a Redis."""
    def prohibido(*a, **k):
        raise AssertionError("Cloud abrió una conexión a Redis con el transporte desactivado")

    monkeypatch.setattr(composition.redis, "from_url", prohibido)


class _Servidor:
    """Sustituye a uvicorn.Server: sirve hasta que se le pide salir."""
    arrancado = False

    def __init__(self, cfg):
        self.config = cfg
        self.should_exit = False

    async def serve(self):
        import asyncio
        type(self).arrancado = True
        while not self.should_exit:
            await asyncio.sleep(0.01)


def _contenedor_con_clasificador_falso() -> Container:
    contenedor = Container()
    contenedor.classifier.override(FakeActionClassifier(result=_crudo()))
    contenedor.model_version_name.override("lstm_6class/run/best_model.pt")
    contenedor.config.redis_url.from_value(config.REDIS_URL)
    contenedor.config.nodos_sha256.from_value(NODOS)
    return contenedor


async def test_cloud_arranca_solo_con_http_sin_tocar_redis(monkeypatch, sin_redis):
    monkeypatch.setattr(config, "REDIS_URL_ENV", None)
    monkeypatch.setattr(config, "CLOUD_NODOS_SHA256", NODOS)
    monkeypatch.setattr(config, "MODEL_RUN_DIR", "/ruta/run")
    monkeypatch.setattr(cloud_main, "Container", _contenedor_con_clasificador_falso)
    monkeypatch.setattr(cloud_main.uvicorn, "Server", _Servidor)
    _Servidor.arrancado = False

    import asyncio
    tarea = asyncio.create_task(cloud_main.main())
    await asyncio.sleep(0.2)
    assert _Servidor.arrancado and not tarea.done()
    tarea.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tarea


def test_la_api_http_se_arma_sin_cliente_de_redis(sin_redis):
    contenedor = _contenedor_con_clasificador_falso()
    assert contenedor.api_http() is not None


async def test_con_redis_activo_cloud_sigue_consumiendo_y_sale_si_pierde_la_cola(monkeypatch):
    """El arranque de FIX04 (ColaPerdidaError -> salida distinta de 0) sigue vigente con Redis activo."""
    from cloud.ports.feature_consumer import ColaPerdidaError

    class CasoDeUso:
        async def run_forever(self):
            raise ColaPerdidaError("Redis no responde")

        def precalentar(self):
            pass

    contenedor = _contenedor_con_clasificador_falso()
    contenedor.classify_and_publish.override(CasoDeUso())
    monkeypatch.setattr(config, "REDIS_URL_ENV", "redis://localhost:6379/0")
    monkeypatch.setattr(config, "ENTORNO", "local")
    monkeypatch.setattr(config, "CLOUD_NODOS_SHA256", None)
    monkeypatch.setattr(config, "MODEL_RUN_DIR", "/ruta/run")
    monkeypatch.setattr(cloud_main, "Container", lambda: contenedor)

    with pytest.raises(SystemExit) as salida:
        await cloud_main.main()
    assert salida.value.code == 1


async def test_nodos_mal_formados_impiden_arrancar(monkeypatch, sin_redis):
    monkeypatch.setattr(config, "REDIS_URL_ENV", None)
    monkeypatch.setattr(config, "CLOUD_NODOS_SHA256", "ana:no-es-un-hash")
    monkeypatch.setattr(config, "MODEL_RUN_DIR", "/ruta/run")

    def contenedor():
        c = _contenedor_con_clasificador_falso()
        c.config.nodos_sha256.from_value("ana:no-es-un-hash")
        return c

    monkeypatch.setattr(cloud_main, "Container", contenedor)
    with pytest.raises(SystemExit) as salida:
        await cloud_main.main()
    assert salida.value.code == 1
