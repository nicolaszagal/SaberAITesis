"""InMemoryMatchRepository — única implementación de MatchRepositoryPort
hoy (ver PLAN_ARQUITECTURA_DDD.md, decisión: persistencia real diferida).
Migrar a MongoDB es escribir un nuevo adaptador con la misma interfaz, sin
tocar application/ ni la API.
"""

import asyncio

from fog.domain.models import Match
from fog.ports.match_repository import MatchRepositoryPort


class InMemoryMatchRepository(MatchRepositoryPort):
    def __init__(self):
        self._matches: dict[str, Match] = {}
        self._lock = asyncio.Lock()

    async def save(self, match: Match) -> None:
        async with self._lock:
            self._matches[match.match_id] = match

    async def get(self, match_id: str) -> Match | None:
        async with self._lock:
            return self._matches.get(match_id)
