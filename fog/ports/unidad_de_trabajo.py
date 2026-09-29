"""UnidadDeTrabajoPort — una transacción que agrupa los repositorios del
esquema de auditoría.

Los repositorios sueltos abren una transacción por llamada. Los flujos que
deben ser atómicos (configurar combate, abrir revisión, registrar
veredicto: RF-21/RF-22) piden una `Transaccion`: todos sus repositorios
comparten la misma transacción, que se confirma al salir del bloque y se
revierte si el bloque lanza una excepción.
"""

from abc import ABC, abstractmethod
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from fog.ports.auditoria_repository import AuditoriaRepositoryPort
from fog.ports.clasificacion_repository import ClasificacionRepositoryPort
from fog.ports.clip_repository import ClipRepositoryPort
from fog.ports.combate_repository import CombateRepositoryPort
from fog.ports.evento_repository import EventoRepositoryPort
from fog.ports.modelo_version_repository import ModeloVersionRepositoryPort
from fog.ports.revision_repository import RevisionRepositoryPort
from fog.ports.tirador_repository import TiradorRepositoryPort
from fog.ports.tocado_repository import TocadoRepositoryPort
from fog.ports.usuario_repository import UsuarioRepositoryPort
from fog.ports.veredicto_repository import VeredictoRepositoryPort


@dataclass(frozen=True)
class Transaccion:
    eventos: EventoRepositoryPort
    usuarios: UsuarioRepositoryPort
    tiradores: TiradorRepositoryPort
    combates: CombateRepositoryPort
    clips: ClipRepositoryPort
    tocados: TocadoRepositoryPort
    modelos: ModeloVersionRepositoryPort
    clasificaciones: ClasificacionRepositoryPort
    revisiones: RevisionRepositoryPort
    veredictos: VeredictoRepositoryPort
    auditoria: AuditoriaRepositoryPort


class UnidadDeTrabajoPort(ABC):
    @abstractmethod
    def transaccion(self) -> AbstractAsyncContextManager[Transaccion]:
        """Abre una transacción.

        Returns:
            Context manager async que entrega la `Transaccion`. Confirma al
            salir sin error; revierte si el bloque lanza una excepción.
        """
        raise NotImplementedError
