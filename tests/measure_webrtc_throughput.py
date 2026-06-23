"""Diagnostico: mide cuanto tarda aiortc en transmitir un clip via WebRTC en
un solo proceso (dos RTCPeerConnection conectados directamente, sin FastAPI,
Redis ni YOLO de por medio). Sirve para aislar si la lentitud observada en el
smoke test end-to-end (ver manual_smoke_test.py) viene del transporte WebRTC
en este entorno, o de otra etapa del pipeline (pose estimation, etc.).

No es parte de la suite de pytest. Uso:
    cd backend
    python tests/measure_webrtc_throughput.py ../dataset/test/RiposteB/RiposteB_0018.mp4
"""
from __future__ import annotations

import argparse
import asyncio
import time

import cv2  # noqa: F401  -- a proposito: replica el orden de import de Fog
            # (ultralytics carga cv2 al arrancar, antes de que aiortc/av
            # toquen ningun frame) para reproducir o descartar la colision
            # de libavdevice entre cv2 y av reportada por macOS al arrancar Fog.

from aiortc import RTCPeerConnection
from aiortc.contrib.media import MediaPlayer
from aiortc.mediastreams import MediaStreamError


async def run(video_path: str) -> None:
    pc_sender = RTCPeerConnection()
    pc_receiver = RTCPeerConnection()

    player = MediaPlayer(video_path)
    pc_sender.addTrack(player.video)

    received = {"count": 0, "first_ts": None, "last_ts": None}

    @pc_receiver.on("track")
    def on_track(track):
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

    t_start = time.monotonic()

    offer = await pc_sender.createOffer()
    await pc_sender.setLocalDescription(offer)
    await pc_receiver.setRemoteDescription(pc_sender.localDescription)
    answer = await pc_receiver.createAnswer()
    await pc_receiver.setLocalDescription(answer)
    await pc_sender.setRemoteDescription(pc_receiver.localDescription)

    t_negotiated = time.monotonic()
    print(f"Negociacion SDP completa en {t_negotiated - t_start:.2f}s")

    deadline = time.monotonic() + 240
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
    print(f"Tiempo total wall-clock: {t_end - t_start:.2f}s")

    await pc_sender.close()
    await pc_receiver.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video_path")
    args = parser.parse_args()
    asyncio.run(run(args.video_path))


if __name__ == "__main__":
    main()
