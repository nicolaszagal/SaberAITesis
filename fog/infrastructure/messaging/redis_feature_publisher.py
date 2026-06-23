"""RedisFeaturePublisher — implementa FeatureStreamPublisherPort publicando
en el stream `fog:features` (ver CONTRATO_API.md sección 3). Agrega los
campos has_luz_A/has_luz_B respecto al contrato viejo, porque el pipeline
lstm_4class usa la luz Favero como input real del modelo, no solo como
máscara post-hoc.
"""

from datetime import datetime, timezone

import redis.asyncio as redis

from fog.domain.models import ExtractedFeatures, LuzSignal, WeaponSide
from fog.ports.feature_publisher import FeatureStreamPublisherPort
from shared import config


class RedisFeaturePublisher(FeatureStreamPublisherPort):
    def __init__(self, client: "redis.Redis"):
        self._client = client

    async def publish(
        self,
        match_id: str,
        features: ExtractedFeatures,
        luz: LuzSignal,
        weapon_side_a: WeaponSide,
        weapon_side_b: WeaponSide,
    ) -> None:
        seq = features.sequence
        if seq is None:
            raise ValueError("no se puede publicar ExtractedFeatures con sequence=None")

        await self._client.xadd(
            config.STREAM_FEATURES,
            {
                "match_id": match_id,
                "shape": f"{seq.shape[0]},{seq.shape[1]}",
                "dtype": str(seq.dtype),
                "features": seq.tobytes(),
                "weapon_side_A": weapon_side_a.value,
                "weapon_side_B": weapon_side_b.value,
                "has_luz_A": "1" if luz.has_luz_a else "0",
                "has_luz_B": "1" if luz.has_luz_b else "0",
                "ts": datetime.now(timezone.utc).isoformat(),
            },
        )
