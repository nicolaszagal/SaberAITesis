"""ConsultarPose — F-031, CU-08: arma la vista de pose de una revisión para que
el árbitro vea los esqueletos de A y B en un modal con fondo negro (D-14).

Solo lectura: lee el .npz de keypoints crudos que guardó `RegistrarClasificacion`
(verificando su SHA-256) y calcula el ángulo del codo del brazo armado con las
mismas funciones geométricas que usa el extractor de features
(`shared.feature_extractor`), para que el árbitro vea el mismo ángulo que
recibe el modelo. No dibuja la línea del arma (D-18).
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass

import numpy as np

from fog.domain.errors import (
    ClasificacionPendiente,
    KeypointsAlterados,
    RecursoNoEncontrado,
)
from fog.domain.models import lado_de_brazo
from fog.ports.consulta_revision_repository import ConsultaRevisionRepositoryPort
from fog.ports.file_storage import FileStoragePort
from shared.feature_extractor import CONF_THR, WEAPON_KPT, angle_three_points, valid_pt

log = logging.getLogger("fog.application")

# Mapeo de colores (contexto_sabre.md): A = ROJ (izquierda en cámara), B = VER.
COLOR_POR_TIRADOR = {"A": "ROJ", "B": "VER"}


@dataclass(frozen=True)
class PoseTirador:
    """Pose de un tirador a lo largo del clip: un elemento por frame del .npz."""

    color: str
    brazo: str
    xy: list[list[list[float]]]
    conf: list[list[float]]
    detectado: list[bool]
    angulo_codo: list[float | None]


@dataclass(frozen=True)
class VistaPose:
    """Vista de pose de una revisión. Con `n_frames == 0` no hay trazos que
    dibujar y `tiradores` es None; `motivo` trae `clasificacion.motivo_no_disp`."""

    revision_id: uuid.UUID
    fps: float
    frame_w: int
    frame_h: int
    frame_inicio: int
    frame_tocado: int
    n_frames: int
    conf_min_keypoint: float
    tiradores: dict[str, PoseTirador] | None
    motivo: str | None


def angulo_codo_grados(
    xy: np.ndarray, conf: np.ndarray, detectado: bool, brazo: str
) -> float | None:
    """Ángulo del codo del brazo armado en un frame, en grados y sin estandarizar.

    Usa `valid_pt` y `angle_three_points` del extractor de features, así que
    aplica el mismo umbral de confianza (`CONF_THR`) y el mismo criterio de
    punto ausente.

    Args:
        xy: keypoints (17, 2) en píxeles.
        conf: confianzas (17,).
        detectado: si el tirador fue detectado en el frame.
        brazo: `diestro` o `zurdo`.

    Returns:
        El ángulo hombro-codo-muñeca en grados, o None si el tirador no fue
        detectado o falta alguno de los tres keypoints.

    Raises:
        ValueError: si `brazo` no es un valor del dominio.
    """
    if not detectado:
        return None
    kp = WEAPON_KPT[lado_de_brazo(brazo).value]
    hombro = valid_pt(xy, conf, kp["shoulder"])
    codo = valid_pt(xy, conf, kp["elbow"])
    muneca = valid_pt(xy, conf, kp["wrist"])
    if hombro[0] == 0 or codo[0] == 0 or muneca[0] == 0:
        return None
    return round(math.degrees(angle_three_points(hombro, codo, muneca)), 1)


class ConsultarPose:
    def __init__(
        self, consulta: ConsultaRevisionRepositoryPort, storage: FileStoragePort
    ):
        self._consulta = consulta
        self._storage = storage

    async def execute(self, revision_id: uuid.UUID) -> VistaPose:
        """Arma la vista de pose de una revisión.

        Args:
            revision_id: id de la revisión.

        Returns:
            La vista con xy, confianza, detección y ángulo de codo por frame.
            Si el .npz no tiene frames (timeout, pose incompleta) devuelve
            `n_frames = 0` y el motivo de la clasificación.

        Raises:
            RecursoNoEncontrado: si la revisión, su clip o su .npz no existen.
            ClasificacionPendiente: si la revisión aún no tiene clasificación.
            KeypointsAlterados: si el .npz no coincide con su SHA-256.
        """
        datos = await self._consulta.datos_pose(revision_id)
        if datos is None:
            raise RecursoNoEncontrado(f"revisión {str(revision_id)!r}")
        if datos.keypoints_uri is None or datos.keypoints_sha256 is None:
            raise ClasificacionPendiente()
        if datos.fps is None or datos.frame_tocado is None:
            raise RecursoNoEncontrado(f"clip de la revisión {str(revision_id)!r}")

        try:
            npz = await self._storage.read_keypoints(
                datos.keypoints_uri, datos.keypoints_sha256
            )
        except KeypointsAlterados:
            log.error(
                "keypoints alterados: revisión %s, uri %s "
                "(el SHA-256 no coincide con el registrado)",
                revision_id,
                datos.keypoints_uri,
            )
            raise
        except FileNotFoundError as exc:
            raise RecursoNoEncontrado(
                f"keypoints de la revisión {str(revision_id)!r}"
            ) from exc

        n_frames = int(npz["a_xy"].shape[0])
        lock_frame = int(npz["lock_frame"])
        comunes = dict(
            revision_id=datos.revision_id,
            fps=datos.fps,
            frame_w=int(npz["frame_w"]),
            frame_h=int(npz["frame_h"]),
            # El .npz solo guarda los frames desde el lock de IDs A/B
            # (YoloV8PoseAdapter): su índice 0 es el frame `lock_frame` del clip.
            frame_inicio=lock_frame if lock_frame >= 0 else 0,
            frame_tocado=datos.frame_tocado,
            n_frames=n_frames,
            conf_min_keypoint=CONF_THR,
        )
        if n_frames == 0:
            return VistaPose(**comunes, tiradores=None, motivo=datos.motivo_no_disp)

        tiradores = {
            lado.upper(): self._pose_tirador(npz, lado, brazo)
            for lado, brazo in (("a", datos.brazo_a), ("b", datos.brazo_b))
        }
        return VistaPose(**comunes, tiradores=tiradores, motivo=None)

    @staticmethod
    def _pose_tirador(
        npz: dict[str, np.ndarray], lado: str, brazo: str
    ) -> PoseTirador:
        xy = npz[f"{lado}_xy"]
        conf = npz[f"{lado}_conf"]
        detectado = npz[f"{lado}_detected"]
        return PoseTirador(
            color=COLOR_POR_TIRADOR[lado.upper()],
            brazo=brazo,
            xy=np.round(xy.astype(np.float64), 1).tolist(),
            conf=np.round(conf.astype(np.float64), 3).tolist(),
            detectado=[bool(d) for d in detectado],
            angulo_codo=[
                angulo_codo_grados(xy[t], conf[t], bool(detectado[t]), brazo)
                for t in range(xy.shape[0])
            ],
        )
