"""RegistrarClasificacion — CU-06: guarda la sugerencia de Cloud, o el
"no disponible", contra el modelo activo, con los keypoints crudos de la
TrackedSequence en .npz (uri + sha256), la latencia medida por Fog y, en las
disponibles, la latencia de inferencia que informa Cloud (NULL si no hay).

La clase y las probabilidades se pasan con los nombres del modelo
(`AttackA`, ...); el adaptador de persistencia las traduce al esquema.
"""

from __future__ import annotations

import uuid

import numpy as np

from fog.domain.audit_models import Clasificacion
from fog.domain.errors import SinModeloActivo
from fog.domain.models import TrackedSequence, UnavailableResult, VerdictView
from fog.ports.file_storage import FileStoragePort
from fog.ports.unidad_de_trabajo import UnidadDeTrabajoPort

def keypoints_a_arrays(tracked: TrackedSequence) -> dict[str, np.ndarray]:
    """Arma los arreglos del .npz de keypoints crudos.

    Args:
        tracked: secuencia de pose+tracking del clip.

    Returns:
        Arreglos por nombre: para cada tirador `{a,b}_xy` (T,17,2),
        `{a,b}_conf` (T,17), `{a,b}_box` (T,4) y `{a,b}_detected` (T,);
        más `frame_w`, `frame_h`, `locked` y `lock_frame` (-1 si no hubo).
    """

    def apilar(persona: str, campo: str, forma: tuple[int, ...], dtype) -> np.ndarray:
        if not tracked.frames:
            return np.zeros((0, *forma), dtype=dtype)
        return np.stack(
            [getattr(getattr(f, persona), campo) for f in tracked.frames]
        ).astype(dtype)

    arrays: dict[str, np.ndarray] = {}
    for lado, persona in (("a", "person_a"), ("b", "person_b")):
        arrays[f"{lado}_xy"] = apilar(persona, "keypoints_xy", (17, 2), np.float32)
        arrays[f"{lado}_conf"] = apilar(persona, "keypoints_conf", (17,), np.float32)
        arrays[f"{lado}_box"] = apilar(persona, "box_xyxy", (4,), np.float32)
        arrays[f"{lado}_detected"] = apilar(persona, "detected", (), np.bool_)
    arrays["frame_w"] = np.array(tracked.frame_w)
    arrays["frame_h"] = np.array(tracked.frame_h)
    arrays["locked"] = np.array(tracked.locked)
    arrays["lock_frame"] = np.array(-1 if tracked.lock_frame is None else tracked.lock_frame)
    return arrays


class RegistrarClasificacion:
    def __init__(self, uow: UnidadDeTrabajoPort, storage: FileStoragePort):
        self._uow = uow
        self._storage = storage

    async def verificar_modelo_activo(self) -> None:
        """Falla pronto si no hay modelo activo, antes de procesar el clip.

        Raises:
            SinModeloActivo: si `modelo_version` no tiene una fila activa.
        """
        async with self._uow.transaccion() as tx:
            if await tx.modelos.obtener_activo() is None:
                raise SinModeloActivo()

    async def execute(
        self,
        *,
        tocado_id: uuid.UUID,
        revision_id: uuid.UUID,
        tracked: TrackedSequence,
        resultado: VerdictView | UnavailableResult,
        latencia_ms: int,
    ) -> Clasificacion:
        """Registra la clasificación y la asigna a la revisión.

        Respeta UNIQUE (tocado_id, modelo_version_id): si ya existe una
        para ese tocado y modelo, la devuelve sin insertar otra.

        Args:
            tocado_id: tocado clasificado.
            revision_id: revisión que recibe la clasificación.
            tracked: pose+tracking del clip (keypoints crudos).
            resultado: veredicto de Cloud o "no disponible" con su motivo.
            latencia_ms: milisegundos desde la recepción del clip hasta la
                sugerencia (o hasta el "no disponible").

        Returns:
            La clasificación registrada.

        Raises:
            SinModeloActivo: si no hay versión de modelo activa.
        """
        keypoints_uri, keypoints_sha256 = await self._storage.save_keypoints(
            keypoints_a_arrays(tracked)
        )
        async with self._uow.transaccion() as tx:
            modelo = await tx.modelos.obtener_activo()
            if modelo is None:
                raise SinModeloActivo()
            existente = await tx.clasificaciones.obtener_por_tocado_y_modelo(
                tocado_id, modelo.id
            )
            if existente is not None:
                return existente

            comunes = dict(
                tocado_id=tocado_id,
                modelo_version_id=modelo.id,
                keypoints_uri=keypoints_uri,
                keypoints_sha256=keypoints_sha256,
                latencia_ms=latencia_ms,
            )
            if isinstance(resultado, VerdictView):
                clasificacion = await tx.clasificaciones.crear(
                    disponible=True,
                    clase=resultado.action,
                    tirador=resultado.action[-1],
                    confianza=resultado.confidence,
                    probabilidades=resultado.probs,
                    latencia_inferencia_ms=resultado.latencia_inferencia_ms,
                    **comunes,
                )
            else:
                clasificacion = await tx.clasificaciones.crear(
                    disponible=False,
                    motivo_no_disp=resultado.motivo.value,
                    **comunes,
                )
            await tx.revisiones.asignar_clasificacion(revision_id, clasificacion.id)
        return clasificacion
