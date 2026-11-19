"""process_uploaded_clip — lee un clip de video subido por HTTP
(multipart, POST /matches/{match_id}/clip) frame a frame, igual que
track_consumer.py hace con los frames que llegan por WebRTC, pero desde
un archivo en disco en vez de una pista en vivo.

Vive en infrastructure/ (no en application/) porque depende directamente
de cv2 y del filesystem temporal — application/ (ProcessIncomingMatch) no
debe saber cómo se obtuvo la TrackedSequence, solo consumirla.

No usa el patrón producer/consumer de track_consumer.py: ese patrón existe
para solapar la espera de red (track.recv()) con el procesamiento de CPU.
Acá el archivo ya está completo en disco antes de empezar — no hay espera
de red que solapar. El cuello de botella es el mismo en ambos casos
(tiempo de inferencia de YOLO por frame), así que un loop secuencial
simple alcanza. cv2.VideoCapture(path) es la misma convención que usa
dataset/05_extract_features.py para leer clips del dataset.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

import asyncio
import dataclasses
import logging
import os
import tempfile
import threading
from concurrent.futures import Executor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
from fastapi import UploadFile

from fog.domain.models import TrackedSequence
from shared import config
from fog.ports.file_storage import FileStoragePort
from fog.ports.pose_estimator import PoseEstimatorPort
from fog.ports.procesador_clip import ClipRecibido, ProcesadorClipPort

log = logging.getLogger("fog.infrastructure.clips")


class ClipTooLargeError(Exception):
    """El archivo subido supera CLIP_MAX_MB (DEF-13). El router lo traduce a HTTP 413."""


class InvalidClipError(Exception):
    """El archivo subido no abre con cv2 o tiene menos de MIN_FRAMES frames
    (DEF-13). El router lo traduce a HTTP 400."""


class TocadoFueraDelClipError(Exception):
    """El instante de una luz (o `t_tocado_ms` obsoleto) no está entre 0 y la
    duración del clip. El router lo traduce a HTTP 422."""


@dataclass(frozen=True)
class ClipGuardado:
    """Clip guardado por SHA-256 con sus metadatos de video, sin pose."""

    uri: str
    sha256: str
    fps: float
    ancho_px: int
    alto_px: int
    duracion_ms: int
    desfase_recorte_ms: int = 0


class ExtraccionAgotadaError(Exception):
    """La extracción de pose superó el plazo (DEF-08, RF-13, RNF-09).

    El clip ya quedó guardado en `clip`, para abrir la revisión sin
    clasificación. El router lo traduce a "no disponible" con motivo `timeout`.
    """

    def __init__(self, clip: ClipGuardado):
        super().__init__("la extracción de pose superó el plazo")
        self.clip = clip


class _ExtraccionCancelada(Exception):
    """Interna: corta el hilo de lectura de frames tras un timeout."""


@dataclass(frozen=True)
class ClipProcesado:
    """Clip subido ya procesado y guardado: pose+tracking y metadatos de
    video para `sabre.clip`."""

    tracked: TrackedSequence
    uri: str
    sha256: str
    fps: float
    ancho_px: int
    alto_px: int
    duracion_ms: int
    desfase_recorte_ms: int = 0


def recortar_ventana(
    ruta: str,
    instantes_ms: Mapping[str, int],
    pre_ms: int,
    post_ms: int,
    nombre: str | None = None,
    min_frames: int = 0,
) -> tuple[str, int] | None:
    """Recorta el clip a `[t_tocado − pre_ms, t_tocado + post_ms]` (DEF-32).

    `t_tocado` es el menor de los instantes de luz. Es idempotente con tolerancia de un frame:
    un clip que ya cubre justo esa ventana (el que recorta Edge) no se toca.

    Args:
        ruta: clip original en disco.
        instantes_ms: instantes de luz por nombre de campo, relativos al clip original.
        pre_ms: milisegundos previos al tocado.
        post_ms: milisegundos posteriores al tocado.
        nombre: nombre del archivo, solo para los mensajes.
        min_frames: con menos frames no se valida ni se recorta: el flujo normal lo rechaza
            con 400 antes que con 422.

    Returns:
        `(ruta del clip recortado, desfase en ms respecto del original)`, o `None` si no hay que
        recortar o el archivo no se puede leer (el flujo normal lo rechaza después).

    Raises:
        TocadoFueraDelClipError: si un instante cae fuera de la duración del clip original.
    """
    cap = cv2.VideoCapture(ruta)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not cap.isOpened() or not fps or fps <= 0:
            return None
        t_tocado = min(instantes_ms.values())
        inicio = max(0, round((t_tocado - pre_ms) / 1000 * fps))
        fin = round((t_tocado + post_ms) / 1000 * fps)
        destino = ruta + ".recorte.mp4"
        escritor = None
        total = 0
        try:
            while True:
                if total <= fin:
                    ok, frame = cap.read()
                else:
                    ok, frame = cap.grab(), None  # solo contar: no hace falta decodificar
                if not ok:
                    break
                if inicio <= total <= fin and frame is not None:
                    if escritor is None:
                        alto, ancho = frame.shape[:2]
                        for codec in ("avc1", "mp4v"):
                            escritor = cv2.VideoWriter(
                                destino, cv2.VideoWriter_fourcc(*codec), fps, (ancho, alto)
                            )
                            if escritor.isOpened():
                                break
                            escritor.release()
                            escritor = None
                        if escritor is None:
                            log.warning("clip %r: no hay codificador; se procesa sin recortar", nombre)
                            return None
                    escritor.write(frame)
                total += 1
        finally:
            if escritor is not None:
                escritor.release()
    finally:
        cap.release()
    if total < min_frames:
        if os.path.exists(destino):
            os.remove(destino)
        return None
    duracion_ms = max(1, round(total / fps * 1000))
    for campo, valor in instantes_ms.items():
        if not 0 <= valor <= duracion_ms:
            raise TocadoFueraDelClipError(
                f"{campo}={valor} está fuera del clip: debe estar entre 0 y "
                f"{duracion_ms} ms (duración del clip {nombre!r})"
            )
    if inicio <= 1 and total - 1 <= fin + 1:
        if os.path.exists(destino):
            os.remove(destino)
        return None
    desfase = round(inicio / fps * 1000)
    log.info(
        "clip %r recortado a la ventana del tocado: frames %d..%d de %d",
        nombre, inicio, min(fin, total - 1), total,
    )
    return destino, desfase


async def process_uploaded_clip(
    file: UploadFile,
    pose_estimator: PoseEstimatorPort,
    executor: Executor,
    storage: FileStoragePort,
    clip_max_mb: float,
    min_frames: int,
    instantes_ms: Mapping[str, int] | None = None,
    plazo_s: float | None = None,
    pre_ms: int | None = None,
    post_ms: int | None = None,
) -> ClipProcesado:
    """Valida el clip subido, corre pose+tracking y lo guarda por SHA-256.

    Args:
        file: archivo multipart recibido.
        pose_estimator: puerto de pose+tracking.
        executor: hilos para el trabajo de CPU.
        storage: almacén donde se guarda el clip (uri + sha256).
        clip_max_mb: tamaño máximo aceptado.
        min_frames: frames mínimos para aceptar el clip.
        instantes_ms: instantes simulados por nombre de campo (`t_luz_a_ms`,
            `t_luz_b_ms`); cada uno debe estar entre 0 y la duración del clip
            (ambos incluidos).
        plazo_s: segundos máximos para la extracción de pose; None = sin límite.
        pre_ms: ventana previa al tocado; por defecto `VENTANA_PRE_MS` (EDGE02).
        post_ms: ventana posterior; por defecto `VENTANA_POST_MS`.

    Returns:
        Secuencia rastreada, uri/sha256 del archivo y metadatos de video. Si el clip se
        recortó, el archivo guardado es el recortado y `desfase_recorte_ms` es lo que hay que
        restar a los instantes de luz originales.

    Raises:
        ClipTooLargeError: si supera `clip_max_mb`.
        InvalidClipError: si no abre como video, no informa fps válidos o
            tiene menos de `min_frames` frames.
        TocadoFueraDelClipError: si algún instante es negativo o supera la
            duración del clip. El clip no se guarda.
        ExtraccionAgotadaError: si la pose no termina en `plazo_s`. El hilo de
            lectura se cancela y el clip se guarda; la excepción lo trae.
    """
    suffix = os.path.splitext(file.filename or "")[1] or ".mp4"
    content = await file.read()

    max_bytes = clip_max_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise ClipTooLargeError(
            f"el clip subido ({file.filename!r}) pesa "
            f"{len(content) / (1024 * 1024):.1f} MB, el máximo es {clip_max_mb:.0f} MB"
        )

    fd, original_path = tempfile.mkstemp(suffix=suffix)
    tmp_path = original_path
    desfase_ms = 0
    try:
        with os.fdopen(fd, "wb") as tmp:
            tmp.write(content)

        if instantes_ms:
            recorte = await asyncio.to_thread(
                recortar_ventana, tmp_path, instantes_ms,
                config.VENTANA_PRE_MS if pre_ms is None else pre_ms,
                config.VENTANA_POST_MS if post_ms is None else post_ms,
                file.filename, min_frames,
            )
            if recorte is not None:
                tmp_path, desfase_ms = recorte
                instantes_ms = {k: v - desfase_ms for k, v in instantes_ms.items()}

        loop = asyncio.get_running_loop()
        limite = None if plazo_s is None else loop.time() + plazo_s
        cancelar = threading.Event()
        pose_session = pose_estimator.start_session()

        def _read_all_frames() -> tuple[int, float, int, int]:
            cap = cv2.VideoCapture(tmp_path)
            if not cap.isOpened():
                raise InvalidClipError(f"no se pudo abrir el clip subido ({file.filename!r})")
            n = 0
            alto = ancho = 0
            fps = cap.get(cv2.CAP_PROP_FPS)
            try:
                while True:
                    if cancelar.is_set():
                        raise _ExtraccionCancelada()
                    ok, frame = cap.read()
                    if not ok:
                        break
                    if n == 0:
                        alto, ancho = frame.shape[:2]
                    pose_session.add_frame(frame)
                    n += 1
            finally:
                cap.release()
            if n < min_frames:
                raise InvalidClipError(
                    f"el clip subido ({file.filename!r}) tiene {n} frames, "
                    f"se requieren al menos {min_frames}"
                )
            if not fps or fps <= 0:
                raise InvalidClipError(
                    f"el clip subido ({file.filename!r}) no informa una tasa de frames válida"
                )
            return n, float(fps), ancho, alto

        def _validar_instantes(duracion_ms: int) -> None:
            for nombre, valor in (instantes_ms or {}).items():
                if not 0 <= valor <= duracion_ms:
                    raise TocadoFueraDelClipError(
                        f"{nombre}={valor} está fuera del clip: debe estar entre 0 y "
                        f"{duracion_ms} ms (duración del clip {file.filename!r})"
                    )

        async def _con_plazo(trabajo: Callable[[], Any]) -> Any:
            restante = None if limite is None else max(0.0, limite - loop.time())
            try:
                return await asyncio.wait_for(
                    loop.run_in_executor(executor, trabajo), restante
                )
            except asyncio.TimeoutError:
                cancelar.set()
                log.warning(
                    "clip %r: la extracción superó el plazo de %.0f s",
                    file.filename,
                    plazo_s,
                )
                guardado = await _guardar_sin_pose(
                    tmp_path, file.filename, storage, instantes_ms, _validar_instantes
                )
                guardado = dataclasses.replace(guardado, desfase_recorte_ms=desfase_ms)
                raise ExtraccionAgotadaError(guardado) from None

        n_frames, fps, ancho, alto = await _con_plazo(_read_all_frames)
        duracion_ms = max(1, round(n_frames / fps * 1000))
        _validar_instantes(duracion_ms)
        tracked = await _con_plazo(pose_session.finish)
        uri, sha256 = await storage.save_clip(Path(tmp_path))
        log.info("clip subido (%s): %d frames procesados", file.filename, n_frames)
        return ClipProcesado(
            tracked=tracked,
            uri=uri,
            sha256=sha256,
            fps=round(fps, 2),
            ancho_px=ancho,
            alto_px=alto,
            duracion_ms=duracion_ms,
            desfase_recorte_ms=desfase_ms,
        )
    finally:
        for ruta in {original_path, tmp_path}:
            if os.path.exists(ruta):
                os.remove(ruta)


async def _guardar_sin_pose(
    ruta: str,
    nombre: str | None,
    storage: FileStoragePort,
    instantes_ms: Mapping[str, int] | None,
    validar_instantes: Callable[[int], None],
) -> ClipGuardado:
    """Guarda el clip y lee sus metadatos sin correr pose (tras un timeout).

    La duración se calcula con los frames realmente leídos, no con
    CAP_PROP_FRAME_COUNT, que sobreestima los clips con preroll.

    Args:
        ruta: archivo temporal con el clip.
        nombre: nombre original del archivo, solo para los mensajes.
        storage: almacén donde se guarda el clip.
        instantes_ms: instantes de luz recibidos, validados contra la duración.
        validar_instantes: valida los instantes contra la duración estimada.

    Returns:
        El clip guardado y sus metadatos de video.

    Raises:
        InvalidClipError: si el clip no informa fps ni dimensiones válidos.
        TocadoFueraDelClipError: si un instante cae fuera de la duración.
    """
    cap = cv2.VideoCapture(ruta)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        ancho = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        alto = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        # CAP_PROP_FRAME_COUNT cuenta paquetes de preroll (PTS negativo) que
        # read() no entrega; grab() recorre solo los frames reales.
        total = 0
        while cap.grab():
            total += 1
    finally:
        cap.release()
    if not fps or fps <= 0 or total <= 0 or not ancho or not alto:
        raise InvalidClipError(
            f"el clip subido ({nombre!r}) no informa fps ni dimensiones válidos"
        )
    duracion_ms = max(1, round(total / fps * 1000))
    validar_instantes(duracion_ms)
    uri, sha256 = await storage.save_clip(Path(ruta))
    return ClipGuardado(
        uri=uri, sha256=sha256, fps=round(float(fps), 2), ancho_px=ancho, alto_px=alto,
        duracion_ms=duracion_ms,
    )


class ProcesadorClips(ProcesadorClipPort):
    """Adaptador de `ProcesadorClipPort` sobre OpenCV y el almacén de archivos."""

    def __init__(
        self,
        pose_estimator: PoseEstimatorPort,
        executor: Executor,
        storage: FileStoragePort,
        clip_max_mb: float,
        min_frames: int,
    ):
        self._pose = pose_estimator
        self._executor = executor
        self._storage = storage
        self._clip_max_mb = clip_max_mb
        self._min_frames = min_frames

    async def guardar(self, contenido, nombre, instantes_ms):
        if len(contenido) > self._clip_max_mb * 1024 * 1024:
            raise ClipTooLargeError(
                f"el clip ({nombre!r}) pesa {len(contenido) / (1024 * 1024):.1f} MB, "
                f"el máximo es {self._clip_max_mb:.0f} MB"
            )
        suffix = os.path.splitext(nombre or "")[1] or ".mp4"
        fd, original = tempfile.mkstemp(suffix=suffix)
        trabajo, desfase = original, 0
        try:
            with os.fdopen(fd, "wb") as tmp:
                tmp.write(contenido)
            recorte = await asyncio.to_thread(
                recortar_ventana, original, instantes_ms,
                config.VENTANA_PRE_MS, config.VENTANA_POST_MS, nombre, self._min_frames,
            )
            if recorte is not None:
                trabajo, desfase = recorte
            ajustados = {k: v - desfase for k, v in instantes_ms.items()}

            def validar(duracion_ms: int) -> None:
                for campo, valor in ajustados.items():
                    if not 0 <= valor <= duracion_ms:
                        raise TocadoFueraDelClipError(
                            f"{campo}={valor} está fuera del clip: debe estar entre 0 y {duracion_ms} ms"
                        )

            guardado = await _guardar_sin_pose(trabajo, nombre, self._storage, ajustados, validar)
            frames = round(guardado.duracion_ms / 1000 * guardado.fps)
            if frames < self._min_frames:
                raise InvalidClipError(
                    f"el clip ({nombre!r}) tiene {frames} frames, se requieren al menos {self._min_frames}"
                )
            return ClipRecibido(
                guardado.uri, guardado.sha256, guardado.fps, guardado.ancho_px, guardado.alto_px,
                guardado.duracion_ms, desfase,
            )
        finally:
            for ruta in {original, trabajo}:
                if os.path.exists(ruta):
                    os.remove(ruta)

    async def extraer_pose(self, uri: str, plazo_s: float) -> TrackedSequence:
        ruta = self._storage.ruta_local(uri)
        if ruta is None:
            raise InvalidClipError("el clip ya no está disponible en el almacén")
        cancelar = threading.Event()
        sesion = self._pose.start_session()

        def leer() -> None:
            cap = cv2.VideoCapture(str(ruta))
            if not cap.isOpened():
                raise InvalidClipError("no se pudo abrir el clip guardado")
            n = 0
            try:
                while not cancelar.is_set():
                    ok, frame = cap.read()
                    if not ok:
                        break
                    sesion.add_frame(frame)
                    n += 1
            finally:
                cap.release()
            if cancelar.is_set():
                raise _ExtraccionCancelada()
            if n < self._min_frames:
                raise InvalidClipError(f"el clip guardado tiene {n} frames, se requieren {self._min_frames}")

        loop = asyncio.get_running_loop()
        limite = loop.time() + plazo_s
        try:
            await asyncio.wait_for(loop.run_in_executor(self._executor, leer), plazo_s)
            restante = max(0.0, limite - loop.time())
            return await asyncio.wait_for(loop.run_in_executor(self._executor, sesion.finish), restante)
        except asyncio.TimeoutError:
            cancelar.set()
            raise ExtraccionAgotadaError(None) from None  # type: ignore[arg-type]
