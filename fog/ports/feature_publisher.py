"""FeatureStreamPublisherPort — envío de features extraídas hacia Cloud."""

from abc import ABC, abstractmethod

from fog.domain.models import ExtractedFeatures, LuzSignal, WeaponSide


class FeatureStreamPublisherPort(ABC):
    @abstractmethod
    async def publish(
        self,
        match_id: str,
        features: ExtractedFeatures,
        luz: LuzSignal,
        weapon_side_a: WeaponSide,
        weapon_side_b: WeaponSide,
    ) -> None:
        raise NotImplementedError
