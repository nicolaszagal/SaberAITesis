"""API local de Edge, señal de prueba, envío a Fog y cámara (EDGE02), sin cámara real ni Fog."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np
import pytest

from edge.api_local import ApiLocal
from edge.captura.camara import evaluar_fps, listar_camaras, parsear_ffmpeg, parsear_system_profiler
from edge.captura.config import ConfigCaptura
from edge.captura.config_edge import ConfigEdge, ConfigInvalida, cargar, guardar
from edge.captura.envio import EnvioFog, cuerpo_multipart, token_desde_entorno
from edge.captura.nucleo import NucleoEdge
from edge.favero.lector import Flanco

FPS = 30
FFMPEG = """\
[AVFoundation indev @ 0x1] AVFoundation video devices:
[AVFoundation indev @ 0x1] [0] FaceTime HD Camera
[AVFoundation indev @ 0x1] [1] iPhone de Nico Camera
[AVFoundation indev @ 0x1] [2] Capture screen 0
[AVFoundation indev @ 0x1] AVFoundation audio devices:
[AVFoundation indev @ 0x1] [0] MacBook Pro Microphone
"""


def _video(ruta: Path, segundos=4):
    w = cv2.VideoWriter(str(ruta), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (1280, 720))
    for i in range(segundos * FPS):
        w.write(np.full((720, 1280, 3), (i * 3) % 200, np.uint8))
    w.release()


def _http(puerto, metodo, ruta, cuerpo=None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{puerto}{ruta}", method=metodo,
        data=None if cuerpo is None else json.dumps(cuerpo).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read(), r.headers.get("Content-Type")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type")


@pytest.fixture
def edge(tmp_path):
    """Núcleo + API local con un video de 720p como cámara; fábrica para modo_prueba."""
    video = tmp_path / "camara.mp4"
    _video(video)
    creados = []

    def crear(modo_prueba, envio=None):
        cfg = ConfigCaptura(directorio=tmp_path / "tocados", archivo_latencia=tmp_path / "lat.json", k_tocados=5)
        nucleo = NucleoEdge(
            cfg, tmp_path / "config.json", modo_prueba=modo_prueba, fuente_video=str(video), envio=envio,
            listar=lambda: parsear_ffmpeg(FFMPEG),
        )
        nucleo.iniciar()
        api = ApiLocal(nucleo, 0)
        api.iniciar()
        creados.append((nucleo, api))
        return nucleo, api

    yield crear
    for nucleo, api in creados:
        api.detener()
        nucleo.detener()


# ------------------------------------------------------------------ cámaras


def test_parsea_las_camaras_de_ffmpeg_sin_pantallas_ni_microfonos():
    camaras = parsear_ffmpeg(FFMPEG)
    assert [(c.indice, c.nombre) for c in camaras] == [(0, "FaceTime HD Camera"), (1, "iPhone de Nico Camera")]


def test_parsea_system_profiler():
    salida = json.dumps({"SPCameraDataType": [{"_name": "FaceTime HD Camera"}, {"_name": "Webcam USB"}]})
    assert [c.nombre for c in parsear_system_profiler(salida)] == ["FaceTime HD Camera", "Webcam USB"]
    assert parsear_system_profiler("no es json") == []


def test_listar_camaras_sin_herramientas_devuelve_vacio(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    assert listar_camaras() == []


def test_avisos_de_fps():
    assert evaluar_fps(30.0, 30, 0, 300) == []
    assert any("menos de los 30" in a for a in evaluar_fps(24.0, 30, 0, 300))
    assert any("RNF-13" in a for a in evaluar_fps(24.0, 30, 0, 300))
    assert any("perdieron" in a for a in evaluar_fps(30.0, 30, 3, 300))


def test_config_valida_rnf13(tmp_path):
    ruta = tmp_path / "datos" / "config.json"
    assert cargar(ruta) == ConfigEdge()  # sin archivo: valores de fábrica
    guardar(ruta, ConfigEdge(camara_indice=1, ancho=1920, alto=1080, fps=60))
    assert cargar(ruta).camara_indice == 1
    for malo in (ConfigEdge(alto=480, ancho=640), ConfigEdge(fps=15), ConfigEdge(camara_indice=-1)):
        with pytest.raises(ConfigInvalida):
            guardar(ruta, malo)
    assert cargar(ruta).fps == 60  # lo inválido no pisó lo guardado


# ------------------------------------------------------------------ API local


def test_api_estado_camaras_y_config(edge):
    nucleo, api = edge(modo_prueba=False)
    time.sleep(1.0)
    estado = json.loads(_http(api.puerto, "GET", "/estado")[1])
    assert estado["camara"]["abierta"] is True
    assert estado["camara"]["resolucion"] == {"ancho": 1280, "alto": 720}
    assert estado["camara"]["fps_medidos"] > 20
    assert estado["modo_prueba"] is False and estado["senal"]["fuente"] == "ninguna"
    camaras = json.loads(_http(api.puerto, "GET", "/camaras")[1])
    assert [c["nombre"] for c in camaras][0] == "FaceTime HD Camera"
    s, cuerpo, _ = _http(api.puerto, "PUT", "/config", {"fps": 15})
    assert s == 422 and "30" in json.loads(cuerpo)["detail"]  # RNF-13
    s, cuerpo, _ = _http(api.puerto, "PUT", "/config", {"camara_indice": 1, "fps": 60})
    assert s == 200 and json.loads(_http(api.puerto, "GET", "/config")[1])["fps"] == 60
    time.sleep(0.5)  # tras cambiar la cámara el buffer se vacía y se vuelve a llenar
    s, jpg, tipo = _http(api.puerto, "GET", "/preview.jpg")
    assert s == 200 and tipo == "image/jpeg" and jpg[:2] == b"\xff\xd8"


def test_senal_de_prueba_no_existe_sin_modo_de_prueba(edge):
    """Con MODO_PRUEBA_SENAL apagado, /senal-prueba responde 404 (no 403, no 405)."""
    nucleo, api = edge(modo_prueba=False)
    assert _http(api.puerto, "POST", "/senal-prueba", {"luz_a": True})[0] == 404
    assert _http(api.puerto, "GET", "/senal-prueba")[0] == 404
    assert nucleo.captura.tocados_escritos == 0


def test_api_solo_escucha_en_loopback(edge):
    nucleo, api = edge(modo_prueba=False)
    assert api._servidor.server_address[0] == "127.0.0.1"
    with pytest.raises(ValueError):
        ApiLocal(nucleo, 0, host="0.0.0.0")


def test_senal_de_prueba_genera_un_tocado_simulado_con_origen_boton(edge):
    nucleo, api = edge(modo_prueba=True)
    time.sleep(2.7)  # buffer con más de 2 s de historial
    assert _http(api.puerto, "POST", "/senal-prueba", {})[0] == 422  # sin luces
    s, cuerpo, _ = _http(api.puerto, "POST", "/senal-prueba", {"luz_a": True, "luz_b": True})
    assert s == 200 and json.loads(cuerpo)["fuente"] == "simulado"
    fin = time.monotonic() + 5
    while nucleo.captura.tocados_escritos == 0 and time.monotonic() < fin:
        time.sleep(0.05)
    (meta,) = json.loads(_http(api.puerto, "GET", "/tocados")[1])
    assert meta["fuente"] == "simulado" and meta["origen"] == "boton"
    assert meta["luz_a"] and meta["luz_b"] and meta["t_luz_a_ms"] == meta["t_luz_b_ms"]
    assert abs(meta["t_luz_a_ms"] - 2000) <= 2 * 1000 / FPS
    assert meta["envio"] == "local"  # sin envío configurado


def test_el_estado_marca_sin_senal_favero_cuando_hay_lector_sin_tramas(edge):
    from edge.favero.lector import LectorFavero

    nucleo, api = edge(modo_prueba=False)
    nucleo.lector = LectorFavero("loop://", lambda f: None, abrir=lambda r, b: type(
        "P", (), {"read": lambda s, n=1: (time.sleep(0.02) or b""), "close": lambda s: None})(),
        espera_arranque_s=0, umbral_sin_senal_s=0.1)
    nucleo.lector.iniciar()
    time.sleep(0.4)
    estado = json.loads(_http(api.puerto, "GET", "/estado")[1])
    nucleo.lector.detener()
    assert estado["senal"]["fuente"] == "favero" and estado["senal"]["sin_senal_favero"] is True


# ------------------------------------------------------------------ envío a Fog


class _FogFalso(BaseHTTPRequestHandler):
    recibidos: list = []
    combate = "11111111-1111-1111-1111-111111111111"
    caido = False
    rechazar = None

    def log_message(self, *a):
        pass

    def _json(self, estado, cuerpo):
        datos = json.dumps(cuerpo).encode()
        self.send_response(estado)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def do_POST(self):
        largo = int(self.headers.get("Content-Length") or 0)
        cuerpo = self.rfile.read(largo)
        if self.headers.get("X-Edge-Token") != "token-de-servicio":
            return self._json(401, {"detail": "No autenticado"})
        if self.caido:
            return self._json(503, {"detail": "caído"})
        if self.rechazar:
            return self._json(self.rechazar, {"detail": "rechazado"})
        self.recibidos.append((self.path, self.headers.get("X-Edge-Token"), cuerpo))
        self._json(200, {"tocado_id": "t-1", "estado": "procesando"})

    def do_GET(self):
        if self.headers.get("X-Edge-Token") != "token-de-servicio":
            return self._json(401, {"detail": "No autenticado"})
        if self.path == "/matches/activo":
            return self._json(200, {"match_id": self.combate})
        self._json(404, {})


@pytest.fixture
def fog_falso():
    _FogFalso.recibidos, _FogFalso.caido, _FogFalso.rechazar = [], False, None
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _FogFalso)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _tocado_en_disco(directorio: Path, nombre="tocado_20261118T100000_000_0001", **extra):
    directorio.mkdir(parents=True, exist_ok=True)
    (directorio / f"{nombre}.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 100)
    meta = {"id": nombre, "t_luz_a_ms": 2000, "t_luz_b_ms": None, "luz_a": True, "luz_b": False,
            "fuente": "simulado", "origen": "boton", "envio": "pendiente", **extra}
    (directorio / f"{nombre}.json").write_text(json.dumps(meta), encoding="utf-8")
    return directorio / f"{nombre}.json"


def test_envio_sube_el_tocado_con_el_token_de_servicio_y_lo_marca_enviado(tmp_path, fog_falso):
    _, url = fog_falso
    ruta = _tocado_en_disco(tmp_path / "t")
    envio = EnvioFog(tmp_path / "t", url, "token-de-servicio")
    assert envio.enviar(ruta) is True
    (peticion,) = _FogFalso.recibidos
    assert peticion[0] == f"/matches/{_FogFalso.combate}/tocados" and peticion[1] == "token-de-servicio"
    cuerpo = peticion[2].decode("latin1")
    for esperado in ('name="fuente"\r\n\r\nsimulado', 'name="origen"\r\n\r\nboton', 'name="t_luz_a_ms"\r\n\r\n2000'):
        assert esperado in cuerpo
    assert "t_luz_b_ms" not in cuerpo
    meta = json.loads(ruta.read_text())
    assert meta["envio"] == "enviado" and meta["tocado_id_fog"] == "t-1"


def test_si_fog_no_responde_queda_pendiente_y_se_reintenta(tmp_path, fog_falso):
    _, url = fog_falso
    ruta = _tocado_en_disco(tmp_path / "t")
    _FogFalso.caido = True
    envio = EnvioFog(tmp_path / "t", url, "token-de-servicio", espera_inicial_s=0.05, espera_max_s=0.1)
    assert envio.enviar(ruta) is False
    assert json.loads(ruta.read_text())["envio"] == "pendiente"
    envio.iniciar()
    time.sleep(0.3)
    assert json.loads(ruta.read_text())["envio"] == "pendiente"  # sigue reintentando
    _FogFalso.caido = False
    fin = time.monotonic() + 5
    while json.loads(ruta.read_text())["envio"] != "enviado" and time.monotonic() < fin:
        time.sleep(0.05)
    envio.detener()
    assert json.loads(ruta.read_text())["envio"] == "enviado"


def test_fog_sin_servidor_no_pierde_el_tocado(tmp_path):
    ruta = _tocado_en_disco(tmp_path / "t")
    envio = EnvioFog(tmp_path / "t", "http://127.0.0.1:9", "token-de-servicio", timeout_s=0.5)
    assert envio.enviar(ruta) is False
    assert json.loads(ruta.read_text())["envio"] == "pendiente"


def test_error_definitivo_del_clip_no_se_reintenta(tmp_path, fog_falso):
    _, url = fog_falso
    _FogFalso.rechazar = 422
    ruta = _tocado_en_disco(tmp_path / "t")
    envio = EnvioFog(tmp_path / "t", url, "token-de-servicio")
    assert envio.enviar(ruta) is True
    assert json.loads(ruta.read_text())["envio"] == "error"
    assert envio.pendientes() == []


def test_varios_tocados_seguidos_se_envian_en_orden_sin_carreras(tmp_path, fog_falso):
    _, url = fog_falso
    d = tmp_path / "t"
    rutas = [_tocado_en_disco(d, f"tocado_20261118T10000{i}_000_000{i}") for i in range(4)]
    envio = EnvioFog(d, url, "token-de-servicio")
    envio.iniciar()
    fin = time.monotonic() + 5
    while len(_FogFalso.recibidos) < 4 and time.monotonic() < fin:
        time.sleep(0.05)
    envio.detener()
    assert len(_FogFalso.recibidos) == 4 and envio.enviados == 4
    assert all(json.loads(r.read_text())["envio"] == "enviado" for r in rutas)


def test_sin_token_no_se_envia_nada(tmp_path, fog_falso):
    _, url = fog_falso
    ruta = _tocado_en_disco(tmp_path / "t")
    envio = EnvioFog(tmp_path / "t", url, None)
    envio.iniciar()
    time.sleep(0.3)
    envio.detener()
    assert _FogFalso.recibidos == [] and json.loads(ruta.read_text())["envio"] == "pendiente"


def test_multipart_incluye_campos_y_archivo(tmp_path):
    f = tmp_path / "a.mp4"
    f.write_bytes(b"VIDEO")
    cuerpo, tipo = cuerpo_multipart({"fuente": "favero"}, f)
    assert tipo.startswith("multipart/form-data; boundary=") and b"VIDEO" in cuerpo
    assert b'filename="a.mp4"' in cuerpo and b'name="fuente"' in cuerpo


def test_un_token_equivocado_deja_el_tocado_pendiente(tmp_path, fog_falso):
    _, url = fog_falso
    ruta = _tocado_en_disco(tmp_path / "t")
    envio = EnvioFog(tmp_path / "t", url, "otro-token")
    assert envio.enviar(ruta) is False  # 401 de Fog: se reintenta, no se descarta
    assert json.loads(ruta.read_text())["envio"] == "pendiente" and _FogFalso.recibidos == []


def test_token_desde_entorno_o_secretos(tmp_path, monkeypatch):
    monkeypatch.delenv("EDGE_TOKEN", raising=False)
    assert token_desde_entorno(tmp_path) is None
    (tmp_path / "edge_token.txt").write_text("abc123\n", encoding="utf-8")
    assert token_desde_entorno(tmp_path) == "abc123"
    monkeypatch.setenv("EDGE_TOKEN", "del-entorno")
    assert token_desde_entorno(tmp_path) == "del-entorno"
    # ya no se usan usuario y clave del maestro
    (tmp_path / "edge_fog_user.txt").write_text("maestro", encoding="utf-8")
    monkeypatch.delenv("EDGE_TOKEN")
    (tmp_path / "edge_token.txt").unlink()
    assert token_desde_entorno(tmp_path) is None
