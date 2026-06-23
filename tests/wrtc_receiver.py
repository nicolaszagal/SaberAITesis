"""Diagnostico (parte 2/2): receptor WebRTC en un PROCESO SEPARADO del
emisor (ver wrtc_sender.py). El script measure_webrtc_throughput.py ya
probo que con ambos RTCPeerConnection en el MISMO proceso la transmision
es rapida (~10s para el clip de prueba), incluso replicando el import de
cv2 y la conversion frame.to_ndarray(format="bgr24") de track_consumer.py.
La unica variable que falta aislar es si el cuello de botella aparece
especificamente al usar dos procesos de SO reales (como en el smoke test
real: cliente = manual_smoke_test.py, servidor = Fog), sin meter FastAPI,
Redis ni YOLO en la ecuacion.

Intercambio de SDP vía archivos en /tmp (polling), para no tener que
copiar/pegar manualmente.

Uso (dos terminales, no importa el orden):
    cd backend
    python tests/wrtc_receiver.py
    python tests/wrtc_sender.py ../dataset/test/RiposteB/RiposteB_0018.mp4
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

# Permite "from shared import config" al correr este script directamente
# (python tests/wrtc_receiver.py), ya que python solo agrega el directorio
# del script a sys.path, no el cwd ni backend/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError

OFFER_PATH = Path("/tmp/wrtc_diag_offer.json")
ANSWER_PATH = Path("/tmp/wrtc_diag_answer.json")

# Replica fog/composition.py: container.pose_estimator() (lifespan de
# fog/main.py) carga YOLO (que importa torch) en el mismo proceso ANTES de
# que llegue cualquier conexion. Se prueba aca si solo tener torch/ultralytics
# cargado en el proceso ya degrada la recepcion WebRTC, sin FastAPI/uvicorn
# de por medio.
LOAD_YOLO = True
YOLO_MODEL_PATH = str(
    Path(__file__).resolve().parents[2] / "dataset" / "yolov8x-pose.pt"
)

# Replica fog/application/forward_verdict.py + RedisVerdictSubscriber:
# corre, EN PARALELO a la recepcion de frames (mismo event loop, igual que
# routes.py:69 con asyncio.ensure_future), un loop de xread(..., block=5000)
# contra un stream que nunca va a tener entradas (simula esperar un
# veredicto que no llega). Si esto degrada la recepcion, confirma que el
# bloqueo esta en esta tarea concurrente, no en consume_track en si.
RUN_FAKE_VERDICT_WAIT = True


async def wait_for_file(path: Path, label: str) -> dict:
    print(f"Esperando {label} en {path} ...")
    while not path.exists():
        await asyncio.sleep(0.2)
    return json.loads(path.read_text())


async def fake_verdict_wait_loop() -> None:
    import redis.asyncio as redis

    from shared import config

    client = redis.from_url(config.REDIS_URL, decode_responses=False, socket_timeout=None)
    stream_key = "wrtc_diag:nunca_llega"
    last_id = "0"
    n = 0
    try:
        while True:
            result = await client.xread({stream_key: last_id}, count=1, block=5000)
            n += 1
            if not result:
                print(f"[fake_verdict_wait] xread #{n} volvio vacio (esperado)")
                await asyncio.sleep(0)
                continue
    except asyncio.CancelledError:
        pass
    finally:
        await client.close()


async def run() -> None:
    for p in (OFFER_PATH, ANSWER_PATH):
        p.unlink(missing_ok=True)

    if RUN_FAKE_VERDICT_WAIT:
        asyncio.ensure_future(fake_verdict_wait_loop())

    if LOAD_YOLO:
        t0 = time.monotonic()
        from ultralytics import YOLO  # importa torch internamente

        print(f"Cargando YOLO desde {YOLO_MODEL_PATH} ...")
        _ = YOLO(YOLO_MODEL_PATH)
        print(f"YOLO cargado en {time.monotonic() - t0:.2f}s")

    pc = RTCPeerConnection()
    received = {"count": 0, "first_ts": None, "last_ts": None}

    @pc.on("track")
    def on_track(track):
        print("Pista recibida, comenzando a consumir frames...")

        async def consume():
            while True:
                try:
                    frame = await track.recv()
                    frame.to_ndarray(format="bgr24")  # igual que track_consumer.py:36
                except MediaStreamError:
                    break
                now = time.monotonic()
                if received["first_ts"] is None:
                    received["first_ts"] = now
                received["last_ts"] = now
                received["count"] += 1

        asyncio.ensure_future(consume())

    offer_data = await wait_for_file(OFFER_PATH, "offer")
    t_offer_received = time.monotonic()
    await pc.setRemoteDescription(
        RTCSessionDescription(sdp=offer_data["sdp"], type=offer_data["type"])
    )
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    ANSWER_PATH.write_text(
        json.dumps({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type})
    )
    t_negotiated = time.monotonic()
    print(f"Negociacion (desde que llego el offer) completa en {t_negotiated - t_offer_received:.2f}s")

    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        await asyncio.sleep(1)
        if received["count"] > 0 and received["last_ts"] is not None:
            if time.monotonic() - received["last_ts"] > 5:
                break

    t_end = time.monotonic()

    print(f"Frames recibidos: {received['count']}")
    if received["first_ts"]:
        print(f"Tiempo hasta primer frame: {received['first_ts'] - t_negotiated:.2f}s")
        print(
            "Tiempo total de transmision (primer a ultimo frame): "
            f"{received['last_ts'] - received['first_ts']:.2f}s"
        )
    print(f"Tiempo total desde negociacion hasta fin: {t_end - t_negotiated:.2f}s")

    await pc.close()
    for p in (OFFER_PATH, ANSWER_PATH):
        p.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(run())
