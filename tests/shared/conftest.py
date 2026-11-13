"""Control de los redis-server que levantan las pruebas de tests/shared.

Cada `redis-server` de prueba usa un puerto libre elegido al vuelo y una carpeta dentro de la
carpeta temporal de la sesión de pytest (`--dir`). Al terminar la sesión, esta fixture busca
procesos `redis-server` cuyo directorio de trabajo esté en esa carpeta (requiere lsof): si queda
alguno, lo mata y hace fallar la sesión, para que un huérfano no pase desapercibido.
"""

import os
import signal
import subprocess

import pytest


def procesos_redis_de(carpeta: str) -> list[int]:
    """Devuelve los pid de los redis-server vivos cuyo directorio de trabajo está bajo `carpeta`.

    `redis-server` reescribe su título de proceso (solo muestra `127.0.0.1:puerto`), así que no
    se puede buscar la carpeta en `ps`; en cambio hace `chdir` a `--dir`, que sí se ve con lsof.
    """
    salida = subprocess.run(["lsof", "-a", "-c", "redis-server", "-d", "cwd", "-Fpn"],
                            capture_output=True, text=True).stdout
    pids, pid = [], None
    for linea in salida.splitlines():
        if linea.startswith("p"):
            pid = int(linea[1:])
        elif linea.startswith("n") and pid is not None and os.path.realpath(linea[1:]).startswith(
                os.path.realpath(carpeta)):
            pids.append(pid)
    return pids


def terminar_grupo(proc: subprocess.Popen, espera_s: float = 10) -> None:
    """Termina `proc` (lanzado con start_new_session=True) matando todo su grupo de procesos."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=espera_s)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
    except ProcessLookupError:
        # Sin grupo propio (no se lanzó con start_new_session): al menos termina al proceso.
        if proc.poll() is None:
            proc.kill()
            proc.wait()


@pytest.fixture(scope="session", autouse=True)
def sin_redis_huerfanos(tmp_path_factory):
    """Falla la sesión si algún redis-server de prueba sigue vivo al terminar."""
    yield
    huerfanos = procesos_redis_de(str(tmp_path_factory.getbasetemp()))
    for pid in huerfanos:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    assert not huerfanos, f"redis-server de prueba sin terminar (matados): pid {huerfanos}"
