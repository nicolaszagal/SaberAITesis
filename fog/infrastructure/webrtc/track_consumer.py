"""consume_track — procesa una pista de video WebRTC frame a frame
(producer/consumer sobre un asyncio.Queue) en vez de juntar todos los
frames del clip y recién después correr pose+tracking. El productor
(track.recv()) y el consumidor (pose_session.add_frame, CPU-bound, corrido
en el ThreadPoolExecutor compartido) corren concurrentemente: mientras se
procesa el frame N, ya puede estar llegando por red el frame N+1, en vez
de esperar a que termine el clip completo para arrancar el procesamiento
(antes 100% serial: tiempo real del clip + tiempo de CPU, uno después del
otro).

Cuando la pista termina, se espera (con timeout) la señal de luz Favero
vía POST /webrtc/{match_id}/luz, y se dispara ProcessIncomingMatch con la
TrackedSequence ya calculada. La espera de luz con timeout es la decisión
de PLAN_ARQUITECTURA_DDD.md sección 2.3: si Edge no manda la luz a
tiempo, se procesa con LuzSignal.none() en vez de bloquear indefinidamente
el clip.

Aislamiento entre combates concurrentes: pose_estimator.start_session()
crea un tracker propio para este combate (ver fog/ports/pose_estimator.py
y YoloV8PoseAdapter) — dos nodos Edge corriendo en paralelo ya no
comparten estado de tracking entre sí. Solo la llamada a model.predict()
en sí se serializa internamente (lock compartido en el adaptador), no el
tracking.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import Executor

import numpy as np
from aiortc.mediastreams import MediaStreamError

from fog.application.process_match import ProcessIncomingMatch
from fog.infrastructure.webrtc.session_registry import MatchSession
from fog.ports.pose_estimator import PoseEstimatorPort

log = logging.getLogger("fog.infrastructure.webrtc")

# Tamaño máximo del buffer entre producer (red) y consumer (CPU). Acotado
# para que, si la CPU se queda atrás del framerate de llegada, se aplique
# backpressure (el producer espera a que haya espacio) en vez de acumular
# frames sin límite en memoria.
_QUEUE_MAXSIZE = 16

# Sentinel para marcar fin de pista en la queue (None es ambiguo: nunca lo
# usamos como "no hay frame", siempre representa "no hay más frames").
_END_OF_TRACK = None


async def consume_track(
    track,
    session: MatchSession,
    pose_estimator: PoseEstimatorPort,
    process_match: ProcessIncomingMatch,
    executor: Executor,
    luz_timeout_s: float,
) -> None:
    log.info("[%s] recibiendo pista de video", session.match_id)
    loop = asyncio.get_running_loop()
    pose_session = pose_estimator.start_session()
    queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)

    async def producer() -> None:
        while True:
            try:
                frame = await track.recv()
            except MediaStreamError:
                break
            await queue.put(frame.to_ndarray(format="bgr24"))
        await queue.put(_END_OF_TRACK)

    async def consumer() -> int:
        n = 0
        while True:
            frame: np.ndarray | None = await queue.get()
            if frame is _END_OF_TRACK:
                break
            await loop.run_in_executor(executor, pose_session.add_frame, frame)
            n += 1
        return n

    _, n_frames = await asyncio.gather(producer(), consumer())
    log.info("[%s] pista finalizada, %d frames procesados", session.match_id, n_frames)

    tracked = await loop.run_in_executor(executor, pose_session.finish)

    if not session.luz_event.is_set():
        try:
            await asyncio.wait_for(session.luz_event.wait(), timeout=luz_timeout_s)
        except asyncio.TimeoutError:
            log.info("[%s] timeout esperando luz Favero, se procesa sin luz", session.match_id)

    await process_match.execute(
        session.match_id,
        tracked,
        session.weapon_side_a,
        session.weapon_side_b,
        session.luz,
    )
