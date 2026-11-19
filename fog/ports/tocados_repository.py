"""TocadosRepositoryPort — consulta de tocados y decisión en pista (EDGE02).

Los tocados se escriben con `TocadoRepositoryPort` dentro de la unidad de trabajo; este puerto
solo lee la lista que ve el operador y agrega filas a `decision_pista` (solo de adición).
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class DecisionPista:
    """Lo que cantó el árbitro en pista (sin ver la sugerencia, D-04).

    Attributes:
        clase: clase del modelo (`AttackA`, ...), o `None` si se anuló.
        anulado: True si el tocado se anuló.
        registrado_en: hora del registro; la fila más reciente reemplaza a las anteriores.
    """

    clase: str | None
    anulado: bool
    registrado_en: datetime


@dataclass(frozen=True)
class TocadoListado:
    """Fila de la lista "Últimos tocados". No lleva la sugerencia (solo dentro de la revisión).

    Attributes:
        id: identificador del tocado.
        combate_id: combate al que pertenece.
        creado_en: hora en que Fog lo registró.
        fuente: 'favero' o 'simulado'.
        luz_a: luz de A encendida.
        luz_b: luz de B encendida.
        t_luz_a_ms: instante de la luz A en el clip, o None.
        t_luz_b_ms: instante de la luz B en el clip, o None.
        tiene_clip: True si el archivo del clip sigue disponible para reproducirlo.
        clasificado: True si ya existe la clasificación (solo el hecho, no su contenido).
        revision_id: revisión abierta con "Solicitar VAR", o None (tocado "No revisado").
        cerrado: True si llegó un tocado posterior del mismo combate: ya no admite VAR.
        decision_pista: la decisión en pista vigente, o None.
    """

    id: uuid.UUID
    combate_id: uuid.UUID
    creado_en: datetime
    fuente: str
    luz_a: bool
    luz_b: bool
    t_luz_a_ms: int | None
    t_luz_b_ms: int | None
    tiene_clip: bool
    clasificado: bool
    revision_id: uuid.UUID | None
    cerrado: bool
    decision_pista: DecisionPista | None


@dataclass(frozen=True)
class ClipDeTocado:
    """Clip guardado de un tocado."""

    clip_id: uuid.UUID
    uri: str
    sha256: str
    fps: float


class TocadosRepositoryPort(ABC):
    @abstractmethod
    async def listar(self, combate_id: uuid.UUID, limite: int) -> list[TocadoListado]:
        """Los últimos `limite` tocados del combate, el más reciente primero."""
        raise NotImplementedError

    @abstractmethod
    async def obtener(self, tocado_id: uuid.UUID) -> TocadoListado | None:
        """Un tocado con el mismo formato de la lista, o None si no existe."""
        raise NotImplementedError

    @abstractmethod
    async def registrar_decision(
        self,
        tocado_id: uuid.UUID,
        *,
        clase: str | None,
        anulado: bool,
        registrado_por: uuid.UUID | None,
    ) -> DecisionPista:
        """Agrega una fila a `decision_pista` (nunca modifica ni borra)."""
        raise NotImplementedError

    @abstractmethod
    async def clip_de(self, tocado_id: uuid.UUID) -> ClipDeTocado | None:
        """El clip vinculado al tocado, o None si aún no se registró."""
        raise NotImplementedError

    @abstractmethod
    async def uris_clips(self, combate_id: uuid.UUID | None = None) -> list[str]:
        """URIs de todos los clips (de un combate, o de todos si es None)."""
        raise NotImplementedError
