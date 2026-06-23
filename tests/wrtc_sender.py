"""Diagnostico (parte 1/2): emisor WebRTC en un PROCESO SEPARADO del
receptor. Ver wrtc_receiver.py para el contexto completo del experimento.

Uso (dos terminales, no importa el orden):
    cd backend
    python tests/wrtc_receiver.py
    python tests/wrtc_sender.py ../dataset/test/RiposteB/RiposteB_0018.mp4
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer

OFFER_PATH = Path("/tmp/wrtc_diag_offer.json")
ANSWER_PATH = Path("/tmp/wrtc_diag_answer.json")


async def wait_for_file(path: Path, label: str) -> dict:
    print(f"Esperando {label} en {path} ...")
    while not path.exists():
        await asyncio.sleep(0.2)
    return json.loads(path.read_text())


async def run(video_path: str) -> None:
    OFFER_PATH.unlink(missing_ok=True)
    ANSWER_PATH.unlink(missing_ok=True)

    player = MediaPlayer(video_path)
    pc = RTCPeerConnection()
    pc.addTrack(player.video)

    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    OFFER_PATH.write_text(
        json.dumps({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type})
    )
    print("Offer escrita, esperando respuesta del receptor...")

    answer_data = await wait_for_file(ANSWER_PATH, "answer")
    await pc.setRemoteDescription(
        RTCSessionDescription(sdp=answer_data["sdp"], type=answer_data["type"])
    )
    print("Respuesta aplicada. Transmitiendo (ver wrtc_receiver.py para las metricas)...")

    # El receptor es quien mide tiempos; aca solo mantenemos el proceso vivo
    # el tiempo suficiente para que termine de transmitirse el clip completo,
    # incluso en el peor caso observado hasta ahora (~215s reales).
    await asyncio.sleep(280)

    await pc.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video_path")
    args = parser.parse_args()
    asyncio.run(run(args.video_path))


if __name__ == "__main__":
    main()
