"""Adaptador de VerificadorAuditoriaPort: llama a
`sabre.fn_verificar_auditoria()` (STABLE, solo lectura)."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fog.domain.audit_models import RegistroAlterado
from fog.ports.verificador_auditoria import VerificadorAuditoriaPort


class PostgresVerificadorAuditoria(VerificadorAuditoriaPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def verificar(self) -> list[RegistroAlterado]:
        async with self._session_factory() as session:
            filas = (
                await session.execute(
                    text("SELECT seq, esperado, guardado FROM sabre.fn_verificar_auditoria()")
                )
            ).all()
        return [RegistroAlterado(seq=f.seq, esperado=f.esperado, guardado=f.guardado) for f in filas]
