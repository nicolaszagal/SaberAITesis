"""
Cloud — clasificación LSTM con dos entradas posibles.

- **Redis** (modo local): lee las features que Fog publica en "fog:features" (grupo
  "cloud_workers") y publica el veredicto en "cloud:verdicts:{revision_id}". Se activa solo si
  hay `REDIS_URL`.
- **HTTP** (modo remoto, DEPLOY11): `POST /v1/clasificar` con el token de un nodo. Se activa solo
  si hay `CLOUD_NODOS_SHA256` (hashes de los tokens). Sin `REDIS_URL`, Cloud corre solo con HTTP.

Las dos entradas usan el mismo caso de uso (`ClasificarSecuencia`): modelo desplegado
(LSTMClassifier, 192 features, 6 clases, luz Favero como filtro sobre logits y, según
run_config.json, también como input real del modelo — ver MODEL_RUN_DIR en
../CONTRATO_API.md) y política de arbitraje (hoy sin regla propia, ver NullArbitrationPolicy).

Arquitectura DDD/hexagonal: domain/, ports/, application/, infrastructure/
(ver PLAN_ARQUITECTURA_DDD.md). Este archivo solo ensambla el Container
(composition.py) y arranca las entradas activas.

Ejecutar (desde backend/):
    python -m cloud.main
"""

import asyncio
import logging
import sys

import uvicorn

from cloud.composition import Container
from cloud.infrastructure.api.nodos import NodosInvalidosError
from cloud.ports.feature_consumer import ColaPerdidaError
from shared import config
from shared.logging_config import configurar_logging_tecnico

configurar_logging_tecnico()
log = logging.getLogger("cloud")


async def _correr(container: Container, redis_on: bool, http_on: bool) -> None:
    """Arranca las entradas activas y termina cuando cualquiera de ellas termina.

    Args:
        container: contenedor ya configurado.
        redis_on: si se consume `fog:features`.
        http_on: si se abre la API HTTP.

    Raises:
        ColaPerdidaError: si el consumidor de Redis pierde la cola (FIX04).
    """
    tareas: dict[str, asyncio.Task] = {}
    servidor = None
    if http_on:
        servidor = uvicorn.Server(uvicorn.Config(
            container.api_http(), host=config.CLOUD_HTTP_HOST, port=config.CLOUD_HTTP_PUERTO,
            log_config=None, access_log=False, server_header=False,
        ))
        tareas["http"] = asyncio.create_task(servidor.serve())
        log.info("Cloud HTTP escuchando en %s:%d (nodos: %s)", config.CLOUD_HTTP_HOST,
                 config.CLOUD_HTTP_PUERTO, ", ".join(container.registro_nodos().nombres))
    if redis_on:
        log.info("Cloud escuchando '%s' como '%s'...", config.STREAM_FEATURES, config.CONSUMER_CLOUD)
        tareas["redis"] = asyncio.create_task(container.classify_and_publish().run_forever())

    try:
        await asyncio.wait(tareas.values(), return_when=asyncio.FIRST_COMPLETED)
    finally:
        if servidor is not None:
            servidor.should_exit = True
        for t in tareas.values():
            if not t.done():
                t.cancel()
        resultados = await asyncio.gather(*tareas.values(), return_exceptions=True)
    for r in resultados:
        if isinstance(r, ColaPerdidaError):
            raise r


async def main() -> None:
    redis_on = config.redis_activo()
    http_on = bool(config.CLOUD_NODOS_SHA256)
    if not redis_on and not http_on:
        log.critical("Cloud no tiene ninguna entrada: defina REDIS_URL (Redis) o CLOUD_NODOS_SHA256 (HTTP).")
        sys.exit(1)
    config.require_paths("MODEL_RUN_DIR")
    # La validación estricta de Redis (FIX04, DEPLOY09) solo aplica si el transporte Redis está activo.
    if redis_on:
        config.require_redis_remoto()

    container = Container()
    container.config.redis_url.from_value(config.REDIS_URL)
    container.config.model_run_dir.from_value(config.MODEL_RUN_DIR)
    container.config.nodos_sha256.from_value(config.CLOUD_NODOS_SHA256)
    if http_on:
        try:
            container.registro_nodos()
        except NodosInvalidosError as e:
            log.critical("%s", e)
            sys.exit(1)

    log.info("Cargando %s ...", config.MODEL_RUN_DIR)
    container.clasificar_secuencia().precalentar()  # F-027: si falla, la excepción impide arrancar
    try:
        await _correr(container, redis_on, http_on)
    except ColaPerdidaError as e:
        # Código distinto de 0: la política de reinicio de la plataforma actúa (FIX04).
        log.critical("%s", e)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
