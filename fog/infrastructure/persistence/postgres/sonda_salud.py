"""Sonda de PostgreSQL para GET /health: `SELECT 1` con tiempo límite."""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fog.ports.sonda_salud import SondaSaludPort


class PostgresSonda(SondaSaludPort):
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], timeout_s: float = 2.0
    ):
        self._session_factory = session_factory
        self._timeout_s = timeout_s

    async def responde(self) -> bool:
        async def consulta() -> None:
            async with self._session_factory() as session:
                await session.execute(text("SELECT 1"))

        try:
            await asyncio.wait_for(consulta(), self._timeout_s)
        except Exception:
            return False
        return True
