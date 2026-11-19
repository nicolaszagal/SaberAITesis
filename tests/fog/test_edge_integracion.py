"""Fog ↔ Edge de punta a punta (EDGE02): botón de prueba → clip → Fog → tocado listo → Solicitar VAR."""

from __future__ import annotations

import threading
import time

import cv2
import numpy as np
import pytest
import uvicorn

from edge.api_local import ApiLocal
from edge.captura.config import ConfigCaptura
from edge.captura.envio import EnvioFog
from edge.captura.nucleo import NucleoEdge
from shared import config

FPS = 30


def _video(ruta, segundos=4):
    w = cv2.VideoWriter(str(ruta), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (1280, 720))
    for i in range(segundos * FPS):
        w.write(np.full((720, 1280, 3), (i * 3) % 200, np.uint8))
    w.release()


@pytest.fixture
def servidor_fog(crear_app):
    """La app de Fog de las pruebas, sirviendo en un puerto real (para el envío de Edge)."""
    app = crear_app()
    srv = uvicorn.Server(uvicorn.Config(app.fastapi, host="127.0.0.1", port=0, log_level="warning", lifespan="off"))
    hilo = threading.Thread(target=srv.run, daemon=True)
    hilo.start()
    fin = time.monotonic() + 10
    while not srv.started and time.monotonic() < fin:
        time.sleep(0.05)
    puerto = srv.servers[0].sockets[0].getsockname()[1]
    yield app, f"http://127.0.0.1:{puerto}"
    srv.should_exit = True
    hilo.join(5)


@pytest.fixture
def edge_real(tmp_path, servidor_fog, monkeypatch):
    app, url = servidor_fog
    video = tmp_path / "camara.mp4"
    _video(video)
    cfg = ConfigCaptura(directorio=tmp_path / "tocados", archivo_latencia=tmp_path / "lat.json")
    envio = EnvioFog(cfg.directorio, url, "token-de-servicio")
    nucleo = NucleoEdge(
        cfg, tmp_path / "config.json", modo_prueba=True, fuente_video=str(video), envio=envio, listar=lambda: []
    )
    nucleo.iniciar()
    api = ApiLocal(nucleo, 0)
    api.iniciar()
    monkeypatch.setattr(config, "EDGE_URL", f"http://127.0.0.1:{api.puerto}")
    monkeypatch.setattr(config, "MODO_PRUEBA_SENAL", True)
    monkeypatch.setattr(config, "EDGE_TOKEN", "token-de-servicio")
    yield app, nucleo
    api.detener()
    nucleo.detener()


def test_punta_a_punta_boton_clip_preproceso_y_solicitar_var(edge_real):
    app, nucleo = edge_real
    match_id = app.configurar()
    time.sleep(2.7)  # historial de la "cámara"
    # el botón pasa por Fog (JWT) y Fog lo reenvía a Edge por 127.0.0.1
    t_boton = time.monotonic()
    r = app.client.post("/edge/senal-prueba", json={"luz_a": True, "luz_b": False})
    assert r.status_code == 200, r.text
    fin = time.monotonic() + 30
    item = None
    while time.monotonic() < fin:
        lista = app.client.get(f"/matches/{match_id}/tocados").json()
        if lista and lista[0]["estado"] == "listo":
            item = lista[0]
            break
        time.sleep(0.1)
    assert item is not None, "el tocado no llegó a 'listo'"
    print(f"botón → 'listo' en {time.monotonic() - t_boton:.2f} s")
    assert item["fuente"] == "simulado" and item["luz_A"] and not item["luz_B"]
    assert abs(item["t_luz_a_ms"] - 2000) <= 2 * 1000 / FPS
    assert item["revisado"] is False and item["admite_var"] is True
    # D-04: sin Solicitar VAR no existe ninguna revisión ni registro de auditoría
    assert app.sql.filas(
        "SELECT count(*) AS n FROM sabre.revision_var r JOIN sabre.tocado t ON t.id = r.tocado_id "
        "WHERE t.combate_id = :m", m=match_id)[0]["n"] == 0
    # Solicitar VAR: la sugerencia aparece al instante
    t0 = time.monotonic()
    v = app.client.post(f"/tocados/{item['tocado_id']}/revision")
    assert v.status_code == 200 and time.monotonic() - t0 < 2.0
    assert v.json()["disponible"] is True and v.json()["action"] == "AttackA"
    assert app.sql.filas("SELECT fuente FROM sabre.tocado WHERE id = :t", t=item["tocado_id"])[0]["fuente"] == "simulado"
    # el clip se reproduce como repetición
    assert app.client.get(f"/tocados/{item['tocado_id']}/clip").status_code == 200
    assert nucleo.envio.enviados == 1


def test_edge_proxy_estado_y_config(edge_real):
    app, _ = edge_real
    estado = app.client.get("/edge/estado").json()
    assert estado["modo_prueba"] is True and estado["camara"]["resolucion"]["alto"] == 720
    assert app.client.put("/edge/config", json={"fps": 15}).status_code == 422  # RNF-13 viene de Edge
    assert app.client.get("/edge/config").json()["fps"] == 30


def test_sin_modo_de_prueba_la_senal_responde_404_en_fog(edge_real, monkeypatch):
    app, _ = edge_real
    monkeypatch.setattr(config, "MODO_PRUEBA_SENAL", False)
    assert app.client.post("/edge/senal-prueba", json={"luz_a": True}).status_code == 404


def test_edge_apagado_da_503_con_codigo_estable(crear_app, monkeypatch):
    app = crear_app()
    monkeypatch.setattr(config, "EDGE_URL", "http://127.0.0.1:9")
    r = app.client.get("/edge/estado")
    assert r.status_code == 503 and r.json()["codigo"] == "edge_no_disponible"


def test_edge_exige_jwt(crear_app):
    app = crear_app(autenticado=False)
    assert app.client.get("/edge/estado").status_code == 401
    assert app.client.get("/matches/activo").status_code == 401
