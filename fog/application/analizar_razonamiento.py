"""AnalizarRazonamientoEvento — EXP03-b: calcula en memoria el razonamiento de
las revisiones de un evento con los parámetros vigentes, para describir cómo se
reparten los estados, las causas de `insuficiente` y las censuras.

Solo lectura (D-17): no escribe en `evidencia` ni en la auditoría, y no cambia
lo que Fog guardó al clasificar. Es un análisis descriptivo, no una métrica de
aceptación.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from fog.application.registrar_clasificacion import (
    ContextoClip,
    calcular_razonamiento,
)
from fog.domain.analisis_razonamiento import ClipAnalizado, analizar_clip
from fog.domain.errors import KeypointsAlterados
from fog.domain.models import PersonPose, TrackedFrame, TrackedSequence, lado_de_brazo
from fog.ports.consulta_revision_repository import ConsultaRevisionRepositoryPort
from fog.ports.feature_extractor import FeatureExtractorPort
from fog.ports.file_storage import FileStoragePort
from fog.ports.parametros_explicacion import ParametrosExplicacionPort

log = logging.getLogger("fog.application")

SIN_CLASIFICACION = "sin_clasificacion"
NO_DISPONIBLE = "clasificacion_no_disponible"
SIN_KEYPOINTS = "sin_keypoints"
KEYPOINTS_ALTERADOS = "keypoints_alterados"
SIN_CLIP = "sin_clip"
ERROR_DE_CALCULO = "error_de_calculo"


@dataclass(frozen=True)
class AnalisisEvento:
    """Resultado del análisis de un evento.

    Attributes:
        evento_id: evento analizado.
        params_version: versión de los parámetros usados.
        revisiones_total: revisiones del evento.
        clips: clips analizados (revisiones con clasificación disponible y pose).
        omitidas: cuántas revisiones se dejaron fuera, por motivo.
    """

    evento_id: uuid.UUID
    params_version: str
    revisiones_total: int
    clips: list[ClipAnalizado]
    omitidas: dict[str, int] = field(default_factory=dict)


def tracked_desde_npz(npz: dict[str, np.ndarray]) -> TrackedSequence:
    """Reconstruye la `TrackedSequence` a partir del .npz de keypoints crudos.

    Args:
        npz: arreglos que guarda `keypoints_a_arrays`.

    Returns:
        La secuencia con los mismos frames y el mismo `lock_frame`.
    """
    n = int(npz["a_xy"].shape[0])

    def persona(lado: str, t: int) -> PersonPose:
        return PersonPose(
            keypoints_xy=npz[f"{lado}_xy"][t],
            keypoints_conf=npz[f"{lado}_conf"][t],
            box_xyxy=npz[f"{lado}_box"][t],
            detected=bool(npz[f"{lado}_detected"][t]),
        )

    lock = int(npz["lock_frame"])
    return TrackedSequence(
        frames=[TrackedFrame(persona("a", t), persona("b", t)) for t in range(n)],
        frame_w=int(npz["frame_w"]),
        frame_h=int(npz["frame_h"]),
        locked=bool(npz["locked"]),
        lock_frame=lock if lock >= 0 else None,
    )


class AnalizarRazonamientoEvento:
    def __init__(
        self,
        consulta: ConsultaRevisionRepositoryPort,
        storage: FileStoragePort,
        extractor: FeatureExtractorPort,
        parametros: ParametrosExplicacionPort,
    ):
        self._consulta = consulta
        self._storage = storage
        self._extractor = extractor
        self._parametros = parametros

    async def execute(self, evento_id: uuid.UUID) -> AnalisisEvento:
        """Calcula el razonamiento en memoria de las revisiones de un evento.

        La atención no se guarda fuera de la ventana ya registrada, así que aquí
        no hay ventana: solo importan el estado y los eventos de pose.

        Args:
            evento_id: evento a analizar.

        Returns:
            Los clips analizados y cuántas revisiones se omitieron, por motivo.
        """
        params = self._parametros.cargar()
        revisiones = await self._consulta.listar(evento_id=evento_id)
        clips: list[ClipAnalizado] = []
        omitidas: Counter[str] = Counter()
        for r in revisiones:
            resultado = await self._una(r.id, params)
            if isinstance(resultado, str):
                omitidas[resultado] += 1
            else:
                clips.append(resultado)
        return AnalisisEvento(
            evento_id, params.version, len(revisiones), clips, dict(omitidas)
        )

    async def _una(self, revision_id: uuid.UUID, params) -> ClipAnalizado | str:
        razon = await self._consulta.datos_razonamiento(revision_id)
        if razon is None or razon.clasificacion_id is None:
            return SIN_CLASIFICACION
        if not razon.disponible:
            return NO_DISPONIBLE
        datos = await self._consulta.datos_pose(revision_id)
        if datos is None or datos.fps is None or datos.frame_tocado is None:
            return SIN_CLIP
        if datos.keypoints_uri is None or datos.keypoints_sha256 is None:
            return SIN_KEYPOINTS
        try:
            npz = await self._storage.read_keypoints(
                datos.keypoints_uri, datos.keypoints_sha256
            )
        except KeypointsAlterados:
            return KEYPOINTS_ALTERADOS
        except FileNotFoundError:
            return SIN_KEYPOINTS
        if int(npz["a_xy"].shape[0]) == 0:
            return SIN_KEYPOINTS
        tracked = tracked_desde_npz(npz)
        try:
            razonamiento = calcular_razonamiento(
                self._extractor,
                params,
                tracked,
                npz,
                razon.clase,
                None,
                ContextoClip(
                    datos.fps,
                    datos.frame_tocado,
                    lado_de_brazo(datos.brazo_a),
                    lado_de_brazo(datos.brazo_b),
                ),
                str(revision_id),
            )
        except Exception:
            log.exception("razonamiento.error revision=%s (análisis)", revision_id)
            return ERROR_DE_CALCULO
        lock = int(npz["lock_frame"])
        return analizar_clip(str(revision_id), razon.clase, razonamiento, lock)
