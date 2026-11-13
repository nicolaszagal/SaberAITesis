"""scripts/redis_nativo.sh (SEC02): Redis con TLS + ACL, solo en 127.0.0.1."""

import os
import pathlib
import shutil
import signal
import socket
import subprocess

import pytest
import redis
from redis.backoff import NoBackoff
from redis.exceptions import NoPermissionError
from redis.retry import Retry

BACKEND = pathlib.Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    shutil.which("redis-server") is None or shutil.which("openssl") is None or shutil.which("nc") is None,
    reason="requiere redis-server, openssl y nc",
)


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _matar_si_sigue(pid_file: pathlib.Path) -> None:
    """Respaldo del teardown: si `stop` no pudo (o `start` falló a medias), mata el pid anotado."""
    try:
        os.kill(int(pid_file.read_text()), signal.SIGKILL)
    except (OSError, ValueError):
        pass


@pytest.fixture(scope="module")
def nativo(tmp_path_factory):
    raiz = tmp_path_factory.mktemp("nativo")
    secretos, datos, puerto = raiz / "secretos", raiz / "datos", _puerto_libre()
    entorno = {
        "PATH": os.environ["PATH"], "SECRETS_DIR": str(secretos), "DATOS_DIR": str(datos),
        "REDIS_PUERTO_NATIVO": str(puerto),
    }
    subprocess.run(["sh", "scripts/generar_pki_redis.sh", "localhost"], cwd=BACKEND,
                   env={**entorno}, check=True, capture_output=True)

    def correr(*args):
        return subprocess.run(["sh", "scripts/redis_nativo.sh", *args], cwd=BACKEND, env=entorno,
                              capture_output=True, text=True, timeout=60)

    try:
        arranque = correr("start")
        assert arranque.returncode == 0, arranque.stderr
        yield secretos, datos, puerto, correr
    finally:
        correr("stop")
        _matar_si_sigue(datos / "redis_nativo" / "redis.pid")


# Sin reintentos de redis-py (3 con espera creciente): aquí el rechazo es el resultado esperado.
SIN_REINTENTOS = {"retry": Retry(NoBackoff(), 0), "socket_connect_timeout": 2, "socket_timeout": 2}


def _cliente(secretos, puerto, usuario, clave_archivo):
    pki = secretos / "redis"
    return redis.Redis(
        host="localhost", port=puerto, ssl=True, username=usuario,
        password=(pki / clave_archivo).read_text(), ssl_ca_certs=str(pki / "ca.crt"),
        ssl_certfile=str(pki / f"{usuario}.crt"), ssl_keyfile=str(pki / f"{usuario}.key"), **SIN_REINTENTOS,
    )


def test_sin_las_contrasenas_por_usuario_se_niega_con_instruccion(tmp_path):
    res = subprocess.run(["sh", "scripts/redis_nativo.sh", "start"], cwd=BACKEND, capture_output=True, text=True,
                         env={"PATH": os.environ["PATH"], "SECRETS_DIR": str(tmp_path), "DATOS_DIR": str(tmp_path)})

    assert res.returncode == 1 and "rotar_secretos.sh" in res.stderr


def test_arranca_con_tls_y_acl_por_usuario(nativo):
    secretos, _, puerto, correr = nativo

    fog = _cliente(secretos, puerto, "fog", "redis_password_fog.txt")
    cloud = _cliente(secretos, puerto, "cloud", "redis_password_cloud.txt")
    assert fog.ping() and cloud.ping()
    with pytest.raises(NoPermissionError):
        fog.execute_command("XADD", "cloud:verdicts:x", "*", "a", "b")
    with pytest.raises(NoPermissionError):
        cloud.execute_command("XADD", "fog:features", "*", "a", "b")
    assert "activo" in correr("status").stdout


def test_escucha_solo_en_loopback_y_rechaza_texto_plano(nativo):
    _, _, puerto, _ = nativo
    if shutil.which("lsof") is None:
        pytest.skip("requiere lsof")

    salida = subprocess.run(["lsof", "-nP", f"-iTCP:{puerto}", "-sTCP:LISTEN"],
                            capture_output=True, text=True).stdout

    direcciones = {linea.split()[8] for linea in salida.splitlines()[1:]}
    assert direcciones == {f"127.0.0.1:{puerto}"}
    with socket.create_connection(("127.0.0.1", puerto), timeout=5) as s:
        s.sendall(b"PING\r\n")  # texto plano contra un puerto TLS: nunca debe responder +PONG
        s.settimeout(3)
        try:
            assert b"PONG" not in s.recv(64)
        except (socket.timeout, ConnectionResetError):
            pass


def test_sin_certificado_de_cliente_o_con_otra_clave_no_entra(nativo):
    secretos, _, puerto, _ = nativo
    pki = secretos / "redis"

    sin_cert = redis.Redis(host="localhost", port=puerto, ssl=True, username="fog",
                           password=(pki / "redis_password_fog.txt").read_text(), ssl_ca_certs=str(pki / "ca.crt"),
                           **SIN_REINTENTOS)
    with pytest.raises(redis.RedisError):
        sin_cert.ping()
    otra_clave = _cliente(secretos, puerto, "fog", "redis_password_cloud.txt")
    with pytest.raises(redis.RedisError):
        otra_clave.ping()


def test_stop_cierra_el_puerto(nativo):
    _, datos, puerto, correr = nativo

    assert correr("stop").returncode == 0

    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", puerto), timeout=2)
    assert not (datos / "redis_nativo" / "redis.pid").exists()
