"""RegistrarClasificacion — CU-06: guarda la sugerencia de Cloud, o el
"no disponible", contra el modelo activo, con los keypoints crudos de la
TrackedSequence en .npz (uri + sha256), la latencia medida por Fog y, en las
disponibles, la latencia de inferencia que informa Cloud (NULL si no hay).

La clase y las probabilidades se pasan con los nombres del modelo
(`AttackA`, ...); el adaptador de persistencia las traduce al esquema.

Con una sugerencia disponible y el contexto del clip, calcula el razonamiento
(F-035, D-15, D-16) y escribe sus filas en `evidencia` en la misma transacción
que la clasificación. Si el cálculo falla, la clasificación se guarda igual, se
deja el evento `razonamiento.error` en el log técnico y se registra una fila
`criterio_fie` con estado `no_calculado`.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

import numpy as np

from fog.application.consultar_pose import angulo_codo_grados
from fog.domain.audit_models import Clasificacion
from fog.domain.errors import SinModeloActivo
from fog.domain.models import (
    TrackedSequence,
    UnavailableResult,
    VerdictView,
    WeaponSide,
    brazo_de,
)
from fog.domain.razonamiento import (
    FilaEvidencia,
    ParametrosExplicacion,
    PoseEventos,
    Razonamiento,
    construir_razonamiento,
    detectar_eventos,
    fila_no_calculado,
    filas_de_razonamiento,
    ventana_atencion,
)
from fog.ports.feature_extractor import FeatureExtractorPort
from fog.ports.file_storage import FileStoragePort
from fog.ports.parametros_explicacion import ParametrosExplicacionPort
from fog.ports.unidad_de_trabajo import UnidadDeTrabajoPort
from shared.feature_extractor import BIO_OFFSET

log = logging.getLogger("fog.application")


@dataclass(frozen=True)
class ContextoClip:
    """Lo que el razonamiento necesita del clip además de la pose.

    Attributes:
        fps: cuadros por segundo del clip.
        frame_tocado: frame del clip en que se simuló el tocado.
        weapon_side_a: brazo armado de A.
        weapon_side_b: brazo armado de B.
    """

    fps: float
    frame_tocado: int
    weapon_side_a: WeaponSide
    weapon_side_b: WeaponSide


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


def calcular_razonamiento(
    extractor: FeatureExtractorPort,
    params: ParametrosExplicacion,
    tracked: TrackedSequence,
    arrays: dict[str, np.ndarray],
    clase: str,
    atencion: list[float] | None,
    contexto: ContextoClip,
    revision_id: str = "",
) -> Razonamiento:
    """Calcula el razonamiento de un clip sin escribir nada.

    Los ángulos salen de los mismos arreglos que se guardan en el .npz, así el
    evento coincide con los trazos de `GET /revisiones/{id}/pose`. La velocidad
    relativa del CM sale del extractor de features. La usan `RegistrarClasificacion`
    y el análisis de solo lectura de la Validación 1.

    Args:
        extractor: extractor de features (para la velocidad relativa del CM).
        params: parámetros U1 a U6.
        tracked: pose+tracking del clip.
        arrays: arreglos del .npz de keypoints crudos.
        clase: clase sugerida con el vocabulario del modelo.
        atencion: pesos de atención por frame, o None si Cloud no los envió.
        contexto: fps, frame del tocado y brazos armados.
        revision_id: solo para el aviso del log si la atención no calza.

    Returns:
        El razonamiento con su estado y sus frases.

    Raises:
        ValueError: si `clase` no es una clase del modelo.
    """
    n = int(arrays["a_xy"].shape[0])
    frame_inicio = int(tracked.lock_frame or 0)
    brazos = {
        "A": brazo_de(contexto.weapon_side_a),
        "B": brazo_de(contexto.weapon_side_b),
    }
    angulos = {
        lado: [
            angulo_codo_grados(
                arrays[f"{lado.lower()}_xy"][t],
                arrays[f"{lado.lower()}_conf"][t],
                bool(arrays[f"{lado.lower()}_detected"][t]),
                brazos[lado],
            )
            for t in range(n)
        ]
        for lado in ("A", "B")
    }
    raw, _ = extractor.extract_raw(
        tracked, contexto.weapon_side_a, contexto.weapon_side_b
    )
    eventos = detectar_eventos(
        PoseEventos(frame_inicio, angulos, [float(v) for v in raw[:, BIO_OFFSET]]),
        contexto.fps,
        contexto.frame_tocado,
        params,
    )
    ventana = None
    if atencion is not None:
        if len(atencion) == n:
            ventana = ventana_atencion(
                atencion,
                [frame_inicio + t for t in range(n)],
                contexto.fps,
                contexto.frame_tocado,
                params,
            )
        else:
            log.warning(
                "[%s] atención de largo %d distinta de los %d frames "
                "de la pose: se omite la ventana",
                revision_id, len(atencion), n,
            )
    return construir_razonamiento(clase, eventos, ventana, params)


class RegistrarClasificacion:
    def __init__(
        self,
        uow: UnidadDeTrabajoPort,
        storage: FileStoragePort,
        extractor: FeatureExtractorPort | None = None,
        parametros: ParametrosExplicacionPort | None = None,
    ):
        self._uow = uow
        self._storage = storage
        self._extractor = extractor
        self._parametros = parametros

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
        revision_id: uuid.UUID | None,
        tracked: TrackedSequence,
        resultado: VerdictView | UnavailableResult,
        latencia_ms: int,
        contexto: ContextoClip | None = None,
    ) -> Clasificacion:
        """Registra la clasificación y la asigna a la revisión.

        Respeta UNIQUE (tocado_id, modelo_version_id): si ya existe una
        para ese tocado y modelo, la devuelve sin insertar otra.

        Args:
            tocado_id: tocado clasificado.
            revision_id: revisión que recibe la clasificación; `None` si el tocado se
                preprocesa sin revisión (EDGE02): se asigna después con `Solicitar VAR`.
            tracked: pose+tracking del clip (keypoints crudos).
            resultado: veredicto de Cloud o "no disponible" con su motivo.
            latencia_ms: milisegundos desde la recepción del clip hasta la
                sugerencia (o hasta el "no disponible").
            contexto: fps, frame del tocado y brazos armados del clip. Sin él,
                o con la clasificación no disponible, no se escribe razonamiento.

        Returns:
            La clasificación registrada.

        Raises:
            SinModeloActivo: si no hay versión de modelo activa.
        """
        arrays = keypoints_a_arrays(tracked)
        keypoints_uri, keypoints_sha256 = await self._storage.save_keypoints(arrays)
        filas: list[FilaEvidencia] = []
        if isinstance(resultado, VerdictView) and contexto is not None:
            filas = self._razonar(tracked, arrays, resultado, contexto)
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
                await tx.razonamientos.registrar(clasificacion.id, filas)
            else:
                clasificacion = await tx.clasificaciones.crear(
                    disponible=False,
                    motivo_no_disp=resultado.motivo.value,
                    **comunes,
                )
            if revision_id is not None:
                await tx.revisiones.asignar_clasificacion(revision_id, clasificacion.id)
        return clasificacion

    def _razonar(
        self,
        tracked: TrackedSequence,
        arrays: dict[str, np.ndarray],
        resultado: VerdictView,
        contexto: ContextoClip,
    ) -> list[FilaEvidencia]:
        """Calcula las filas de `evidencia` de una sugerencia disponible.

        Los ángulos salen de los mismos arreglos que se guardan en el .npz, así
        el evento coincide con los trazos de `GET /revisiones/{id}/pose`. La
        velocidad relativa del CM sale del extractor de features.

        Args:
            tracked: pose+tracking del clip.
            arrays: arreglos del .npz de keypoints crudos.
            resultado: sugerencia de Cloud, con la atención si la envió.
            contexto: fps, frame del tocado y brazos.

        Returns:
            Las filas a escribir; vacía si no hay extractor o parámetros o la
            pose no tiene frames. Si el cálculo falló, la fila `no_calculado`
            y el evento `razonamiento.error` en el log técnico.
        """
        n = int(arrays["a_xy"].shape[0])
        if self._extractor is None or self._parametros is None or n == 0:
            return []
        version = None
        try:
            params = self._parametros.cargar()
            version = params.version
            razonamiento = calcular_razonamiento(
                self._extractor,
                params,
                tracked,
                arrays,
                resultado.action,
                resultado.atencion,
                contexto,
                resultado.revision_id,
            )
            return filas_de_razonamiento(razonamiento, params.version)
        except Exception:
            log.exception(
                "razonamiento.error revision=%s: no se pudo calcular el razonamiento",
                resultado.revision_id,
            )
            return [fila_no_calculado(version)]
