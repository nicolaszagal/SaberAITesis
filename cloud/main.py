"""
Cloud — consumidor Redis Streams + inferencia LSTM.

Lee features extraídas por Fog desde el stream "fog:features" (grupo de
consumidores "cloud_workers"), corre el modelo desplegado (LSTMClassifier,
192 features, 6 clases, luz Favero como filtro sobre logits y, según
run_config.json, también como input real del modelo — ver MODEL_RUN_DIR en
../CONTRATO_API.md), aplica la política de arbitraje (hoy sin regla propia,
ver NullArbitrationPolicy) y publica el veredicto en
"cloud:verdicts:{revision_id}" para que Fog lo reenvíe al front por WebSocket.

Arquitectura DDD/hexagonal: domain/, ports/, application/, infrastructure/
(ver PLAN_ARQUITECTURA_DDD.md). Este archivo solo ensambla el Container
(composition.py) y arranca el loop del caso de uso.

Ejecutar (desde backend/):
    python -m cloud.main
"""

import asyncio
import logging

from cloud.composition import Container
from shared import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s:%(name)s:%(message)s")
log = logging.getLogger("cloud")


async def main() -> None:
    config.require_paths("MODEL_RUN_DIR")

    container = Container()
    container.config.redis_url.from_value(config.REDIS_URL)
    container.config.model_run_dir.from_value(config.MODEL_RUN_DIR)

    log.info("Cargando %s ...", config.MODEL_RUN_DIR)
    use_case = container.classify_and_publish()
    log.info("Cloud escuchando '%s' como '%s'...", config.STREAM_FEATURES, config.CONSUMER_CLOUD)
    await use_case.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
