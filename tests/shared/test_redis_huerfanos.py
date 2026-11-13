"""La guarda de tests/shared/conftest.py detecta y termina a un redis-server de prueba."""

import shutil
import socket
import subprocess
import time

import pytest

from tests.shared.conftest import procesos_redis_de, terminar_grupo

pytestmark = pytest.mark.skipif(shutil.which("redis-server") is None, reason="requiere redis-server")


def test_detecta_el_redis_vivo_y_terminar_grupo_lo_mata(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    proc = subprocess.Popen(
        [shutil.which("redis-server"), "--port", str(puerto), "--bind", "127.0.0.1", "--save", "",
         "--dir", str(tmp_path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    try:
        for _ in range(50):
            if procesos_redis_de(str(tmp_path)):
                break
            time.sleep(0.1)
        assert procesos_redis_de(str(tmp_path)) == [proc.pid]
    finally:
        terminar_grupo(proc)

    assert procesos_redis_de(str(tmp_path)) == []
