"""Smoke test manual end-to-end: manda un clip de video real a Fog por
WebRTC (la única vía de ingesta que expone la API — no hay endpoint REST
de upload, ver CONTRATO_API.md sección 2), reporta luz Favero opcional, y
espera el veredicto por WebSocket.

No es parte de la suite de pytest (no corre con `pytest tests/`) — es una
herramienta de verificación manual contra Fog+Cloud+Redis ya levantados.

Requisitos extra, solo para correr este script (no van en requirements.txt
porque el backend en producción no los usa):
    pip install websockets

Uso:
    cd backend
    python tests/manual_smoke_test.py ../dataset/test/RiposteB/RiposteB_0018.mp4 \\
        --fog-url http://localhost:8001 \\
        --luz-b

Ajustar --fog-url al puerto real con el que levantaste Fog
(`python -m uvicorn fog.main:app --port <puerto>`).
"""

from __future__ import annotations

import argparse
import asyncio
import json

import av
import httpx
import websockets
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer


def _clip_duration_s(video_path: str) -> float:
    """Duracion real del clip via metadata del contenedor (PyAV), no
    hardcodeada -- usada para saber cuando la pista termino de enviarse
    sin depender de internals de aiortc.contrib.media.MediaPlayer."""
    with av.open(video_path) as container:
        stream = container.streams.video[0]
        return float(stream.duration * stream.time_base)


async def _close_pc_after(pc: RTCPeerConnection, delay_s: float) -> None:
    # RTP no tiene una señal nativa de "fin de pista": si el emisor deja la
    # conexion abierta despues de que el archivo se agota, el receptor
    # (Fog) se queda en track.recv() esperando indefinidamente, hasta que
    # el mecanismo de consent-freshness de ICE (RFC 7675) declara la
    # conexion muerta -- esto tarda ~30s+ y fue la causa real de que el
    # smoke test pareciera "lento" (~180-215s solo para un clip de 10s).
    # Cerrar pc explicitamente en cuanto el clip termina hace que Fog
    # detecte el cierre (DTLS close_notify) casi de inmediato. Esto es
    # ademas un hueco de protocolo real, no solo del script de prueba:
    # Edge en produccion necesitara la misma señal explicita al terminar
    # de transmitir cada combate.
    await asyncio.sleep(delay_s)
    await pc.close()


async def run(
    video_path: str,
    fog_url: str,
    weapon_side_a: str,
    weapon_side_b: str,
    luz_a: bool,
    luz_b: bool,
    timeout_s: float,
) -> None:
    ws_url = fog_url.replace("http://", "ws://").replace("https://", "wss://")

    player = MediaPlayer(video_path)
    if player.video is None:
        raise RuntimeError(f"{video_path} no tiene pista de video")

    pc = RTCPeerConnection()
    pc.addTrack(player.video)
    asyncio.ensure_future(_close_pc_after(pc, _clip_duration_s(video_path) + 1.0))

    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)

    async with httpx.AsyncClient(timeout=30.0) as client:
        print(f"POST {fog_url}/webrtc/offer ...")
        resp = await client.post(
            f"{fog_url}/webrtc/offer",
            json={
                "sdp": pc.localDescription.sdp,
                "type": pc.localDescription.type,
                "match_id": None,
                "weapon_side_A": weapon_side_a,
                "weapon_side_B": weapon_side_b,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        match_id = data["match_id"]
        print(f"match_id = {match_id}")

        await pc.setRemoteDescription(RTCSessionDescription(sdp=data["sdp"], type=data["type"]))

        if luz_a or luz_b:
            luz_resp = await client.post(
                f"{fog_url}/webrtc/{match_id}/luz",
                json={"has_luz_A": luz_a, "has_luz_B": luz_b},
            )
            luz_resp.raise_for_status()
            print("luz reportada:", luz_resp.json())

        print(
            "Esperando veredicto por WebSocket (carga de modelos + extracción "
            "de features + inferencia puede tardar; timeout = "
            f"{timeout_s:.0f}s)..."
        )
        async with websockets.connect(f"{ws_url}/ws/veredicto/{match_id}") as ws:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout_s)
            print("VEREDICTO:")
            print(json.dumps(json.loads(raw), indent=2, ensure_ascii=False))

    await pc.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("video_path", help="Ruta a un clip .mp4 del dataset")
    parser.add_argument("--fog-url", default="http://localhost:8001")
    parser.add_argument("--weapon-side-a", default="right", choices=["right", "left"])
    parser.add_argument("--weapon-side-b", default="right", choices=["right", "left"])
    parser.add_argument("--luz-a", action="store_true", help="Simula luz Favero encendida del lado A")
    parser.add_argument("--luz-b", action="store_true", help="Simula luz Favero encendida del lado B")
    parser.add_argument("--timeout", type=float, default=60.0, dest="timeout_s")
    args = parser.parse_args()

    asyncio.run(
        run(
            args.video_path,
            args.fog_url,
            args.weapon_side_a,
            args.weapon_side_b,
            args.luz_a,
            args.luz_b,
            args.timeout_s,
        )
    )


if __name__ == "__main__":
    main()
