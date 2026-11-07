"""SEC02: el limitador de login vive en la memoria de Fog y no depende de Redis."""

import inspect

from fog.composition import Container
from fog.infrastructure.auth.memoria_limitador import MemoriaLimitador


class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _limitador(reloj=None):
    return MemoriaLimitador(max_fallos=5, ventana_s=900, bloqueo_s=900, reloj=reloj or Reloj())


async def test_el_quinto_fallo_bloquea_y_el_cuarto_no():
    lim = _limitador()
    for _ in range(4):
        assert await lim.registrar_fallo("1.1.1.1") is False
    assert await lim.segundos_bloqueado("1.1.1.1") == 0

    assert await lim.registrar_fallo("1.1.1.1") is True
    assert await lim.segundos_bloqueado("1.1.1.1") == 900


async def test_el_bloqueo_vence_y_la_ip_vuelve_a_empezar():
    reloj = Reloj()
    lim = _limitador(reloj)
    for _ in range(5):
        await lim.registrar_fallo("1.1.1.1")

    reloj.t += 899
    assert await lim.segundos_bloqueado("1.1.1.1") > 0
    reloj.t += 2
    assert await lim.segundos_bloqueado("1.1.1.1") == 0
    assert await lim.registrar_fallo("1.1.1.1") is False


async def test_fallos_fuera_de_la_ventana_no_se_acumulan():
    reloj = Reloj()
    lim = _limitador(reloj)
    for _ in range(4):
        await lim.registrar_fallo("1.1.1.1")
    reloj.t += 901

    assert await lim.registrar_fallo("1.1.1.1") is False


async def test_exito_borra_los_fallos_y_las_ips_son_independientes():
    lim = _limitador()
    for _ in range(4):
        await lim.registrar_fallo("1.1.1.1")
    await lim.registrar_exito("1.1.1.1")
    assert await lim.registrar_fallo("1.1.1.1") is False

    for _ in range(5):
        await lim.registrar_fallo("2.2.2.2")
    assert await lim.segundos_bloqueado("2.2.2.2") > 0
    assert await lim.segundos_bloqueado("1.1.1.1") == 0


def test_composition_no_ata_el_limitador_a_redis():
    """Con la nube comprometida, el contador no puede estar en un Redis que ella escribe."""
    fuente = inspect.getsource(Container)
    assert "MemoriaLimitador" in fuente
    assert "RedisLimitador" not in fuente
