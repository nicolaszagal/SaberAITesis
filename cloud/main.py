"""
Cloud — consumidor Redis Streams + inferencia LSTM.

Lee features extraídas por Fog desde el stream "fog:features" (grupo de
consumidores "cloud_workers"), corre el modelo desplegado (LSTMClassifier,
192 features, 4 clases, luz Favero como input, dataset/lstm_4class/
checkpoints/best_model.pt — ver ../CONTRATO_API.md), aplica la política de
arbitraje (máscara hard de luz Favero) y publica el veredicto en
"cloud:verdicts:{match_id}" para que Fog lo reenvíe al front por WebSocket.

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
    container = Container()
    container.config.redis_url.from_value(config.REDIS_URL)
    container.config.checkpoint_path.from_value(config.LSTM_CHECKPOINT_PATH)

    log.info("Cargando %s ...", config.LSTM_CHECKPOINT_PATH)
    use_case = container.classify_and_publish()
    log.info("Cloud escuchando '%s' como '%s'...", config.STREAM_FEATURES, config.CONSUMER_CLOUD)
    await use_case.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
