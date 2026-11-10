"""scripts/fog_remoto.sh (SEC02): el acceso remoto exige ventana y se cierra solo.

Entorno simulado: `cloudflared`, `tailscale`, `curl` y `caffeinate` son stubs en el PATH, así que
no se abre ningún túnel ni se publica nada en una tailnet real. Una "hora" dura 2 s
(FOG_REMOTO_SEGUNDOS_POR_HORA). El Redis nativo lo hace un socket de Python en un puerto libre.
"""

import os
import pathlib
import shutil
import socket
import subprocess
import threading
import time

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(shutil.which("nc") is None, reason="requiere nc")


def _stub(ruta: pathlib.Path, cuerpo: str) -> None:
    ruta.write_text("#!/bin/sh\n" + cuerpo)
    ruta.chmod(0o755)


@pytest.fixture
def redis_falso():
    """Un puerto en escucha que hace de Redis nativo."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    srv.settimeout(0.2)
    activo = threading.Event()
    activo.set()

    def aceptar():
        while activo.is_set():
            try:
                srv.accept()[0].close()
            except OSError:
                pass

    hilo = threading.Thread(target=aceptar, daemon=True)
    hilo.start()
    yield srv.getsockname()[1]
    activo.clear()
    hilo.join(timeout=2)
    srv.close()


@pytest.fixture
def sim(tmp_path, redis_falso):
    raiz = tmp_path / "backend"
    (raiz / "scripts").mkdir(parents=True)
    shutil.copy(BACKEND / "scripts" / "fog_remoto.sh", raiz / "scripts" / "fog_remoto.sh")
    _stub(raiz / "scripts" / "recordar_respaldo.sh", "exit 0\n")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    bitacora = tmp_path / "tailscale.log"
    _stub(bin_ / "cloudflared", 'echo "https://prueba-simulada.trycloudflare.com" >&2\nexec sleep 600\n')
    _stub(bin_ / "caffeinate", "exec sleep 600\n")
    _stub(bin_ / "curl", "exit 0\n")
    _stub(bin_ / "tailscale", f'echo "$@" >> "{bitacora}"\nexit 0\n')
    base = {
        "PATH": f"{bin_}:/usr/bin:/bin",
        "PROXY_SHARED_TOKEN": "token-de-prueba",
        "FOG_REMOTO_SEGUNDOS_POR_HORA": "2",
        "FOG_REMOTO_SONDEO_S": "0.2",
        "FOG_HOST_PORT": "8123",
        "REDIS_PUERTO_NATIVO": str(redis_falso),
    }

    def correr(*args, modo=None, **extra):
        entorno = {**base, **extra}
        if modo:
            entorno["FOG_REMOTO_MODO"] = modo
        return subprocess.run(
            ["sh", str(raiz / "scripts" / "fog_remoto.sh"), *args],
            cwd=raiz, env=entorno, capture_output=True, text=True, timeout=60,
        )

    yield raiz, correr, bitacora
    correr("stop")
    correr("stop", modo="cloudflared")


def _vivo(pid_file: pathlib.Path) -> bool:
    if not pid_file.exists():
        return False
    try:
        os.kill(int(pid_file.read_text()), 0)
        return True
    except OSError:
        return False


def _esperar(condicion, segundos=10):
    for _ in range(int(segundos * 10)):
        if condicion():
            return True
        time.sleep(0.1)
    return False


# --- Ventana: vale para los dos modos ---------------------------------------


@pytest.mark.parametrize("modo", ["tailscale", "cloudflared"])
def test_start_sin_horas_o_fuera_de_rango_se_niega_y_no_abre_nada(sim, modo):
    raiz, correr, bitacora = sim

    for args in (["start"], ["start", "--horas"], ["start", "--horas", "0"],
                 ["start", "--horas", "9"], ["start", "--horas", "x"], ["start", "--horas", "-1"]):
        res = correr(*args, modo=modo)
        assert res.returncode == 2, args
        assert "horas" in res.stderr, args
    assert not (raiz / "datos" / "fog_remoto_tunel.pid").exists()
    assert not bitacora.exists()


def test_modo_desconocido_se_rechaza(sim):
    _, correr, _ = sim

    res = correr("start", "--horas", "1", modo="otro")

    assert res.returncode == 2 and "tailscale o cloudflared" in res.stderr


# --- Modo tailscale (por defecto) -------------------------------------------


def test_tailscale_publica_fog_y_redis_y_los_cierra_al_vencer(sim, redis_falso):
    raiz, correr, bitacora = sim
    datos = raiz / "datos"

    inicio = correr("start", "--horas", "1")

    assert inicio.returncode == 0, inicio.stderr
    publicado = bitacora.read_text()
    assert "serve --bg --tcp 8001 tcp://127.0.0.1:8123" in publicado
    assert f"serve --bg --tcp 6379 tcp://127.0.0.1:{redis_falso}" in publicado
    assert "cloudflared" not in inicio.stdout and not (datos / "fog_remoto_url.txt").exists()
    estado = correr("status").stdout
    assert "tailnet" in estado and "Quedan" in estado and "vence a las" in estado

    assert _esperar(lambda: not (datos / "fog_remoto_modo.txt").exists())

    assert "serve reset" in bitacora.read_text()
    assert not (datos / "fog_remoto_vence.txt").exists() and not any(datos.glob("*.pid"))
    assert correr("status").stdout.strip() == "Acceso remoto detenido."


def test_tailscale_exige_el_redis_nativo_arriba(sim):
    _, correr, bitacora = sim

    res = correr("start", "--horas", "1", REDIS_PUERTO_NATIVO="1")

    assert res.returncode == 1 and "redis_nativo.sh start" in res.stderr
    assert "serve" not in (bitacora.read_text() if bitacora.exists() else "")


def test_tailscale_stop_manual_cierra_lo_publicado_y_el_vigia(sim):
    raiz, correr, bitacora = sim
    datos = raiz / "datos"
    assert correr("start", "--horas", "8").returncode == 0
    pid_vigia = int((datos / "fog_remoto_vigia.pid").read_text())

    assert correr("stop").returncode == 0

    assert "serve reset" in bitacora.read_text()
    time.sleep(0.5)
    with pytest.raises(OSError):
        os.kill(pid_vigia, 0)
    assert not any(datos.glob("fog_remoto_*"))


def test_tailscale_avisa_si_quedaron_archivos_del_arranque_anterior(sim):
    raiz, correr, _ = sim
    datos = raiz / "datos"
    datos.mkdir()
    (datos / "fog_remoto_modo.txt").write_text("tailscale")
    (datos / "fog_remoto_vence.txt").write_text("1")

    res = correr("start", "--horas", "1")

    assert res.returncode == 0, res.stderr
    assert "el último 'stop' no corrió" in res.stderr


def test_datos_dir_cambia_donde_se_guarda_el_estado(sim, tmp_path):
    raiz, correr, _ = sim
    otro = tmp_path / "estado_aparte"

    assert correr("start", "--horas", "8", DATOS_DIR=str(otro)).returncode == 0

    assert (otro / "fog_remoto_vence.txt").exists() and not (raiz / "datos").exists()
    correr("stop", DATOS_DIR=str(otro))


def test_tailscale_sin_tailscale_conectado_se_niega(sim, tmp_path):
    _, correr, bitacora = sim
    _stub(tmp_path / "bin" / "tailscale", "exit 1\n")

    res = correr("start", "--horas", "1")

    assert res.returncode == 1 and "Tailscale no está" in res.stderr


# --- Modo cloudflared (respaldo, como en DEPLOY07) --------------------------


def test_cloudflared_se_cierra_solo_al_vencer_la_ventana(sim):
    raiz, correr, _ = sim
    datos = raiz / "datos"

    inicio = correr("start", "--horas", "1", modo="cloudflared")

    assert inicio.returncode == 0, inicio.stderr
    assert "Se cierra solo a las" in inicio.stdout
    assert _vivo(datos / "fog_remoto_tunel.pid") and _vivo(datos / "fog_remoto_vigia.pid")
    estado = correr("status", modo="cloudflared").stdout
    assert "Túnel activo" in estado and "Quedan" in estado
    pid_tunel = int((datos / "fog_remoto_tunel.pid").read_text())

    assert _esperar(lambda: not (datos / "fog_remoto_tunel.pid").exists())

    assert not (datos / "fog_remoto_url.txt").exists()
    with pytest.raises(OSError):
        os.kill(pid_tunel, 0)
    assert correr("status", modo="cloudflared").stdout.strip() == "Acceso remoto detenido."


def test_cloudflared_stop_manual_cierra_tambien_el_vigia(sim):
    raiz, correr, _ = sim
    datos = raiz / "datos"
    assert correr("start", "--horas", "8", modo="cloudflared").returncode == 0
    pid_vigia = int((datos / "fog_remoto_vigia.pid").read_text())

    assert correr("stop", modo="cloudflared").returncode == 0

    time.sleep(0.5)
    with pytest.raises(OSError):
        os.kill(pid_vigia, 0)
    assert not any(datos.glob("fog_remoto_*.pid"))


def test_cloudflared_avisa_si_quedaron_pid_viejos(sim):
    raiz, correr, _ = sim
    datos = raiz / "datos"
    datos.mkdir()
    (datos / "fog_remoto_tunel.pid").write_text("999999")
    (datos / "fog_remoto_url.txt").write_text("https://vieja.trycloudflare.com")

    res = correr("start", "--horas", "1", modo="cloudflared")

    assert res.returncode == 0, res.stderr
    assert "el último 'stop' no corrió" in res.stderr
    assert "vieja" not in (datos / "fog_remoto_url.txt").read_text()


def test_status_con_restos_sin_proceso_lo_dice(sim):
    raiz, correr, _ = sim
    datos = raiz / "datos"
    datos.mkdir()
    (datos / "fog_remoto_tunel.pid").write_text("999999")

    assert "el último 'stop' no corrió" in correr("status").stdout
