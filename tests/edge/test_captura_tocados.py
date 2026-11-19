"""Buffer circular, recorte del clip e instantes de luz (EDGE01), sin cámara ni aparato."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from edge.captura.buffer import BufferCircular, memoria_estimada_mb
from edge.captura.clip import ErrorClip, remuestrear
from edge.captura.config import ConfigCaptura
from edge.captura.fuente import HiloCaptura
from edge.captura.tocados import CapturaTocados, cargar_desfase_ms
from edge.favero.lector import BIT_ROJA, BIT_VERDE, Flanco, LectorFavero
from edge.favero.simulador import SimuladorFavero, abrir_pty

FPS = 30
PERIODO_NS = 1_000_000_000 // FPS
ALTO, ANCHO = 120, 160


def _imagen(encendida: bool) -> np.ndarray:
    return np.full((ALTO, ANCHO, 3), 255 if encendida else 10, np.uint8)


def _llenar(buffer: BufferCircular, desde_ns: int, hasta_ns: int, luz_ns: int | None = None, jitter=True):
    """Frames a 30 fps con algo de jitter; la 'lámpara' se ve desde el primer frame ≥ luz_ns."""
    rng = np.random.default_rng(1)
    t = desde_ns
    while t <= hasta_ns:
        marca = t + (int(rng.integers(-3, 4)) * 1_000_000 if jitter else 0)
        buffer.agregar(_imagen(luz_ns is not None and marca >= luz_ns), marca)
        t += PERIODO_NS


def _primer_encendido(ruta: Path) -> tuple[int, int]:
    """(índice del primer frame brillante, total de frames) leyendo el MP4."""
    cap = cv2.VideoCapture(str(ruta))
    primero, i = -1, 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        if primero < 0 and f.mean() > 128:
            primero = i
        i += 1
    cap.release()
    return primero, i


@pytest.fixture
def cfg(tmp_path):
    return ConfigCaptura(directorio=tmp_path / "tocados", archivo_latencia=tmp_path / "lat.json", k_tocados=3)


class Reloj:
    def __init__(self, t=0):
        self.t = t

    def __call__(self):
        return self.t


# ------------------------------------------------------------------ buffer


def test_buffer_conserva_solo_la_capacidad_y_extrae_por_rango():
    b = BufferCircular(1.0)
    for i in range(100):
        b.agregar(i, i * PERIODO_NS)
    assert b.mas_nuevo_ns - b.mas_viejo_ns <= 1_000_000_000
    assert len(b) == 31  # 1 s a 30 fps = 30 intervalos = 31 frames
    assert b.frames_descartados == 69
    sub = b.extraer(b.mas_nuevo_ns - 3 * PERIODO_NS, b.mas_nuevo_ns)
    assert len(sub) == 4


def test_buffer_rechaza_reloj_que_retrocede_y_capacidad_invalida():
    b = BufferCircular(1.0)
    b.agregar(0, 100)
    with pytest.raises(ValueError):
        b.agregar(0, 50)
    with pytest.raises(ValueError):
        BufferCircular(0)


def test_capacidad_cubre_5s_y_la_ventana_posterior():
    assert ConfigCaptura().capacidad_buffer_s == 5.5  # 5 s (RF-04) + 0,5 s posteriores
    assert ConfigCaptura(pre_ms=8000, post_ms=500).capacidad_buffer_s == 8.5
    assert memoria_estimada_mb(5.5, 30, 1280, 720) == pytest.approx(456, abs=1)


def test_no_se_pierde_ningun_frame_a_30fps_durante_10_minutos_simulados():
    b = BufferCircular(5.5)
    n = 30 * 600
    for i in range(n):
        b.agregar(None, i * PERIODO_NS)
    assert b.frames_agregados == n
    assert len(b) == round(5.5 * 30) + 1  # solo cae lo que sale de la ventana, nada por error


# ------------------------------------------------------------------ remuestreo


def test_remuestrear_da_grilla_constante_y_cuenta_repetidos():
    b = BufferCircular(10)
    # 10 frames normales y un hueco de 4 periodos (la cámara se atrasó)
    ts = [i * PERIODO_NS for i in range(10)] + [14 * PERIODO_NS + 5_000_000]
    for i, t in enumerate(ts):
        b.agregar(i, t)
    clip = remuestrear(b.extraer(0, 10**12), FPS, hasta_ns=10**12)
    assert len(clip.imagenes) == 15  # 0..14 periodos
    assert clip.repetidos == 4
    assert clip.t0_ns == 0
    assert clip.imagenes[:10] == list(range(10))


def test_remuestrear_sin_frames_falla():
    with pytest.raises(ErrorClip):
        remuestrear([], FPS, 0)


# ------------------------------------------------------------------ recorte e instantes


def _capturar(cfg, flancos, reloj_final, *, buffer=None, desfase_ms=None, desde=0):
    buffer = buffer or BufferCircular(cfg.capacidad_buffer_s)
    reloj = Reloj(reloj_final)
    cap = CapturaTocados(buffer, cfg, desfase_ms=desfase_ms, reloj_ns=reloj)
    return cap, buffer, reloj


def test_instante_de_luz_coincide_con_el_flanco_y_con_el_video_en_un_frame(cfg):
    s = 4_000_000_000  # flanco serie a 4 s
    buffer = BufferCircular(cfg.capacidad_buffer_s)
    _llenar(buffer, 0, s + 700_000_000, luz_ns=s)  # la lámpara se ve desde S (latencia 0)
    cap = CapturaTocados(buffer, cfg, reloj_ns=Reloj(s + 600_000_000))
    cap.registrar_flanco(Flanco("A", "ROJA", s))
    (res,) = cap.procesar()
    meta = res.metadatos
    assert meta["t_luz_b_ms"] is None and meta["luz_b"] is False and meta["luz_a"] is True
    assert isinstance(meta["t_luz_a_ms"], int)
    # el clip empieza ~2 s antes y la luz está ~2000 ms adentro
    assert abs(meta["t_luz_a_ms"] - cfg.pre_ms) <= 1000 / FPS
    # ... y es el frame donde se ve encenderse la lámpara en el MP4 (tolerancia de 1 frame)
    primero, total = _primer_encendido(res.ruta_video)
    assert total == meta["n_frames"] == pytest.approx((cfg.pre_ms + cfg.post_ms) * FPS / 1000, abs=1)
    assert abs(primero - meta["t_luz_a_ms"] * FPS / 1000) <= 1
    # cumple el contrato de §4: entero entre 0 y la duración del clip
    assert 0 <= meta["t_luz_a_ms"] <= round(total / FPS * 1000)


def test_doble_agrega_la_segunda_luz_al_mismo_tocado(cfg):
    s = 4_000_000_000
    buffer = BufferCircular(cfg.capacidad_buffer_s)
    _llenar(buffer, 0, s + 700_000_000, luz_ns=s)
    cap = CapturaTocados(buffer, cfg, reloj_ns=Reloj(s + 700_000_000))
    cap.registrar_flanco(Flanco("A", "ROJA", s))
    cap.registrar_flanco(Flanco("B", "VERDE", s + 125_000_000))  # 3 tramas después
    res = cap.procesar()
    assert len(res) == 1
    meta = res[0].metadatos
    assert meta["luz_a"] and meta["luz_b"]
    assert abs((meta["t_luz_b_ms"] - meta["t_luz_a_ms"]) - 125) <= 1000 / FPS


def test_luz_posterior_a_la_ventana_abre_otro_tocado(cfg):
    s = 4_000_000_000
    buffer = BufferCircular(cfg.capacidad_buffer_s)
    _llenar(buffer, 0, s + 2_000_000_000)
    reloj = Reloj(s + 600_000_000)
    cap = CapturaTocados(buffer, cfg, reloj_ns=reloj)
    cap.registrar_flanco(Flanco("A", "ROJA", s))
    cap.registrar_flanco(Flanco("B", "VERDE", s + 900_000_000))  # después de los 500 ms: tocado nuevo
    reloj.t = s + 1_500_000_000
    res = cap.procesar()
    assert [(r.metadatos["luz_a"], r.metadatos["luz_b"]) for r in res] == [(True, False), (False, True)]


def test_no_cierra_el_tocado_antes_de_la_ventana_posterior(cfg):
    s = 4_000_000_000
    buffer = BufferCircular(cfg.capacidad_buffer_s)
    _llenar(buffer, 0, s + 700_000_000)
    reloj = Reloj(s + 400_000_000)
    cap = CapturaTocados(buffer, cfg, reloj_ns=reloj)
    cap.registrar_flanco(Flanco("A", "ROJA", s))
    assert cap.procesar() == []
    reloj.t = s + 500_000_000
    assert len(cap.procesar()) == 1


def test_correccion_de_latencia_desplaza_la_luz_y_lo_dice_el_json(cfg):
    s = 4_000_000_000
    for desfase, calibrado in ((None, False), (100.0, True)):
        buffer = BufferCircular(cfg.capacidad_buffer_s)
        _llenar(buffer, 0, s + 900_000_000, jitter=False)
        cap = CapturaTocados(buffer, cfg, desfase_ms=desfase, reloj_ns=Reloj(s + 900_000_000))
        cap.registrar_flanco(Flanco("A", "ROJA", s))
        (res,) = cap.procesar()
        meta = res.metadatos
        assert meta["latencia_calibrada"] is calibrado
        assert meta["latencia_camara_ms"] == (desfase or 0.0)
        # el clip se centra en S + desfase, así que la luz queda siempre a ~pre_ms del inicio
        assert abs(meta["t_luz_a_ms"] - cfg.pre_ms) <= 1000 / FPS


def test_la_correccion_se_suma_al_instante_en_el_clip(cfg):
    """Con la ventana fija en el buffer, desfase = +66 ms mueve la luz 66 ms adelante en el clip."""
    s = 4_000_000_000
    buffer = BufferCircular(10)
    _llenar(buffer, 0, s + 900_000_000, jitter=False)
    # clip de ventana pre más corta que el buffer: el primer frame es el mismo en ambos casos
    base = ConfigCaptura(pre_ms=1000, directorio=cfg.directorio / "a")
    cap0 = CapturaTocados(buffer, base, reloj_ns=Reloj(s + 900_000_000))
    cap0.registrar_flanco(Flanco("A", "ROJA", s))
    t0 = cap0.procesar()[0].metadatos["t_luz_a_ms"]
    # con desfase la ventana también se mueve: la luz relativa al inicio no cambia (se centra), por lo
    # que se comprueba la fórmula directamente con una ventana previa mayor al historial disponible
    corto = BufferCircular(10)
    _llenar(corto, 3_000_000_000, s + 900_000_000, jitter=False)  # historial: solo 1 s antes de S
    cfg2 = ConfigCaptura(directorio=cfg.directorio / "b")
    c1 = CapturaTocados(corto, cfg2, reloj_ns=Reloj(s + 900_000_000))
    c1.registrar_flanco(Flanco("A", "ROJA", s))
    sin = c1.procesar()[0].metadatos["t_luz_a_ms"]
    cfg3 = ConfigCaptura(directorio=cfg.directorio / "c")
    c2 = CapturaTocados(corto, cfg3, desfase_ms=66.0, reloj_ns=Reloj(s + 900_000_000))
    c2.registrar_flanco(Flanco("A", "ROJA", s))
    con = c2.procesar()[0].metadatos["t_luz_a_ms"]
    assert t0 == pytest.approx(1000, abs=34)
    assert sin == pytest.approx(1000, abs=34)
    assert con - sin == pytest.approx(66, abs=34)


def test_buffer_corto_al_arrancar_avisa_y_el_clip_empieza_en_el_primer_frame(cfg, caplog):
    s = 4_000_000_000
    buffer = BufferCircular(cfg.capacidad_buffer_s)
    _llenar(buffer, s - 500_000_000, s + 700_000_000, jitter=False)  # solo 0,5 s antes
    cap = CapturaTocados(buffer, cfg, reloj_ns=Reloj(s + 600_000_000))
    cap.registrar_flanco(Flanco("A", "ROJA", s))
    with caplog.at_level("WARNING"):
        (res,) = cap.procesar()
    assert abs(res.metadatos["t_luz_a_ms"] - 500) <= 1000 / FPS
    assert "no cubre toda la ventana previa" in caplog.text


def test_buffer_vacio_cuenta_error_y_no_escribe(cfg):
    cap = CapturaTocados(BufferCircular(5.5), cfg, reloj_ns=Reloj(10**10))
    cap.registrar_flanco(Flanco("A", "ROJA", 4_000_000_000))
    assert cap.procesar() == []
    assert cap.errores == 1
    assert not list(cfg.directorio.glob("*")) if cfg.directorio.exists() else True


def test_conserva_solo_los_ultimos_k(cfg):
    buffer = BufferCircular(cfg.capacidad_buffer_s)
    reloj = Reloj(0)
    cap = CapturaTocados(buffer, cfg, reloj_ns=reloj)
    for n in range(5):
        s = 4_000_000_000 + n * 3_000_000_000
        _llenar(buffer, s - 1_000_000_000 if n else 0, s + 700_000_000, jitter=False)
        cap.registrar_flanco(Flanco("A", "ROJA", s))
        reloj.t = s + 600_000_000
        cap.procesar()
        time.sleep(0.002)
    mp4 = sorted(cfg.directorio.glob("tocado_*.mp4"))
    jsons = sorted(cfg.directorio.glob("tocado_*.json"))
    assert len(mp4) == len(jsons) == 3
    assert [p.stem for p in mp4] == [p.stem for p in jsons]
    assert cap.tocados_escritos == 5


def test_el_mp4_es_h264(cfg):
    if shutil.which("ffprobe") is None:
        pytest.skip("ffprobe no está instalado")
    s = 4_000_000_000
    buffer = BufferCircular(cfg.capacidad_buffer_s)
    _llenar(buffer, 0, s + 700_000_000)
    cap = CapturaTocados(buffer, cfg, reloj_ns=Reloj(s + 600_000_000))
    cap.registrar_flanco(Flanco("A", "ROJA", s))
    (res,) = cap.procesar()
    salida = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name,r_frame_rate", "-of", "csv=p=0", str(res.ruta_video)],
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert salida == "h264,30/1"


def test_json_en_disco_coincide_con_el_resultado(cfg):
    s = 4_000_000_000
    buffer = BufferCircular(cfg.capacidad_buffer_s)
    _llenar(buffer, 0, s + 700_000_000)
    cap = CapturaTocados(buffer, cfg, fuente="simulado", reloj_ns=Reloj(s + 600_000_000))
    cap.registrar_flanco(Flanco("B", "VERDE", s))
    (res,) = cap.procesar()
    en_disco = json.loads(res.ruta_json.read_text(encoding="utf-8"))
    assert en_disco == res.metadatos
    assert en_disco["fuente"] == "simulado" and en_disco["t_luz_a_ms"] is None and en_disco["luz_b"] is True


def test_cargar_desfase(tmp_path):
    archivo = tmp_path / "lat.json"
    assert cargar_desfase_ms(archivo, "frontal") is None
    archivo.write_text(json.dumps({"frontal": {"desfase_ms": -12.5}}), encoding="utf-8")
    assert cargar_desfase_ms(archivo, "frontal") == -12.5
    assert cargar_desfase_ms(archivo, "otra") is None


# ------------------------------------------------------------------ de punta a punta (simulador + video)


def _video_de_prueba(ruta: Path, segundos=3):
    w = cv2.VideoWriter(str(ruta), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (ANCHO, ALTO))
    for i in range(segundos * FPS):
        w.write(np.full((ALTO, ANCHO, 3), (i * 3) % 200, np.uint8))
    w.release()


def test_punta_a_punta_simulador_video_y_clip(tmp_path):
    """Simulador (tramas reales por pty) + video pregrabado como cámara -> clip con instantes."""
    video = tmp_path / "camara.mp4"
    _video_de_prueba(video)
    cfg = ConfigCaptura(directorio=tmp_path / "tocados", archivo_latencia=tmp_path / "lat.json")
    buffer = BufferCircular(cfg.capacidad_buffer_s)
    camara = HiloCaptura(str(video), buffer, fps=FPS, al_ritmo_del_archivo=True)
    captura = CapturaTocados(buffer, cfg, fuente="simulado")
    maestro, ruta = abrir_pty()
    sim = SimuladorFavero(lambda d: os.write(maestro, d))
    lector = LectorFavero(ruta, captura.registrar_flanco, baudios=2400, espera_arranque_s=0)
    camara.iniciar()
    captura.iniciar()
    sim.iniciar()
    lector.iniciar()
    try:
        time.sleep(2.6)  # que el buffer tenga más de 2 s de historial
        sim.encender(BIT_ROJA | BIT_VERDE, 6)
        fin = time.monotonic() + 5
        while captura.tocados_escritos == 0 and time.monotonic() < fin:
            time.sleep(0.05)
    finally:
        lector.detener()
        sim.detener()
        captura.detener()
        camara.detener()
        os.close(maestro)
    assert captura.tocados_escritos == 1
    (ruta_json,) = list(cfg.directorio.glob("tocado_*.json"))
    meta = json.loads(ruta_json.read_text(encoding="utf-8"))
    assert meta["luz_a"] and meta["luz_b"] and meta["fuente"] == "simulado"
    assert abs(meta["t_luz_a_ms"] - cfg.pre_ms) <= 2 * 1000 / FPS
    assert abs(meta["t_luz_b_ms"] - meta["t_luz_a_ms"]) <= 2 * 1000 / FPS  # doble simultáneo
    cap = cv2.VideoCapture(str(ruta_json.with_suffix(".mp4")))
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == meta["n_frames"]
    assert cap.get(cv2.CAP_PROP_FPS) == pytest.approx(FPS)
    cap.release()
