"""AbrirRevisionVar — CU-02, CU-03, CU-05: al recibir el clip registra
`clip`, `tocado` simulado, su vínculo y la `revision_var` aceptada, en una
sola transacción. No guarda qué tirador pidió la revisión (D-04).
"""

from __future__ import annotations

from dataclasses import dataclass

from fog.domain.audit_models import Clip, Combate, Revision, Tocado
from fog.domain.models import LuzSignal
from fog.ports.unidad_de_trabajo import UnidadDeTrabajoPort


@dataclass(frozen=True)
class VideoGuardado:
    """Clip ya almacenado (FileStoragePort) con sus metadatos de video."""

    uri: str
    sha256: str
    fps: float
    ancho_px: int
    alto_px: int
    duracion_ms: int


@dataclass(frozen=True)
class RevisionAbierta:
    clip: Clip
    tocado: Tocado
    revision: Revision


class AbrirRevisionVar:
    def __init__(self, uow: UnidadDeTrabajoPort):
        self._uow = uow

    async def execute(
        self,
        *,
        combate: Combate,
        video: VideoGuardado,
        luz: LuzSignal,
        t_tocado_ms: int,
    ) -> RevisionAbierta:
        """Registra clip, tocado simulado y revisión abierta.

        `frame_tocado` = round(t_tocado_ms / 1000 · fps).

        Args:
            combate: combate activo al que pertenece el clip.
            video: archivo guardado y sus metadatos.
            luz: luces Favero simuladas (al menos una encendida).
            t_tocado_ms: instante del tocado desde el inicio del clip.

        Returns:
            Las tres filas creadas.
        """
        async with self._uow.transaccion() as tx:
            clip = await tx.clips.crear(
                combate_id=combate.id,
                origen="carga",
                camara="unica",
                uri=video.uri,
                sha256=video.sha256,
                fps=video.fps,
                ancho_px=video.ancho_px,
                alto_px=video.alto_px,
                duracion_ms=video.duracion_ms,
            )
            tocado = await tx.tocados.crear(
                combate_id=combate.id,
                fuente="simulado",
                luz_a=luz.has_luz_a,
                luz_b=luz.has_luz_b,
                t_tocado_ms=t_tocado_ms,
            )
            await tx.tocados.vincular_clip(
                tocado.id, clip.id, round(t_tocado_ms / 1000 * video.fps)
            )
            revision = await tx.revisiones.crear(
                tocado_id=tocado.id, aceptada=True, arbitro_id=combate.arbitro_id
            )
        return RevisionAbierta(clip=clip, tocado=tocado, revision=revision)
