"""MatchRepositoryPort — persistencia del agregado Match.

Hoy solo existe InMemoryMatchRepository (decisión "no por ahora, pero con
puerto listo", ver PLAN_ARQUITECTURA_DDD.md sección 1). Agregar MongoDB
más adelante (como muestra arquitectura_diagramas.html) es escribir un
nuevo adaptador, sin tocar application/ ni infrastructure/api/.
"""

from abc import ABC, abstractmethod

from fog.domain.models import Match


class MatchRepositoryPort(ABC):
    @abstractmethod
    async def save(self, match: Match) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get(self, match_id: str) -> Match | None:
        raise NotImplementedError
